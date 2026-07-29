"""
工单自动升级脚本：未接单工单超过时限自动升优先级
- 超过15分钟未接单：normal → urgent（加急🟡）
- 超过30分钟未接单：urgent → emergency（紧急🔴）
- emergency 不再升级
"""
import sys, os
sys.path.insert(0, '/var/www/hospital-workorder')
os.chdir('/var/www/hospital-workorder')

from wsgi import app
from models import db, WorkOrder
from datetime import datetime, timedelta

with app.app_context():
    now = datetime.now()
    deadline_15 = now - timedelta(minutes=15)
    deadline_30 = now - timedelta(minutes=30)

    escalated = {'normal_to_urgent': 0, 'urgent_to_emergency': 0}

    # 查找超15分钟还未接单的 normal 工单 → 升urgent
    orders = WorkOrder.query.filter(
        WorkOrder.status == 'pending',
        WorkOrder.priority == 'normal',
        WorkOrder.created_at <= deadline_15,
    ).all()
    for o in orders:
        o.priority = 'urgent'
        escalated['normal_to_urgent'] += 1

    # 查找超30分钟还未接单的 urgent 工单 → 升emergency
    orders = WorkOrder.query.filter(
        WorkOrder.status == 'pending',
        WorkOrder.priority == 'urgent',
        WorkOrder.created_at <= deadline_30,
    ).all()
    for o in orders:
        o.priority = 'emergency'
        escalated['urgent_to_emergency'] += 1

    db.session.commit()

    total = escalated['normal_to_urgent'] + escalated['urgent_to_emergency']
    if total > 0:
        print(f'[AUTO-ESCALATE] {now.strftime("%Y-%m-%d %H:%M")} | '
              f'normal→urgent: {escalated["normal_to_urgent"]} | '
              f'urgent→emergency: {escalated["urgent_to_emergency"]}')
    else:
        print(f'[AUTO-ESCALATE] {now.strftime("%Y-%m-%d %H:%M")} | 无需升级')
