"""跨院区借调管理 - 借调记录 CRUD + 权限控制"""
import json
from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, jsonify, request, g, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from models import (
    db, CrossHospitalAssignment, Hospital, User,
    log_audit,
)
from utils.time_helpers import fmt_dt, fmt_date, now, today_start
from utils.permissions import permission_required

cross_bp = Blueprint('cross', __name__, url_prefix='/cross')


def _get_hospital_id():
    """获取当前用户作用中的院区ID"""
    hid = getattr(g, 'hospital_id', 0)
    return hid if hid else 0


def _json_error(msg, code=400):
    return jsonify(success=False, error=msg), code


def _json_success(data=None, **kw):
    result = {'success': True}
    if data is not None:
        result['data'] = data
    result.update(kw)
    return jsonify(result)


# ======================== 页面路由 ========================


@cross_bp.route('/assignments')
@permission_required('biz:cross_assign')
def assignments_page():
    """借调管理页面"""
    hid = _get_hospital_id()
    hospital = Hospital.query.get(hid) if hid else None

    # 获取所有医院列表（供创建借调时选择借调目标院区）
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

    # 本院作为 target_hospital 的活跃借调 + 所有历史记录
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # 借调记录：本院是被借调目标（借来的人）
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

        # 计算剩余天数
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

    # 当前活跃借调中的 user_id 集合（跨所有医院，一个用户不能被借调两次）
    active_assigned = set()
    active_records = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.status == 'active'
    ).all()
    for rec in active_records:
        active_assigned.add(rec.user_id)

    # 获取除本院以外的所有医院（借调人员来源）
    source_hospitals = Hospital.query.filter(
        Hospital.id != hid,
        Hospital.is_active == True
    ).all()
    source_hospital_ids = [h.id for h in source_hospitals]

    if not source_hospital_ids:
        return _json_suggestions({'users': [], 'hospitals': []})

    # 查询其他院区可用用户
    # 排除：本院用户、管理员用户、已处于借调状态的用户
    users_query = User.query.filter(
        User.hospital_id.in_(source_hospital_ids),
        User.is_admin == False,
    )

    # 排除已借调人员
    if active_assigned:
        users_query = users_query.filter(~User.id.in_(active_assigned))

    # 可选搜索
    q = request.args.get('q', '').strip()
    if q:
        users_query = users_query.filter(
            or_(
                User.name.ilike(f'%{q}%'),
                User.username.ilike(f'%{q}%'),
            )
        )

    # 按医院分组
    users = users_query.order_by(User.hospital_id, User.sort_order, User.id).all()

    # 返回按医院分组的用户列表
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

    # 校验参数
    if not user_id:
        return _json_error('请选择被借调人员')
    if not start_date_str or not end_date_str:
        return _json_error('请填写借调起止日期')

    user = User.query.get(user_id)
    if not user:
        return _json_error('用户不存在')
    if user.is_admin:
        return _json_error('管理员不能被借调')

    # 校验所属医院
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
        return _json_error(f'该用户当前已有活跃借调（目标院区：{existing.target_hospital.name}）')

    # 创建借调记录
    assignment = CrossHospitalAssignment(
        hospital_id=hid,          # 目标院区（HospitalMixin）
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

    # 标记用户处于借调状态
    user.is_cross_assigned = True

    try:
        db.session.commit()
        log_audit(
            'create', 'cross_assignment', current_user.name or current_user.username,
            target_id=assignment.id,
            target_desc=f'借调 {user.name} 到 {assignment.target_hospital.name}',
            detail=json.dumps({
                'user_id': user_id, 'user_name': user.name,
                'start_date': start_date_str, 'end_date': end_date_str,
                'reason': reason, 'source_hospital_name': Hospital.query.get(user.hospital_id).name if user.hospital_id else '',
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
        # 检查该用户是否还有其他活跃借调
        other_active = CrossHospitalAssignment.query.filter(
            CrossHospitalAssignment.user_id == assignment.user_id,
            CrossHospitalAssignment.status == 'active',
            CrossHospitalAssignment.id != assignment.id,
        ).count()
        if other_active == 0:
            user.is_cross_assigned = False

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


@cross_bp.route('/api/cross-users')
@login_required
def get_cross_users():
    """获取当前医院所有活跃借调人员的ID列表（供权限系统使用）"""
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
    # 校验内部token
    token = request.headers.get('X-Internal-Token', '')
    expected = current_app.config.get('INTERNAL_API_TOKEN', '')
    if expected and token != expected:
        return _json_error('无效的请求令牌', 403)

    now_dt = now()
    expired = CrossHospitalAssignment.query.filter(
        CrossHospitalAssignment.status == 'active',
        CrossHospitalAssignment.end_date < now_dt,
    ).all()

    count = 0
    for assignment in expired:
        assignment.status = 'expired'
        user = User.query.get(assignment.user_id)
        if user:
            # 检查是否有其他活跃借调
            other_active = CrossHospitalAssignment.query.filter(
                CrossHospitalAssignment.user_id == assignment.user_id,
                CrossHospitalAssignment.status == 'active',
                CrossHospitalAssignment.id != assignment.id,
            ).count()
            if other_active == 0:
                user.is_cross_assigned = False
        count += 1

    try:
        db.session.commit()
        current_app.logger.info(f'自动过期 {count} 条借调记录')
        return _json_success({
            'expired_count': count,
            'message': f'已自动过期 {count} 条借调记录',
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'自动过期借调记录失败: {e}')
        return _json_error('操作失败')


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


def _can_cross_assign(user):
    """检查用户是否拥有跨院借调管理权限的快捷函数"""
    from utils.permissions import has_permission
    return has_permission(user, 'biz:cross_assign')
