"""人员管理子蓝图（从 routes/data.py 提取）"""

from utils.helpers import safe_get, safe_get_or_404
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, User, WorkOrder, SystemSetting, Hospital, RoleGroup
from routes.auth import admin_required
from utils.permissions import permission_required, has_permission
from services import data_service
from datetime import datetime

data_personnel_bp = Blueprint('data_personnel', __name__, url_prefix='/data/personnel')


@data_personnel_bp.route('/')
@permission_required('user:view')
def index():
    """人员列表页"""
    persons, user_map = data_service.list_persons()
    import re

    # 获取每个人员的工单数
    order_counts = {}
    for p in persons:
        name = p.display_name or p.username
        if name:
            cnt = WorkOrder.query.filter(WorkOrder.created_by == name).count()
            if cnt:
                order_counts[p.id] = cnt
    from flask import g
    cur_hid = getattr(g, 'hospital_id', None)
    team_options = data_service.get_team_options(hospital_id=cur_hid if cur_hid and cur_hid != 0 else None)
    hospitals = Hospital.query.order_by(Hospital.id).all()
    hospital_map = {h.id: h for h in hospitals}
    role_groups = RoleGroup.query.order_by(RoleGroup.id).all()

    team_sel = request.args.get('team', '')
    if not team_sel:
        if has_permission(current_user, 'user:view'):
            _def_setting = SystemSetting.query.filter_by(key='default_dashboard_team').first()
            team_sel = _def_setting.value if _def_setting and _def_setting.value else ''
        else:
            if current_user.team:
                team_sel = current_user.team
    if team_sel:
        persons = [p for p in persons if p.team == team_sel]

    from collections import OrderedDict
    hospital_groups = OrderedDict()
    for p in persons:
        h_name = None
        if p.hospital_id and p.hospital_id in hospital_map:
            h_name = hospital_map[p.hospital_id].name
        if not h_name:
            h_list = p.hospitals.all()
            if h_list:
                h_name = h_list[0].name
        h_name = h_name or '未分配医院'
        if h_name not in hospital_groups:
            hospital_groups[h_name] = {}
        t = p.team or '未分组'
        if t not in hospital_groups[h_name]:
            hospital_groups[h_name][t] = []
        hospital_groups[h_name][t].append(p)
    return render_template('data/persons.html', persons=persons, user_map=user_map,
                           team_options=team_options,
                           hospital_groups=hospital_groups, hospitals=hospitals,
                           role_groups=role_groups, team_sel=team_sel,
                           order_counts=order_counts)


@data_personnel_bp.route('/add', methods=['POST'])
@permission_required('user:create')
def add():
    ok, msg = data_service.add_person(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/import-from-orders', methods=['POST'])
@permission_required('user:create')
def import_from_orders():
    imported = data_service.import_persons_from_orders()
    flash(f'从工单中导入 {imported} 名新人员', 'success')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/<int:pid>/toggle', methods=['POST'])
@permission_required('user:edit')
def toggle(pid):
    p = data_service.toggle_person(pid)
    flash(f'已{"停用" if not p.is_active else "启用"}「{p.display_name}」', 'success')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/<int:pid>/delete', methods=['POST'])
@permission_required('user:delete')
def delete(pid):
    p = safe_get_or_404(User, pid)
    if p.is_admin:
        flash('管理员账号不可删除', 'danger')
        return redirect(url_for('data_personnel.index'))
    name, err = data_service.delete_person(pid, current_user.display_name or current_user.username)
    if err:
        flash(err, 'danger')
    else:
        flash(f'已删除人员「{name}」', 'success')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/<int:pid>/reassign-orders', methods=['POST'])
@permission_required('user:edit')
def reassign_orders(pid):
    p = safe_get_or_404(User, pid)
    source_name = p.display_name or p.username
    target_name = request.form.get('target_name', '').strip()
    if not target_name:
        flash('请填写接收人姓名', 'warning')
        return redirect(url_for('data_personnel.index'))
    count = WorkOrder.query.filter(WorkOrder.created_by == source_name).update(
        {WorkOrder.created_by: target_name}, synchronize_session=False
    )
    db.session.commit()
    from models import log_audit
    log_audit('reassign_orders', f'{source_name}→{target_name}', current_user.display_name or current_user.username,
              target_id=pid, target_desc=f'批量转移工单 {count} 条')
    flash(f'已将 {source_name} 的 {count} 条工单转移给 {target_name}', 'success')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/<int:pid>/edit-field', methods=['POST'])
@permission_required('user:edit')
def edit_field(pid):
    field = request.form.get('field', '')
    value = request.form.get('value', '').strip()
    ok, err = data_service.edit_person_field(pid, field, value)
    if ok:
        flash('已更新', 'success')
    else:
        flash(err or '未知字段', 'danger')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/batch-action', methods=['POST'])
@permission_required('user:edit')
def batch_action():
    action = request.form.get('batch_action', '')
    ids_str = request.form.get('batch_ids', '')
    value = request.form.get('batch_value', '').strip()
    ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
    if not ids:
        flash('未选择有效的人员', 'warning')
        return redirect(url_for('data_personnel.index'))

    count = 0
    try:
        if action == 'enable':
            count = User.query.filter(User.id.in_(ids)).update({User.is_active: True}, synchronize_session=False)
            db.session.commit()
            flash(f'已启用 {count} 名人员', 'success')
        elif action == 'disable':
            count = User.query.filter(User.id.in_(ids)).update({User.is_active: False}, synchronize_session=False)
            db.session.commit()
            flash(f'已禁用 {count} 名人员', 'success')
        elif action == 'change_team':
            if not value:
                flash('请选择目标组', 'warning')
                return redirect(url_for('data_personnel.index'))
            count = User.query.filter(User.id.in_(ids)).update({User.team: value}, synchronize_session=False)
            db.session.commit()
            flash(f'已将 {count} 名人员移动到「{value}」', 'success')
        elif action == 'delete':
            protected = []
            deleted_names = []
            for pid in ids:
                p = safe_get(User, pid)
                if p:
                    name = p.display_name or p.username
                    wo_count = WorkOrder.query.filter(WorkOrder.created_by == name).count()
                    if wo_count:
                        protected.append(name)
                        continue
                    deleted_names.append(name)
                    from models import log_audit
                    log_audit('delete_person', f'删除人员「{name}」', current_user.display_name or current_user.username)
                    db.session.delete(p)
            db.session.commit()
            if protected:
                flash(f'已删除 {len(deleted_names)} 名人员；{len(protected)} 名人员因有关联工单记录被跳过：{", ".join(protected)}', 'warning')
            else:
                flash(f'已删除 {len(deleted_names)} 名人员', 'success')
        else:
            flash(f'未知操作: {action}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'批量操作失败：{str(e)}', 'danger')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/<int:pid>/account', methods=['GET', 'POST'])
@permission_required('user:create')
def account(pid):
    if request.method == 'GET':
        return jsonify(data_service.person_account_info(pid))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    display_name = request.form.get('display_name', '').strip()
    is_admin = request.form.get('is_admin') == 'on'
    hospital_ids = request.form.getlist('hospital_ids')
    group_id = request.form.get('group_id', type=int)
    ok, msg = data_service.person_account_save(pid, username, password, display_name, is_admin, hospital_ids, group_id)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_personnel.index'))


@data_personnel_bp.route('/lottery-json')
@permission_required('user:view')
def lottery_json():
    from flask import session
    hid = session.get('hospital_id')
    team = request.args.get('team', '')
    query = User.query.filter(User.is_active == True)
    if hid:
        query = query.filter_by(hospital_id=hid)
    if team:
        query = query.filter(User.team == team)
    persons = query.order_by(db.func.random()).all()
    colors = ['#FF6B6B','#FECA57','#48DBFB','#FF9FF3','#54A0FF','#5F27CD','#01A3A4','#F368E0','#EE5A24','#0ABDE3','#10AC84','#5D62E5','#A29BFE','#FD79A8','#6C5CE7','#00CEC9','#E17055','#0984E3']
    data = [{'id': p.id, 'name': p.display_name, 'color': colors[i % len(colors)]} for i, p in enumerate(persons)]
    return jsonify({'persons': data, 'total': len(data)})
