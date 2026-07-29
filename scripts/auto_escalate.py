"""
工单自动升级脚本：未接单工单超过时限自动升优先级
- 超过15分钟未接单：normal → urgent（加急🟡）
- 超过30分钟未接单：urgent → emergency（紧急🔴）
- emergency 不再升级

多院区兼容：遍历所有医院分别处理，确保每所医院的工单按各自时限升级
"""
import sys, os
sys.path.insert(0, '/var/www/hospital-workorder')
os.chdir('/var/www/hospital-workorder')

from wsgi import app
from models import db, WorkOrder, Hospital
from datetime import datetime, timedelta

with app.app_context():
    now = datetime.now()
    deadline_15 = now - timedelta(minutes=15)
    deadline_30 = now - timedelta(minutes=30)

    escalated = {'normal_to_urgent': 0, 'urgent_to_emergency': 0}

    # 获取所有活跃医院，逐院处理
    hospitals = Hospital.query.filter_by(is_active=True).all()
    if not hospitals:
        hospitals = [None]  # 兜底：无医院配置时全量处理

    for hospital in hospitals:
        hid = hospital.id if hospital else None

        q = WorkOrder.query.filter(
            WorkOrder.status == 'pending',
            WorkOrder.created_at <= deadline_15,
        )
        if hid:
            q = q.filter(WorkOrder.hospital_id == hid)

        # 超15分钟未接单的 normal → urgent
        normal_orders = q.filter(WorkOrder.priority == 'normal').all()
        for o in normal_orders:
            o.priority = 'urgent'
        escalated['normal_to_urgent'] += len(normal_orders)

        # 超30分钟未接单的 urgent → emergency
        urgent_orders = q.filter(WorkOrder.priority == 'urgent').all()
        for o in urgent_orders:
            o.priority = 'emergency'
        escalated['urgent_to_emergency'] += len(urgent_orders)

    db.session.commit()

    total = escalated['normal_to_urgent'] + escalated['urgent_to_emergency']
    if total > 0:
        print(f'[AUTO-ESCALATE] {now.strftime("%Y-%m-%d %H:%M")} | '
              f'normal→urgent: {escalated["normal_to_urgent"]} | '
              f'urgent→emergency: {escalated["urgent_to_emergency"]}')
    else:
        print(f'[AUTO-ESCALATE] {now.strftime("%Y-%m-%d %H:%M")} | 无需升级')
