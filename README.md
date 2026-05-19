
# ChatGPT Mirror

ChatGPT Mirror 是一个由 Vue 管理后台、Django 后台服务、Cloudflare Bypass 辅助服务和 Docker 编排组成的镜像站管理项目。

> 维护完成。
>
> 说明：`Gateway/` 目录在本文档中声明为空目录/预留目录，不包含在本 README 的目录结构、功能说明和使用说明中。

## 功能概览

- 管理后台：基于 Vue 3、Vite、Pinia、Vue Router 和 TDesign Vue Next。
- 用户管理：支持用户列表、注册配置、免费账号登录、用户过期时间、模型限制和备注管理。
- ChatGPT 账号管理：支持账号登录、账号枚举、Token 有效性诊断、Token 过期检查和账号备注。
- 号池管理：支持 ChatGPT 账号分组、用户绑定号池和号池枚举。
- 访问日志：记录用户、ChatGPT 账号、登录类型、IP、User-Agent 和访问时间。
- 代理配置：支持代理配置读取、保存和测试。
- 自定义脚本配置：支持后台接口维护脚本配置。
- Cloudflare Bypass：提供基于 FastAPI、DrissionPage 和 Chromium 的可选辅助服务。
- Docker 部署：提供 `docker-compose.yml` 和 `vps-docker-compose.yml` 编排文件。

## 当前排障快照

这个仓库是用于 GPT-5.5 Pro 分析的脱敏快照。运行时数据库、`.env`、日志、cookie 导出、access token、session token、构建产物均未上传。

重点看：

- `docs/current-debug-context.md`
- `docs/GPT55Pro-prompt.md`
- `edge-proxy/proxy.py`
- `docker-compose.yml`
- `cfbypass/app.py`
