from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web


UPSTREAM = os.environ.get("UPSTREAM", "http://chatgpt-mirror:50003").rstrip("/")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "50002"))

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

CHATGPT_ROUTE_COOKIE_ALLOWLIST = {
    "mirror_token",
    "gateway_user_name",
    "login_mode",
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


def sanitize_cookie_header(value: str) -> str:
    parts: list[str] = []
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if name in CHATGPT_ROUTE_COOKIE_ALLOWLIST:
            parts.append(part)
    return "; ".join(parts)


def request_headers(request: web.Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP or lower == "host":
            continue
        if lower == "cookie" and not is_local_route(request.path):
            value = sanitize_cookie_header(value)
            if not value:
                continue
        headers[key] = value
    headers["Accept-Encoding"] = "identity"
    return headers


def copy_response_headers(headers: Iterable[tuple[str, str]], *, preserve_set_cookie: bool) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    for key, value in headers:
        lower = key.lower()
        if lower in HOP_BY_HOP or lower in {"content-length", "content-encoding"}:
            continue
        if lower == "set-cookie" and not preserve_set_cookie:
            continue
        copied.append((key, value))
    return copied


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
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)

    target = upstream_url(request).replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    session: ClientSession = request.app["session"]

    async with session.ws_connect(target, headers=request_headers(request), timeout=ClientTimeout(total=None)) as ws_upstream:
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

        await asyncio.gather(client_to_upstream(), upstream_to_client())
    return ws_client


async def proxy_http(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["session"]
    body = await request.read()
    preserve_set_cookie = is_local_route(request.path)
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
            for key, value in copy_response_headers(upstream.headers.items(), preserve_set_cookie=preserve_set_cookie):
                response.headers.add(key, value)
            return response

        response = web.StreamResponse(status=upstream.status, reason=upstream.reason)
        for key, value in copy_response_headers(upstream.headers.items(), preserve_set_cookie=preserve_set_cookie):
            response.headers.add(key, value)
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


app = web.Application(client_max_size=128 * 1024**2)
app.router.add_route("*", "/{tail:.*}", handler)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT)
