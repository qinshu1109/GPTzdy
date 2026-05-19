# Session Isolation Investigation Context

This repository is a sanitized deployment/debug snapshot for `Jasa-Chi-Ray/chatgpt-mirror`.
It intentionally excludes `.env`, databases, logs, cookies, tokens, and account secrets.

## Current Deployment Shape

- Public mirror/admin domain: `https://167.254.240.189.sslip.io/`
- Admin path: `/admin#/`
- Docker Compose services:
  - `edge-proxy`: public reverse proxy on port `50002`
  - `chatgpt-mirror`: Rust gateway image on internal port `50003`
  - `django`: backend/admin API
  - `cfbypass`: Cloudflare cookie collector
- `docker-compose.yml` keeps Rust gateway and `cfbypass` on the same outbound proxy.
- `edge-proxy` preserves streaming, WebSocket, upload bodies, forwarded proto, and runtime cookies while filtering auth cookies that can conflict with gateway-managed auth.

## User-Visible Issue To Analyze Next

The mirror can now log in, send messages, and upload files. However, account/session isolation appears ineffective.

Desired behavior:

- Different local users should bind to independent ChatGPT Web/API sessions.
- User A should consistently use only the ChatGPT account/session assigned through their pool.
- User B should use a different assigned ChatGPT account/session.
- Chat history, gateway session, mirror token, usage counters, and upstream auth cookies should not bleed between local users.
- Browser cookies from one local user should not cause another local user to inherit the same ChatGPT session.

Observed/suspected behavior:

- User management has `gptcar_list` on `accounts.User`.
- Pools are represented by `chatgpt.ChatgptCar.gpt_account_list`.
- Backend account selection uses `ChatgptAccount.get_by_gptcar_list(user.gptcar_list)`.
- Gateway login payload includes `user_name`, `access_token`, `session_token`, `extra_cookies`, `login_mode`, and `isolated_session`.
- There is an `isolated_session` flag on local users, but it may not be enough if browser cookies or gateway session keys are shared globally.
- Need determine whether isolation should be implemented at Django pool binding, gateway session keying, browser cookie names, mirror token issue, or all of the above.

## Local Source Files Relevant To Inspect Upstream

If this snapshot does not include enough source, inspect the upstream project `Jasa-Chi-Ray/chatgpt-mirror` and focus on these paths:

- `backend/app/accounts/models.py`
- `backend/app/accounts/serializers.py`
- `backend/app/accounts/views/__init__.py`
- `backend/app/accounts/views/login.py`
- `backend/app/chatgpt/models.py`
- `backend/app/chatgpt/views/chatgpt.py`
- `backend/app/chatgpt/views/gptcar.py`
- `frontend/src/pages/account/user.vue`
- `frontend/src/pages/account/gptcar.vue`
- `frontend/src/pages/account/chatgpt.vue`
- `frontend/src/pages/login/chatgpt.vue`
- `frontend/src/store/user.ts`
- `frontend/src/api/request.ts`
- `frontend/src/router/index.ts`
- `docker-compose.yml`
- `edge-proxy/proxy.py`
- `cfbypass/app.py`

## Constraints

- Do not require leaking or printing tokens/cookies.
- Keep fixes minimal and compatible with the existing Docker images when possible.
- The public upstream Rust gateway source is not included in full; infer gateway behavior from API contracts, DB schema, binary behavior, and Django/Vue code.
- If Rust gateway changes are required, describe exact expected behavior and fallback workarounds in Django/edge-proxy.
