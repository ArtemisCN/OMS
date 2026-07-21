#!/bin/bash
# ============================================================
# 医院工单系统 — 自动清理脚本
# 清理内容：
#   1. 过期手机令牌（超过 30 天未使用）
#   2. SQLite VACUUM 回收空间
#   3. SQLite WAL 检查点
#   4. gunicorn 日志（仅保留最近 30 天）
#   5. nginx 日志（仅保留最近 7 天）
#   6. journald 系统日志（仅保留最近 7 天）
#   7. 系统 syslog（仅保留最近 7 天）
# ============================================================
# 配置
RETENTION_DAYS=180           # 已完成工单保留天数
JOURNAL_DAYS=7               # 系统日志保留天数
NGINX_LOG_DAYS=7             # nginx 日志保留天数
GUNICORN_LOG_DAYS=30         # gunicorn 日志保留天数
TOKEN_EXPIRE_DAYS=30           # 手机令牌过期天数

APP_DIR="/var/www/hospital-workorder"
VENV_PYTHON="$APP_DIR/venv/bin/python3"
GUNICORN_LOG="/var/log/hospital-workorder.log"
NGINX_LOG_DIR="/var/log/nginx"
NOW=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$NOW] ====== 开始自动清理 ======"

# ------ 1. 清理过期手机令牌 ------
echo "[$NOW] 1/8 清理过期手机令牌（超过 ${TOKEN_EXPIRE_DAYS} 天）..."
cd "$APP_DIR" 2>/dev/null || { echo "ERROR: $APP_DIR 不存在"; exit 1; }

"$VENV_PYTHON" -c "
import sys, os
sys.path.insert(0, '$APP_DIR')
os.environ['WECHAT_APPID'] = 'dummy'
os.environ['WECHAT_SECRET'] = 'dummy'
os.environ['WECHAT_TEMPLATE_ID'] = 'dummy'
from app import create_app
from models import db, MobileToken
from datetime import datetime, timedelta

app = create_app()
with app.app_context():
    token_cutoff = datetime.now() - timedelta(days=$TOKEN_EXPIRE_DAYS)
    old_tokens = MobileToken.query.filter(
        MobileToken.created_at < token_cutoff
    ).all()
    token_count = len(old_tokens)
    for t in old_tokens:
        db.session.delete(t)
    db.session.commit()
    print(f'已删除过期令牌: {token_count} 条')
" 2>&1 || echo "WARNING: 令牌清理异常"

# ------ 2. SQLite VACUUM 回收空间 ------
echo "[$NOW] 2/8 执行 SQLite VACUUM 回收空间..."
"$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '$APP_DIR')
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    db.session.execute(text('VACUUM'))
    db.session.commit()
    print('SQLite VACUUM 完成')
" 2>&1 || echo "WARNING: VACUUM 异常"

# ------ 3. SQLite WAL 检查点 ------
echo "[$NOW] 3/8 SQLite WAL 检查点..."
"$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '$APP_DIR')
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    db.session.execute(text('PRAGMA wal_checkpoint(TRUNCATE);'))
    db.session.commit()
    print('WAL 检查点完成')
" 2>&1 || echo "WARNING: WAL 检查点异常"

# ------ 4. 清理 gunicorn 日志 ------
echo "[$NOW] 4/8 清理 gunicorn 日志（保留 ${GUNICORN_LOG_DAYS} 天）..."
if [ -f "$GUNICORN_LOG" ]; then
    if [ $(wc -l < "$GUNICORN_LOG") -gt 1000 ]; then
        tail -n 5000 "$GUNICORN_LOG" > "${GUNICORN_LOG}.tmp" && mv "${GUNICORN_LOG}.tmp" "$GUNICORN_LOG"
        echo 'gunicorn日志已截断'
    else
        echo 'gunicorn日志较小，无需截断'
    fi
else
    echo "gunicorn日志不存在"
fi

# ------ 5. 清理 nginx 日志 ------
echo "[$NOW] 5/8 清理 nginx 日志（保留 ${NGINX_LOG_DAYS} 天）..."
if [ -d "$NGINX_LOG_DIR" ]; then
    find "$NGINX_LOG_DIR" -name 'access.log*' -o -name 'error.log*' | while read f; do
        if [ -f "$f" ] && [ "$(find "$f" -mtime +${NGINX_LOG_DAYS} 2>/dev/null)" ]; then
            : > "$f"
            echo "清空: $f"
        fi
    done
else
    echo "nginx日志目录不存在"
fi

# ------ 6. 清理 journald 日志 ------
echo "[$NOW] 6/8 清理 journald 日志（保留 ${JOURNAL_DAYS} 天）..."
journalctl --vacuum-time="${JOURNAL_DAYS}d" 2>/dev/null && echo "journald 清理完成" || echo "WARNING: journald 清理失败"

# ------ 7. 清理系统 syslog ------
echo "[$NOW] 7/8 清理 syslog..."
if [ -f /var/log/syslog ]; then
    if [ -f /var/log/syslog.1 ]; then
        rm -f /var/log/syslog.1 /var/log/syslog.2.gz /var/log/syslog.3.gz 2>/dev/null
        : > /var/log/syslog
        echo 'syslog 已清理'
    else
        echo 'syslog 无需清理'
    fi
fi

# ------ 8. 报告磁盘使用情况 ------
echo "[$NOW] 8/8 磁盘使用情况..."
echo "磁盘: $(df -h / | tail -1 | awk '{print $3, "/", $2, "(" $5 ")"}')"

echo "[$NOW] ====== 自动清理完成 ======"
echo ""
