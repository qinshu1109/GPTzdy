# Prompt For GPT-5.5 Pro

Please analyze the public GitHub repo `qinshu1109/GPTzdy`, which is a sanitized snapshot of a `Jasa-Chi-Ray/chatgpt-mirror` deployment.

Important: runtime databases, `.env`, logs, cookie exports, access tokens, session tokens, and generated static bundles were intentionally removed from the repo. Do not ask for real tokens in the answer.

Current deployment facts:

- Public URL during debugging: `http://167.254.240.189:50002`
- Services:
  - `chatgpt-mirror`: Rust gateway image `lisa666520/chatgpt-mirror-django:frontend`, internal port `50003`
  - `django`: backend image `lisa666520/chatgpt-mirror-django:backend`
  - `cfbypass`: Cloudflare bypass service
  - `edge-proxy`: custom aiohttp reverse proxy on port `50002`
- Login now works: the ChatGPT Web page greets the account by name, and `/api/auth/session` returns a logged-in user.
- Remaining failures:
  - Sending a message stays on "thinking" and never returns a model response.
  - File upload shows `因网络问题上传失败。请检查网络连接后重试。`
  - The floating status sometimes still shows `CFToken失效`.

Already applied fixes:

- `cfbypass/app.py` now adds `POST /cfbypass/collect`, returns simplified `{name, value}` cookies, and can default to `CF_BYPASS_PROXY_SERVER`.
- `docker-compose.yml` runs the Rust gateway internally on `50003` and exposes a new `edge-proxy` on public `50002`.
- The Rust gateway no longer receives `CF_BYPASS_PROXY_SERVER`, avoiding accidental proxying of internal `http://cfbypass:8000`.
- `edge-proxy/proxy.py` injects a `crypto.randomUUID` polyfill for HTTP bare-IP usage.
- `edge-proxy/proxy.py` uses `DummyCookieJar`, filters browser cookies on non-local ChatGPT routes to `mirror_token`, `gateway_user_name`, and `login_mode`, and suppresses upstream `Set-Cookie` on non-local ChatGPT routes.

Please inspect the repo and answer:

1. Why can `/api/auth/session` be logged in while conversation responses and uploads still fail?
2. Is `edge-proxy/proxy.py` breaking streaming, SSE, WebSocket, multipart upload, request headers, response headers, or required cookies?
3. Does the Rust gateway likely need browser cookies beyond `mirror_token`, `gateway_user_name`, and `login_mode` for `/backend-api/conversation`, file upload endpoints, or websocket paths?
4. Should `edge-proxy` stop stripping `Set-Cookie` for some paths, or should it strip only ChatGPT auth cookies while preserving gateway/session cookies?
5. Are `content-length`, `origin`, `referer`, `sec-fetch-*`, `accept-encoding`, CORS, or websocket upgrade headers mishandled?
6. Could the remaining failure instead be stale/expired `cf_clearance` or missing full ChatGPT cookies such as `_puid`, `oai-*`, `__Secure-oai-is`, `_cfuvid`, `__cf_bm`, or `__cflb`?
7. What exact browser Network requests should be captured next, and what log commands should be run, without leaking tokens?
8. Provide a minimal patch plan with exact file/function changes, especially for `edge-proxy/proxy.py` and `docker-compose.yml`.

Please prioritize a practical fix over theory. The desired result is: logged-in ChatGPT page can send messages, receive streaming responses, and upload files through the mirror.
