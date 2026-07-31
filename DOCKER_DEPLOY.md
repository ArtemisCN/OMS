# Docker 化部署指南（2026-07-31 新增）

## 文件清单
- `Dockerfile` — python:3.12-slim，非 root（appuser uid=10001），healthcheck 三件套
- `docker-compose.yml` — web + cron sidecar 双服务
- `.dockerignore` — 排除 .git/venv/instance DB/.secret/.env/bak

## 启动步骤（在装有 Docker 的服务器上）
```bash
# 1. 准备 .env（生产密钥：SECRET_KEY / WECHAT_APPID / WECHAT_SECRET / WECOM_WEBHOOK_URL）
cp .env.example .env   # 手工填写真实密钥（.env 已在 .gitignore/.dockerignore 排除）

# 2. 构建并启动
docker compose up -d --build

# 3. 验证
curl http://127.0.0.1:5000/health          # {"status":"ok","database":"ok"}
docker compose ps                          # web: healthy / cron: running
docker compose logs -f web                 # gunicorn 启动日志
```

## 数据卷（必须持久化，删除 = 丢数据）
| 卷 | 挂载点 | 内容 |
|---|---|---|
| workorder_data | /app/instance | SQLite 数据库（含 -wal/-shm）|
| workorder_uploads | /app/uploads | 上传文件 |
| workorder_secret | /app/.secret | SECRET_KEY（重建变化 → 全部 session 失效）|

## 与生产 systemd 部署的关系
- **当前生产仍在 systemd**（`hospital-workorder.service`，gunicorn 3w --preload），nginx 反代 HTTPS → 127.0.0.1:5000
- Docker 化是**可选的容器化路径**，两者不冲突：docker 版本绑定 127.0.0.1:5000 与 nginx 反代兼容
- 切换时迁移数据：`instance/workorders.db` + `.secret` + `uploads/` 三个目录整体搬入卷

## cron 调度（docker 版 vs systemd 版）
| 脚本 | 宿主 crontab（当前） | Docker cron sidecar |
|---|---|---|
| auto_escalate.py | */5 * * * * | ✅ 已配 */
| inspection_recurring.py | */5 * * * * | ✅ 已配 |
| health_monitor.py | 0 8 * * * | ✅ 已配 |
| cleanup.sh（宿主级：nginx/journald 日志） | 0 3 * * 7 | ❌ 留宿主 cron（容器内无 nginx/journald）|

## 已知注意事项
1. WAL 已由 models.py 全局事件启用（PRAGMA journal_mode=WAL + synchronous=NORMAL），无需额外配置
2. `SESSION_COOKIE_SECURE=1` 已在 compose 环境变量开启（生产 HTTPS 必需）；本地 HTTP 测试时移除
3. 首次启动 `instance/` 为空 → wsgi.py 的 db.create_all 自动建表（见 wsgi-bootstrap-instance-dir 参考）
4. 镜像内 gunicorn 3 worker 与 systemd 一致；--preload 使代码热更新需重启容器
5. `.secret` 卷首次为空 → app.py 启动时生成并写入卷（权限 600）
