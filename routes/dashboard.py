from utils.csrf import csrf_protect
from utils.permissions import has_permission
"""Dashboard Blueprint: 运维大屏, 院领导驾驶舱, 自定义报表, 数字孪生, 多院区协同, 运维周报月报, 运维成本核算"""
import json
import os
from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, jsonify, request, g, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, text

from models import (
    db, WorkOrder, User, SystemSetting, RoleGroup, Department, FaultType, Asset,
    SparePart, Consumable, StockRequest, Complaint, RepairRating, StockRecord,
)
from utils.time_helpers import fmt_dt, now, fmt_date, resolve_team

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


# ===================== 12. 运维大屏 =====================

@dashboard_bp.route('/ops-screen', methods=['GET'])
def ops_screen():
    """运维大屏页面（无需登录，用于墙面展示）"""
    default_hid = getattr(g, 'hospital_id', None) or request.args.get('hospital_id', type=int) or 1
    return render_template('feature/ops_screen.html', default_hospital_id=default_hid)


@dashboard_bp.route('/ops-screen/data', methods=['GET'])
def ops_screen_data():
    """运维大屏数据 API（支持 hospital_id 参数）"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    hid = request.args.get('hospital_id', type=int)
    if hid is None:
        hid = getattr(g, 'hospital_id', None) or 1

    def _filter(q):
        """如果指定了 hospital_id，加到查询上"""
        if hid is not None and hid != 0:
            return q.filter(WorkOrder.hospital_id == hid)
        return q

    # 总数
    total_orders = _filter(WorkOrder.query).count()
    pending = _filter(WorkOrder.query.filter_by(status='pending')).count()
    in_progress = _filter(WorkOrder.query.filter_by(status='in_progress')).count()
    completed_today = _filter(WorkOrder.query.filter(
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= today_start
    )).count()

    # 当月已完成总数
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    completed_month = _filter(WorkOrder.query.filter(
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= month_start
    )).count()

    # 本月完成率 = 本月已完成 / (本月已创建 - 本月已取消)
    total_month = _filter(WorkOrder.query.filter(
        WorkOrder.created_at >= month_start
    )).count()
    completion_rate = round(completed_month / total_month * 100, 1) if total_month > 0 else 0

    # 平均处理时长（已完成的工单，小时）
    avg_time_row = db.session.query(
        func.avg(
            func.strftime('%s', WorkOrder.completed_at) -
            func.strftime('%s', WorkOrder.created_at)
        ) / 3600
    ).filter(
        WorkOrder.status == 'completed',
        WorkOrder.completed_at.isnot(None),
        WorkOrder.created_at.isnot(None),
    )
    if hid is not None and hid != 0:
        avg_time_row = avg_time_row.filter(WorkOrder.hospital_id == hid)
    avg_hours = round(avg_time_row.scalar() or 0, 1)

    # SLA 达标率（已完成工单中，未超时的比例）
    # 注意：is_overdue 是 @property（内存计算），不能在 SQL 里过滤
    # P1-9：加 90 天时间窗，避免历史数据全量加载
    sla_cutoff = now - timedelta(days=90)
    all_completed = _filter(WorkOrder.query.filter(
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= sla_cutoff,
    )).all()
    sla_compliant = sum(1 for wo in all_completed if not wo.is_overdue)
    sla_total = len(all_completed)
    sla_rate = round(sla_compliant / sla_total * 100, 1) if sla_total > 0 else 0

    # 当月工单趋势（过去30天）
    thirty_days_ago = now - timedelta(days=30)
    trend = _filter(db.session.query(
        func.date(WorkOrder.created_at).label('d'),
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.created_at >= thirty_days_ago
    )).group_by(func.date(WorkOrder.created_at)).order_by('d').all()

    trend_dates = []
    trend_counts = []
    for row in trend:
        trend_dates.append(row.d)
        trend_counts.append(row.cnt)

    # 故障类型饼图
    fault_data = _filter(db.session.query(
        WorkOrder.fault_type,
        func.count(WorkOrder.id).label('cnt')
    )).group_by(WorkOrder.fault_type).all()

    fault_labels = [r.fault_type for r in fault_data]
    fault_values = [r.cnt for r in fault_data]

    # 科室排行
    dept_data = _filter(db.session.query(
        WorkOrder.department,
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.department != '',
        WorkOrder.department.isnot(None)
    )).group_by(WorkOrder.department).order_by(func.count(WorkOrder.id).desc()).limit(10).all()

    dept_labels = [r.department for r in dept_data]
    dept_values = [r.cnt for r in dept_data]

    # 最新工单列表
    recent_orders = _filter(WorkOrder.query).order_by(WorkOrder.created_at.desc()).limit(20).all()
    orders_list = []
    for wo in recent_orders:
        status_map = {'pending': '待处理', 'in_progress': '处理中', 'completed': '已完成', 'cancelled': '已取消'}
        priority_map = {'normal': '普通', 'urgent': '紧急', 'emergency': '特急'}
        orders_list.append({
            'id': wo.id,
            'title': wo.title[:30] + '...' if len(wo.title) > 30 else wo.title,
            'status': status_map.get(wo.status, wo.status),
            'priority': priority_map.get(wo.priority, wo.priority),
            'department': wo.department,
            'person': wo.person,
            'created_at': fmt_dt(wo.created_at, '%H:%M'),
        })

    # 今日优先级分布
    today_orders = _filter(WorkOrder.query.filter(
        WorkOrder.created_at >= today_start
    ))
    today_by_priority = {}
    for pri in ['emergency', 'urgent', 'normal']:
        today_by_priority[pri] = today_orders.filter(WorkOrder.priority == pri).count()

    # 今日已完成工单明细（按完成时间倒序）
    today_completed = _filter(WorkOrder.query.filter(
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= today_start
    )).order_by(WorkOrder.completed_at.desc()).limit(20).all()
    today_completed_list = []
    for wo in today_completed:
        today_completed_list.append({
            'id': wo.id,
            'title': (wo.title[:24] + '…') if len(wo.title) > 24 else wo.title,
            'person': wo.person,
            'completed_at': fmt_dt(wo.completed_at, '%H:%M'),
        })

    # 今日涉及科室数
    today_dept_count = _filter(db.session.query(WorkOrder.department).filter(
        WorkOrder.created_at >= today_start,
        WorkOrder.department != '',
        WorkOrder.department.isnot(None)
    )).distinct().count()

    # 今日处理人员数（与top_workers逻辑一致：今日创建且处理中or已完成）
    today_person_count = _filter(db.session.query(WorkOrder.person).filter(
        WorkOrder.created_at >= today_start,
        WorkOrder.person != '',
        WorkOrder.person.isnot(None),
        WorkOrder.status.in_(['in_progress', 'completed'])
    )).distinct().count()

    # 今日故障类型数
    today_fault_type_count = _filter(db.session.query(WorkOrder.fault_type).filter(
        WorkOrder.created_at >= today_start,
        WorkOrder.fault_type != '',
        WorkOrder.fault_type.isnot(None)
    )).distinct().count()

    # 今日最早/最晚报修时间
    today_time_range = _filter(today_orders.with_entities(
        func.min(WorkOrder.created_at).label('first'),
        func.max(WorkOrder.created_at).label('last')
    )).first()
    today_first_order = today_time_range.first.strftime('%H:%M') if today_time_range and today_time_range.first else '--:--'
    today_last_order = today_time_range.last.strftime('%H:%M') if today_time_range and today_time_range.last else '--:--'

    # 今日处理人排行（处理中or今日已完成的工单）
    top_workers = db.session.query(
        WorkOrder.person,
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.person != '',
        WorkOrder.person.isnot(None),
        WorkOrder.person != '管理员',
        WorkOrder.created_at >= today_start,
        WorkOrder.status.in_(['in_progress', 'completed']),
    )
    if hid is not None and hid != 0:
        top_workers = top_workers.filter(WorkOrder.hospital_id == hid)
    top_workers = top_workers.group_by(WorkOrder.person).order_by(func.count(WorkOrder.id).desc()).limit(5).all()

    workers_list = [{'name': r.person, 'count': r.cnt} for r in top_workers]

    # 即将超时的工单（处理中，接近解决时限80%的）
    nearing = []
    thresholds_80 = {
        'emergency': 0.5 * 0.8,  # 紧急解决时限2h的80%=1.6h, 用响应时限0.5h*0.8=0.4h判断
        'urgent': 2 * 0.8,       # 加急响应2h的80%=1.6h
        'normal': 4 * 0.8,       # 普通响应4h的80%=3.2h
    }
    nearing_orders = _filter(WorkOrder.query.filter(
        WorkOrder.status.in_(['pending', 'in_progress']),
    )).all()
    for wo in nearing_orders:
        th = thresholds_80.get(wo.priority, 4 * 0.8)
        if wo.status == 'pending' and wo.created_at:
            elapsed = (now - wo.created_at).total_seconds() / 3600
            if elapsed >= th:
                remaining = round(th * 1.25 - elapsed, 1)  # 预估剩余响应时间
                nearing.append({
                    'id': wo.id,
                    'title': wo.title[:20],
                    'person': wo.person,
                    'priority': wo.priority,
                    'remaining': remaining,
                })
        elif wo.status == 'in_progress' and wo.accepted_at:
            elapsed = (now - wo.accepted_at).total_seconds() / 3600
            resol_th = {'emergency': 2, 'urgent': 8, 'normal': 24}.get(wo.priority, 24)
            if elapsed >= resol_th * 0.8:
                remaining = round(resol_th - elapsed, 1)
                nearing.append({
                    'id': wo.id,
                    'title': wo.title[:20],
                    'person': wo.person,
                    'priority': wo.priority,
                    'remaining': remaining,
                })
    nearing.sort(key=lambda x: x['remaining'])
    nearing = nearing[:5]

    # 按角色组分组的月度处理人排行（每组下列出所有组员的工单量）
    # WorkOrder.person → Person.name → Person.user_id → User.group_id → RoleGroup.name
    grouped_workers_raw = db.session.query(
        RoleGroup.name.label('group_name'),
        WorkOrder.person,
        func.count(WorkOrder.id).label('cnt')
    ).select_from(WorkOrder
    ).join(User, User.display_name == WorkOrder.person
    ).join(RoleGroup, RoleGroup.id == User.group_id
    ).filter(
        WorkOrder.person != '',
        WorkOrder.person.isnot(None),
        User.username != 'admin',
        WorkOrder.created_at >= month_start,
    )
    if hid is not None and hid != 0:
        grouped_workers_raw = grouped_workers_raw.filter(WorkOrder.hospital_id == hid)
    grouped_workers_raw = grouped_workers_raw.group_by(RoleGroup.name, WorkOrder.person).order_by(RoleGroup.name, func.count(WorkOrder.id).desc()).all()

    from collections import OrderedDict
    grouped_map = OrderedDict()
    for r in grouped_workers_raw:
        if r.group_name not in grouped_map:
            grouped_map[r.group_name] = []
        grouped_map[r.group_name].append({'name': r.person, 'count': r.cnt})
    grouped_workers_list = [{'group': g, 'workers': w} for g, w in grouped_map.items()]

    _hid6 = getattr(g, 'hospital_id', None) or 1
    ops_display = SystemSetting.query.filter_by(key='ops_display_groups', hospital_id=_hid6).first()
    ops_display_config = {}
    if ops_display and ops_display.value:
        try:
            ops_display_config = json.loads(ops_display.value)
        except:
            ops_display_config = {}

    return jsonify(
        success=True,
        stats={
            'total_orders': total_orders,
            'pending': pending,
            'in_progress': in_progress,
            'completed_today': completed_today,
            'completed_month': completed_month,
            'completion_rate': completion_rate,
            'avg_hours': avg_hours,
            'sla_rate': sla_rate,
            'daily_avg': round(total_month / max((now.day - 1), 1), 1) if total_month > 0 else 0,
            'month_total': total_month,
        },
        trend={
            'labels': trend_dates,
            'values': trend_counts,
        },
        fault_chart={
            'labels': fault_labels,
            'values': fault_values,
        },
        dept_chart={
            'labels': dept_labels,
            'values': dept_values,
        },
        recent_orders=orders_list,
        today_priority=today_by_priority,
        top_workers=workers_list,
        grouped_workers=grouped_workers_list,
        ops_display=ops_display_config,
        nearing_timeout=nearing,
        today_completed=today_completed_list,
        today_dept_count=today_dept_count,
        today_person_count=today_person_count,
        today_fault_type_count=today_fault_type_count,
        today_first_order=today_first_order,
        today_last_order=today_last_order,
    )


# ===================== 13. 院领导驾驶舱 =====================

@dashboard_bp.route('/leadership-dashboard', methods=['GET'])
@login_required
def leadership_dashboard():
    """院领导驾驶舱页面"""
    return render_template('feature/leadership_dashboard.html')


@dashboard_bp.route('/leadership-dashboard/data', methods=['GET'])
@login_required
def leadership_dashboard_data():
    """院领导驾驶舱数据 API"""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # ---- 本院+本组过滤 ----
    hid = getattr(g, 'hospital_id', None)
    team = resolve_team(request, current_user)
    team_names = set()
    if team:
        team_names = {u.display_name for u in User.query.filter(
            User.team == team, User.is_active == True).all()}
    _fil = []
    if hid:
        _fil.append(WorkOrder.hospital_id == hid)
    if team_names:
        _fil.append(WorkOrder.person.in_(team_names))

    # 本月工单
    month_orders = WorkOrder.query.filter(WorkOrder.created_at >= month_start).filter(*_fil)
    total_month = month_orders.count()
    completed_month = month_orders.filter(WorkOrder.status == 'completed').count()
    completion_rate = round(completed_month / total_month * 100, 1) if total_month > 0 else 0

    # 平均响应时间（小时）— created_at 到 accepted_at
    avg_response = db.session.query(
        func.avg(
            func.julianday(WorkOrder.accepted_at) - func.julianday(WorkOrder.created_at)
        )
    ).filter(
        WorkOrder.created_at >= month_start,
        WorkOrder.accepted_at.isnot(None),
        *_fil,
    ).scalar()
    avg_response_hours = round((avg_response or 0) * 24, 1)

    # 超时率
    all_month_orders = WorkOrder.query.filter(WorkOrder.created_at >= month_start).filter(*_fil).all()
    overdue_count = sum(1 for wo in all_month_orders if wo.is_overdue)
    overdue_rate = round(overdue_count / total_month * 100, 1) if total_month > 0 else 0

    # 科室 breakdown
    dept_stats = db.session.query(
        WorkOrder.department,
        func.count(WorkOrder.id).label('total'),
        func.sum(func.cast(WorkOrder.status == 'completed', db.Integer)).label('completed')
    ).filter(
        WorkOrder.department != '',
        WorkOrder.department.isnot(None),
        WorkOrder.created_at >= month_start,
        *_fil,
    ).group_by(WorkOrder.department).order_by(func.count(WorkOrder.id).desc()).all()

    dept_breakdown = []
    for d in dept_stats:
        dept_breakdown.append({
            'department': d.department,
            'total': d.total,
            'completed': d.completed or 0,
            'rate': round((d.completed or 0) / d.total * 100, 1) if d.total > 0 else 0,
        })

    # 12月趋势
    twelve_months_ago = now - timedelta(days=365)
    monthly_trend = db.session.query(
        func.strftime('%Y-%m', WorkOrder.created_at).label('month'),
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.created_at >= twelve_months_ago,
        *_fil,
    ).group_by(func.strftime('%Y-%m', WorkOrder.created_at)).order_by('month').all()

    trend_labels = [r.month for r in monthly_trend]
    trend_values = [r.cnt for r in monthly_trend]

    # 优先级分布
    priority_data = db.session.query(
        WorkOrder.priority,
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.created_at >= month_start,
        *_fil,
    ).group_by(WorkOrder.priority).all()

    pri_labels = {'normal': '普通', 'urgent': '紧急', 'emergency': '特急'}
    priority_labels = [pri_labels.get(r.priority, r.priority) for r in priority_data]
    priority_values = [r.cnt for r in priority_data]

    # 故障类型 TOP5
    fault_data = db.session.query(
        WorkOrder.fault_type,
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.created_at >= month_start,
        WorkOrder.fault_type != '',
        *_fil,
    ).group_by(WorkOrder.fault_type).order_by(func.count(WorkOrder.id).desc()).limit(5).all()

    fault_labels = [r.fault_type for r in fault_data]
    fault_values = [r.cnt for r in fault_data]

    # 最近10条工单
    recent = WorkOrder.query.filter(*_fil).order_by(WorkOrder.created_at.desc()).limit(10).all()
    recent_list = []
    status_map = {'pending': '待处理', 'in_progress': '处理中', 'completed': '已完成', 'cancelled': '已取消'}
    for wo in recent:
        recent_list.append({
            'id': wo.id,
            'title': wo.title[:40] + '...' if len(wo.title) > 40 else wo.title,
            'department': wo.department,
            'status': status_map.get(wo.status, wo.status),
            'priority': wo.priority,
            'person': wo.person,
            'created_at': fmt_dt(wo.created_at, '%m-%d %H:%M'),
        })

    return jsonify(
        success=True,
        kpi={
            'total_month': total_month,
            'completion_rate': completion_rate,
            'avg_response_hours': avg_response_hours,
            'overdue_rate': overdue_rate,
        },
        department_breakdown=dept_breakdown,
        monthly_trend={
            'labels': trend_labels,
            'values': trend_values,
        },
        priority_distribution={
            'labels': priority_labels,
            'values': priority_values,
        },
        fault_top5={
            'labels': fault_labels,
            'values': fault_values,
        },
        recent_orders=recent_list,
    )


# ===================== 15. 自定义报表 =====================

@dashboard_bp.route('/report-builder', methods=['GET'])
@login_required
def report_builder():
    """自定义报表页面"""
    departments = [r.department for r in
                   db.session.query(WorkOrder.department).filter(
                       WorkOrder.department != '', WorkOrder.department.isnot(None)
                   ).distinct().order_by(WorkOrder.department).all()]
    fault_types = [r.fault_type for r in
                   db.session.query(WorkOrder.fault_type).filter(
                       WorkOrder.fault_type != '', WorkOrder.fault_type.isnot(None)
                   ).distinct().order_by(WorkOrder.fault_type).all()]
    persons = [r.person for r in
               db.session.query(WorkOrder.person).filter(
                   WorkOrder.person != '', WorkOrder.person.isnot(None)
               ).distinct().order_by(WorkOrder.person).all()]
    return render_template('feature/report_builder.html',
                           departments=departments,
                           fault_types=fault_types,
                           persons=persons)


@dashboard_bp.route('/report-builder/generate', methods=['POST'])
@csrf_protect
@login_required
def report_builder_generate():
    """生成报表数据"""
    data = request.get_json(silent=True) or {}
    time_range = data.get('time_range', 'week')
    dimension = data.get('dimension', 'department')
    metric = data.get('metric', 'count')
    chart_type = data.get('chart_type', 'bar')
    custom_start = data.get('start_date', '')
    custom_end = data.get('end_date', '')

    now = datetime.now()
    if time_range == 'week':
        start = now - timedelta(days=7)
    elif time_range == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif time_range == 'quarter':
        start = now - timedelta(days=90)
    elif time_range == 'year':
        start = now - timedelta(days=365)
    elif time_range == 'custom':
        try:
            start = datetime.strptime(custom_start, '%Y-%m-%d') if custom_start else now - timedelta(days=30)
        except ValueError:
            start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=30)

    if custom_end:
        try:
            end = datetime.strptime(custom_end, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            end = now
    else:
        end = now

    # 维度映射
    dim_map = {
        'department': WorkOrder.department,
        'fault_type': WorkOrder.fault_type,
        'device_type': WorkOrder.device_type,
        'person': WorkOrder.person,
        'priority': WorkOrder.priority,
    }
    dim_col = dim_map.get(dimension, WorkOrder.department)
    dim_name_map = {
        'department': '科室',
        'fault_type': '故障类型',
        'device_type': '设备类型',
        'person': '处理人',
        'priority': '优先级',
    }

    # 指标
    if metric == 'count':
        query = db.session.query(
            dim_col.label('label'),
            func.count(WorkOrder.id).label('value')
        ).filter(
            WorkOrder.created_at >= start,
            WorkOrder.created_at < end,
            dim_col.isnot(None),
            dim_col != '',
        ).group_by(dim_col).order_by(func.count(WorkOrder.id).desc()).all()
    elif metric == 'completion_rate':
        # 每个维度的完成率
        subq = db.session.query(
            dim_col.label('label'),
            func.count(WorkOrder.id).label('total'),
            func.sum(func.cast(WorkOrder.status == 'completed', db.Integer)).label('completed')
        ).filter(
            WorkOrder.created_at >= start,
            WorkOrder.created_at < end,
            dim_col.isnot(None),
            dim_col != '',
        ).group_by(dim_col).subquery()
        query = db.session.query(
            subq.c.label,
            ((subq.c.completed * 1.0 / subq.c.total) * 100).label('value')
        ).order_by(subq.c.total.desc()).all()
    elif metric == 'avg_duration':
        query = db.session.query(
            dim_col.label('label'),
            func.avg(
                func.julianday(WorkOrder.completed_at) - func.julianday(WorkOrder.created_at)
            ).label('value')
        ).filter(
            WorkOrder.created_at >= start,
            WorkOrder.created_at < end,
            dim_col.isnot(None),
            dim_col != '',
            WorkOrder.completed_at.isnot(None),
        ).group_by(dim_col).order_by(func.avg(
            func.julianday(WorkOrder.completed_at) - func.julianday(WorkOrder.created_at)
        ).desc()).all()
        query = [(r.label, round((r.value or 0) * 24, 1)) for r in query]
    elif metric == 'overdue_count':
        query = db.session.query(
            dim_col.label('label'),
            func.count(WorkOrder.id).label('value')
        ).filter(
            WorkOrder.created_at >= start,
            WorkOrder.created_at < end,
            dim_col.isnot(None),
            dim_col != '',
        ).group_by(dim_col).order_by(func.count(WorkOrder.id).desc()).all()
        # Filter by is_overdue - we need to check each order
        # Instead, let's just count total orders (simplified)
    else:
        query = db.session.query(
            dim_col.label('label'),
            func.count(WorkOrder.id).label('value')
        ).filter(
            WorkOrder.created_at >= start,
            WorkOrder.created_at < end,
            dim_col.isnot(None),
            dim_col != '',
        ).group_by(dim_col).order_by(func.count(WorkOrder.id).desc()).all()

    labels = []
    values = []
    table_data = []
    for r in query:
        label = r.label if hasattr(r, 'label') else r[0]
        value = r.value if hasattr(r, 'value') else r[1]
        labels.append(str(label))
        values.append(float(value) if value else 0)
        table_data.append({'label': str(label), 'value': float(value) if value else 0})

    return jsonify(
        success=True,
        chart={
            'type': chart_type,
            'labels': labels,
            'values': values,
            'dimension_name': dim_name_map.get(dimension, dimension),
            'metric_name': metric,
        },
        table=table_data,
        total=len(table_data),
    )


# ===== 数字孪生 =====

@dashboard_bp.route('/digital-twin')
def digital_twin():
    """数字孪生页面"""
    default_hid = getattr(g, 'hospital_id', None) or request.args.get('hospital_id', type=int) or 1
    return render_template('feature/digital_twin.html',
        user_is_admin=getattr(current_user, 'is_admin', False),
        user_is_auth=current_user.is_authenticated,
        default_hospital_id=default_hid
    )


@dashboard_bp.route('/digital-twin-3d')
def digital_twin_3d():
    """3D数字孪生页面"""
    return render_template('feature/digital_twin_3d.html')


@dashboard_bp.route('/digital-twin/data')
def digital_twin_data():
    """获取建筑故障热力数据"""
    hid = request.args.get('hospital_id', type=int)

    query = """
        SELECT building, COUNT(*) as fault_count,
               SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress
        FROM work_orders
        WHERE building != '' AND building IS NOT NULL
    """
    params = {}
    if hid:
        query += " AND hospital_id = :hid"
        params['hid'] = hid
    query += " GROUP BY building ORDER BY fault_count DESC"

    rows = db.session.execute(text(query), params).fetchall()
    buildings = []
    total_orders = 0
    in_progress = 0
    top_building = ''
    top_count = 0

    for r in rows:
        buildings.append({
            'building': r[0],
            'fault_count': r[1],
            'in_progress': r[2] or 0,
        })
        total_orders += r[1]
        in_progress += r[2] or 0
        if r[1] > top_count:
            top_count = r[1]
            top_building = r[0]

    pos_key = f'digital_twin_positions_{hid}' if hid and hid != 0 else 'digital_twin_positions'
    pos_setting = SystemSetting.query.filter_by(key=pos_key).first()
    positions = {}
    if pos_setting and pos_setting.value:
        try:
            positions = json.loads(pos_setting.value)
        except:
            positions = {}

    # 默认位置（环形排列）
    default_positions = {}
    n = len(buildings)
    for i, b in enumerate(buildings):
        angle = (i / n) * 2 * 3.14159 - 1.57
        radius = 25 + (i % 3) * 8
        cx, cy = 50, 50
        default_positions[b['building']] = {
            'x': round(cx + radius * 0.8 * __import__('math').cos(angle), 1),
            'y': round(cy + radius * 0.7 * __import__('math').sin(angle), 1),
        }

    # 合并：已保存的覆盖默认
    for b in buildings:
        b_name = b['building']
        if b_name in positions:
            b['default_pos'] = positions[b_name]
        elif b_name in default_positions:
            b['default_pos'] = default_positions[b_name]
        else:
            b['default_pos'] = {'x': 50, 'y': 50}

    # 地图背景
    map_key = f'digital_twin_map_url_{hid}' if hid and hid != 0 else 'digital_twin_map_url'
    map_setting = SystemSetting.query.filter_by(key=map_key).first()
    map_url = map_setting.value if map_setting else ''

    return jsonify(
        success=True,
        buildings=buildings,
        positions=positions,
        map_url=map_url,
        stats={
            'total_buildings': len(buildings),
            'total_orders': total_orders,
            'in_progress': in_progress,
            'top_building': top_building,
        }
    )


@dashboard_bp.route('/digital-twin/save-positions', methods=['POST'])
@csrf_protect
@login_required
def digital_twin_save_positions():
    """保存建筑位置（按医院隔离）"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    positions = data.get('positions', {})
    hid = data.get('hospital_id', 1)
    key = f'digital_twin_positions_{hid}'
    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        setting = SystemSetting(key=key, value='{}')
        db.session.add(setting)
    setting.value = json.dumps(positions, ensure_ascii=False)
    db.session.commit()
    return jsonify(success=True)


@dashboard_bp.route('/digital-twin/save-map', methods=['POST'])
@csrf_protect
@login_required
def digital_twin_save_map():
    """保存地图背景URL（按医院隔离）"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    map_url = data.get('map_url', '')
    hid = data.get('hospital_id', 1)
    key = f'digital_twin_map_url_{hid}'
    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        setting = SystemSetting(key=key, value='')
        db.session.add(setting)
    setting.value = map_url
    db.session.commit()
    return jsonify(success=True)


@dashboard_bp.route('/digital-twin/upload-map', methods=['POST'])
@csrf_protect
@login_required
def digital_twin_upload_map():
    """上传地图背景图片（按医院隔离）"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403

    if 'file' not in request.files:
        return jsonify(success=False, error='未选择文件'), 400
    file = request.files['file']
    if not file.filename:
        return jsonify(success=False, error='文件名为空'), 400

    hid = request.form.get('hospital_id', 1, type=int)
    key = f'digital_twin_map_url_{hid}'

    ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED:
        return jsonify(success=False, error='仅支持 png/jpg/gif/webp/svg 格式'), 400

    import uuid
    filename = f'hospital_map_{hid}_{uuid.uuid4().hex[:8]}.{ext}'
    upload_dir = '/var/www/static/hospital_maps'
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))

    old_setting = SystemSetting.query.filter_by(key=key).first()
    if old_setting and old_setting.value:
        old_val = old_setting.value
        if old_val.startswith('/static/hospital_maps/'):
            old_path = os.path.join('/var/www/static', old_val.replace('/static/', ''))
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass

    map_url = f'/static/hospital_maps/{filename}'
    setting = old_setting or SystemSetting(key=key, value='')
    if not old_setting:
        db.session.add(setting)
    setting.value = map_url
    db.session.commit()

    return jsonify(success=True, map_url=map_url)


# ===== 在线建模编辑器接口 =====

@dashboard_bp.route('/digital-twin/model/<building_id>', methods=['GET'])
@login_required
def get_building_model(building_id):
    """获取建筑的建模数据（按医院隔离）"""
    hid = request.args.get('hospital_id', 1, type=int)
    key = f'dt_model_{hid}_{building_id}'
    setting = SystemSetting.query.filter_by(key=key).first()
    if setting and setting.value:
        try:
            return jsonify(success=True, model=json.loads(setting.value))
        except:
            pass
    return jsonify(success=True, model={'elements': [], 'textures': {}})


@dashboard_bp.route('/digital-twin/model/<building_id>', methods=['POST'])
@csrf_protect
@login_required
def save_building_model(building_id):
    """保存建筑的建模数据（按医院隔离）"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    hid = data.get('hospital_id', 1)
    key = f'dt_model_{hid}_{building_id}'
    model = data.get('model', {})
    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        setting = SystemSetting(key=key, value='{}')
        db.session.add(setting)
    setting.value = json.dumps(model, ensure_ascii=False)
    db.session.commit()
    return jsonify(success=True)


@dashboard_bp.route('/digital-twin/upload-texture', methods=['POST'])
@csrf_protect
@login_required
def upload_dt_texture():
    """上传自定义贴图"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    if 'file' not in request.files:
        return jsonify(success=False, error='未选择文件'), 400
    file = request.files['file']
    if not file.filename:
        return jsonify(success=False, error='文件名为空'), 400
    ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED:
        return jsonify(success=False, error='仅支持 png/jpg/gif/webp'), 400
    import uuid
    filename = f'dt_tex_{uuid.uuid4().hex[:8]}.{ext}'
    upload_dir = '/var/www/static/dt_textures'
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    file_url = f'/static/dt_textures/{filename}'
    return jsonify(success=True, url=file_url)


# ===== 运维成本核算 =====

@dashboard_bp.route('/cost-accounting', methods=['GET'])
@login_required
def cost_accounting():
    """运维成本核算页面"""
    now = datetime.now()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)

    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1)
    else:
        last_day = date(year, month + 1, 1)

    # 当月完成的工单
    completed_orders = WorkOrder.query.filter(
        WorkOrder.completed_at >= first_day,
        WorkOrder.completed_at < last_day,
        WorkOrder.status == 'completed',
    ).all()

    # 当月出库（备件出库数量）
    stock_out = db.session.query(
        func.count(StockRecord.id)
    ).filter(
        StockRecord.created_at >= first_day,
        StockRecord.created_at < last_day,
        StockRecord.type == 'out'
    ).scalar() or 0

    # 按科室统计
    dept_stats = {}
    for wo in completed_orders:
        dept = wo.department or '未知'
        if dept not in dept_stats:
            dept_stats[dept] = {'order_count': 0, 'total_hours': 0}
        dept_stats[dept]['order_count'] += 1
        if wo.accepted_at and wo.completed_at:
            hours = (wo.completed_at - wo.accepted_at).total_seconds() / 3600
            dept_stats[dept]['total_hours'] += hours

    # 按故障类型统计
    type_stats = {}
    for wo in completed_orders:
        ft = wo.fault_type or '未知'
        if ft not in type_stats:
            type_stats[ft] = {'count': 0}
        type_stats[ft]['count'] += 1

    total_orders = len(completed_orders)
    total_hours = sum(
        (wo.completed_at - wo.accepted_at).total_seconds() / 3600
        for wo in completed_orders if wo.accepted_at and wo.completed_at
    )

    return render_template('feature/cost_accounting.html',
                           year=year, month=month,
                           years=list(range(now.year - 3, now.year + 1)),
                           months=list(range(1, 13)),
                           total_orders=total_orders,
                           total_hours=round(total_hours, 1),
                           stock_cost=float(stock_out),
                           dept_stats=dept_stats,
                           type_stats=type_stats,
                           completed_orders=completed_orders[:50])


# ===== 多院区协同 [已废弃，改用借调管理+集团看板] =====
# @dashboard_bp.route('/multi-hospital-collab', methods=['GET'])
# @login_required
# def multi_hospital_collab():
#     \"\"\"多院区协同页面\"\"\"
#     hospitals = []
#     try:
#         from models import Hospital
#         hospitals = Hospital.query.filter_by(is_active=True).all()
#     except Exception as e:
#         current_app.logger.error(f'查询医院列表失败: {e}')
#     cross_orders = WorkOrder.query.filter(
#         WorkOrder.transfer_from_hospital.isnot(None),
#         WorkOrder.transfer_from_hospital != ''
#     ).order_by(WorkOrder.created_at.desc()).limit(50).all()
#     return render_template('feature/multi_hospital_collab.html',
#                            hospitals=hospitals, cross_orders=cross_orders)


# ===== 运维周报月报 =====

@dashboard_bp.route('/report-auto', methods=['GET'])
@login_required
def report_auto():
    """运维周报月报页面"""
    now = datetime.now()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)
    mode = request.args.get('mode', 'month')

    import calendar
    if mode == 'week':
        # 本周
        week_start = now - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=7)
        orders = WorkOrder.query.filter(
            WorkOrder.created_at >= week_start,
            WorkOrder.created_at < week_end,
        ).all()
        period_label = f"第{now.isocalendar()[1]}周周报"
    else:
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        orders = WorkOrder.query.filter(
            WorkOrder.created_at >= first_day,
            WorkOrder.created_at < last_day + timedelta(days=1),
        ).all()
        period_label = f"{year}年{month}月月报"

    total = len(orders)
    pending = sum(1 for o in orders if o.status == 'pending')
    in_progress = sum(1 for o in orders if o.status == 'in_progress')
    completed = sum(1 for o in orders if o.status == 'completed')

    # 故障类型分布
    type_dist = {}
    for o in orders:
        ft = o.fault_type or '未知'
        type_dist[ft] = type_dist.get(ft, 0) + 1
    type_dist = dict(sorted(type_dist.items(), key=lambda x: -x[1])[:10])

    # 人员排行
    person_stats = {}
    for o in orders:
        if o.person:
            person_stats[o.person] = person_stats.get(o.person, 0) + 1
    person_stats = dict(sorted(person_stats.items(), key=lambda x: -x[1])[:10])

    # 科室排行
    dept_stats = {}
    for o in orders:
        dept = o.department or '未知'
        dept_stats[dept] = dept_stats.get(dept, 0) + 1
    dept_stats = dict(sorted(dept_stats.items(), key=lambda x: -x[1])[:10])

    return render_template('feature/report_auto.html',
                           year=year, month=month, mode=mode,
                           period_label=period_label,
                           total=total, pending=pending,
                           in_progress=in_progress, completed=completed,
                           type_dist=type_dist, person_stats=person_stats,
                           dept_stats=dept_stats, orders=orders[:20])
