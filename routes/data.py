"""基础数据管理路由（HTTP 编排层）"""
import io
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, session, g
from flask_login import login_required, current_user
from datetime import datetime
from models import (db, Department, SolutionTemplate, WorkOrder,
    AddressOverride, User, FaultType, FaultCategory, FaultSubcategory,
    FaultKeyword, Hospital, FaultTemplateGroup, FaultTemplateItem, PartPrice,
    SystemSetting, Asset, SparePart, StorageLocation, Supplier,
    Consumable, ConsumableRecord, DutySchedule, DutyStaff, KnowledgeBase,
    RegistrationRequest, RoleGroup,
    log_audit, get_module_permissions, save_module_permissions, can_access)
import config
from routes.auth import admin_required
from services import data_service
from services.data_service import get_team_options
from utils.time_helpers import resolve_team, fmt_dt
from utils.permissions import permission_required, has_permission
from flask import redirect

data_bp = Blueprint('data', __name__, url_prefix='/data')


# ==================== 医院管理（预留） ====================

@data_bp.route('/hospitals')
@permission_required('system:config')
def list_hospitals():
    """医院列表（豪华卡片版）"""
    hospitals = Hospital.query.order_by(Hospital.id).all()
    from models import User
    # 暂存并清除医院过滤，获取全院数据
    from flask import g as flask_g
    _saved_hid = getattr(flask_g, 'hospital_id', None)
    flask_g.hospital_id = None
    try:
        # 各医院人员数
        person_counts = {}
        for h in hospitals:
            person_counts[h.id] = User.query.filter(User.hospital_id == h.id, User.is_active == True).count()
        # 各医院人员按组别归类
        hospital_person_teams = {}
        for h in hospitals:
            persons = User.query.filter(User.hospital_id == h.id, User.is_active == True).order_by(User.team, User.display_name).all()
            teams = {}
            for p in persons:
                t = p.team or '未分组'
                if t not in teams:
                    teams[t] = []
                account_info = None
                if p.id:
                    u = User.query.get(p.id)
                    account_info = {'username': u.username, 'active': u.is_active} if u else None
                teams[t].append({'name': p.display_name, 'phone': p.phone or '', 'is_active': p.is_active, 'account': account_info})
            hospital_person_teams[h.id] = teams
    finally:
        flask_g.hospital_id = _saved_hid
    return render_template('data/hospitals.html',
                           hospitals=hospitals,
                           person_counts=person_counts,
                           hospital_person_teams=hospital_person_teams)


@data_bp.route('/hospitals/add', methods=['POST'])
@permission_required('system:config')
def add_hospital():
    ok, msg = data_service.add_hospital(
        request.form.get('name', '').strip(),
        request.form.get('code', '').strip(),
        request.form.get('address', '').strip(),
        request.form.get('phone', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_hospitals'))


@data_bp.route('/hospitals/<int:hid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_hospital(hid):
    ok, msg = data_service.edit_hospital(hid,
        request.form.get('name', '').strip(),
        request.form.get('code', '').strip(),
        request.form.get('address', '').strip(),
        request.form.get('phone', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_hospitals'))


import os, uuid
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

@data_bp.route('/hospitals/<int:hid>/upload_logo', methods=['POST'])
@permission_required('system:config')
def upload_hospital_logo(hid):
    """上传医院头像"""
    hospital = Hospital.query.get(hid)
    if not hospital:
        return jsonify({'error': '医院不存在'}), 404
    if 'logo' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['logo']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': '仅支持 png/jpg/gif/webp/svg 格式'}), 400
    filename = f'hospital_{hid}_{uuid.uuid4().hex[:8]}.{ext}'
    upload_dir = '/var/www/static/uploads/hospitals'
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    if hospital.logo:
        old_path = os.path.join(upload_dir, hospital.logo)
        if os.path.exists(old_path):
            os.remove(old_path)
    hospital.logo = filename
    db.session.commit()
    return jsonify({'ok': True, 'filename': filename, 'url': f'/static/uploads/hospitals/{filename}'})


@data_bp.route('/hospitals/<int:hid>/toggle', methods=['POST'])
@permission_required('system:config')
def toggle_hospital(hid):
    ok, msg = data_service.toggle_hospital(hid)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_hospitals'))


@data_bp.route('/switch_hospital/<int:hid>')
@login_required
def switch_hospital(hid):
    """切换当前查看的医院"""
    from services.cache import clear_cache
    clear_cache()
    if hid == 0:
        if has_permission(current_user, 'system:config'):
            session['admin_hospital_id'] = 0
        else:
            session['user_hospital_id'] = 0
        flash('已切换到: 全部医院', 'success')
        return redirect(request.referrer or url_for('main.dashboard'))
    h = Hospital.query.get(hid)
    if not h:
        flash('医院不存在', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))
    if has_permission(current_user, 'system:config'):
        session['admin_hospital_id'] = hid
    else:
        allowed_ids = current_user.get_assigned_hospital_ids()
        if hid not in allowed_ids:
            flash('您无权访问该医院', 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))
        session['user_hospital_id'] = hid
    flash(f'已切换到: {h.name}', 'success')
    return redirect(request.referrer or url_for('main.dashboard'))


# ==================== 数据管理首页 ====================

@data_bp.route('/')
@permission_required('system:config')
def index():
    """数据管理总览"""
    from services.address import get_all_buildings
    return render_template('data/index.html',
        persons_count=User.query.count(),
        departments_count=Department.query.count(),
        solutions_count=SolutionTemplate.query.count(),
        orders_count=WorkOrder.query.count(),
        buildings_count=len(get_all_buildings()),
        type_count=FaultType.query.count(),
        settings_count=SystemSetting.query.count(),
        assets_count=Asset.query.count(),
        spare_parts_count=SparePart.query.filter(SparePart.hospital_id == getattr(g, 'hospital_id', None)).count() if getattr(g, 'hospital_id', None) and getattr(g, 'hospital_id', None) != 0 else SparePart.query.count(),
        storage_count=StorageLocation.query.count(),
        suppliers_count=Supplier.query.count(),
        consumables_count=Consumable.query.count(),
        duty_count=DutySchedule.query.count(),
        knowledge_count=KnowledgeBase.query.count(),
        users_count=User.query.count(),
        pending_reg_count=RegistrationRequest.query.filter_by(status='pending').count())


# ==================== 人员管理 ====================

@data_bp.route('/persons')
@permission_required('user:view')
def list_persons():
    persons, user_map = data_service.list_persons()
    # 按组分类
    from models import SystemSetting, WorkOrder
    import re

    # 获取每个人员的工单数
    order_counts = {}
    for p in persons:
        name = p.display_name or p.username
        if name:
            cnt = WorkOrder.query.filter(WorkOrder.created_by == name).count()
            if cnt:
                order_counts[p.id] = cnt
    from flask import g as flask_g
    cur_hid = getattr(flask_g, 'hospital_id', None)
    team_options = get_team_options(hospital_id=cur_hid if cur_hid and cur_hid != 0 else None)
    from models import Hospital, RoleGroup
    hospitals = Hospital.query.order_by(Hospital.id).all()
    hospital_map = {h.id: h for h in hospitals}
    role_groups = RoleGroup.query.order_by(RoleGroup.id).all()

    # ===== 组别筛选：默认同仪表盘 =====
    team_sel = request.args.get('team', '')
    if not team_sel:
        if has_permission(current_user, 'system:config'):
            _def_setting = SystemSetting.query.filter_by(key='default_dashboard_team').first()
            team_sel = _def_setting.value if _def_setting and _def_setting.value else ''
        else:
            if current_user.team:
                team_sel = current_user.team
    if team_sel:
        persons = [p for p in persons if p.team == team_sel]

    # ===== 按医院→组分二层分组 =====
    from collections import OrderedDict
    hospital_groups = OrderedDict()
    for p in persons:
        # 取医院名
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


@data_bp.route('/persons/add', methods=['POST'])
@permission_required('user:create')
def add_person():
    ok, msg = data_service.add_person(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/import-from-orders', methods=['POST'])
@permission_required('user:create')
def import_persons_from_orders():
    imported = data_service.import_persons_from_orders()
    flash(f'从工单中导入 {imported} 名新人员', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/toggle', methods=['POST'])
@permission_required('user:edit')
def toggle_person(pid):
    p = data_service.toggle_person(pid)
    flash(f'已{"停用" if not p.is_active else "启用"}「{p.display_name}」', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/delete', methods=['POST'])
@permission_required('user:delete')
def delete_person(pid):
    p = User.query.get_or_404(pid)
    if p.is_admin:
        flash('管理员账号不可删除', 'danger')
        return redirect(url_for('data.list_persons'))
    name, err = data_service.delete_person(pid, current_user.display_name or current_user.username)
    if err:
        flash(err, 'danger')
    else:
        flash(f'已删除人员「{name}」', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/reassign-orders', methods=['POST'])
@permission_required('user:edit')
def reassign_person_orders(pid):
    """将某人的工单批量转移给另一个人"""
    p = User.query.get_or_404(pid)
    source_name = p.display_name or p.username
    target_name = request.form.get('target_name', '').strip()
    if not target_name:
        flash('请填写接收人姓名', 'warning')
        return redirect(url_for('data.list_persons'))

    count = WorkOrder.query.filter(WorkOrder.created_by == source_name).update(
        {WorkOrder.created_by: target_name}, synchronize_session=False
    )
    db.session.commit()
    log_audit('reassign_orders', f'{source_name}→{target_name}', current_user.display_name or current_user.username,
              target_id=pid, target_desc=f'批量转移工单 {count} 条')
    flash(f'已将 {source_name} 的 {count} 条工单转移给 {target_name}', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/edit-field', methods=['POST'])
@permission_required('user:edit')
def edit_person_field(pid):
    field = request.form.get('field', '')
    value = request.form.get('value', '').strip()
    ok, err = data_service.edit_person_field(pid, field, value)
    if ok:
        flash('已更新', 'success')
    else:
        flash(err or '未知字段', 'danger')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/batch-action', methods=['POST'])
@permission_required('user:edit')
def batch_person_action():
    """批量操作人员：启用/禁用/改组分/删除"""
    action = request.form.get('batch_action', '')
    ids_str = request.form.get('batch_ids', '')
    value = request.form.get('batch_value', '').strip()
    ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
    if not ids:
        flash('未选择有效的人员', 'warning')
        return redirect(url_for('data.list_persons'))

    from models import db, User
    count = 0
    try:
        if action == 'enable':
            count = User.query.filter(User.id.in_(ids)).update(
                {User.is_active: True}, synchronize_session=False)
            db.session.commit()
            flash(f'已启用 {count} 名人员', 'success')
        elif action == 'disable':
            count = User.query.filter(User.id.in_(ids)).update(
                {User.is_active: False}, synchronize_session=False)
            db.session.commit()
            flash(f'已禁用 {count} 名人员', 'success')
        elif action == 'change_team':
            if not value:
                flash('请选择目标组', 'warning')
                return redirect(url_for('data.list_persons'))
            count = User.query.filter(User.id.in_(ids)).update(
                {User.team: value}, synchronize_session=False)
            db.session.commit()
            flash(f'已将 {count} 名人员移动到「{value}」', 'success')
        elif action == 'delete':
            protected = []
            deleted_names = []
            for pid in ids:
                p = User.query.get(pid)
                if p:
                    name = p.display_name or p.username
                    # 检查关联记录
                    wo_count = WorkOrder.query.filter(
                        WorkOrder.created_by == name
                    ).count()
                    if wo_count:
                        protected.append(name)
                        continue
                    deleted_names.append(name)
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
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/account', methods=['GET', 'POST'])
@permission_required('user:create')
def person_account(pid):
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
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/lottery-json')
@permission_required('user:view')
def lottery_persons_json():
    """返回当前医院活跃人员列表（大转盘抽奖用），支持 ?team= 筛选"""
    from flask import session, jsonify
    from models import db, User
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


# ==================== 科室字典管理 ====================

@data_bp.route('/departments')
@permission_required('system:config')
def list_departments():
    return render_template('data/departments.html', departments=data_service.list_departments())


@data_bp.route('/departments/add', methods=['POST'])
@permission_required('system:config')
def add_department():
    ok, msg = data_service.add_department(
        request.form.get('name', '').strip(),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('phone', '').strip(),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_departments'))


@data_bp.route('/departments/edit/<int:id>', methods=['POST'])
@permission_required('system:config')
def edit_department(id):
    ok, msg = data_service.edit_department(
        id,
        request.form.get('name', '').strip(),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('phone', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_departments'))


@data_bp.route('/departments/delete/<int:id>', methods=['POST'])
@permission_required('system:config')
def delete_department(id):
    ok, msg = data_service.delete_department(id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_departments'))


# ==================== 方案模板管理 ====================

@data_bp.route('/solutions')
@permission_required('system:config')
def list_solutions():
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    device_filter = request.args.get('device_filter', '')
    fault_filter = request.args.get('fault_filter', '')
    team_filter = request.args.get('team_filter', '')
    pagination = data_service.list_solutions(keyword, device_filter, fault_filter, page, team_filter=team_filter)
    all_teams = data_service.get_team_options()
    return render_template('data/solutions.html', pagination=pagination,
                           keyword=keyword, device_filter=device_filter,
                           fault_filter=fault_filter, team_filter=team_filter,
                           all_teams=all_teams)


@data_bp.route('/solutions/add', methods=['POST'])
@permission_required('system:config')
def add_solution():
    teams_list = request.form.getlist('teams')
    teams = ','.join([t for t in teams_list if t]) if teams_list else ''
    ok, msg = data_service.add_solution(
        request.form.get('title', '').strip(),
        request.form.get('content', '').strip(),
        request.form.get('keywords', ''),
        request.form.get('device_type', ''),
        request.form.get('fault_type', ''),
        request.form.get('fault_subcategory', ''),
        teams)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/reset', methods=['POST'])
@permission_required('system:config')
def reset_solutions():
    count = data_service.reset_solutions()
    flash(f'已重置 {count} 条方案模板到默认值', 'success')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/solutions/import-from-orders', methods=['POST'])
@permission_required('system:config')
def import_solutions_from_orders():
    imported = data_service.import_solutions_from_orders()
    flash(f'从工单中导入 {imported} 条新方案模板', 'success')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/<int:sid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_solution(sid):
    field = request.form.get('field', '')
    if field == 'teams':
        value = ','.join([v for v in request.form.getlist('value') if v])
    else:
        value = request.form.get('value', '')
    data_service.edit_solution(
        sid, field, value,
        request.form.get('value2'))
    if request.args.get('ajax'):
        return jsonify({'ok': True})
    flash('方案已更新', 'success')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/<int:sid>/edit-full', methods=['POST'])
@permission_required('system:config')
def edit_solution_full(sid):
    """编辑方案模板全部字段"""
    from models import SolutionTemplate
    s = SolutionTemplate.query.get(sid)
    if not s:
        flash('方案不存在', 'danger')
        return redirect(url_for('data.list_templates'))
    s.title = request.form.get('title', s.title)
    s.content = request.form.get('content', s.content)
    s.fault_type = request.form.get('fault_type', s.fault_type)
    s.keywords = request.form.get('keywords', s.keywords)
    s.device_type = request.form.get('device_type', s.device_type)
    teams = request.form.get('teams', '')
    if teams:
        s.teams = teams
    db.session.commit()
    flash(f'方案「{s.title}」已更新', 'success')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/solutions/<int:sid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_solution(sid):
    title = data_service.delete_solution(sid, current_user.display_name or current_user.username)
    if request.args.get('ajax'):
        return jsonify({'ok': True, 'title': title})
    flash(f'方案「{title}」已删除', 'success')
    return redirect(url_for('data.list_solutions'))


# ==================== 地址数据查看 ====================

@data_bp.route('/addresses')
@permission_required('system:config')
def list_addresses():
    building = request.args.get('building', '')
    keyword = request.args.get('keyword', '')
    team = resolve_team(request, current_user)
    groups, buildings, current_addresses, total = data_service.list_addresses(building, keyword, team=team)
    all_teams = get_team_options()
    return render_template('data/addresses.html',
                           groups=groups, buildings=buildings,
                           building=building, keyword=keyword,
                           addresses=current_addresses, total=total,
                           team=team, all_teams=all_teams)


@data_bp.route('/addresses/edit', methods=['POST'])
@permission_required('system:config')
def edit_address():
    ok, msg = data_service.edit_address(
        request.form.get('override_id', type=int),
        request.form.get('base_index', type=int),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


@data_bp.route('/addresses/add', methods=['POST'])
@permission_required('system:config')
def add_address():
    ok, msg = data_service.add_address(
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


@data_bp.route('/addresses/<int:oid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_address(oid):
    building = data_service.delete_address(oid)
    flash('地址已删除', 'success')
    return redirect(url_for('data.list_addresses', building=building))


@data_bp.route('/addresses/delete-base', methods=['POST'])
@permission_required('system:config')
def delete_base_address():
    ok, msg = data_service.delete_base_address(
        request.form.get('base_index', type=int),
        request.form.get('building', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


# ==================== 故障类型管理 ====================

@data_bp.route('/fault-types')
@permission_required('system:config')
def list_fault_types():
    team = resolve_team(request, current_user)
    all_teams = get_team_options()
    return render_template('data/fault_types.html', types=data_service.list_fault_types(team=team),
                           team=team, all_teams=all_teams)


@data_bp.route('/fault-types/add', methods=['POST'])
@permission_required('system:config')
def add_fault_type():
    ok, msg = data_service.add_fault_type(
        request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_types'))


@data_bp.route('/fault-types/<int:fid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_fault_type(fid):
    ok, msg = data_service.edit_fault_type(
        fid, request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_types'))


@data_bp.route('/fault-types/<int:fid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_fault_type(fid):
    name = data_service.delete_fault_type(fid, current_user.display_name or current_user.username)
    flash(f'故障类型「{name}」已删除', 'success')
    return redirect(url_for('data.list_fault_types'))


# ==================== 存放位置字典 ====================

@data_bp.route('/storage-locations')
@permission_required('system:config')
def list_storage_locations():
    return render_template('data/storage_locations.html', locations=data_service.list_storage_locations())


@data_bp.route('/storage-locations/add', methods=['POST'])
@permission_required('system:config')
def add_storage_location():
    ok, msg = data_service.add_storage_location(
        request.form.get('name', '').strip(),
        request.form.get('building', ''),
        request.form.get('floor', ''),
        request.form.get('area', ''),
        request.form.get('contact', ''),
        request.form.get('phone', ''),
        request.form.get('is_default') == 'on')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_storage_locations'))


@data_bp.route('/storage-locations/<int:lid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_storage_location(lid):
    ok, msg = data_service.edit_storage_location(
        lid, request.form.get('name', '').strip(),
        request.form.get('building', ''),
        request.form.get('floor', ''),
        request.form.get('area', ''),
        request.form.get('contact', ''),
        request.form.get('phone', ''),
        request.form.get('is_default') == 'on')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_storage_locations'))


@data_bp.route('/storage-locations/<int:lid>/toggle', methods=['POST'])
@permission_required('system:config')
def toggle_storage_location(lid):
    data_service.toggle_storage_location(lid)
    return redirect(url_for('data.list_storage_locations'))


@data_bp.route('/storage-locations/<int:lid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_storage_location(lid):
    name = data_service.delete_storage_location(lid)
    flash(f'已删除存放位置「{name}」', 'success')
    return redirect(url_for('data.list_storage_locations'))


# ==================== 供应商管理 ====================

@data_bp.route('/suppliers')
@permission_required('system:config')
def list_suppliers():
    return render_template('data/suppliers.html', suppliers=data_service.list_suppliers())


@data_bp.route('/suppliers/add', methods=['POST'])
@permission_required('system:config')
def add_supplier():
    ok, msg = data_service.add_supplier(
        request.form.get('name', '').strip(),
        request.form.get('contact_person', ''),
        request.form.get('phone', ''),
        request.form.get('address', ''),
        request.form.get('service_scope', ''),
        request.form.get('notes', ''),
        request.form.get('contract_end', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_suppliers'))


@data_bp.route('/suppliers/<int:sid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_supplier(sid):
    ok, msg = data_service.edit_supplier(
        sid, request.form.get('name', '').strip(),
        request.form.get('contact_person', ''),
        request.form.get('phone', ''),
        request.form.get('address', ''),
        request.form.get('service_scope', ''),
        request.form.get('notes', ''),
        request.form.get('contract_end', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_suppliers'))


@data_bp.route('/suppliers/<int:sid>/toggle', methods=['POST'])
@permission_required('system:config')
def toggle_supplier(sid):
    data_service.toggle_supplier(sid)
    return redirect(url_for('data.list_suppliers'))


@data_bp.route('/suppliers/<int:sid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_supplier(sid):
    name = data_service.delete_supplier(sid)
    flash(f'已删除供应商「{name}」', 'success')
    return redirect(url_for('data.list_suppliers'))


# ==================== 耗材管理 ====================

@data_bp.route('/consumables')
@permission_required('system:config')
def list_consumables():
    q = request.args.get('q', '').strip()
    return render_template('data/consumables.html', consumables=data_service.list_consumables(q), q=q)


@data_bp.route('/consumables/add', methods=['POST'])
@permission_required('system:config')
def add_consumable():
    ok, msg = data_service.add_consumable(
        request.form.get('name', '').strip(),
        request.form.get('spec', ''),
        request.form.get('unit', '个'),
        int(request.form.get('quantity', 0)),
        int(request.form.get('min_quantity', 5)),
        request.form.get('location', ''),
        request.form.get('supplier_name', ''),
        request.form.get('compatible_printers', ''),
        request.form.get('notes', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_consumables'))


@data_bp.route('/consumables/<int:cid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_consumable(cid):
    ok, msg = data_service.edit_consumable(
        cid, request.form.get('name', '').strip(),
        request.form.get('spec', ''),
        request.form.get('unit', '个'),
        int(request.form.get('quantity', 0)),
        int(request.form.get('min_quantity', 5)),
        request.form.get('location', ''),
        request.form.get('supplier_name', ''),
        request.form.get('compatible_printers', ''),
        request.form.get('notes', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_consumables'))


@data_bp.route('/consumables/<int:cid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_consumable(cid):
    name = data_service.delete_consumable(cid)
    flash(f'已删除耗材「{name}」', 'success')
    return redirect(url_for('data.list_consumables'))


@data_bp.route('/consumables/import-excel', methods=['POST'])
@permission_required('system:config')
def import_consumables_excel():
    file = request.files.get('file')
    if not file:
        flash('请选择文件', 'danger')
        return redirect(url_for('data.list_consumables'))
    try:
        ok, imported, skipped, errors = data_service.import_consumables_from_excel(file)
        if ok:
            msg = f'导入完成: 成功 {imported} 条'
            if skipped:
                msg += f', 跳过 {skipped} 条'
            if errors:
                msg += '<br>' + '<br>'.join(errors[:10])
            flash(msg, 'success' if not errors else 'warning')
        else:
            flash(f'导入失败', 'danger')
    except Exception as e:
        flash(f'导入失败: {str(e)}', 'danger')
    return redirect(url_for('data.list_consumables'))


@data_bp.route('/consumables/inout', methods=['POST'])
@permission_required('system:config')
def consumable_inout():
    cid = request.form.get('cid', type=int)
    action = request.form.get('action')
    qty = request.form.get('quantity', type=int, default=0)
    note = request.form.get('note', '')
    ok, msg, balance = data_service.consumable_inout(
        cid, action, qty, note, current_user.display_name)
    if ok:
        return jsonify({'ok': True, 'balance': balance})
    return jsonify({'ok': False, 'msg': msg}), 400


@data_bp.route('/consumables/export-template')
@permission_required('system:config')
def export_consumables_template():
    try:
        output = data_service.export_consumables_template()
        return send_file(output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name='耗材导入模板.xlsx')
    except Exception as e:
        flash(f'导出失败: {str(e)}', 'danger')
        return redirect(url_for('data.list_consumables'))


# ==================== 值班排班 ====================

@data_bp.route('/duty-schedules')
@permission_required('system:config')
def list_duty_schedules():
    from datetime import datetime, date
    from models import SystemSetting
    import re
    now = date.today()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)
    staff = data_service.get_duty_schedule_staff()
    # 医院映射：仅取活跃医院
    from models import Hospital
    active_hospitals = Hospital.query.filter_by(is_active=True).all()
    active_hids = {h.id for h in active_hospitals}
    hospital_map = {h.id: h.name for h in active_hospitals}
    # 过滤：停用医院的人员不显示；排除非值班人员（系统管理员、测试账号等）
    _excluded_usernames = {'admin', 'testminiapp'}
    _excluded_ids = {u.id for u in User.query.filter(User.username.in_(_excluded_usernames)).all()}
    staff = [s for s in staff if s.id not in _excluded_ids
             and (s.hospital_id is None or s.hospital_id in active_hids
             or any(h.id in active_hids for h in s.hospitals))]
    # 按当前院区筛选（管理员选了特定医院则只看该医院）
    from flask import g as flask_g
    cur_hid = getattr(flask_g, 'hospital_id', None)
    if cur_hid and cur_hid in hospital_map:
        staff = [s for s in staff if s.hospital_id == cur_hid
                 or any(h.id == cur_hid for h in s.hospitals)]
    total_days, first_weekday, holidays = data_service.get_duty_month_info(year, month)
    team_list = get_team_options(hospital_id=cur_hid if cur_hid and cur_hid != 0 else None)

    # ===== 组别默认值：resolve_team 统一处理 =====
    team_sel = resolve_team(request, current_user)

    # 按组别筛选值班人员
    if team_sel:
        staff = [s for s in staff if s.team == team_sel]

    # 按医院分组
    from collections import OrderedDict
    staff_groups = OrderedDict()
    staff_groups['__unassigned__'] = []  # 未分配医院的放最后
    for s in staff:
        # 取该人员的主医院名
        hname = None
        if s.hospital_id and s.hospital_id in hospital_map:
            hname = hospital_map[s.hospital_id]
        if not hname:
            h = s.hospitals.first()
            if h:
                hname = h.name
        key = hname or '__unassigned__'
        if key not in staff_groups:
            staff_groups[key] = []
        staff_groups[key].append(s)
    # 把"未分配"移到末尾
    if staff_groups.get('__unassigned__'):
        unassigned = staff_groups.pop('__unassigned__')
        staff_groups['__unassigned__'] = unassigned
    return render_template('data/duty_schedules.html', staff=staff, staff_groups=staff_groups, year=year, month=month,
                           total_days=total_days, first_weekday=first_weekday,
                           now=datetime.combine(date.today(), datetime.min.time()),
                           holidays=holidays, team_list=team_list, team_sel=team_sel,
                           hospital_map=hospital_map)


@data_bp.route('/duty-schedules/api')
@permission_required('system:config')
def duty_schedules_api():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not year or not month:
        return jsonify({'error': '参数错误'}), 400
    data = data_service.get_duty_schedules_api(year, month)
    return jsonify({'records': data})


@data_bp.route('/duty-schedules/api/update', methods=['POST'])
@permission_required('system:config')
def duty_schedule_update():
    ok, msg, shift = data_service.duty_schedule_update(
        request.form.get('year', type=int),
        request.form.get('month', type=int),
        request.form.get('person', '').strip(),
        request.form.get('day', type=int),
        request.form.get('shift', '').strip())
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    return jsonify({'ok': True, 'shift': shift})


@data_bp.route('/duty-schedules/api/batch', methods=['POST'])
@permission_required('system:config')
def duty_schedule_batch():
    ok, msg = data_service.duty_schedule_batch(
        request.form.get('action', ''),
        request.form.get('year', type=int),
        request.form.get('month', type=int),
        person=request.form.get('person', '').strip(),
        shift=request.form.get('shift', '').strip())
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    return jsonify({'ok': True, 'msg': msg})


@data_bp.route('/duty-schedules/api/import', methods=['POST'])
@permission_required('system:config')
def duty_schedule_import():
    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'msg': '请上传文件'}), 400
    ok, msg = data_service.duty_schedule_import_excel(
        file,
        request.form.get('year', type=int),
        request.form.get('month', type=int))
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    return jsonify({'ok': True, 'msg': msg})


@data_bp.route('/duty-schedules/staff', methods=['GET', 'POST'])
@permission_required('system:config')
def duty_staff_manage():
    if request.method == 'POST':
        ok, msg = data_service.add_duty_staff(request.form.get('name', '').strip())
        flash(msg, 'success' if ok else 'danger')
        return redirect(url_for('data.duty_staff_manage'))
    staff = data_service.list_duty_staff()
    return render_template('data/duty_staff.html', staff=staff)


@data_bp.route('/duty-schedules/staff/<int:sid>/toggle', methods=['POST'])
@permission_required('system:config')
def duty_staff_toggle(sid):
    active = data_service.toggle_duty_staff(sid)
    return jsonify({'ok': True, 'active': active})


@data_bp.route('/duty-schedules/staff/<int:sid>/delete', methods=['POST'])
@permission_required('system:config')
def duty_staff_delete(sid):
    data_service.delete_duty_staff(sid)
    return jsonify({'ok': True})


# ==================== 知识库/公告 ====================

@data_bp.route('/knowledge')
@login_required
def list_knowledge():
    category = request.args.get('category', '')
    articles, categories = data_service.list_knowledge(category)
    # 获取热门故障（供AI问答tab使用）
    from models import SolutionTemplate
    hot_questions = SolutionTemplate.query.order_by(SolutionTemplate.id.desc()).limit(8).all()
    hot_titles = [q.title for q in hot_questions]
    return render_template('data/knowledge.html', articles=articles, categories=categories, cur_cat=category,
                           hot_questions=hot_titles)


@data_bp.route('/knowledge/add', methods=['POST'])
@permission_required('system:config')
def add_knowledge():
    ok, msg = data_service.add_knowledge(
        request.form.get('title', '').strip(),
        request.form.get('category', '公告'),
        request.form.get('content', ''),
        request.form.get('is_pinned') == 'on')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_knowledge'))


@data_bp.route('/knowledge/<int:kid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_knowledge(kid):
    ok, msg = data_service.edit_knowledge(
        kid, request.form.get('title', '').strip(),
        request.form.get('category', ''),
        request.form.get('content', ''),
        request.form.get('is_pinned') == 'on')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_knowledge'))


@data_bp.route('/knowledge/api/<int:kid>')
@login_required
def knowledge_api(kid):
    return jsonify(data_service.get_knowledge_api(kid))


@data_bp.route('/knowledge/<int:kid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_knowledge(kid):
    title = data_service.delete_knowledge(kid)
    flash(f'已删除文章「{title}」', 'success')
    return redirect(url_for('data.list_knowledge'))


# ==================== 权限管理 ====================

@data_bp.route('/permissions')
@permission_required('system:permission')
def permissions():
    """权限管理页面"""
    from models import RoleGroup, ALL_MODULE_NAMES
    users = User.query.order_by(User.id).all()
    persons = users
    role_groups = RoleGroup.query.order_by(RoleGroup.id).all()
    module_perms = get_module_permissions()
    all_module_names = ALL_MODULE_NAMES

    user_group_map = {}
    for u in users:
        if u.is_admin:
            user_group_map[u.id] = '管理员'
        elif u.group_id:
            rg = RoleGroup.query.get(u.group_id)
            user_group_map[u.id] = rg.name if rg else (u.group or '普通用户')
        else:
            user_group_map[u.id] = u.group or '普通用户'

    users_by_group = {}
    for gname in module_perms.get('groups', {}).keys():
        users_by_group[gname] = {'users': [], 'role_groups': []}
    for g in role_groups:
        key = g.name
        if key not in users_by_group:
            users_by_group[key] = {'users': [], 'role_groups': []}
        users_by_group[key]['role_groups'].append(g)
        for u in users:
            if u.group_id == g.id or (u.group == g.name and u.group_id is None):
                if u not in users_by_group[key]['users']:
                    users_by_group[key]['users'].append(u)
    if '管理员' not in users_by_group:
        users_by_group['管理员'] = {'users': [], 'role_groups': []}
    for u in users:
        if u.is_admin:
            if u not in users_by_group['管理员']['users']:
                users_by_group['管理员']['users'].append(u)
    assigned = set()
    for gdata in users_by_group.values():
        for u in gdata['users']:
            assigned.add(u.id)
    for u in users:
        if u.id not in assigned:
            key = u.group or '未分组'
            if key not in users_by_group:
                users_by_group[key] = {'users': [], 'role_groups': []}
            users_by_group[key]['users'].append(u)
            if u.id not in user_group_map:
                user_group_map[u.id] = key

    return render_template('data/permissions.html', users=users, module_perms=module_perms,
                           all_module_names=all_module_names, persons=persons,
                           users_by_group=users_by_group, role_groups=role_groups,
                           user_group_map=user_group_map)


@data_bp.route('/permissions/sync-users', methods=['POST'])
@permission_required('user:create')
def sync_users_from_persons():
    created, msg = data_service.sync_users_from_persons(
        current_user.display_name or current_user.username)
    flash(msg, 'success' if created else 'info')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/save', methods=['POST'])
@permission_required('system:permission')
def save_permissions():
    data = request.get_json(force=True)
    if not data or 'groups' not in data:
        return {'ok': False, 'msg': '无效数据'}, 400
    ok, msg = data_service.save_permissions(data)
    return {'ok': ok, 'msg': msg}


@data_bp.route('/permissions/toggle-admin/<int:uid>', methods=['POST'])
@permission_required('user:role_assign')
def toggle_admin(uid):
    ok, msg, _ = data_service.toggle_admin(
        uid, current_user.id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/set-group', methods=['POST'])
@permission_required('user:role_assign')
def set_user_group():
    uid = request.form.get('uid', type=int)
    group_id = request.form.get('group_id', type=int)
    from models import RoleGroup
    if group_id:
        rg = RoleGroup.query.get(group_id)
        group_name = rg.name if rg else ''
    else:
        group_name = ''
    ok, msg = data_service.set_user_group(
        uid, group_name,
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/add-group', methods=['POST'])
@permission_required('system:permission')
def add_permission_group():
    ok, msg = data_service.add_permission_group(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/delete-group', methods=['POST'])
@permission_required('system:permission')
def delete_permission_group():
    ok, msg = data_service.delete_permission_group(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/add-module', methods=['POST'])
@permission_required('system:permission')
def add_permission_module():
    ok, msg = data_service.add_permission_module(
        request.form.get('module', '').strip(),
        request.form.get('category', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/delete-module', methods=['POST'])
@permission_required('system:permission')
def delete_permission_module():
    ok, msg = data_service.delete_permission_module(request.form.get('module', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/rename-group', methods=['POST'])
@permission_required('system:permission')
def rename_permission_group():
    """重命名角色组（预留）"""
    flash('功能开发中', 'info')
    return redirect(url_for('data.permissions'))


# ==================== 故障二级分类管理 ====================

@data_bp.route('/fault-categories')
@permission_required('system:config')
def list_fault_categories():
    team = resolve_team(request, current_user)
    cats = data_service.list_fault_categories(team=team)
    all_teams = get_team_options()
    return render_template('data/fault_categories.html', categories=cats,
                           team=team, all_teams=all_teams)


@data_bp.route('/fault-categories/subcategory/add', methods=['POST'])
@permission_required('system:config')
def add_fault_subcategory():
    ok, msg = data_service.add_fault_subcategory(
        request.form.get('category_id', type=int),
        request.form.get('name', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/subcategory/delete/<int:sub_id>', methods=['POST'])
@permission_required('system:config')
def delete_fault_subcategory(sub_id):
    data_service.delete_fault_subcategory(sub_id)
    flash('已删除子分类', 'success')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/keyword/add', methods=['POST'])
@permission_required('system:config')
def add_fault_keyword():
    ok, msg = data_service.add_fault_keywords(
        request.form.get('subcategory_id', type=int),
        request.form.get('keywords', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/keyword/delete/<int:kw_id>', methods=['POST'])
@permission_required('system:config')
def delete_fault_keyword(kw_id):
    data_service.delete_fault_keyword(kw_id)
    flash('已删除关键词', 'success')
    return redirect(url_for('data.list_fault_categories'))


# ==================== 零件价格管理 ====================

@data_bp.route('/parts')
@permission_required('system:config')
def list_parts():
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    supplier = request.args.get('supplier', '').strip()
    parts, categories, suppliers = data_service.list_parts(q, cat, supplier)
    return render_template('data/parts.html', parts=parts, q=q, cat=cat,
                           supplier=supplier, categories=categories, suppliers=suppliers)


@data_bp.route('/parts/add', methods=['POST'])
@permission_required('system:config')
def add_part():
    ok, msg = data_service.add_part(
        request.form.get('product_name', '').strip(),
        request.form.get('unit', '个'),
        request.form.get('unit_price', 0, type=float),
        request.form.get('category', '电脑配件'),
        request.form.get('spec', ''),
        request.form.get('brand', ''),
        request.form.get('model_no', ''),
        request.form.get('supplier', ''),
        request.form.get('remark', ''),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_parts'))


@data_bp.route('/parts/<int:part_id>/delete', methods=['POST'])
@permission_required('system:config')
def delete_part(part_id):
    name = data_service.delete_part(part_id, current_user.display_name or current_user.username)
    flash(f'已删除零件「{name}」', 'success')
    return redirect(url_for('data.list_parts'))


# ==================== 耗材出入库记录 ====================

@data_bp.route('/consumables/records')
@permission_required('system:config')
def consumable_records_view():
    q = request.args.get('q', '').strip()
    action = request.args.get('action', '').strip()
    page = request.args.get('page', 1, type=int)
    records, pagination, total = data_service.list_consumable_records(q, action, page)
    return render_template('data/consumable_records.html', records=records,
                           pagination=pagination, total=total, q=q, action=action)


@data_bp.route('/consumables/records/<int:rid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_consumable_record(rid):
    data_service.delete_consumable_record(rid)
    flash('记录已删除', 'success')
    return redirect(url_for('data.consumable_records_view'))


# ==================== 统一模板管理 ====================

@data_bp.route('/templates')
@permission_required('system:config')
def list_templates():
    """统一模板管理页面（按组查看故障模板组+方案模板）"""
    from models import FaultTemplateGroup, SolutionTemplate, FaultTemplateItem
    all_teams = data_service.get_team_options()
    current_team = request.args.get('team', '')

    fault_groups = FaultTemplateGroup.query.order_by(FaultTemplateGroup.id).all()
    for g in fault_groups:
        g.items = FaultTemplateItem.query.filter_by(
            group_id=g.id
        ).order_by(FaultTemplateItem.sort_order).all()

    fault_group_map = {'': []}
    for g in fault_groups:
        if g.teams:
            for t in g.teams.split(','):
                t = t.strip()
                if t not in fault_group_map:
                    fault_group_map[t] = []
                fault_group_map[t].append(g)
        else:
            fault_group_map[''].append(g)

    solutions = SolutionTemplate.query.order_by(SolutionTemplate.title).all()
    solution_map = {'': []}
    for s in solutions:
        if s.teams:
            for t in s.teams.split(','):
                t = t.strip()
                if t not in solution_map:
                    solution_map[t] = []
                solution_map[t].append(s)
        else:
            solution_map[''].append(s)

    # 分离通用/专属
    general_fault_groups = FaultTemplateGroup.query.filter(
        (FaultTemplateGroup.teams == '') | (FaultTemplateGroup.teams.is_(None))
    ).order_by(FaultTemplateGroup.id).all()
    for g in general_fault_groups:
        g.items = FaultTemplateItem.query.filter_by(
            group_id=g.id
        ).order_by(FaultTemplateItem.sort_order).all()
    general_solutions = SolutionTemplate.query.filter(
        (SolutionTemplate.teams == '') | (SolutionTemplate.teams.is_(None))
    ).order_by(SolutionTemplate.title).all()

    team_fault_groups = [g for g in fault_groups if g.teams]
    team_solutions = [s for s in solutions if s.teams]

    return render_template('data/templates.html', all_teams=all_teams,
                           fault_groups=fault_groups, fault_group_map=fault_group_map,
                           solutions=solutions, solution_map=solution_map,
                           general_fault_groups=general_fault_groups,
                           general_solutions=general_solutions,
                           team_fault_groups=team_fault_groups,
                           team_solutions=team_solutions,
                           current_team=current_team)


# ==================== 故障模板组管理 ====================

@data_bp.route('/fault-template-groups')
@permission_required('system:config')
def list_fault_template_groups():
    groups, all_teams = data_service.list_fault_template_groups()
    return render_template('data/fault_template_groups.html', groups=groups, all_teams=all_teams)


@data_bp.route('/fault-template-groups/add', methods=['POST'])
@permission_required('system:config')
def add_fault_template_group():
    ok, msg = data_service.add_fault_template_group(
        request.form.get('name', '').strip(),
        request.form.getlist('teams'),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/fault-template-groups/<int:gid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_fault_template_group(gid):
    data_service.edit_fault_template_group(gid,
        request.form.get('field', ''),
        request.form.get('value', ''))
    flash('模板组已更新', 'success')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/fault-template-groups/<int:gid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_fault_template_group(gid):
    name = data_service.delete_fault_template_group(gid,
        current_user.display_name or current_user.username)
    flash(f'已删除模板组「{name}」', 'success')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/fault-template-groups/<int:gid>/items/add', methods=['POST'])
@permission_required('system:config')
def add_fault_template_item(gid):
    ok, msg = data_service.add_fault_template_item(gid,
        request.form.get('fault_type', '硬件'),
        request.form.get('display_name', '').strip(),
        int(request.form.get('default_count', 1)))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/edit', methods=['POST'])
@permission_required('system:config')
def edit_fault_template_item(gid, iid):
    data_service.edit_fault_template_item(gid, iid,
        request.form.get('fault_type', ''),
        request.form.get('display_name', ''),
        int(request.form.get('default_count', 1)))
    flash('故障项已更新', 'success')
    return redirect(url_for('data.list_templates'))


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/delete', methods=['POST'])
@permission_required('system:config')
def delete_fault_template_item(gid, iid):
    data_service.delete_fault_template_item(gid, iid)
    flash('故障项已删除', 'success')
    return redirect(url_for('data.list_templates'))


# ==================== 模板管理 JSON API ====================

@data_bp.route('/fault-template-groups/api/add', methods=['POST'])
@permission_required('system:config')
def add_fault_template_group_api():
    """API：新增故障模板组，返回JSON"""
    ok, msg = data_service.add_fault_template_group(
        request.form.get('name', '').strip(),
        request.form.getlist('teams'),
        current_user.display_name or current_user.username)
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    from models import FaultTemplateGroup
    g = FaultTemplateGroup.query.filter_by(name=request.form.get('name', '').strip()).order_by(FaultTemplateGroup.id.desc()).first()
    return jsonify({'ok': True, 'group': {
        'id': g.id, 'name': g.name, 'teams': g.teams or ''
    }})


@data_bp.route('/fault-template-groups/<int:gid>/api/edit', methods=['POST'])
@permission_required('system:config')
def edit_fault_template_group_api(gid):
    """API：编辑故障模板组，返回JSON"""
    data_service.edit_fault_template_group(gid,
        request.form.get('field', ''),
        request.form.get('value', ''))
    from models import FaultTemplateGroup
    g = FaultTemplateGroup.query.get(gid)
    return jsonify({'ok': True, 'group': {
        'id': g.id, 'name': g.name, 'teams': g.teams or ''
    }})


@data_bp.route('/fault-template-groups/<int:gid>/api/delete', methods=['POST'])
@permission_required('system:config')
def delete_fault_template_group_api(gid):
    """API：删除故障模板组，返回JSON"""
    name = data_service.delete_fault_template_group(gid,
        current_user.display_name or current_user.username)
    return jsonify({'ok': True})


@data_bp.route('/fault-template-groups/<int:gid>/items/api/add', methods=['POST'])
@permission_required('system:config')
def add_fault_template_item_api(gid):
    """API：新增故障模板项，返回JSON"""
    ok, msg = data_service.add_fault_template_item(gid,
        request.form.get('fault_type', '硬件'),
        request.form.get('display_name', '').strip(),
        int(request.form.get('default_count', 1)))
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    from models import FaultTemplateItem
    items = FaultTemplateItem.query.filter_by(group_id=gid).order_by(FaultTemplateItem.id.desc()).all()
    item = items[0] if items else None
    return jsonify({'ok': True, 'item': {
        'id': item.id, 'fault_type': item.fault_type,
        'display_name': item.display_name, 'group_id': item.group_id
    }})


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/api/edit', methods=['POST'])
@permission_required('system:config')
def edit_fault_template_item_api(gid, iid):
    """API：编辑故障模板项，返回JSON"""
    data_service.edit_fault_template_item(gid, iid,
        request.form.get('fault_type', ''),
        request.form.get('display_name', ''),
        int(request.form.get('default_count', 1)))
    from models import FaultTemplateItem
    item = FaultTemplateItem.query.get(iid)
    return jsonify({'ok': True, 'item': {
        'id': item.id, 'fault_type': item.fault_type,
        'display_name': item.display_name, 'group_id': item.group_id
    }})


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/api/delete', methods=['POST'])
@permission_required('system:config')
def delete_fault_template_item_api(gid, iid):
    """API：删除故障模板项，返回JSON"""
    data_service.delete_fault_template_item(gid, iid)
    return jsonify({'ok': True})


@data_bp.route('/solutions/api/add', methods=['POST'])
@permission_required('system:config')
def add_solution_api():
    """API：新增方案模板，返回JSON"""
    teams_list = request.form.getlist('teams')
    teams = ','.join([t for t in teams_list if t]) if teams_list else ''
    ok, msg = data_service.add_solution(
        request.form.get('title', '').strip(),
        request.form.get('content', '').strip(),
        request.form.get('keywords', ''),
        request.form.get('device_type', ''),
        request.form.get('fault_type', ''),
        request.form.get('fault_subcategory', ''),
        teams)
    if not ok:
        return jsonify({'ok': False, 'msg': msg}), 400
    from models import SolutionTemplate
    s = SolutionTemplate.query.filter_by(title=request.form.get('title', '').strip()).order_by(SolutionTemplate.id.desc()).first()
    return jsonify({'ok': True, 'solution': {
        'id': s.id, 'title': s.title, 'content': s.content,
        'fault_type': s.fault_type or '', 'teams': s.teams or ''
    }})


@data_bp.route('/solutions/<int:sid>/api/edit', methods=['POST'])
@permission_required('system:config')
def edit_solution_api(sid):
    """API：编辑方案模板，返回JSON"""
    from models import SolutionTemplate
    s = SolutionTemplate.query.get(sid)
    if not s:
        return jsonify({'ok': False, 'msg': '方案不存在'}), 404
    s.title = request.form.get('title', s.title)
    s.content = request.form.get('content', s.content)
    s.fault_type = request.form.get('fault_type', s.fault_type)
    s.keywords = request.form.get('keywords', s.keywords)
    s.device_type = request.form.get('device_type', s.device_type)
    teams = request.form.get('teams', '')
    if teams:
        s.teams = teams
    db.session.commit()
    return jsonify({'ok': True, 'solution': {
        'id': s.id, 'title': s.title, 'content': s.content,
        'fault_type': s.fault_type or '', 'teams': s.teams or ''
    }})


@data_bp.route('/solutions/<int:sid>/api/delete', methods=['POST'])
@permission_required('system:config')
def delete_solution_api(sid):
    """API：删除方案模板，返回JSON"""
    data_service.delete_solution(sid, current_user.display_name or current_user.username)
    return jsonify({'ok': True})


# ==================== 注册审批 ====================

@data_bp.route('/registration-approvals')
@permission_required('user:create')
def list_registration_approvals():
    """注册审批列表"""
    if not can_access('注册审批'):
        flash('无权限访问', 'danger')
        return redirect(url_for('data.index'))
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    q = RegistrationRequest.query.order_by(RegistrationRequest.created_at.desc())
    if status != 'all':
        q = q.filter_by(status=status)
    pagination = q.paginate(page=page, per_page=20, error_out=False)
    return render_template('data/registration_approvals.html',
                         pagination=pagination, current_status=status)


@data_bp.route('/registration-approvals/<int:rid>/approve', methods=['POST'])
@permission_required('user:create')
def approve_registration(rid):
    """通过注册申请：创建用户"""
    if not can_access('注册审批'):
        flash('无权限访问', 'danger')
        return redirect(url_for('data.index'))
    req = RegistrationRequest.query.get(rid)
    if not req or req.status != 'pending':
        flash('申请不存在或已处理', 'danger')
        return redirect(url_for('data.list_registration_approvals'))
    if User.query.filter_by(username=req.username).first():
        flash('用户名已被占用，无法通过', 'danger')
        req.status = 'rejected'
        req.reject_reason = '用户名已被占用'
        req.reviewed_by = current_user.id
        req.reviewed_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('data.list_registration_approvals'))
    target_hospital_id = req.hospital_id or current_user.hospital_id
    user = User(
        username=req.username,
        display_name=req.display_name,
        hospital_id=target_hospital_id,
    )
    user.password_hash = req.password_hash  # 使用已加密的密码
    # 分配角色组（优先用注册时选的，其次常规运维权限，其次普通用户）
    if req.group_id:
        user.group_id = req.group_id
    else:
        default_group = (RoleGroup.query.filter_by(name='常规运维权限').first()
                         or RoleGroup.query.filter_by(name='普通用户').first())
        if default_group:
            user.group_id = default_group.id
    db.session.add(user)
    db.session.flush()
    # 同步创建User记录（使人员管理能看到此人）
    if not User.query.filter(User.display_name == req.display_name).first():
        user_obj = User(display_name=req.display_name, is_active=True, team='')
        db.session.add(user_obj)
    # 分配医院（同时写入多对多关联表，确保 get_assigned_hospitals 能查到）
    h = Hospital.query.get(target_hospital_id)
    if h:
        user.hospitals.append(h)
    req.status = 'approved'
    req.reviewed_by = current_user.id
    req.reviewed_at = datetime.utcnow()
    db.session.commit()
    log_audit('register_approve', 'registration', req.username,
              target_id=user.id, target_desc=f'审批通过注册: {req.username}')
    flash(f'已通过 {req.display_name} 的注册申请', 'success')
    return redirect(url_for('data.list_registration_approvals'))


@data_bp.route('/registration-approvals/<int:rid>/reject', methods=['POST'])
@permission_required('user:create')
def reject_registration(rid):
    """拒绝注册申请"""
    if not can_access('注册审批'):
        flash('无权限访问', 'danger')
        return redirect(url_for('data.index'))
    req = RegistrationRequest.query.get(rid)
    if not req or req.status != 'pending':
        flash('申请不存在或已处理', 'danger')
        return redirect(url_for('data.list_registration_approvals'))
    reason = request.form.get('reason', '').strip() or '未通过审批'
    req.status = 'rejected'
    req.reject_reason = reason
    req.reviewed_by = current_user.id
    req.reviewed_at = datetime.utcnow()
    db.session.commit()
    log_audit('register_reject', 'registration', req.username,
              target_id=rid, target_desc=f'拒绝注册: {req.username}')
    flash(f'已拒绝 {req.display_name} 的注册申请', 'success')
    return redirect(url_for('data.list_registration_approvals'))


# ==================== 子蓝图重定向（保持向后兼容） ====================

@data_bp.route('/personnel')
def redirect_to_personnel():
    """重定向到新版人员管理"""
    return redirect(url_for('data_personnel.index'), 301)


@data_bp.route('/department')
def redirect_to_department():
    """重定向到新版科室管理"""
    return redirect(url_for('data_department.index'), 301)


@data_bp.route('/fault')
def redirect_to_fault():
    """重定向到新版故障类型管理"""
    return redirect(url_for('data_fault.index'), 301)


@data_bp.route('/address')
def redirect_to_address():
    """重定向到新版地址管理"""
    return redirect(url_for('data_address.index'), 301)
