"""集团看板 - 全局仪表盘"""

from utils.helpers import safe_get
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, jsonify, request, g
from flask_login import login_required, current_user
from sqlalchemy import func, case, and_

from models import (
    db, WorkOrder, Hospital, User, Person,
    CrossHospitalAssignment,
)
from utils.time_helpers import fmt_dt, fmt_date
from utils.permissions import permission_required, has_permission

global_dashboard_bp = Blueprint('global_dashboard', __name__, url_prefix='/dashboard/global')


def _get_hid():
    hid = getattr(g, 'hospital_id', 0)
    return hid if hid and hid != 0 else 0


def _region_filter(query, model_class):
    """按区域过滤查询"""
    region = request.args.get('region', '').strip()
    if not region or region == '全市' or region == '全部':
        return query
    # 找到该区域下的所有医院ID
    hospital_ids = [
        h.id for h in Hospital.query.filter(
            Hospital.region == region,
            Hospital.is_active == True
        ).all()
    ]
    if not hospital_ids:
        return query.filter(model_class.hospital_id == -1)  # 无匹配
    return query.filter(model_class.hospital_id.in_(hospital_ids))


def _days_filter(query, model_class):
    """按天数过滤查询"""
    days = request.args.get('days', 30, type=int)
    if days and days > 0:
        cutoff = datetime.now() - timedelta(days=days)
        return query.filter(model_class.created_at >= cutoff)
    return query


# ======================== 页面路由 ========================


@global_dashboard_bp.route('/')
@permission_required('report:global_view')
def index():
    """集团看板页面"""
    regions = db.session.query(Hospital.region).filter(
        Hospital.region != '',
        Hospital.region != '其他',
        Hospital.is_active == True
    ).distinct().order_by(Hospital.region).all()
    regions = [r[0] for r in regions if r[0]]
    return render_template(
        'global_dashboard/index.html',
        regions=regions,
        can_view_staff_load=has_permission(current_user, 'report:staff_load'),
        can_view_region=has_permission(current_user, 'report:region_view'),
    )


# ======================== API 路由 ========================


@global_dashboard_bp.route('/api/stats')
@permission_required('report:global_view')
def get_stats():
    # 全局视图：清除医院过滤，让 auto_hospital_filter 跳过
    g.hospital_id = 0
    # 基础工单查询
    base = _days_filter(WorkOrder.query, WorkOrder)
    base = _region_filter(base, WorkOrder)

    total = base.count()
    completed = base.filter(WorkOrder.status == 'completed').count()
    pending = base.filter(WorkOrder.status.in_(['pending', 'confirmed'])).count()
    active_orders = base.filter(WorkOrder.status.in_(['processing', 'confirmed'])).count()

    completion_rate = round(completed / total * 100, 1) if total else 0

    # SLA响应时长（从 accepted_at 到 created_at 的差值平均值）
    sla_stats = base.with_entities(
        func.avg(
            func.strftime('%s', WorkOrder.accepted_at) -
            func.strftime('%s', WorkOrder.created_at)
        )
    ).filter(
        WorkOrder.accepted_at.isnot(None),
        WorkOrder.created_at.isnot(None),
    ).first()
    avg_response_seconds = sla_stats[0] if sla_stats and sla_stats[0] else 0
    avg_response_minutes = round(avg_response_seconds / 60, 1) if avg_response_seconds else 0

    # SLA达标率：响应时间 < 30分钟视为达标
    sla_pass = base.with_entities(
        func.count(WorkOrder.id)
    ).filter(
        WorkOrder.accepted_at.isnot(None),
        WorkOrder.created_at.isnot(None),
        (
            func.strftime('%s', WorkOrder.accepted_at) -
            func.strftime('%s', WorkOrder.created_at)
        ) <= 1800
    ).scalar() or 0
    sla_total = base.filter(WorkOrder.accepted_at.isnot(None)).count()
    sla_rate = round(sla_pass / sla_total * 100, 1) if sla_total else 0

    # 当前借调总人数
    active_cross = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.status == 'active'
    ).count()

    return jsonify(success=True, data={
        'total_orders': total,
        'completion_rate': completion_rate,
        'sla_rate': sla_rate,
        'avg_response_time': avg_response_minutes,
        'active_cross_assignments': active_cross,
        'pending_orders': pending,
    })


@global_dashboard_bp.route('/api/hospital-ranking')
@permission_required('report:global_view')
def get_hospital_ranking():
    # 全局视图：清除医院过滤
    g.hospital_id = 0
    days = request.args.get('days', 30, type=int)
    region = request.args.get('region', '').strip()
    sort_by = request.args.get('sort_by', 'order_count')  # order_count / completion_rate / avg_response

    cutoff = datetime.now() - timedelta(days=days) if days else None

    # 获取所有活跃医院
    hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
    if region and region not in ('全市', '全部'):
        hospitals = [h for h in hospitals if h.region == region]

    result = []
    for h in hospitals:
        q = WorkOrder.query.filter(WorkOrder.hospital_id == h.id)
        if cutoff:
            q = q.filter(WorkOrder.created_at >= cutoff)

        total = q.count()
        completed = q.filter(WorkOrder.status == 'completed').count()
        pending = q.filter(WorkOrder.status.in_(['pending', 'confirmed'])).count()
        completion_rate = round(completed / total * 100, 1) if total else 0

        # 平均响应时间
        avg_resp = q.with_entities(
            func.avg(
                func.strftime('%s', WorkOrder.accepted_at) -
                func.strftime('%s', WorkOrder.created_at)
            )
        ).filter(
            WorkOrder.accepted_at.isnot(None),
            WorkOrder.created_at.isnot(None),
        ).first()
        avg_resp_sec = avg_resp[0] if avg_resp and avg_resp[0] else 0
        avg_resp_min = round(avg_resp_sec / 60, 1) if avg_resp_sec else 0

        # SLA达标率
        sla_q = q.filter(WorkOrder.accepted_at.isnot(None))
        sla_pass = sla_q.with_entities(
            func.count(WorkOrder.id)
        ).filter(
            (
                func.strftime('%s', WorkOrder.accepted_at) -
                func.strftime('%s', WorkOrder.created_at)
            ) <= 1800
        ).scalar() or 0
        sla_total = sla_q.count()
        sla_rate = round(sla_pass / sla_total * 100, 1) if sla_total else 0

        # 人员数
        staff_count = Person.query.filter(
            Person.hospital_id == h.id,
            Person.is_active == True,
        ).count()

        # 人均负载
        staff_load = round(active_orders_count(h.id) / staff_count, 2) if staff_count else 0

        result.append({
            'hospital_id': h.id,
            'hospital_name': h.name,
            'region': h.region or '',
            'order_count': total,
            'completed_count': completed,
            'pending_count': pending,
            'completion_rate': completion_rate,
            'avg_response_time': avg_resp_min,
            'sla_rate': sla_rate,
            'staff_count': staff_count,
            'staff_load': staff_load,
        })

    # 排序
    if sort_by == 'completion_rate':
        result.sort(key=lambda x: x['completion_rate'], reverse=True)
    elif sort_by == 'avg_response':
        result.sort(key=lambda x: x['avg_response_time'])
    elif sort_by == 'sla_rate':
        result.sort(key=lambda x: x['sla_rate'], reverse=True)
    else:
        result.sort(key=lambda x: x['order_count'], reverse=True)

    return jsonify(success=True, data=result)


def active_orders_count(hospital_id):
    return WorkOrder.query.filter(
        WorkOrder.hospital_id == hospital_id,
        WorkOrder.status.in_(['pending', 'processing', 'confirmed']),
    ).count()


@global_dashboard_bp.route('/api/timeline')
@permission_required('report:global_view')
def get_timeline():
    # 全局视图：清除医院过滤
    g.hospital_id = 0
    days = request.args.get('days', 30, type=int)
    region = request.args.get('region', '').strip()
    granularity = request.args.get('granularity', 'day')

    cutoff = datetime.now() - timedelta(days=days)
    base = WorkOrder.query.filter(WorkOrder.created_at >= cutoff)
    base = _region_filter(base, WorkOrder)

    # 获取所有统计数据
    all_orders = base.order_by(WorkOrder.created_at).all()

    # 按日期分组统计
    from collections import defaultdict
    daily = defaultdict(lambda: {'total': 0, 'solved': 0, 'pending': 0})

    # 生成日期轴
    date_labels = []
    for i in range(days):
        d = cutoff + timedelta(days=i)
        key = d.strftime('%Y-%m-%d')
        date_labels.append(key)

    for wo in all_orders:
        if wo.created_at:
            key = wo.created_at.strftime('%Y-%m-%d')
            daily[key]['total'] += 1
            if wo.status == 'solved':
                daily[key]['solved'] += 1
            elif wo.status in ('pending', 'confirmed'):
                daily[key]['pending'] += 1

    timeline = []
    for d in date_labels:
        timeline.append({
            'date': d,
            'total': daily[d]['total'],
            'solved': daily[d]['solved'],
            'pending': daily[d]['pending'],
        })

    return jsonify(success=True, data={
        'timeline': timeline,
        'granularity': granularity,
    })


@global_dashboard_bp.route('/api/staff-load')
@permission_required('report:staff_load')
def get_staff_load():
    # 全局视图：清除医院过滤
    g.hospital_id = 0
    days = request.args.get('days', 30, type=int)
    region = request.args.get('region', '').strip()

    cutoff = datetime.now() - timedelta(days=days) if days else None
    hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
    if region and region not in ('全市', '全部'):
        hospitals = [h for h in hospitals if h.region == region]

    result = []
    for h in hospitals:
        # 人员数
        staff_count = Person.query.filter(
            Person.hospital_id == h.id,
            Person.is_active == True,
        ).count()

        # 活跃工单
        active_count = active_orders_count(h.id)

        # 30天内工单总量
        total_orders = 0
        if cutoff:
            total_orders = WorkOrder.query.filter(
                WorkOrder.hospital_id == h.id,
                WorkOrder.created_at >= cutoff,
            ).count()

        # 人均活跃负载
        load = round(active_count / staff_count, 2) if staff_count else 0

        result.append({
            'hospital_id': h.id,
            'hospital_name': h.name,
            'region': h.region or '',
            'staff_count': staff_count,
            'active_orders': active_count,
            'total_orders': total_orders,
            'active_load': load,
        })

    result.sort(key=lambda x: x['active_load'], reverse=True)
    return jsonify(success=True, data=result)


@global_dashboard_bp.route('/api/regional-stats')
@permission_required('report:region_view')
def get_regional_stats():
    # 全局视图：清除医院过滤
    g.hospital_id = 0
    days = request.args.get('days', 30, type=int)
    cutoff = datetime.now() - timedelta(days=days) if days else None

    # 按区域分组
    regions = db.session.query(
        Hospital.region,
        func.count(Hospital.id),
    ).filter(
        Hospital.region != '',
        Hospital.is_active == True,
    ).group_by(Hospital.region).all()

    result = []
    for region_name, hospital_count in regions:
        hid_list = [h.id for h in Hospital.query.filter(
            Hospital.region == region_name,
            Hospital.is_active == True,
        ).all()]
        if not hid_list:
            continue

        q = WorkOrder.query.filter(WorkOrder.hospital_id.in_(hid_list))
        if cutoff:
            q = q.filter(WorkOrder.created_at >= cutoff)

        total = q.count()
        completed = q.filter(WorkOrder.status == 'completed').count()
        pending = q.filter(WorkOrder.status.in_(['pending', 'confirmed'])).count()
        completion_rate = round(completed / total * 100, 1) if total else 0

        avg_resp = q.with_entities(
            func.avg(
                func.strftime('%s', WorkOrder.accepted_at) -
                func.strftime('%s', WorkOrder.created_at)
            )
        ).filter(
            WorkOrder.accepted_at.isnot(None),
            WorkOrder.created_at.isnot(None),
        ).first()
        avg_resp_sec = avg_resp[0] if avg_resp and avg_resp[0] else 0
        avg_resp_min = round(avg_resp_sec / 60, 1) if avg_resp_sec else 0

        result.append({
            'region': region_name,
            'hospital_count': hospital_count,
            'total_orders': total,
            'completed': completed,
            'pending': pending,
            'completion_rate': completion_rate,
            'avg_response_time': avg_resp_min,
        })

    result.sort(key=lambda x: x['total_orders'], reverse=True)
    return jsonify(success=True, data=result)


@global_dashboard_bp.route('/api/pending-orders')
@permission_required('report:global_view')
def get_pending_orders():
    # 全局视图：清除医院过滤
    g.hospital_id = 0
    days = request.args.get('days', 30, type=int)
    region = request.args.get('region', '').strip()
    limit = request.args.get('limit', 20, type=int)

    base = WorkOrder.query.filter(
        WorkOrder.status.in_(['pending', 'confirmed'])
    )
    base = _days_filter(base, WorkOrder)
    base = _region_filter(base, WorkOrder)

    orders = base.order_by(WorkOrder.created_at.desc()).limit(limit).all()

    result = []
    for o in orders:
        hospital = safe_get(Hospital, o.hospital_id)
        result.append({
            'id': o.id,
            'title': o.title,
            'status': o.status,
            'priority': o.priority,
            'department': o.department or '',
            'person': o.person or '',
            'hospital_name': hospital.name if hospital else '',
            'hospital_id': o.hospital_id,
            'created_at': fmt_dt(o.created_at),
            'age_hours': round((datetime.now() - o.created_at).total_seconds() / 3600, 1) if o.created_at else 0,
        })

    return jsonify(success=True, data=result)
