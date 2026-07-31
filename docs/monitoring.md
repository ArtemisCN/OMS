# 医院工单系统 · Docker 监控告警

## 架构

```
业务流量 → Nginx(容器) → web(容器:5000) → Prometheus 抓取 /metrics
                                              ↓
                                        Grafana(3001) 可视化
```

## 服务清单（docker compose）

| 服务 | 容器名 | 端口 | 说明 |
|---|---|---|---|
| web | hospital-workorder-web | 127.0.0.1:5000 | gunicorn 主服务，暴露 /metrics |
| cron | hospital-workorder-cron | - | 定时任务 sidecar |
| nginx | hospital-workorder-nginx | 80/443 | 反向代理（host 网络） |
| prometheus | hospital-workorder-prometheus | 127.0.0.1:9090 | 指标采集 + 告警评估 |
| grafana | hospital-workorder-grafana | 127.0.0.1:3001 | 可视化仪表盘 |

## 访问方式

- **Grafana**: `http://<服务器IP>:3001`，账号 admin / 密码在 `.env` 的 `GRAFANA_ADMIN_PASSWORD`
- **Prometheus API**: `http://127.0.0.1:9090/api/v1/query?query=<PromQL>`
- **web /metrics**: `http://127.0.0.1:5000/metrics`（仅内网）

## 告警规则（5条，docker/monitoring/alert_rules.yml）

| 规则 | 触发条件 | 严重度 |
|---|---|---|
| WebServiceDown | up 指标 = 0 持续 1m | critical |
| HighCPUUsage | 进程 CPU > 80% 持续 5m | warning |
| High5xxRate | 5xx 占比 > 5% 持续 5m | warning |
| SlowResponse | P95 响应 > 3s 持续 5m | warning |
| RequestRateDrop | QPS < 0.05 持续 15m | warning |

告警目前为 Prometheus 内部状态（Alertmanager 未部署，轻量版）。
查看触发状态：`curl http://127.0.0.1:9090/api/v1/alerts`

## Grafana 仪表盘

- 预置：「医院工单系统 · 运行监控」uid=`hospital-workorder-overview`
- 面板：服务健康 / QPS / 5xx错误率 / P95响应时间 / CPU使用率
- provisioning 自动导入（`docker/monitoring/grafana/provisioning/`）

## 运维命令

```bash
cd /var/www/hospital-workorder

# 查看全部容器
sudo docker compose ps

# 查看 Prometheus 抓取目标
curl http://127.0.0.1:9090/api/v1/targets

# 查看告警
curl http://127.0.0.1:9090/api/v1/alerts

# 更新告警规则后热加载
sudo docker kill -s SIGHUP hospital-workorder-prometheus
# 或
curl -X POST http://127.0.0.1:9090/-/reload

# Grafana 数据持久化：grafana_data 卷
# Prometheus 数据持久化：prometheus_data 卷（保留 30 天）
```

## 安全说明

- `/metrics` 端点无认证，但仅绑定 127.0.0.1（host 网络），外网不可达
- Grafana 管理员密码在 `.env` 中（`GRAFANA_ADMIN_PASSWORD`），不在 git 中
- Prometheus/Grafana 端口仅监听 127.0.0.1，如需外网访问需额外加 Nginx 反代 + 认证
