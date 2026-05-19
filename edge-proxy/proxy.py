from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, client_exceptions, web


UPSTREAM = os.environ.get("UPSTREAM", "http://chatgpt-mirror:50003").rstrip("/")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "50002"))
CLIENT_MAX_SIZE = int(os.environ.get("CLIENT_MAX_SIZE", str(512 * 1024**2)))

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

AUTH_COOKIE_DENY_PREFIXES = (
    "__Secure-next-auth.",
    "__Host-next-auth.",
    "next-auth.",
)

AUTH_COOKIE_DENY_NAMES = {
    "__Secure-next-auth.session-token",
    "__Host-next-auth.csrf-token",
    "__Secure-next-auth.callback-url",
    "next-auth.session-token",
    "next-auth.csrf-token",
    "next-auth.callback-url",
}

DROP_REQUEST_HEADERS_ALWAYS = {
    "content-length",
    "accept-encoding",
}

DROP_CHATGPT_ROUTE_HEADERS = {
    "origin",
    "referer",
}

DROP_WEBSOCKET_HEADERS = {
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
}

DROP_RESPONSE_HEADERS = {
    "alt-svc",
    "alt-used",
    "strict-transport-security",
    "nel",
    "report-to",
    "reporting-endpoints",
    "cross-origin-opener-policy",
}

LOCAL_PREFIXES = (
    "/0x/",
    "/admin",
)

LOCAL_EXACT_PATHS = {
    "/api/login",
    "/api/logout",
    "/api/not-login",
    "/auth/logout",
}

POLYFILL = """<script id="http-crypto-randomuuid-polyfill">
(function(){try{var cryptoObj=globalThis.crypto;if(!cryptoObj||typeof cryptoObj.randomUUID==="function")return;var hex=[];for(var i=0;i<256;i+=1){hex[i]=(i+256).toString(16).slice(1)}Object.defineProperty(cryptoObj,"randomUUID",{configurable:true,enumerable:false,writable:true,value:function(){var bytes=new Uint8Array(16);if(typeof cryptoObj.getRandomValues==="function"){cryptoObj.getRandomValues(bytes)}else{for(var i=0;i<bytes.length;i+=1){bytes[i]=Math.floor(Math.random()*256)}}bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;return hex[bytes[0]]+hex[bytes[1]]+hex[bytes[2]]+hex[bytes[3]]+"-"+hex[bytes[4]]+hex[bytes[5]]+"-"+hex[bytes[6]]+hex[bytes[7]]+"-"+hex[bytes[8]]+hex[bytes[9]]+"-"+hex[bytes[10]]+hex[bytes[11]]+hex[bytes[12]]+hex[bytes[13]]+hex[bytes[14]]+hex[bytes[15]]}})}catch(e){}})();
</script>"""


def upstream_url(request: web.Request) -> str:
    return f"{UPSTREAM}{request.rel_url}"


def is_local_route(path: str) -> bool:
    return path in LOCAL_EXACT_PATHS or any(path.startswith(prefix) for prefix in LOCAL_PREFIXES)


def is_auth_cookie_name(name: str) -> bool:
    normalized = name.strip()
    return normalized in AUTH_COOKIE_DENY_NAMES or any(
        normalized.startswith(prefix) for prefix in AUTH_COOKIE_DENY_PREFIXES
    )


def cookie_name_from_set_cookie(value: str) -> str:
    return value.split("=", 1)[0].strip()


def sanitize_cookie_header(value: str) -> str:
    parts: list[str] = []
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if is_auth_cookie_name(name):
            continue
        parts.append(part)
    return "; ".join(parts)


def request_headers(request: web.Request, *, websocket: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP or lower == "host" or lower in DROP_REQUEST_HEADERS_ALWAYS:
            continue
        if websocket and lower in DROP_WEBSOCKET_HEADERS:
            continue
        if not websocket and not is_local_route(request.path) and (
            lower in DROP_CHATGPT_ROUTE_HEADERS or lower.startswith("sec-fetch-")
        ):
            continue
        if lower == "cookie" and not is_local_route(request.path):
            value = sanitize_cookie_header(value)
            if not value:
                continue
        headers[key] = value

    if not websocket:
        headers["Accept-Encoding"] = "identity"

    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    headers["Host"] = request.host
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = forwarded_proto
    if request.remote:
        prior = request.headers.get("X-Forwarded-For")
        headers["X-Forwarded-For"] = f"{prior}, {request.remote}" if prior else request.remote
        headers["X-Real-IP"] = request.remote
    return headers


def websocket_protocols(request: web.Request) -> list[str]:
    raw = request.headers.get("Sec-WebSocket-Protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def copy_response_headers(headers: Iterable[tuple[str, str]], *, path: str) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    local = is_local_route(path)
    for key, value in headers:
        lower = key.lower()
        if lower in HOP_BY_HOP or lower in DROP_RESPONSE_HEADERS:
            continue
        if lower in {"content-length", "content-encoding"}:
            continue
        if lower == "set-cookie" and not local:
            if is_auth_cookie_name(cookie_name_from_set_cookie(value)):
                continue
        copied.append((key, value))
    return copied


def mark_response_safe_for_http_origin(response: web.StreamResponse) -> web.StreamResponse:
    # Upstream ChatGPT/Cloudflare advertises HTTP/3 over :443. On a bare HTTP mirror
    # origin that poisons Chrome's Alt-Svc cache and causes ERR_ALPN_NEGOTIATION_FAILED.
    response.headers["Alt-Svc"] = "clear"
    return response


def inject_polyfill(body: bytes, content_type: str) -> bytes:
    charset = "utf-8"
    match = re.search(r"charset=([^;]+)", content_type, re.I)
    if match:
        charset = match.group(1).strip()

    text = body.decode(charset, errors="replace")
    if "http-crypto-randomuuid-polyfill" in text:
        return body

    patched, count = re.subn(
        r"(<head\b[^>]*>)",
        r"\1" + POLYFILL,
        text,
        count=1,
        flags=re.I,
    )
    if count == 0:
        patched = POLYFILL + text
    return patched.encode(charset, errors="replace")


async def proxy_websocket(request: web.Request) -> web.StreamResponse:
    target = upstream_url(request).replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    session: ClientSession = request.app["session"]
    protocols = websocket_protocols(request)

    try:
        async with session.ws_connect(
            target,
            headers=request_headers(request, websocket=True),
            protocols=protocols,
            timeout=ClientTimeout(total=None),
        ) as ws_upstream:
            ws_client = web.WebSocketResponse(
                protocols=[ws_upstream.protocol] if ws_upstream.protocol else (),
            )
            await ws_client.prepare(request)

            async def client_to_upstream() -> None:
                async for msg in ws_client:
                    if msg.type == WSMsgType.TEXT:
                        await ws_upstream.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await ws_upstream.send_bytes(msg.data)
                    elif msg.type == WSMsgType.PING:
                        await ws_upstream.ping()
                    elif msg.type == WSMsgType.PONG:
                        await ws_upstream.pong()
                    elif msg.type == WSMsgType.CLOSE:
                        await ws_upstream.close()

            async def upstream_to_client() -> None:
                async for msg in ws_upstream:
                    if msg.type == WSMsgType.TEXT:
                        await ws_client.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await ws_client.send_bytes(msg.data)
                    elif msg.type == WSMsgType.PING:
                        await ws_client.ping()
                    elif msg.type == WSMsgType.PONG:
                        await ws_client.pong()
                    elif msg.type == WSMsgType.CLOSE:
                        await ws_client.close()

            tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
            return ws_client
    except client_exceptions.WSServerHandshakeError as exc:
        return web.Response(status=exc.status, text="upstream websocket rejected")


async def proxy_http(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["session"]
    body = await request.read()
    async with session.request(
        request.method,
        upstream_url(request),
        headers=request_headers(request),
        data=body if body else None,
        allow_redirects=False,
        timeout=ClientTimeout(total=None),
    ) as upstream:
        content_type = upstream.headers.get("content-type", "")
        is_html = "text/html" in content_type.lower()

        if is_html:
            payload = inject_polyfill(await upstream.read(), content_type)
            print(
                f"[edge-proxy] html patched path={request.rel_url} "
                f"status={upstream.status} injected={b'http-crypto-randomuuid-polyfill' in payload}",
                flush=True,
            )
            response = web.Response(status=upstream.status, reason=upstream.reason, body=payload)
            for key, value in copy_response_headers(upstream.headers.items(), path=request.path):
                response.headers.add(key, value)
            mark_response_safe_for_http_origin(response)
            return response

        response = web.StreamResponse(status=upstream.status, reason=upstream.reason)
        for key, value in copy_response_headers(upstream.headers.items(), path=request.path):
            response.headers.add(key, value)
        mark_response_safe_for_http_origin(response)
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await response.write(chunk)
        await response.write_eof()
        return response


async def handler(request: web.Request) -> web.StreamResponse:
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await proxy_websocket(request)
    return await proxy_http(request)


async def on_startup(app: web.Application) -> None:
    app["session"] = ClientSession(
        cookie_jar=DummyCookieJar(),
        max_line_size=64 * 1024,
        max_field_size=64 * 1024,
    )


async def on_cleanup(app: web.Application) -> None:
    await app["session"].close()


app = web.Application(client_max_size=CLIENT_MAX_SIZE)
app.router.add_route("*", "/{tail:.*}", handler)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)


async def main() -> None:
    runner = web.AppRunner(
        app,
        handle_signals=True,
        max_line_size=64 * 1024,
        max_field_size=64 * 1024,
    )
    await runner.setup()
    site = web.TCPSite(runner, host=LISTEN_HOST, port=LISTEN_PORT)
    await site.start()
    print(f"======== Running on http://{LISTEN_HOST}:{LISTEN_PORT} ========", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


asyncio.run(main())
