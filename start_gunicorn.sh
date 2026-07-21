#!/bin/bash
# 启动工单管理系统
cd /var/www/hospital-workorder
source venv/bin/activate
pip install -r requirements.txt -q
pkill -f gunicorn 2>/dev/null
sleep 1
nohup venv/bin/gunicorn -w 3 -b 0.0.0.0:5000 wsgi:app > /var/log/hospital-workorder.log 2>&1 &
echo "gunicorn started, PID: $!"
sleep 2
curl -s -o /dev/null -w "HTTP code: %{http_code}\n" http://localhost:5000/
