from utils.permissions import has_permission
"""Efficiency Blueprint: 人员效能看板, 自动派单+超时催办, 交接班日志, 维修评价, 投诉管理"""
import json
import re
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, request, g
from flask_login import login_required, current_user
from sqlalchemy import func, text

from models import db, WorkOrder, User, SystemSetting, RoleGroup, ShiftHandover, RepairRating, Complaint
from utils.time_helpers import fmt_dt, resolve_team

efficiency_bp = Blueprint('efficiency', __name__, url_prefix='/efficiency')


# ===================== 1. 人员效能看板 =====================

@efficiency_bp.route('/personnel/dashboard', methods=['GET'])
@login_required
def personnel_dashboard():
    """人员效能看板页面"""
    import re
    from utils.time_helpers import resolve_team
    from flask import g
    from services.data_service import get_team_options
    team_list = get_team_options(hospital_id=getattr(g, 'hospital_id', None))
    default_team = resolve_team(request, current_user, setting_key='personnel_default_team')
    return render_template('feature/personnel_dashboard.html',
                           team_list=team_list,
                           default_team=default_team)


@efficiency_bp.route('/personnel/data', methods=['GET'])
@login_required
def personnel_data():
    """人员效能统计 JSON（支持 hospital 和 group 过滤）"""
    from utils.time_helpers import resolve_team

    group_id = request.args.get('group_id', type=int)
    team = request.args.get('team')
    # 未指定 team 时自动解析当前用户所属团队
    if team is None:
        team = resolve_team(request, current_user, setting_key='personnel_default_team')
    hid = getattr(g, 'hospital_id', None)

    # --- 1. 一次性查出所有符合条件的 Person 名单 ---
    # 团队/角色组过滤
    person_scope = None  # None = 不限制
    scope_sql = []
    scope_params = {}
    if team:
        scope_sql.append("team = :team")
        scope_params['team'] = team
    if group_id:
        scope_sql.append("group_id = :gid")
        scope_params['gid'] = group_id
    if scope_sql:
        scope_where = " AND ".join(scope_sql)
        scope_rows = db.session.execute(
            text(f"SELECT display_name FROM users WHERE is_active = 1 AND ({scope_where})"),
            scope_params
        ).fetchall()
        person_scope = {r[0] for r in scope_rows}
        if not person_scope:
            # 该团队/组下无在岗人员
            groups = RoleGroup.query.order_by(RoleGroup.name).all()
            return jsonify(success=True, data=[], total=0, groups=[{'id': rg.id, 'name': rg.name} for rg in groups])

    # --- 2. 基础聚合：按 person 聚合已完成工单的 总数+耗时 ---
    # 用 raw SQL 绕过 ORM + auto_hospital_filter 性能问题
    agg_sql = "SELECT person, COUNT(id) as total_orders, " \
              "SUM(CAST(julianday(completed_at) - julianday(created_at) AS REAL)) as total_days " \
              "FROM work_orders WHERE person != '' AND person IS NOT NULL " \
              "AND completed_at IS NOT NULL AND created_at IS NOT NULL"
    agg_params = {}
    if person_scope is not None:
        placeholders = ','.join(f':ps{i}' for i in range(len(person_scope)))
        agg_sql += f" AND person IN ({placeholders})"
        for i, n in enumerate(person_scope):
            agg_params[f'ps{i}'] = n
    if hid:
        agg_sql += " AND hospital_id = :agg_hid"
        agg_params['agg_hid'] = hid
    agg_sql += " GROUP BY person"
    agg_rows = db.session.execute(text(agg_sql), agg_params).fetchall()
    person_names = {r[0] for r in agg_rows}

    # --- 3. 批量查询：所有人员的 in_progress / pending ---
    st_sql = "SELECT person, status FROM work_orders WHERE person IS NOT NULL AND person != ''"
    st_params = {}
    if person_names:
        placeholders = ','.join(f':sn{i}' for i in range(len(person_names)))
        st_sql += f" AND person IN ({placeholders})"
        for i, n in enumerate(person_names):
            st_params[f'sn{i}'] = n
    st_sql += " AND status IN ('in_progress', 'pending')"
    if hid:
        st_sql += " AND hospital_id = :st_hid"
        st_params['st_hid'] = hid
    status_rows = db.session.execute(text(st_sql), st_params).fetchall()
    status_map = {}
    for sr in status_rows:
        name, st = sr[0], sr[1]
        if name not in status_map:
            status_map[name] = {'in_progress': 0, 'pending': 0}
        if st in status_map[name]:
            status_map[name][st] += 1

    # --- 4. 批量查询：所有人员的 SLA 数据（is_overdue 是 Python property，需在代码中计算）---
    if person_names:
        # 先读 SLA 阈值（只读一次，避免每条工单都查 DB）
        def _batch_get_th():
            rows = SystemSetting.query.with_entities(SystemSetting.key, SystemSetting.value).filter(
                SystemSetting.key.like('sla_response_%') | SystemSetting.key.like('sla_resolution_%')
            ).all()
            return {r.key: float(r.value) for r in rows if r.value}
        sla_th_cache = _batch_get_th()
        def _get_th(key, default):
            return sla_th_cache.get(key, default)

        # 用 raw SQL 避免 SQLAlchemy `is_overdue` property 问题
        sla_sql = "SELECT person, priority, created_at, completed_at, end_time " \
                  "FROM work_orders WHERE status = 'completed'"
        sla_params = {}
        if hid:
            sla_sql += " AND hospital_id = :hid"
            sla_params['hid'] = hid
        # 用 IN 批量查
        placeholders = ','.join(f':n{i}' for i in range(len(person_names)))
        sla_sql += f" AND person IN ({placeholders})"
        for i, n in enumerate(person_names):
            sla_params[f'n{i}'] = n
        sla_fields = db.session.execute(text(sla_sql), sla_params).fetchall()
    else:
        sla_fields = []
    # 读 SLA 阈值
    def _get_th(key, default):
        s = SystemSetting.query.with_entities(SystemSetting.value).filter_by(key=key).scalar()
        return float(s) if s else default
    sla_map = {}
    for sr in sla_fields:
        name = sr[0]
        priority = sr[1] or 'normal'
        created_raw = sr[2]
        completed_raw = sr[4] or sr[3]  # end_time > completed_at
        if not created_raw or not completed_raw:
            continue
        # SQLite 返回字符串，需转为 datetime
        try:
            created = datetime.strptime(str(created_raw)[:19], '%Y-%m-%d %H:%M:%S')
            completed = datetime.strptime(str(completed_raw)[:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        resp_th = _get_th(f'sla_response_{priority}',
                          {'emergency': 0.5, 'urgent': 2, 'normal': 4}.get(priority, 4))
        resol_th = _get_th(f'sla_resolution_{priority}',
                           {'emergency': 2, 'urgent': 8, 'normal': 24}.get(priority, 24))
        duration_h = (completed - created).total_seconds() / 3600
        overdue = duration_h > (resp_th + resol_th)
        if name not in sla_map:
            sla_map[name] = {'total': 0, 'ok': 0}
        sla_map[name]['total'] += 1
        if not overdue:
            sla_map[name]['ok'] += 1

    # --- 5. 在岗人员名单 ---
    active_q = text("SELECT display_name FROM users WHERE is_active = 1")
    active_params = {}
    if hid:
        active_q = text("SELECT display_name FROM users WHERE is_active = 1 AND hospital_id = :hid")
        active_params['hid'] = hid
    p_rows = db.session.execute(active_q, active_params).fetchall()
    all_active_names = {r[0] for r in p_rows}
    if person_scope is not None:
        all_active_names &= person_scope

    # --- 6. 组装结果 ---
    stats = []
    for row in agg_rows:
        name = row.person
        total = row.total_orders
        total_days = float(row.total_days or 0)
        avg_hours = round(total_days * 24 / total, 1) if total > 0 else 0

        st = status_map.get(name, {})
        sl = sla_map.get(name, {})
        sla_pct = round(sl['ok'] / sl['total'] * 100) if sl.get('total', 0) > 0 else 0

        stats.append({
            'name': name,
            'total_orders': total,
            'in_progress': st.get('in_progress', 0),
            'pending': st.get('pending', 0),
            'avg_hours': avg_hours,
            'active': name in all_active_names,
            'sla_total': sl.get('total', 0),
            'sla_ok': sla_pct,
        })

    stats.sort(key=lambda x: x['total_orders'], reverse=True)

    groups = RoleGroup.query.order_by(RoleGroup.name).all()
    group_list = [{'id': rg.id, 'name': rg.name} for rg in groups]

    return jsonify(success=True, data=stats, total=len(stats), groups=group_list)


# ===================== 2. 自动派单 + 超时催办 快捷开关 =====================

def _get_feature_toggle(key, default='false'):
    """获取功能开关状态"""
    s = SystemSetting.query.filter_by(key=f'feature_toggle_{key}').first()
    if s:
        return s.value
    return default


def _set_feature_toggle(key, value):
    """设置功能开关"""
    SystemSetting.set(f'feature_toggle_{key}', value,
                      label=key, category='功能开关')


@efficiency_bp.route('/auto-assign/check', methods=['POST'])
@login_required
def auto_assign_check():
    """自动派单检查：检查订单是否应自动分配"""
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')
    if not order_id:
        return jsonify(success=False, error='缺少工单ID'), 400
    if _get_feature_toggle('auto_assign') != 'true':
        return jsonify(success=True, assigned=False, reason='自动派单未启用')

    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify(success=False, error='工单不存在'), 404

    # 找最闲的匹配人员：同故障类型待处理最少的
    available = User.query.filter(
        User.is_active == True,
        User.display_name != ''
    ).all()

    best_person = None
    min_load = 999
    for u in available:
        load = WorkOrder.query.filter(
            WorkOrder.person == u.display_name,
            WorkOrder.status.in_(['pending', 'in_progress'])
        ).count()
        if load < min_load:
            # 优先匹配同故障类型的处理经验
            same_type_count = WorkOrder.query.filter(
                WorkOrder.person == u.display_name,
                WorkOrder.fault_type == order.fault_type
            ).count()
            weighted = load - same_type_count * 0.3  # 有经验的人权重更轻
            if weighted < min_load:
                min_load = weighted
                best_person = u.display_name

    if best_person:
        order.person = best_person
        db.session.commit()
        return jsonify(success=True, assigned=True, person=best_person)
    return jsonify(success=True, assigned=False, reason='无可用人员')


@efficiency_bp.route('/timeout-reminder/check', methods=['POST'])
@login_required
def timeout_reminder_check():
    """超时催办检查：检查超时工单并推送"""
    from flask import current_app

    if _get_feature_toggle('timeout_reminder') != 'true':
        return jsonify(success=True, notified=0, reason='超时催办未启用')

    timeout_hours_setting = SystemSetting.query.filter_by(key='wecom_timeout_hours').first()
    timeout_hours = float(timeout_hours_setting.value) if timeout_hours_setting and timeout_hours_setting.value else 4.0

    now = datetime.now()
    threshold_time = now - timedelta(hours=timeout_hours)

    # 查找超时未处理工单
    overdue_orders = WorkOrder.query.filter(
        WorkOrder.status.in_(['pending', 'in_progress']),
        WorkOrder.created_at < threshold_time,
        WorkOrder.wecom_timeout_notified == False
    ).all()

    notified = 0
    for order in overdue_orders:
        try:
            from routes.api_mobile import send_wecom_notification
            send_wecom_notification(order, is_urge=True)
            order.wecom_timeout_notified = True
            notified += 1
        except Exception as e:
            current_app.logger.error(f'超时催办通知失败: {e}')

    if notified > 0:
        db.session.commit()

    return jsonify(success=True, notified=notified)


@efficiency_bp.route('/feature-toggles', methods=['GET'])
@login_required
def get_feature_toggles():
    """获取所有功能开关状态"""
    return jsonify(success=True, toggles={
        'auto_assign': _get_feature_toggle('auto_assign'),
        'timeout_reminder': _get_feature_toggle('timeout_reminder'),
    })


@efficiency_bp.route('/feature-toggle/save', methods=['POST'])
@login_required
def save_feature_toggle():
    """保存功能开关"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    key = request.form.get('key', '')
    value = request.form.get('value', 'false')
    if key not in ('auto_assign', 'timeout_reminder'):
        return jsonify(success=False, error='无效的开关'), 400
    _set_feature_toggle(key, value)
    return jsonify(success=True)


# ===================== 3. 交接班日志 =====================

@efficiency_bp.route('/shift-handover', methods=['GET'])
@login_required
def shift_handover():
    """交接班日志列表页"""
    handovers = ShiftHandover.query.order_by(ShiftHandover.created_at.desc()).all()
    # 未完成工单列表
    pending_orders = WorkOrder.query.filter(
        WorkOrder.status.in_(['pending', 'in_progress'])
    ).order_by(WorkOrder.created_at.desc()).all()
    # 人员列表
    persons = User.query.filter(User.is_active == True).order_by(User.display_name).all()
    return render_template('feature/shift_handover.html',
                           stats={
                               'total': len(handovers),
                               'today': sum(1 for h in handovers if h.created_at and h.created_at.date() == datetime.now().date()),
                               'unfinished': len(pending_orders),
                               'staff_count': len(set(h.handover_person for h in handovers) | set(h.receive_person for h in handovers)),
                           },
                           handovers=handovers,
                           handovers_json=json.dumps([{
                               'id': h.id,
                               'handover_person': h.handover_person,
                               'receive_person': h.receive_person,
                               'content': h.content,
                               'unfinished_orders': h.unfinished_orders or [],
                               'notes': h.notes,
                               'status': h.status,
                               'created_at': fmt_dt(h.created_at, '%Y-%m-%d %H:%M'),
                           } for h in handovers], ensure_ascii=False),
                           pending_orders=pending_orders,
                           pending_orders_json=json.dumps([{
                               'id': o.id, 'title': o.title,
                               'status': o.status, 'priority': o.priority,
                               'department': o.department, 'person': o.person,
                           } for o in pending_orders], ensure_ascii=False),
                           persons=persons)


@efficiency_bp.route('/shift-handover/save', methods=['POST'])
@login_required
def shift_handover_save():
    """保存交接班记录"""
    if not has_permission(current_user, 'system:config'):
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    handover_person = data.get('handover_person', '').strip()
    receive_person = data.get('receive_person', '').strip()
    content = data.get('content', '').strip()
    unfinished_order_ids = data.get('unfinished_order_ids', [])
    notes = data.get('notes', '').strip()
    if not handover_person or not receive_person:
        return jsonify(success=False, error='交班人和接班人不能为空'), 400
    orders_summary = []
    if unfinished_order_ids:
        orders = WorkOrder.query.filter(WorkOrder.id.in_(unfinished_order_ids)).all()
        for o in orders:
            orders_summary.append({
                'id': o.id, 'title': o.title,
                'department': o.department, 'priority': o.priority
            })
    handover = ShiftHandover.new_with_hospital(
        handover_person=handover_person,
        receive_person=receive_person,
        content=content,
        unfinished_orders=orders_summary,
        notes=notes,
        status='completed',
    )
    db.session.add(handover)
    db.session.commit()
    return jsonify(success=True, id=handover.id)


@efficiency_bp.route('/shift-handover/<int:hid>', methods=['GET'])
@login_required
def shift_handover_detail(hid):
    """获取交接班记录详情"""
    h = ShiftHandover.query.get(hid)
    if not h:
        return jsonify(success=False, error='记录不存在'), 404
    return jsonify(success=True, data={
        'id': h.id,
        'handover_person': h.handover_person,
        'receive_person': h.receive_person,
        'content': h.content,
        'unfinished_orders': h.unfinished_orders or [],
        'notes': h.notes,
        'status': h.status,
        'created_at': fmt_dt(h.created_at, '%Y-%m-%d %H:%M'),
    })


# ===================== 4. 维修评价 =====================

@efficiency_bp.route('/repair-ratings', methods=['GET'])
@login_required
def repair_ratings():
    """维修评价列表页"""
    page = request.args.get('page', 1, type=int)
    rating_filter = request.args.get('rating', type=int)
    q = RepairRating.query.order_by(RepairRating.created_at.desc())
    q = q.filter(RepairRating.rating == rating_filter)
    pagination = q.paginate(page=page, per_page=20, error_out=False)
    ratings = pagination.items
    stats = {
        'total': RepairRating.query.count(),
        'avg': db.session.query(func.avg(RepairRating.rating)).scalar() or 0,
        'five_star': RepairRating.query.filter(RepairRating.rating == 5).count(),
        'low_score': RepairRating.query.filter(RepairRating.rating <= 2).count(),
    }
    return render_template('feature/repair_ratings.html',
                           ratings=ratings, pagination=pagination, stats=stats)


@efficiency_bp.route('/repair-rating/save', methods=['POST'])
@login_required
def repair_rating_save():
    """提交维修评价"""
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')
    rating = data.get('rating', 5)
    comment = data.get('comment', '').strip()
    if not order_id:
        return jsonify(success=False, error='缺少工单ID'), 400
    existing = RepairRating.query.filter_by(work_order_id=order_id).first()
    if existing:
        existing.rating = rating
        existing.comment = comment
        existing.created_by = current_user.display_name or current_user.username
    else:
        rr = RepairRating.new_with_hospital(
            work_order_id=order_id,
            rating=rating,
            comment=comment,
            created_by=current_user.display_name or current_user.username,
        )
        db.session.add(rr)
    db.session.commit()
    return jsonify(success=True)


@efficiency_bp.route('/repair-rating/<int:oid>/detail', methods=['GET'])
@login_required
def repair_rating_detail(oid):
    """评价详情"""
    rr = RepairRating.query.filter_by(work_order_id=oid).first()
    if not rr:
        return jsonify(success=False, error='未找到评价'), 404
    wo = WorkOrder.query.get(oid)
    return jsonify(success=True, data={
        'id': rr.id,
        'order_id': rr.work_order_id,
        'order_title': wo.title if wo else '',
        'rating': rr.rating,
        'comment': rr.comment,
        'reviewer': rr.created_by,
        'created_at': fmt_dt(rr.created_at, '%Y-%m-%d %H:%M'),
    })


# ===================== 5. 投诉管理 =====================

@efficiency_bp.route('/complaints', methods=['GET'])
@login_required
def complaints():
    """投诉管理列表页"""
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    stats = {
        'pending': Complaint.query.filter_by(status='pending').count(),
        'processing': Complaint.query.filter_by(status='processing').count(),
        'resolved': Complaint.query.filter_by(status='resolved').count(),
        'closed': Complaint.query.filter_by(status='closed').count(),
    }
    return render_template('feature/complaints.html',
                           complaints=complaints,
                           complaints_json=json.dumps([{
                               'id': c.id, 'title': c.title,
                               'description': c.description,
                               'complainant': c.complainant,
                               'department': c.department,
                               'handler': c.handler,
                               'status': c.status,
                               'resolution': c.resolution,
                               'resolved_at': fmt_dt(c.resolved_at, '%Y-%m-%d %H:%M'),
                               'created_at': fmt_dt(c.created_at, '%Y-%m-%d %H:%M'),
                           } for c in complaints], ensure_ascii=False),
                           stats=stats)


@efficiency_bp.route('/complaint/save', methods=['POST'])
@login_required
def complaint_save():
    """保存投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    complainant = data.get('complainant', '').strip()
    department = data.get('department', '').strip()
    if not title or not complainant:
        return jsonify(success=False, error='标题和投诉人不能为空'), 400
    if cid:
        c = Complaint.query.get(cid)
        if not c:
            return jsonify(success=False, error='投诉不存在'), 404
        c.title = title
        c.description = description
        c.complainant = complainant
        c.department = department
    else:
        c = Complaint.new_with_hospital(title=title, description=description,
                      complainant=complainant, department=department)
        db.session.add(c)
    db.session.commit()
    return jsonify(success=True)


@efficiency_bp.route('/complaint/handle', methods=['POST'])
@login_required
def complaint_handle():
    """处理投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    handler = data.get('handler', '').strip()
    resolution = data.get('resolution', '').strip()
    new_status = data.get('status', 'processing')
    c = Complaint.query.get(cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.handler = handler or current_user.display_name or current_user.username
    c.resolution = resolution
    c.status = new_status
    if new_status == 'resolved':
        c.resolved_at = datetime.now()
    db.session.commit()
    return jsonify(success=True)


@efficiency_bp.route('/complaint/close', methods=['POST'])
@login_required
def complaint_close():
    """关闭投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    c = Complaint.query.get(cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.status = 'closed'
    db.session.commit()
    return jsonify(success=True)


@efficiency_bp.route('/complaint/reopen', methods=['POST'])
@login_required
def complaint_reopen():
    """重新打开投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    c = Complaint.query.get(cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.status = 'processing'
    db.session.commit()
    return jsonify(success=True)
