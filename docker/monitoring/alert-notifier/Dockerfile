# alert-notifier: 接收 Alertmanager webhook → 推送企业微信/短信
FROM python:3.12-alpine

WORKDIR /app

COPY notifier.py /app/notifier.py

# 非 root 运行
RUN adduser -D -u 10002 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 9119

CMD ["python", "-u", "/app/notifier.py"]
