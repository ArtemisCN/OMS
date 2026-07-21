"""基础数据管理路由（HTTP 编排层）"""
import io
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import login_required, current_user
from models import (db, Person, Department, SolutionTemplate, WorkOrder,
    AddressOverride, User, FaultType, FaultCategory, FaultSubcategory,
    FaultKeyword, Hospital, FaultTemplateGroup, FaultTemplateItem, PartPrice,
    SystemSetting, Asset, SparePart, StorageLocation, Supplier,
    Consumable, ConsumableRecord, ConsumableSignRequest,
    DutySchedule, DutyStaff, KnowledgeBase,
    log_audit, get_module_permissions, save_module_permissions)
import config
from routes.auth import admin_required
from services import data_service
from flask import redirect

data_bp = Blueprint('data', __name__, url_prefix='/data')


# ==================== 医院管理（预留） ====================

@data_bp.route('/hospitals')
@admin_required
def list_hospitals():
    """医院列表（豪华卡片版）"""
    hospitals = Hospital.query.order_by(Hospital.id).all()
    from models import Person, User
    # 暂存并清除医院过滤，获取全院数据
    from flask import g as flask_g
    _saved_hid = getattr(flask_g, 'hospital_id', None)
    flask_g.hospital_id = None
    try:
        # 各医院人员数
        person_counts = {}
        for h in hospitals:
            person_counts[h.id] = Person.query.filter_by(hospital_id=h.id, is_active=True).count()
        # 各医院关联账号数
        user_counts = {}
        for h in hospitals:
            user_counts[h.id] = User.query.join(Person, User.id == Person.user_id).filter(Person.hospital_id == h.id, Person.is_active == True).count()
        # 各医院人员按组别归类
        hospital_person_teams = {}
        for h in hospitals:
            persons = Person.query.filter_by(hospital_id=h.id, is_active=True).order_by(Person.team, Person.name).all()
            teams = {}
            for p in persons:
                t = p.team or '未分组'
                if t not in teams:
                    teams[t] = []
                account_info = None
                if p.user_id:
                    u = User.query.get(p.user_id)
                    account_info = {'username': u.username, 'active': u.is_active} if u else None
                teams[t].append({'name': p.name, 'phone': p.phone or '', 'is_active': p.is_active, 'account': account_info})
            hospital_person_teams[h.id] = teams
    finally:
        flask_g.hospital_id = _saved_hid
    return render_template('data/hospitals.html',
                           hospitals=hospitals,
                           person_counts=person_counts,
                           user_counts=user_counts,
                           hospital_person_teams=hospital_person_teams)


@data_bp.route('/hospitals/add', methods=['POST'])
@admin_required
def add_hospital():
    ok, msg = data_service.add_hospital(
        request.form.get('name', '').strip(),
        request.form.get('code', '').strip(),
        request.form.get('address', '').strip(),
        request.form.get('phone', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_hospitals'))


@data_bp.route('/hospitals/<int:hid>/edit', methods=['POST'])
@admin_required
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
@admin_required
def upload_hospital_logo(hid):
    """上传医院头像"""
    hospital = db.session.get(Hospital, hid)
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
    # 生成唯一文件名
    filename = f'hospital_{hid}_{uuid.uuid4().hex[:8]}.{ext}'
    upload_dir = '/var/www/static/uploads/hospitals'
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    # 删除旧头像
    if hospital.logo:
        old_path = os.path.join(upload_dir, hospital.logo)
        if os.path.exists(old_path):
            os.remove(old_path)
    hospital.logo = filename
    db.session.commit()
    return jsonify({'ok': True, 'filename': filename, 'url': f'/static/uploads/hospitals/{filename}'})


@data_bp.route('/hospitals/<int:hid>/toggle', methods=['POST'])
@admin_required
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
        if current_user.is_admin:
            session['admin_hospital_id'] = 0
        else:
            session['user_hospital_id'] = 0
        flash('已切换到: 全部医院', 'success')
        return redirect(request.referrer or url_for('main.dashboard'))
    h = db.session.get(Hospital, hid)
    if not h:
        flash('医院不存在', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))
    if current_user.is_admin:
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
@admin_required
def index():
    """数据管理总览"""
    from services.address import get_all_buildings
    return render_template('data/index.html',
        persons_count=Person.query.count(),
        departments_count=Department.query.count(),
        solutions_count=SolutionTemplate.query.count(),
        orders_count=WorkOrder.query.count(),
        buildings_count=len(get_all_buildings()),
        type_count=FaultType.query.count(),
        settings_count=SystemSetting.query.count(),
        assets_count=Asset.query.count(),
        spare_parts_count=SparePart.query.count(),
        storage_count=StorageLocation.query.count(),
        suppliers_count=Supplier.query.count(),
        consumables_count=Consumable.query.count(),
        duty_count=DutySchedule.query.count(),
        knowledge_count=KnowledgeBase.query.count(),
        users_count=User.query.count())


# ==================== 人员管理 ====================

@data_bp.route('/persons')
@admin_required
def list_persons():
    persons, user_map = data_service.list_persons()
    # 按组分类
    from models import SystemSetting
    import re
    team_setting = SystemSetting.query.filter_by(key='person_teams').first()
    if team_setting and team_setting.value:
        team_options = [x.strip() for x in re.split(r'[,，]', team_setting.value) if x.strip()]
    else:
        team_options = ['信息科', '后勤', '外包服务']
    team_groups = {}
    team_list = []
    for p in persons:
        t = p.team or '未分组'
        if t not in team_groups:
            team_groups[t] = []
            team_list.append(t)
        team_groups[t].append(p)
    return render_template('data/persons.html', persons=persons, user_map=user_map,
                           team_options=team_options,
                           team_groups=team_groups, team_list=team_list)


@data_bp.route('/persons/add', methods=['POST'])
@admin_required
def add_person():
    ok, msg = data_service.add_person(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/import-from-orders', methods=['POST'])
@admin_required
def import_persons_from_orders():
    imported = data_service.import_persons_from_orders()
    flash(f'从工单中导入 {imported} 名新人员', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/toggle', methods=['POST'])
@admin_required
def toggle_person(pid):
    p = data_service.toggle_person(pid)
    flash(f'已{"停用" if not p.is_active else "启用"}「{p.name}」', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/delete', methods=['POST'])
@admin_required
def delete_person(pid):
    name = data_service.delete_person(pid, current_user.display_name or current_user.username)
    flash(f'已删除人员「{name}」', 'success')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/edit-field', methods=['POST'])
@admin_required
def edit_person_field(pid):
    field = request.form.get('field', '')
    value = request.form.get('value', '').strip()
    ok, err = data_service.edit_person_field(pid, field, value)
    if ok:
        flash('已更新', 'success')
    else:
        flash(err or '未知字段', 'danger')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/<int:pid>/account', methods=['GET', 'POST'])
@admin_required
def person_account(pid):
    if request.method == 'GET':
        return jsonify(data_service.person_account_info(pid))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    display_name = request.form.get('display_name', '').strip()
    is_admin = request.form.get('is_admin') == 'on'
    hospital_ids = request.form.getlist('hospital_ids')
    ok, msg = data_service.person_account_save(pid, username, password, display_name, is_admin, hospital_ids)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_persons'))


@data_bp.route('/persons/lottery-json')
@admin_required
def lottery_persons_json():
    """返回当前医院活跃人员列表（大转盘抽奖用），支持 ?team= 筛选"""
    from flask import session, jsonify
    from models import Person, db
    hid = session.get('hospital_id')
    team = request.args.get('team', '')
    query = Person.query.filter_by(is_active=True)
    if hid:
        query = query.filter_by(hospital_id=hid)
    if team:
        query = query.filter(Person.team == team)
    persons = query.order_by(db.func.random()).all()
    colors = ['#FF6B6B','#FECA57','#48DBFB','#FF9FF3','#54A0FF','#5F27CD','#01A3A4','#F368E0','#EE5A24','#0ABDE3','#10AC84','#5D62E5','#A29BFE','#FD79A8','#6C5CE7','#00CEC9','#E17055','#0984E3']
    data = [{'id': p.id, 'name': p.name, 'color': colors[i % len(colors)]} for i, p in enumerate(persons)]
    return jsonify({'persons': data, 'total': len(data)})


# ==================== 科室字典管理 ====================

@data_bp.route('/departments')
@admin_required
def list_departments():
    return render_template('data/departments.html', departments=data_service.list_departments())


@data_bp.route('/departments/add', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def delete_department(id):
    ok, msg = data_service.delete_department(id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_departments'))


# ==================== 方案模板管理 ====================

@data_bp.route('/solutions')
@admin_required
def list_solutions():
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    device_filter = request.args.get('device_filter', '')
    fault_filter = request.args.get('fault_filter', '')
    pagination = data_service.list_solutions(keyword, device_filter, fault_filter, page)
    return render_template('data/solutions.html', pagination=pagination,
                           keyword=keyword, device_filter=device_filter, fault_filter=fault_filter)


@data_bp.route('/solutions/add', methods=['POST'])
@admin_required
def add_solution():
    ok, msg = data_service.add_solution(
        request.form.get('title', '').strip(),
        request.form.get('content', '').strip(),
        request.form.get('keywords', ''),
        request.form.get('device_type', ''),
        request.form.get('fault_type', ''),
        request.form.get('fault_subcategory', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/reset', methods=['POST'])
@admin_required
def reset_solutions():
    count = data_service.reset_solutions()
    flash(f'已重置 {count} 条方案模板到默认值', 'success')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/import-from-orders', methods=['POST'])
@admin_required
def import_solutions_from_orders():
    imported = data_service.import_solutions_from_orders()
    flash(f'从工单中导入 {imported} 条新方案模板', 'success')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/<int:sid>/edit', methods=['POST'])
@admin_required
def edit_solution(sid):
    data_service.edit_solution(
        sid,
        request.form.get('field', ''),
        request.form.get('value', ''),
        request.form.get('value2'))
    flash('方案已更新', 'success')
    return redirect(url_for('data.list_solutions'))


@data_bp.route('/solutions/<int:sid>/delete', methods=['POST'])
@admin_required
def delete_solution(sid):
    title = data_service.delete_solution(sid, current_user.display_name or current_user.username)
    flash(f'方案「{title}」已删除', 'success')
    return redirect(url_for('data.list_solutions'))


# ==================== 地址数据查看 ====================

@data_bp.route('/addresses')
@admin_required
def list_addresses():
    building = request.args.get('building', '')
    keyword = request.args.get('keyword', '')
    groups, buildings, current_addresses, total = data_service.list_addresses(building, keyword)
    return render_template('data/addresses.html',
                           groups=groups, buildings=buildings,
                           building=building, keyword=keyword,
                           addresses=current_addresses, total=total)


@data_bp.route('/addresses/edit', methods=['POST'])
@admin_required
def edit_address():
    ok, msg = data_service.edit_address(
        request.form.get('override_id', type=int),
        request.form.get('base_index', type=int),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


@data_bp.route('/addresses/add', methods=['POST'])
@admin_required
def add_address():
    ok, msg = data_service.add_address(
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


@data_bp.route('/addresses/<int:oid>/delete', methods=['POST'])
@admin_required
def delete_address(oid):
    building = data_service.delete_address(oid)
    flash('地址已删除', 'success')
    return redirect(url_for('data.list_addresses', building=building))


@data_bp.route('/addresses/delete-base', methods=['POST'])
@admin_required
def delete_base_address():
    ok, msg = data_service.delete_base_address(
        request.form.get('base_index', type=int),
        request.form.get('building', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_addresses', building=request.form.get('building', '')))


# ==================== 故障类型管理 ====================

@data_bp.route('/fault-types')
@admin_required
def list_fault_types():
    return render_template('data/fault_types.html', types=data_service.list_fault_types())


@data_bp.route('/fault-types/add', methods=['POST'])
@admin_required
def add_fault_type():
    ok, msg = data_service.add_fault_type(
        request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_types'))


@data_bp.route('/fault-types/<int:fid>/edit', methods=['POST'])
@admin_required
def edit_fault_type(fid):
    ok, msg = data_service.edit_fault_type(
        fid, request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_types'))


@data_bp.route('/fault-types/<int:fid>/delete', methods=['POST'])
@admin_required
def delete_fault_type(fid):
    name = data_service.delete_fault_type(fid, current_user.display_name or current_user.username)
    flash(f'故障类型「{name}」已删除', 'success')
    return redirect(url_for('data.list_fault_types'))


# ==================== 存放位置字典 ====================

@data_bp.route('/storage-locations')
@admin_required
def list_storage_locations():
    return render_template('data/storage_locations.html', locations=data_service.list_storage_locations())


@data_bp.route('/storage-locations/add', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def toggle_storage_location(lid):
    data_service.toggle_storage_location(lid)
    return redirect(url_for('data.list_storage_locations'))


@data_bp.route('/storage-locations/<int:lid>/delete', methods=['POST'])
@admin_required
def delete_storage_location(lid):
    name = data_service.delete_storage_location(lid)
    flash(f'已删除存放位置「{name}」', 'success')
    return redirect(url_for('data.list_storage_locations'))


# ==================== 供应商管理 ====================

@data_bp.route('/suppliers')
@admin_required
def list_suppliers():
    return render_template('data/suppliers.html', suppliers=data_service.list_suppliers())


@data_bp.route('/suppliers/add', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def toggle_supplier(sid):
    data_service.toggle_supplier(sid)
    return redirect(url_for('data.list_suppliers'))


@data_bp.route('/suppliers/<int:sid>/delete', methods=['POST'])
@admin_required
def delete_supplier(sid):
    name = data_service.delete_supplier(sid)
    flash(f'已删除供应商「{name}」', 'success')
    return redirect(url_for('data.list_suppliers'))


# ==================== 耗材管理 ====================

@data_bp.route('/consumables')
@admin_required
def list_consumables():
    q = request.args.get('q', '').strip()
    return render_template('data/consumables.html', consumables=data_service.list_consumables(q), q=q)


@data_bp.route('/consumables/add', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def delete_consumable(cid):
    name = data_service.delete_consumable(cid)
    flash(f'已删除耗材「{name}」', 'success')
    return redirect(url_for('data.list_consumables'))


@data_bp.route('/consumables/import-excel', methods=['POST'])
@admin_required
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
@admin_required
def consumable_inout():
    cid = request.form.get('cid', type=int)
    action = request.form.get('action')
    qty = request.form.get('quantity', type=int, default=0)
    note = request.form.get('note', '')
    department = request.form.get('department', '')
    ok, msg, balance = data_service.consumable_inout(
        cid, action, qty, note, current_user.display_name, department)
    if ok:
        return jsonify({'ok': True, 'balance': balance})
    return jsonify({'ok': False, 'msg': msg}), 400


@data_bp.route('/consumables/batch-out', methods=['POST'])
@admin_required
def consumable_batch_out():
    """耗材一键出库"""
    department = request.form.get('department', '').strip()
    items_raw = request.form.getlist('items[]')
    items = []
    for item in items_raw:
        parts = item.split(':')
        if len(parts) != 2:
            continue
        try:
            cid, qty = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if qty <= 0:
            continue
        items.append({'cid': cid, 'qty': qty})
    ok, msg, out_records = data_service.batch_consumable_out(
        items, department, current_user.display_name)
    if ok:
        return jsonify({'ok': True, 'msg': msg, 'records': out_records})
    return jsonify({'ok': False, 'msg': msg}), 400


@data_bp.route('/consumables/batch-out-sign/init', methods=['POST'])
@admin_required
def consumable_batch_out_sign_init():
    """创建耗材出库签名请求，返回token和二维码URL"""
    import secrets, json as pyjson
    department = request.form.get('department', '').strip()
    if not department:
        return jsonify({'ok': False, 'msg': '请选择科室'}), 400
    items_raw = request.form.getlist('items[]')
    if not items_raw:
        return jsonify({'ok': False, 'msg': '请选择出库物品'}), 400
    # 检查库存
    for item in items_raw:
        parts = item.split(':')
        if len(parts) != 2:
            continue
        try:
            cid, qty = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if qty <= 0:
            continue
        c = Consumable.query.get(cid)
        if not c:
            continue
        if c.quantity < qty:
            return jsonify({'ok': False, 'msg': f'「{c.name}」库存不足'}), 400
    token = secrets.token_hex(16)
    sign_req = ConsumableSignRequest(
        token=token, department=department,
        items_json=pyjson.dumps(items_raw),
        operator=current_user.display_name,
    )
    db.session.add(sign_req)
    db.session.commit()
    qr_url = f'https://demolin.cn/forms/sign-consumable/{token}'
    return jsonify({'ok': True, 'token': token, 'qr_url': qr_url})


@data_bp.route('/consumables/batch-out-sign/execute/<token>', methods=['POST'])
@admin_required
def consumable_batch_out_sign_execute(token):
    """签名完成后执行耗材出库"""
    import json as pyjson
    from datetime import datetime
    sign_req = ConsumableSignRequest.query.filter_by(token=token).first()
    if not sign_req:
        return jsonify({'ok': False, 'msg': '签名请求不存在'}), 404
    if sign_req.status != 'signed':
        return jsonify({'ok': False, 'msg': '尚未签名'}), 400
    if sign_req.status == 'completed':
        return jsonify({'ok': False, 'msg': '已执行'}), 400
    department = sign_req.department
    items = pyjson.loads(sign_req.items_json)
    signature = sign_req.signature
    out_records = []
    for item in items:
        parts = item.split(':')
        if len(parts) != 2:
            continue
        try:
            cid, qty = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if qty <= 0:
            continue
        c = Consumable.query.get(cid)
        if not c:
            continue
        if c.quantity < qty:
            return jsonify({'ok': False, 'msg': f'「{c.name}」库存不足'}), 400
        c.quantity -= qty
        record = ConsumableRecord(
            consumable_id=cid, type='out', quantity=qty,
            balance=c.quantity, operator=sign_req.operator,
            department=department, note=f'扫码签名出库至{department}',
            signature=signature,
        )
        db.session.add(record)
        out_records.append({'name': c.name, 'qty': qty, 'unit': c.unit})
    sign_req.status = 'completed'
    sign_req.completed_at = datetime.now()
    db.session.commit()
    log_audit('batch_out', 'consumable', sign_req.operator,
              target_desc=f'耗材扫码签名出库至{department}，共{len(out_records)}项')
    return jsonify({'ok': True, 'msg': f'已出库 {len(out_records)} 项至「{department}」', 'records': out_records})


@data_bp.route('/consumables/export-template')
@admin_required
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
@admin_required
def list_duty_schedules():
    from datetime import datetime, date
    from models import SystemSetting
    import re
    now = date.today()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)
    staff = data_service.get_duty_schedule_staff()
    total_days, first_weekday, holidays = data_service.get_duty_month_info(year, month)
    # 获取系统配置的组别选项
    team_setting = SystemSetting.query.filter_by(key='person_teams').first()
    if team_setting and team_setting.value:
        team_list = [x.strip() for x in re.split(r'[,，]', team_setting.value) if x.strip()]
    else:
        team_list = ['信息科', '后勤', '外包服务']
    team_sel = request.args.get('team', '')
    # 按组别筛选值班人员
    if team_sel:
        staff = [s for s in staff if s.team == team_sel]
    return render_template('data/duty_schedules.html', staff=staff, year=year, month=month,
                           total_days=total_days, first_weekday=first_weekday,
                           now=datetime.combine(date.today(), datetime.min.time()),
                           holidays=holidays, team_list=team_list, team_sel=team_sel)


@data_bp.route('/duty-schedules/api')
@admin_required
def duty_schedules_api():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not year or not month:
        return jsonify({'error': '参数错误'}), 400
    data = data_service.get_duty_schedules_api(year, month)
    return jsonify({'records': data})


@data_bp.route('/duty-schedules/api/update', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def duty_staff_manage():
    if request.method == 'POST':
        ok, msg = data_service.add_duty_staff(request.form.get('name', '').strip())
        flash(msg, 'success' if ok else 'danger')
        return redirect(url_for('data.duty_staff_manage'))
    staff = data_service.list_duty_staff()
    return render_template('data/duty_staff.html', staff=staff)


@data_bp.route('/duty-schedules/staff/<int:sid>/toggle', methods=['POST'])
@admin_required
def duty_staff_toggle(sid):
    active = data_service.toggle_duty_staff(sid)
    return jsonify({'ok': True, 'active': active})


@data_bp.route('/duty-schedules/staff/<int:sid>/delete', methods=['POST'])
@admin_required
def duty_staff_delete(sid):
    data_service.delete_duty_staff(sid)
    return jsonify({'ok': True})


# ==================== 知识库/公告 ====================

@data_bp.route('/knowledge')
@login_required
def list_knowledge():
    category = request.args.get('category', '')
    articles, categories = data_service.list_knowledge(category)
    return render_template('data/knowledge.html', articles=articles, categories=categories, cur_cat=category)


@data_bp.route('/knowledge/add', methods=['POST'])
@admin_required
def add_knowledge():
    ok, msg = data_service.add_knowledge(
        request.form.get('title', '').strip(),
        request.form.get('category', '公告'),
        request.form.get('content', ''),
        request.form.get('is_pinned') == 'on')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_knowledge'))


@data_bp.route('/knowledge/<int:kid>/edit', methods=['POST'])
@admin_required
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
@admin_required
def delete_knowledge(kid):
    title = data_service.delete_knowledge(kid)
    flash(f'已删除文章「{title}」', 'success')
    return redirect(url_for('data.list_knowledge'))


# ==================== 权限管理 ====================

@data_bp.route('/permissions')
@admin_required
def permissions():
    users, module_perms, all_module_names, persons, users_by_group, role_groups = data_service.get_permissions_page_data()
    return render_template('data/permissions.html', users=users, module_perms=module_perms,
                           all_module_names=all_module_names, persons=persons,
                           users_by_group=users_by_group, role_groups=role_groups)


@data_bp.route('/permissions/sync-users', methods=['POST'])
@admin_required
def sync_users_from_persons():
    created, msg = data_service.sync_users_from_persons(
        current_user.display_name or current_user.username)
    flash(msg, 'success' if created else 'info')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/save', methods=['POST'])
@admin_required
def save_permissions():
    data = request.get_json(force=True)
    if not data or 'groups' not in data:
        return {'ok': False, 'msg': '无效数据'}, 400
    ok, msg = data_service.save_permissions(data)
    return {'ok': ok, 'msg': msg}


@data_bp.route('/permissions/toggle-admin/<int:uid>', methods=['POST'])
@admin_required
def toggle_admin(uid):
    ok, msg, _ = data_service.toggle_admin(
        uid, current_user.id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/set-group', methods=['POST'])
@admin_required
def set_user_group():
    ok, msg = data_service.set_user_group(
        request.form.get('uid', type=int),
        request.form.get('group', '').strip(),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/add-group', methods=['POST'])
@admin_required
def add_permission_group():
    ok, msg = data_service.add_permission_group(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/delete-group', methods=['POST'])
@admin_required
def delete_permission_group():
    ok, msg = data_service.delete_permission_group(request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/add-module', methods=['POST'])
@admin_required
def add_permission_module():
    ok, msg = data_service.add_permission_module(
        request.form.get('module', '').strip(),
        request.form.get('category', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/delete-module', methods=['POST'])
@admin_required
def delete_permission_module():
    ok, msg = data_service.delete_permission_module(request.form.get('module', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.permissions'))


@data_bp.route('/permissions/rename-group', methods=['POST'])
@admin_required
def rename_permission_group():
    """重命名角色组（预留）"""
    flash('功能开发中', 'info')
    return redirect(url_for('data.permissions'))


# ==================== 故障二级分类管理 ====================

@data_bp.route('/fault-categories')
@admin_required
def list_fault_categories():
    cats = data_service.list_fault_categories()
    return render_template('data/fault_categories.html', categories=cats)


@data_bp.route('/fault-categories/subcategory/add', methods=['POST'])
@admin_required
def add_fault_subcategory():
    ok, msg = data_service.add_fault_subcategory(
        request.form.get('category_id', type=int),
        request.form.get('name', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/subcategory/delete/<int:sub_id>', methods=['POST'])
@admin_required
def delete_fault_subcategory(sub_id):
    data_service.delete_fault_subcategory(sub_id)
    flash('已删除子分类', 'success')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/keyword/add', methods=['POST'])
@admin_required
def add_fault_keyword():
    ok, msg = data_service.add_fault_keywords(
        request.form.get('subcategory_id', type=int),
        request.form.get('keywords', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_categories'))


@data_bp.route('/fault-categories/keyword/delete/<int:kw_id>', methods=['POST'])
@admin_required
def delete_fault_keyword(kw_id):
    data_service.delete_fault_keyword(kw_id)
    flash('已删除关键词', 'success')
    return redirect(url_for('data.list_fault_categories'))


# ==================== 零件价格管理 ====================

@data_bp.route('/parts')
@admin_required
def list_parts():
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    supplier = request.args.get('supplier', '').strip()
    parts, categories, suppliers = data_service.list_parts(q, cat, supplier)
    return render_template('data/parts.html', parts=parts, q=q, cat=cat,
                           supplier=supplier, categories=categories, suppliers=suppliers)


@data_bp.route('/parts/add', methods=['POST'])
@admin_required
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
@admin_required
def delete_part(part_id):
    name = data_service.delete_part(part_id, current_user.display_name or current_user.username)
    flash(f'已删除零件「{name}」', 'success')
    return redirect(url_for('data.list_parts'))


# ==================== 耗材出入库记录 ====================

@data_bp.route('/consumables/records')
@admin_required
def consumable_records_view():
    q = request.args.get('q', '').strip()
    action = request.args.get('action', '').strip()
    department = request.args.get('department', '').strip()
    page = request.args.get('page', 1, type=int)
    records, pagination, total = data_service.list_consumable_records(q, action, department, page)
    # 获取所有出库科室列表（用于筛选下拉）
    departments_list = data_service.get_consumable_departments()
    return render_template('data/consumable_records.html', records=records,
                           pagination=pagination, total=total, q=q,
                           action=action, department=department,
                           departments=departments_list)


@data_bp.route('/consumables/records/<int:rid>/delete', methods=['POST'])
@admin_required
def delete_consumable_record(rid):
    data_service.delete_consumable_record(rid)
    flash('记录已删除', 'success')
    return redirect(url_for('data.consumable_records_view'))


# ==================== 故障模板组管理 ====================

@data_bp.route('/fault-template-groups')
@admin_required
def list_fault_template_groups():
    groups, all_teams = data_service.list_fault_template_groups()
    return render_template('data/fault_template_groups.html', groups=groups, all_teams=all_teams)


@data_bp.route('/fault-template-groups/add', methods=['POST'])
@admin_required
def add_fault_template_group():
    ok, msg = data_service.add_fault_template_group(
        request.form.get('name', '').strip(),
        request.form.getlist('teams'),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_template_groups'))


@data_bp.route('/fault-template-groups/<int:gid>/edit', methods=['POST'])
@admin_required
def edit_fault_template_group(gid):
    data_service.edit_fault_template_group(gid,
        request.form.get('field', ''),
        request.form.get('value', ''))
    flash('模板组已更新', 'success')
    return redirect(url_for('data.list_fault_template_groups'))


@data_bp.route('/fault-template-groups/<int:gid>/delete', methods=['POST'])
@admin_required
def delete_fault_template_group(gid):
    name = data_service.delete_fault_template_group(gid,
        current_user.display_name or current_user.username)
    flash(f'已删除模板组「{name}」', 'success')
    return redirect(url_for('data.list_fault_template_groups'))


@data_bp.route('/fault-template-groups/<int:gid>/items/add', methods=['POST'])
@admin_required
def add_fault_template_item(gid):
    ok, msg = data_service.add_fault_template_item(gid,
        request.form.get('fault_type', '硬件'),
        request.form.get('display_name', '').strip(),
        int(request.form.get('default_count', 1)))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data.list_fault_template_groups'))


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/edit', methods=['POST'])
@admin_required
def edit_fault_template_item(gid, iid):
    data_service.edit_fault_template_item(gid, iid,
        request.form.get('fault_type', ''),
        request.form.get('display_name', ''),
        int(request.form.get('default_count', 1)))
    flash('故障项已更新', 'success')
    return redirect(url_for('data.list_fault_template_groups'))


@data_bp.route('/fault-template-groups/<int:gid>/items/<int:iid>/delete', methods=['POST'])
@admin_required
def delete_fault_template_item(gid, iid):
    data_service.delete_fault_template_item(gid, iid)
    flash('故障项已删除', 'success')
    return redirect(url_for('data.list_fault_template_groups'))
