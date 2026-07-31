#!/usr/bin/env python3
"""告警推送接收服务 — 接收 Alertmanager webhook，推送企业微信 + 短信

协议:
  POST /alert  (Alertmanager webhook 格式)
  企业微信: POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send (markdown)
  短信:     POST {sms_api_url}  json={phone, content, api_key}

配置 (环境变量):
  WECOM_WEBHOOK  企业微信机器人 webhook 地址（可空=不推送微信）
  SMS_API_URL    短信 API 地址（可空=不推送短信）
  SMS_API_KEY    短信 API Key
  SMS_PHONE      接收告警短信的手机号
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

WECOM_WEBHOOK = os.environ.get('WECOM_WEBHOOK', '')
SMS_API_URL = os.environ.get('SMS_API_URL', '')
SMS_API_KEY = os.environ.get('SMS_API_KEY', '')
SMS_PHONE = os.environ.get('SMS_PHONE', '')
# 系统设置数据库（可选）：notifier 可直接读工单系统的短信配置，无需重复填 env
DB_PATH = os.environ.get('DB_PATH', '/app/instance/workorders.db')

# 告警冷却：同一 alert 10 分钟内只推一次，避免刷屏
_cooldown = {}
_COOLDOWN_SECONDS = 600


def _get_setting(key, default=''):
    """从系统设置数据库读取配置（env 优先）"""
    if not DB_PATH or not os.path.exists(DB_PATH):
        return default
    try:
        conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=3)
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key=? ORDER BY id LIMIT 1",
            (key,)
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else default
    except Exception:
        return default


def _load_sms_config():
    """加载短信配置：env 优先，其次系统设置"""
    api_url = SMS_API_URL or _get_setting('sms_api_url')
    api_key = SMS_API_KEY or _get_setting('sms_api_key')
    enabled = _get_setting('sms_enabled') == '1'
    return api_url, api_key, enabled


def _fingerprint(alert):
    return f"{alert.get('labels', {}).get('alertname', '')}|{alert.get('labels', {}).get('instance', '')}"


def _is_throttled(fp):
    now = time.time()
    last = _cooldown.get(fp, 0)
    if now - last < _COOLDOWN_SECONDS:
        return True
    _cooldown[fp] = now
    # 清理
    for k in [k for k, v in _cooldown.items() if now - v > _COOLDOWN_SECONDS * 2]:
        _cooldown.pop(k, None)
    return False


def _send_wecom(text):
    """推送企业微信机器人"""
    if not WECOM_WEBHOOK:
        return False, '未配置 WECOM_WEBHOOK'
    try:
        req = urllib.request.Request(
            WECOM_WEBHOOK,
            data=json.dumps({"msgtype": "markdown", "markdown": {"content": text}}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if resp.get('errcode') == 0:
            return True, 'ok'
        return False, f"errcode={resp.get('errcode')} {resp.get('errmsg')}"
    except Exception as e:
        return False, str(e)


def _send_sms(content):
    """发送短信（动态读取系统设置配置）"""
    api_url, api_key, enabled = _load_sms_config()
    if not enabled:
        return False, '短信功能未启用'
    if not api_url:
        return False, '未配置 SMS_API_URL'
    if not SMS_PHONE:
        return False, '未配置接收手机号 (ALERT_SMS_PHONE)'
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps({
                'phone': SMS_PHONE,
                'content': content,
                'api_key': api_key,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200, f'HTTP {resp.status}'
    except Exception as e:
        return False, str(e)


def _format_alert(alert):
    """格式化单条告警为可读文本"""
    labels = alert.get('labels', {})
    annotations = alert.get('annotations', {})
    name = labels.get('alertname', '未知告警')
    severity = labels.get('severity', 'unknown')
    status = alert.get('status', 'firing')

    icon = '🔴' if severity == 'critical' else '🟡'
    status_txt = '🔥 触发' if status == 'firing' else '✅ 恢复'
    lines = [
        f"{icon} **{name}** {status_txt}",
        f"---",
        f"**级别**: {'严重' if severity == 'critical' else '警告'}",
    ]
    if annotations.get('summary'):
        lines.append(f"**摘要**: {annotations['summary']}")
    if annotations.get('description'):
        lines.append(f"**详情**: {annotations['description'][:120]}")
    if labels.get('instance'):
        lines.append(f"**实例**: {labels['instance']}")
    started = alert.get('startsAt', '')
    if started:
        lines.append(f"**时间**: {started.replace('T', ' ').replace('Z', '')[:19]}")
    return '\n'.join(lines)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(body or b'{}')
            alerts = payload.get('alerts', [])

            results = []
            for alert in alerts:
                fp = _fingerprint(alert)
                if _is_throttled(fp):
                    results.append(f"{alert.get('labels', {}).get('alertname', '')}: 冷却期内跳过")
                    continue
                text = _format_alert(alert)

                # 企业微信
                ok_w, msg_w = _send_wecom(text)
                # 短信（仅 critical 或故障触发时发送）
                ok_s, msg_s = ('skipped', '非严重级别')
                if alert.get('status') == 'firing' and alert.get('labels', {}).get('severity') == 'critical':
                    sms_text = f"[告警]{alert.get('labels', {}).get('alertname', '')} {alert.get('annotations', {}).get('summary', '')[:60]}"
                    ok_s, msg_s = _send_sms(sms_text)
                results.append(
                    f"{alert.get('labels', {}).get('alertname', '')}: 微信{'✓' if ok_w else '✗'} 短信{'✓' if ok_s else '✗'} ({msg_w}/{msg_s})"
                )

            resp_body = json.dumps({'success': True, 'results': results}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
            print(f"[{time.strftime('%H:%M:%S')}] 处理 {len(alerts)} 条告警: {results}", flush=True)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            resp_body = json.dumps({'success': False, 'error': str(e)}).encode()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '9119'))
    print(f"alert-notifier 启动: 0.0.0.0:{port}")
    print(f"  企业微信: {'已配置' if WECOM_WEBHOOK else '未配置'}")
    print(f"  短信: {'已配置 ' + SMS_API_URL if SMS_API_URL else '未配置'}")
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
