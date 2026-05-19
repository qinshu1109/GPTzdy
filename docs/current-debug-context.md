# Current Debug Context

This repository is a sanitized snapshot of a cloud deployment used to debug `chatgpt-mirror`.
Runtime databases, `.env`, logs, cookie exports, access tokens, session tokens, and generated static bundles are intentionally excluded.

## Deployment

- Public URL during debugging: `http://167.254.240.189:50002`
- Docker services:
  - `chatgpt-mirror`: Rust gateway image `lisa666520/chatgpt-mirror-django:frontend`, internal port `50003`
  - `django`: backend image `lisa666520/chatgpt-mirror-django:backend`
  - `cfbypass`: Cloudflare bypass service
  - `edge-proxy`: local aiohttp reverse proxy on public port `50002`

## Fixes Already Applied

- Added `cfbypass` endpoint `POST /cfbypass/collect` and simplified returned cookie entries to `{name, value}`.
- Stopped passing `CF_BYPASS_PROXY_SERVER` to the Rust gateway so internal requests to `cfbypass` do not accidentally go through an external proxy.
- Added `edge-proxy` to inject a `crypto.randomUUID` polyfill for HTTP bare-IP deployments.
- Changed the admin frontend hash history base from `/admin/` to `/admin`.
- Prefer Web/mixed login mode when a ChatGPT account has a valid session token.
- Filtered browser cookies in `edge-proxy` for ChatGPT routes so stale browser `__Secure-next-auth*` cookies do not collide with gateway-injected DB cookies.
- Disabled the aiohttp client cookie jar in `edge-proxy` to avoid upstream `Set-Cookie` values being replayed on later requests.

## Current Verified State

- Admin page loads.
- ChatGPT Web page logs in and `/api/auth/session` returns a user.
- `cfbypass` can collect `cf_clearance`; `/api/refresh-cfbypass` has previously returned 200 after configuration fixes.
- The user now sees the ChatGPT page greeting the account by name.

## Remaining Broken Behavior

- Sending a message leaves the UI stuck at "thinking".
- File upload fails with the red toast text: `因网络问题上传失败。请检查网络连接后重试。`
- The floating status sometimes shows `CFToken失效` again after the page is loaded.

## Files Most Relevant For Analysis

- `edge-proxy/proxy.py`
- `docker-compose.yml`
- `cfbypass/app.py`

