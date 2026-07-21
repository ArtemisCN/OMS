"""
循环巡检计划生成脚本
由 crontab 每5分钟调用，检查循环计划并生成工单
"""
import sys, os
sys.path.insert(0, '/var/www/hospital-workorder')
os.chdir('/var/www/hospital-workorder')
os.environ.setdefault('SECRET_KEY', 'hospital-workorder-secret-2026')

from wsgi import app
from models import db, InspectionPlan, WorkOrder
from datetime import datetime, timedelta
import calendar


def generate_inspection_order(plan):
    """生成巡检工单（与 inspection.py 逻辑一致）"""
    from models import WorkOrder
    tpl = plan.template
    if not tpl:
        return None
    title = f'🔍巡检: {tpl.name} - {plan.building} {plan.department}'.strip()
    if title.endswith('-'):
        title = title[:-2]
    order = WorkOrder(
        title=title, work_type='inspection', fault_type='巡检', device_type='巡检',
        description=f'巡检区域: {plan.building} {plan.floor} {plan.department} {plan.location}',
        building=plan.building, floor=plan.floor, department=plan.department,
        location=plan.location, start_time=datetime.now(), status='pending',
        inspection_data={'template_name': tpl.name, 'items': [{'name': item, 'result': None} for item in tpl.items]},
        created_by='系统(巡检)'
    )
    db.session.add(order)
    db.session.flush()
    ids = list(plan.work_order_ids or [])
    ids.append(order.id)
    plan.work_order_ids = ids
    plan.last_generated_at = datetime.now()
    return order


with app.app_context():
    now = datetime.now()
    recurring = InspectionPlan.query.filter(
        InspectionPlan.status == 'pending',
        InspectionPlan.schedule_type.in_(['daily', 'workday', 'monthly'])
    ).all()

    generated = 0
    for plan in recurring:
        should_run = False
        try:
            h, m = map(int, (plan.schedule_time or '09:00').split(':'))
        except:
            continue

        if plan.schedule_type == 'daily':
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                last = plan.last_generated_at
                if last is None or last.date() < now.date():
                    should_run = True

        elif plan.schedule_type == 'workday':
            if now.weekday() < 5:
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    last = plan.last_generated_at
                    if last is None or last.date() < now.date():
                        should_run = True

        elif plan.schedule_type == 'monthly':
            day = min(plan.schedule_day or 1, 28)
            if now.day == day:
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    last = plan.last_generated_at
                    if last is None or (last.month != now.month or last.year != now.year):
                        should_run = True

        if should_run:
            order = generate_inspection_order(plan)
            if order:
                generated += 1
                if plan.schedule_type in ('daily', 'workday'):
                    plan.scheduled_time = now + timedelta(days=1)
                elif plan.schedule_type == 'monthly':
                    nm = now.month % 12 + 1
                    ny = now.year + (1 if now.month == 12 else 0)
                    md = calendar.monthrange(ny, nm)[1]
                    d = min(plan.schedule_day or 1, md)
                    plan.scheduled_time = now.replace(year=ny, month=nm, day=d, hour=h, minute=m, second=0, microsecond=0)

    db.session.commit()
    if generated:
        print(f'[INSPECTION-RECUR] {now.strftime("%Y-%m-%d %H:%M")} 生成 {generated} 条循环巡检工单')
    else:
        print(f'[INSPECTION-RECUR] {now.strftime("%Y-%m-%d %H:%M")} 无到期循环计划')
