from utils.csrf import csrf_protect
from utils.permissions import has_permission
"""SLA Blueprint: SLA 时限监控"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from models import db, WorkOrder, SystemSetting
from utils.time_helpers import fmt_dt

sla_bp = Blueprint('sla', __name__, url_prefix='/sla')


def _get_sla_thresholds():
    """从 SystemSetting 读取 SLA 阈值"""
    def get_val(key, default):
        s = SystemSetting.query.filter_by(key=key).first()
        return s.value if s and s.value else default

    return {
        'emergency': {
            'response': float(get_val('sla_response_emergency', '0.5')),
            'resolution': float(get_val('sla_resolution_emergency', '2')),
        },
        'urgent': {
            'response': float(get_val('sla_response_urgent', '2')),
            'resolution': float(get_val('sla_resolution_urgent', '8')),
        },
        'normal': {
            'response': float(get_val('sla_response_normal', '4')),
            'resolution': float(get_val('sla_resolution_normal', '24')),
        },
    }


def _check_overdue(wo, thresholds, now):
    """直接判断工单是否超时"""
    resp_th = thresholds['response']
    resol_th = thresholds['resolution']
    if wo.status == 'completed' and (wo.end_time or wo.completed_at):
        end = wo.end_time or wo.completed_at
        start = wo.start_time or wo.accepted_at or wo.created_at
        if start:
            return (end - start).total_seconds() / 3600 > resol_th
        return False
    elif wo.status == 'in_progress' and wo.accepted_at:
        return (now - wo.accepted_at).total_seconds() / 3600 > resol_th
    elif wo.status == 'pending' and wo.created_at:
        return (now - wo.created_at).total_seconds() / 3600 > resp_th
    return False


@sla_bp.route('/dashboard', methods=['GET'])
@login_required
def sla_dashboard():
    """SLA 监控页面"""
    return render_template('feature/sla_dashboard.html',
                           thresholds=_get_sla_thresholds())


@sla_bp.route('/data', methods=['GET'])
@login_required
def sla_data():
    """SLA 数据 JSON"""
    now = datetime.now()
    thresholds = _get_sla_thresholds()

    # 只查最近3个月的工单
    three_months_ago = now - timedelta(days=90)

    all_orders = WorkOrder.query.filter(
        WorkOrder.status.in_(['pending', 'in_progress', 'completed']),
        WorkOrder.created_at >= three_months_ago
    ).order_by(WorkOrder.created_at.desc()).all()

    overdue_list = []
    for wo in all_orders:
        t = thresholds.get(wo.priority, thresholds['normal'])
        is_overdue = _check_overdue(wo, t, now)
        if not is_overdue:
            continue

        cost_hours = None
        if wo.end_time or wo.completed_at:
            end = wo.end_time or wo.completed_at
            start = wo.start_time or wo.accepted_at or wo.created_at
            if start:
                cost_hours = round((end - start).total_seconds() / 3600, 1)
        elif wo.status in ('pending', 'in_progress') and wo.created_at:
            cost_hours = round((now - wo.created_at).total_seconds() / 3600, 1)

        display_time = ''
        if cost_hours is not None:
            if cost_hours >= 24:
                days = int(cost_hours // 24)
                hours = int(cost_hours % 24)
                display_time = f'{days}d{hours}h'
            else:
                display_time = f'{cost_hours}h'

        overdue_list.append({
            'id': wo.id,
            'title': wo.title,
            'priority': wo.priority,
            'status': wo.status,
            'person': wo.person,
            'department': wo.department,
            'created_at': fmt_dt(wo.created_at, '%Y-%m-%d %H:%M'),
            'cost_hours': cost_hours,
            'display_time': display_time,
        })

    total_count = len(all_orders)
    by_priority = {}
    for pri in ['normal', 'urgent', 'emergency']:
        t = thresholds.get(pri, thresholds['normal'])
        pri_orders = [wo for wo in all_orders if wo.priority == pri]
        total = len(pri_orders)
        overdue = sum(1 for wo in pri_orders if _check_overdue(wo, t, now))
        by_priority[pri] = {
            'total': total,
            'overdue': overdue,
            'rate': round(overdue / total * 100, 1) if total > 0 else 0,
        }

    return jsonify(success=True, overdue_count=len(overdue_list),
                   total_count=total_count, overdue_list=overdue_list,
                   by_priority=by_priority)


@sla_bp.route('/settings', methods=['POST'])
@csrf_protect
@login_required
def sla_settings():
    """保存 SLA 阈值设置"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可修改'), 403

    data = request.get_json(silent=True) or {}
    mappings = [
        ('sla_response_emergency', 'emergency_response'),
        ('sla_resolution_emergency', 'emergency_resolution'),
        ('sla_response_urgent', 'urgent_response'),
        ('sla_resolution_urgent', 'urgent_resolution'),
        ('sla_response_normal', 'normal_response'),
        ('sla_resolution_normal', 'normal_resolution'),
    ]

    for key, field in mappings:
        val = data.get(field)
        if val is not None:
            setting = SystemSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = str(val)
            else:
                setting = SystemSetting(key=key, value=str(val), label=key, category='SLA')
                db.session.add(setting)

    db.session.commit()
    return jsonify(success=True, message='SLA 阈值已保存')
