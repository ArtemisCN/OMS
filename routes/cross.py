"""跨院区借调管理 - 借调记录 CRUD + 权限控制 + 排班联动 + 操作日志"""
import json
from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, jsonify, request, g, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from models import (
    db, CrossHospitalAssignment, Hospital, User,
    DutySchedule, CrossAssignmentLog,
    log_audit,
)
from utils.time_helpers import fmt_dt, fmt_date, now, today_start
from utils.permissions import permission_required

cross_bp = Blueprint('cross', __name__, url_prefix='/cross')


def _get_hospital_id():
    """获取当前用户作用中的院区ID"""
    hid = getattr(g, 'hospital_id', 0)
    if hid:
        return hid
    # 无医院上下文时回退到默认医院，避免新库/未配置时报错
    from models import SystemSetting
    try:
        default = SystemSetting.query.filter_by(key='default_hospital_id').first()
        if default and default.value:
            return int(default.value)
    except Exception:
        pass
    from models import Hospital
    first_hosp = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).first()
    return first_hosp.id if first_hosp else 0


def _json_error(msg, code=400):
    return jsonify(success=False, error=msg), code


def _json_success(data=None, **kw):
    result = {'success': True}
    if data is not None:
        result['data'] = data
    result.update(kw)
    return jsonify(result)


# ======================== 排班联动辅助函数 ========================


def _upsert_duty_schedule(hospital_id, duty_date, user, shift, tag):
    """在指定院区写入一条排班记录。

    存在同院区同日期同人记录时更新（shift/notes/user_id），否则新建。
    原因：duty_schedules 有 (hospital_id, duty_date, person_name) 唯一索引，
    同一天同一人在同一院区只能有一条排班，避免借调联动时插入冲突。
    """
    user_name = user.display_name or user.name or user.username
    # 临时跳过自动医院过滤：existing 查询显式指定了 hospital_id，避免被 g.hospital_id 干扰
    _prev_hid = getattr(g, 'hospital_id', None)
    try:
        g.hospital_id = None
        existing = DutySchedule.query.filter_by(
            hospital_id=hospital_id,
            duty_date=duty_date,
            person_name=user_name,
        ).first()
    finally:
        g.hospital_id = _prev_hid
    if existing:
        existing.shift = shift
        existing.user_id = user.id
        existing.notes = tag
        return existing
    record = DutySchedule(
        hospital_id=hospital_id,
        duty_date=duty_date,
        person_name=user_name,
        user_id=user.id,
        shift=shift,
        notes=tag,
    )
    db.session.add(record)
    return record


def _add_duty_schedule_records(assignment):
    """为借调记录创建排班标记（目标院区=支援, 本院区=被借调）"""
    user = assignment.user
    if not user:
        return
    tag = f'cross_assignment:{assignment.id}'
    # 目标院区：插入 '支援' 排班
    _upsert_duty_schedule(assignment.target_hospital_id, assignment.start_date, user, '支援', tag)
    # 本院区：插入 '被借调' 排班
    _upsert_duty_schedule(assignment.source_hospital_id, assignment.start_date, user, '被借调', tag)


def _cleanup_duty_schedule_records(assignment):
    """清除借调相关的排班标记"""
    tag = f'cross_assignment:{assignment.id}'
    # 临时跳过自动医院过滤：排班记录分属两个院区，必须全量清除
    _prev_hid = getattr(g, 'hospital_id', None)
    try:
        g.hospital_id = None
        DutySchedule.query.filter(
            DutySchedule.notes == tag
        ).delete(synchronize_session=False)
    finally:
        g.hospital_id = _prev_hid


def _sync_duty_schedule_dates(assignment):
    """借调日期修改后，同步更新排班记录日期（保留 shift 标记）"""
    tag = f'cross_assignment:{assignment.id}'
    # 临时跳过自动医院过滤：排班记录分属两个院区，必须全量更新
    _prev_hid = getattr(g, 'hospital_id', None)
    try:
        g.hospital_id = None
        records = DutySchedule.query.filter(DutySchedule.notes == tag).all()
        for rec in records:
            rec.duty_date = assignment.start_date
    finally:
        g.hospital_id = _prev_hid


def _log_cross_action(assignment, action, operator_id, old_value=None, new_value=None):
    """记录借调操作日志"""
    log = CrossAssignmentLog(
        assignment_id=assignment.id,
        action=action,
        operator_id=operator_id,
        old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
        new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
    )
    db.session.add(log)


def _auto_expire_overdue():
    """自动过期检查 — 提取为公共函数，多处复用"""
    now_dt = now()
    expire_cutoff = now_dt.replace(hour=23, minute=0, second=0, microsecond=0)
    overdue = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.status == 'active',
        CrossHospitalAssignment.end_date < expire_cutoff,
    ).all()

    expired_ids = []
    for assignment in overdue:
        assignment.status = 'expired'
        user = User.query.get(assignment.user_id)
        if user:
            other_active = CrossHospitalAssignment.query.filter(
                CrossHospitalAssignment.user_id == assignment.user_id,
                CrossHospitalAssignment.status == 'active',
                CrossHospitalAssignment.id != assignment.id,
            ).count()
            if other_active == 0:
                user.is_cross_assigned = False
        # 清除排班标记
        _cleanup_duty_schedule_records(assignment)
        # 记录操作日志
        _log_cross_action(
            assignment, 'expire', operator_id=0,
            new_value={'status': 'expired'}
        )
        expired_ids.append(assignment.id)

    if overdue:
        db.session.commit()
        current_app.logger.info(f'自动过期 {len(overdue)} 条借调记录: {expired_ids}')
    return len(overdue)


# ======================== 页面路由 ========================


@cross_bp.route('/assignments')
@permission_required('biz:cross_assign')
def assignments_page():
    """借调管理页面"""
    hid = _get_hospital_id()
    hospital = Hospital.query.get(hid) if hid else None

    # 获取所有医院列表
    hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()

    return render_template(
        'cross/index.html',
        hospital=hospital,
        hospitals=hospitals,
        now=datetime.now(),
    )


# ======================== API 路由 ========================


@cross_bp.route('/api/assignments')
@login_required
def get_assignments():
    """获取当前医院的所有借调记录"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    # ===== 每次加载时自动过期检查 =====
    try:
        _auto_expire_overdue()
    except Exception as e:
        current_app.logger.error(f'自动过期失败: {e}')
        db.session.rollback()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = CrossHospitalAssignment.query.filter_by(hospital_id=hid)

    # 状态过滤
    status = request.args.get('status', '')
    if status:
        if status == 'active':
            query = query.filter(CrossHospitalAssignment.status == 'active')
        elif status == 'expired':
            query = query.filter(CrossHospitalAssignment.status == 'expired')
        elif status == 'cancelled':
            query = query.filter(CrossHospitalAssignment.status == 'cancelled')
        else:
            query = query.filter(CrossHospitalAssignment.status == 'active')

    total = query.count()
    records = query.order_by(
        db.case(
            (CrossHospitalAssignment.status == 'active', 0),
            else_=1
        ),
        CrossHospitalAssignment.created_at.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for r in records:
        user = r.user
        user_name = user.name if user else '未知用户'
        user_group = user.group or ''
        source_hospital_name = r.source_hospital.name if r.source_hospital else ''

        remaining_days = 0
        if r.status == 'active':
            delta = r.end_date - now()
            remaining_days = max(0, delta.days)

        result.append({
            'id': r.id,
            'user_id': r.user_id,
            'user_name': user_name,
            'user_group': user_group,
            'source_hospital_id': r.source_hospital_id,
            'source_hospital_name': source_hospital_name,
            'start_date': fmt_date(r.start_date),
            'end_date': fmt_date(r.end_date),
            'reason': r.reason or '',
            'status': r.status,
            'remaining_days': remaining_days,
            'created_by_name': r.creator.name if r.creator else '',
            'created_at': fmt_dt(r.created_at),
        })

    return _json_success({
        'assignments': result,
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@cross_bp.route('/api/available-users')
@login_required
def get_available_users():
    """获取可被借调的人员（其他院区的未处于借调状态的用户）"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    # 当前活跃借调中的 user_id 集合
    active_assigned = set()
    active_records = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.status == 'active'
    ).all()
    for rec in active_records:
        active_assigned.add(rec.user_id)

    # 获取除本院以外的所有医院
    source_hospitals = Hospital.query.filter(
        Hospital.id != hid,
        Hospital.is_active == True
    ).all()
    source_hospital_ids = [h.id for h in source_hospitals]

    if not source_hospital_ids:
        return _json_success({'users': [], 'hospitals': []})

    users_query = User.query.filter(
        User.hospital_id.in_(source_hospital_ids),
        User.is_admin == False,
    )

    if active_assigned:
        users_query = users_query.filter(~User.id.in_(active_assigned))

    q = request.args.get('q', '').strip()
    if q:
        users_query = users_query.filter(
            or_(
                User.name.ilike(f'%{q}%'),
                User.username.ilike(f'%{q}%'),
            )
        )

    users = users_query.order_by(User.hospital_id, User.sort_order, User.id).all()

    hospital_users = {}
    for h in source_hospitals:
        hospital_users[h.id] = {
            'id': h.id,
            'name': h.name,
            'users': [],
        }

    for u in users:
        h_id = u.hospital_id
        if h_id in hospital_users:
            hospital_users[h_id]['users'].append({
                'id': u.id,
                'name': u.name or u.username,
                'display_name': u.display_name or u.name or u.username,
                'group': u.group or '',
            })

    return _json_success({
        'users': list(hospital_users.values()),
        'hospitals': [
            {'id': h.id, 'name': h.name}
            for h in source_hospitals
        ],
    })


@cross_bp.route('/api/assign', methods=['POST'])
@login_required
def create_assignment():
    """创建借调记录"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if user_id is not None:
        user_id = int(user_id)
    start_date_str = (data.get('start_date') or '').strip()
    end_date_str = (data.get('end_date') or '').strip()
    reason = (data.get('reason') or '临时借调').strip() or '临时借调'

    if not user_id:
        return _json_error('请选择被借调人员')
    if not start_date_str or not end_date_str:
        return _json_error('请填写借调起止日期')

    user = User.query.get(user_id)
    if not user:
        return _json_error('用户不存在')
    if user.is_admin:
        return _json_error('管理员不能被借调')

    if user.hospital_id == hid:
        return _json_error('不能借调本院人员')
    if user.hospital_id not in [h.id for h in Hospital.query.filter_by(is_active=True)]:
        return _json_error('用户所属医院无效')

    # 校验日期
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError:
        return _json_error('日期格式无效，请使用 YYYY-MM-DD')

    today = today_start()
    # 允许当天借调：不允许过去日期，允许 start_date == today
    if start_date < today:
        return _json_error('开始日期不能早于今天')
    if end_date < start_date:
        return _json_error('结束日期不能早于开始日期')

    # 检查用户是否已有活跃借调
    existing = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.user_id == user_id,
        CrossHospitalAssignment.status == 'active',
    ).first()
    if existing:
        return _json_error('该人员当前已有借调，请先撤销后再操作')

    # ===== 创建借调记录 =====
    assignment = CrossHospitalAssignment(
        hospital_id=hid,
        user_id=user_id,
        source_hospital_id=user.hospital_id,
        target_hospital_id=hid,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status='active',
        created_by=current_user.id,
    )
    db.session.add(assignment)
    # 先 flush 获取 assignment.id
    db.session.flush()

    # 标记用户处于借调状态
    user.is_cross_assigned = True

    # 排班联动：目标院区=支援，本院区=被借调
    _add_duty_schedule_records(assignment)

    # 操作日志
    _log_cross_action(
        assignment, 'create', operator_id=current_user.id,
        new_value={
            'user_id': user_id, 'user_name': user.name,
            'source_hospital_id': user.hospital_id,
            'target_hospital_id': hid,
            'start_date': start_date_str, 'end_date': end_date_str,
            'reason': reason,
        }
    )

    try:
        db.session.commit()
        log_audit(
            'create', 'cross_assignment', current_user.name or current_user.username,
            target_id=assignment.id,
            target_desc=f'借调 {user.name} 到 {assignment.target_hospital.name}',
            detail=json.dumps({
                'user_id': user_id, 'user_name': user.name,
                'start_date': start_date_str, 'end_date': end_date_str,
                'reason': reason,
                'source_hospital_name': Hospital.query.get(user.hospital_id).name if user.hospital_id else '',
            }),
        )
        return _json_success({
            'id': assignment.id,
            'message': f'已成功借调 {user.name}，借调期至 {end_date_str}',
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'创建借调记录失败: {e}')
        return _json_error('创建失败，请重试')


@cross_bp.route('/api/assign/<int:assignment_id>', methods=['DELETE'])
@login_required
def cancel_assignment(assignment_id):
    """撤销借调"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()

    assignment = CrossHospitalAssignment.query.get(assignment_id)
    if not assignment:
        return _json_error('借调记录不存在', 404)
    if assignment.hospital_id != hid:
        return _json_error('无权操作其他院区的借调记录')
    if assignment.status != 'active':
        return _json_error('只能撤销活跃状态的借调')

    old_status = assignment.status
    assignment.status = 'cancelled'

    # 清除用户借调标记
    user = User.query.get(assignment.user_id)
    if user:
        other_active = CrossHospitalAssignment.query.filter(
            CrossHospitalAssignment.user_id == assignment.user_id,
            CrossHospitalAssignment.status == 'active',
            CrossHospitalAssignment.id != assignment.id,
        ).count()
        if other_active == 0:
            user.is_cross_assigned = False

    # 清除排班标记
    _cleanup_duty_schedule_records(assignment)

    # 操作日志
    _log_cross_action(
        assignment, 'cancel', operator_id=current_user.id,
        old_value={'status': old_status},
        new_value={'status': 'cancelled'},
    )

    try:
        db.session.commit()
        log_audit(
            'update', 'cross_assignment', current_user.name or current_user.username,
            target_id=assignment_id,
            target_desc=f'撤销借调 {assignment.user.name if assignment.user else ""}',
            detail=json.dumps({
                'assignment_id': assignment_id,
                'old_status': old_status,
                'new_status': 'cancelled',
            }),
        )
        return _json_success(message='已撤销借调')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'撤销借调失败: {e}')
        return _json_error('撤销失败，请重试')


@cross_bp.route('/api/assign/<int:assignment_id>', methods=['PUT'])
@login_required
def update_assignment(assignment_id):
    """修改借调（日期/理由），记录修改前后变化"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    assignment = CrossHospitalAssignment.query.get(assignment_id)
    if not assignment:
        return _json_error('借调记录不存在', 404)
    if assignment.hospital_id != hid:
        return _json_error('无权操作其他院区的借调记录')
    if assignment.status != 'active':
        return _json_error('只能修改活跃状态的借调')

    data = request.get_json(silent=True) or {}
    new_start_str = (data.get('start_date') or '').strip()
    new_end_str = (data.get('end_date') or '').strip()
    new_reason = (data.get('reason') or '').strip()

    if not new_start_str or not new_end_str:
        return _json_error('请填写借调起止日期')

    try:
        new_start = datetime.strptime(new_start_str, '%Y-%m-%d')
        new_end = datetime.strptime(new_end_str, '%Y-%m-%d')
    except ValueError:
        return _json_error('日期格式无效，请使用 YYYY-MM-DD')

    today = today_start()
    if new_start < today:
        return _json_error('开始日期不能早于今天')
    if new_end < new_start:
        return _json_error('结束日期不能早于开始日期')

    # 记录修改前后差异
    old_value = {
        'start_date': fmt_date(assignment.start_date),
        'end_date': fmt_date(assignment.end_date),
        'reason': assignment.reason or '',
    }
    new_value = {
        'start_date': new_start_str,
        'end_date': new_end_str,
        'reason': new_reason,
    }
    changed = {k: v for k, v in new_value.items() if old_value.get(k) != v}
    if not changed:
        return _json_error('没有需要修改的内容')

    # 应用修改
    assignment.start_date = new_start
    assignment.end_date = new_end
    assignment.reason = new_reason or '临时借调'

    # 排班日期同步（start_date 变了则更新排班记录日期）
    if old_value['start_date'] != new_start_str:
        _sync_duty_schedule_dates(assignment)

    # 操作日志
    _log_cross_action(
        assignment, 'update', operator_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )

    try:
        db.session.commit()
        log_audit(
            'update', 'cross_assignment', current_user.name or current_user.username,
            target_id=assignment_id,
            target_desc=f'修改借调 {assignment.user.name if assignment.user else ""}',
            detail=json.dumps({
                'assignment_id': assignment_id,
                'changed': changed,
            }),
        )
        return _json_success(message='已修改借调信息')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'修改借调失败: {e}')
        return _json_error('修改失败，请重试')


@cross_bp.route('/api/cross-users')
@login_required
def get_cross_users():
    """获取当前医院所有活跃借调人员的ID列表"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_success([])

    assignments = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.hospital_id == hid,
        CrossHospitalAssignment.status == 'active',
    ).all()

    user_ids = [a.user_id for a in assignments]
    return _json_success(list(set(user_ids)))


@cross_bp.route('/api/auto-expire', methods=['POST'])
def auto_expire():
    """自动过期借调记录（内部/定时任务调用）"""
    token = request.headers.get('X-Internal-Token', '')
    expected = current_app.config.get('INTERNAL_API_TOKEN', '')
    if expected and token != expected:
        return _json_error('无效的请求令牌', 403)

    try:
        count = _auto_expire_overdue()
        return _json_success({
            'expired_count': count,
            'message': f'已自动过期 {count} 条借调记录',
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'自动过期借调记录失败: {e}')
        return _json_error('操作失败', 500)


@cross_bp.route('/api/history')
@login_required
def get_history():
    """获取当前医院的历史（已过期/已撤销）借调记录"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.hospital_id == hid,
        CrossHospitalAssignment.status.in_(['expired', 'cancelled']),
    )

    total = query.count()
    records = query.order_by(
        CrossHospitalAssignment.updated_at.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for r in records:
        user = r.user
        result.append({
            'id': r.id,
            'user_name': user.name if user else '未知用户',
            'user_group': user.group if user else '',
            'source_hospital_name': r.source_hospital.name if r.source_hospital else '',
            'start_date': fmt_date(r.start_date),
            'end_date': fmt_date(r.end_date),
            'reason': r.reason or '',
            'status': r.status,
            'updated_at': fmt_dt(r.updated_at),
            'created_by_name': r.creator.name if r.creator else '',
        })

    return _json_success({
        'records': result,
        'total': total,
        'page': page,
    })


# ======================== 操作日志 API ========================


@cross_bp.route('/api/logs')
@login_required
def get_logs():
    """获取当前医院的借调操作日志"""
    if not current_user.is_admin and not _can_cross_assign(current_user):
        return _json_error('无权限', 403)

    hid = _get_hospital_id()
    if not hid:
        return _json_error('请选择医院', 400)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # 先找出当前医院的借调记录 ID 列表
    assignment_ids = db.session.query(CrossHospitalAssignment.id).filter(
        CrossHospitalAssignment.hospital_id == hid
    ).subquery()

    query = CrossAssignmentLog.query.filter(
        CrossAssignmentLog.assignment_id.in_(assignment_ids)
    )

    total = query.count()
    logs = query.order_by(CrossAssignmentLog.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    result = []
    for log in logs:
        assignment = log.assignment
        assign_info = None
        if assignment and assignment.user:
            assign_info = {
                'user_name': assignment.user.name or '',
                'source_hospital_name': assignment.source_hospital.name if assignment.source_hospital else '',
                'target_hospital_name': assignment.target_hospital.name if assignment.target_hospital else '',
            }
        result.append({
            'id': log.id,
            'assignment_id': log.assignment_id,
            'action': log.action,
            'action_label': {
                'create': '创建借调',
                'update': '修改借调',
                'cancel': '撤销借调',
                'expire': '自动过期',
            }.get(log.action, log.action),
            'operator_name': log.operator.name if log.operator else '系统',
            'old_value': log.old_value,
            'new_value': log.new_value,
            'created_at': fmt_dt(log.created_at),
            'assignment': assign_info,
        })

    return _json_success({
        'logs': result,
        'total': total,
        'page': page,
    })


def _can_cross_assign(user):
    """检查用户是否拥有跨院借调管理权限的快捷函数"""
    from utils.permissions import has_permission
    return has_permission(user, 'biz:cross_assign')
