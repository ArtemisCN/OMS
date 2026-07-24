"""Feature Blueprint: 工单转交, SLA监控, 历史追溯, 效能看板, 资产二维码,
耗材预测, 备件联动, 供应商管理, 合同管理, 资产折旧,
NFC巡检签到, 运维大屏, 领导驾驶舱, 自定义报表, 短信通知"""
import io
import json
import os
from datetime import datetime, date, timedelta

from flask import current_app,  Blueprint, render_template, jsonify, request, send_file, g
from flask_login import login_required, current_user
from sqlalchemy import func

from utils.time_helpers import fmt_dt, now, fmt_date
from models import (
    db, WorkOrder, WorkOrderTransferLog, WorkOrderChatMessage,
    Asset, User, SystemSetting, RoleGroup,
    SparePart, StockRecord, Consumable, ConsumableRecord,
    Supplier, MaintenanceContract, InspectionPlan, InspectionCheckin,
    Department, FaultType, SmsLog, SolutionTemplate,
    ShiftHandover, RepairRating, Complaint, StockRequest,
    InspectionRoute, SparePartAlert,
)

feature_bp = Blueprint('feature', __name__, url_prefix='/feature')

HOSPITAL_ID = 1  # 演示用固定值，后续可改为 g.hospital_id
QR_BASE_URL = 'https://demolin.cn/scan/1/submit?asset_id='


# ===================== 1. 工单转交/协办 =====================

@feature_bp.route('/transfer/<int:order_id>', methods=['POST'])
@login_required
def transfer_order(order_id):
    """转交工单给他人"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        return jsonify(success=False, error='工单不存在'), 404

    data = request.get_json(silent=True) or {}
    to_person = data.get('to_person', '').strip()
    remark = data.get('remark', '').strip()

    if not to_person:
        return jsonify(success=False, error='请选择接收人'), 400

    log = WorkOrderTransferLog(
        work_order_id=order.id,
        action='transfer',
        from_person=order.person,
        to_person=to_person,
        operator_name=current_user.display_name or current_user.username,
        remark=remark
    )
    db.session.add(log)

    order.person = to_person
    db.session.commit()

    return jsonify(success=True, message=f'工单已转交给 {to_person}')


@feature_bp.route('/transfer/page/<int:order_id>', methods=['GET'])
@login_required
def transfer_page(order_id):
    """转交页面"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        return render_template('errors/404.html'), 404

    persons = User.query.filter(User.is_active==True).order_by(User.sort_order, User.display_name).all()
    return render_template('feature/transfer_page.html', order=order, persons=persons)


# ===================== 2. 历史工单追溯 =====================

@feature_bp.route('/history/<int:order_id>', methods=['GET'])
@login_required
def history_data(order_id):
    """返回与工单同设备类型或同科室的历史工单 JSON"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        return jsonify(success=False, error='工单不存在'), 404

    # 查找相同 device_type 或相同 department 的已关闭工单
    related = WorkOrder.query.filter(
        WorkOrder.id != order.id,
        WorkOrder.status == 'completed',
        (WorkOrder.device_type == order.device_type) | (WorkOrder.department == order.department)
    ).order_by(WorkOrder.completed_at.desc()).limit(50).all()

    result = []
    for wo in related:
        cost_hours = None
        if wo.created_at and wo.completed_at:
            cost_hours = round((wo.completed_at - wo.created_at).total_seconds() / 3600, 1)

        result.append({
            'id': wo.id,
            'title': wo.title,
            'device_type': wo.device_type,
            'department': wo.department,
            'person': wo.person,
            'fault_type': wo.fault_type,
            'priority': wo.priority,
            'solution': wo.solution[:200] if wo.solution else '',
            'created_at': fmt_dt(wo.created_at, '%Y-%m-%d %H:%M'),
            'completed_at': fmt_dt(wo.completed_at, '%Y-%m-%d %H:%M'),
            'cost_hours': cost_hours,
        })

    return jsonify(success=True, data=result, total=len(result))


@feature_bp.route('/history/page/<int:order_id>', methods=['GET'])
@login_required
def history_page(order_id):
    """历史追溯页面"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        return render_template('errors/404.html'), 404
    return render_template('feature/history_page.html', order=order)


# ===================== 3. 人员效能看板 =====================

@feature_bp.route('/personnel/dashboard', methods=['GET'])
@login_required
def personnel_dashboard():
    """人员效能看板页面"""
    import re
    team_setting = SystemSetting.query.filter_by(key='person_teams').first()
    team_list = []
    if team_setting and team_setting.value:
        team_list = [t.strip() for t in re.split(r'[,，]', team_setting.value) if t.strip()]
    default_team = SystemSetting.query.filter_by(key='personnel_default_team').first()
    return render_template('feature/personnel_dashboard.html',
                           team_list=team_list,
                           default_team=default_team.value if default_team and default_team.value else '')


@feature_bp.route('/personnel/data', methods=['GET'])
@login_required
def personnel_data():
    """人员效能统计 JSON（支持 hospital 和 group 过滤）"""
    group_id = request.args.get('group_id', type=int)
    team = request.args.get('team')
    hid = getattr(g, 'hospital_id', None)
    from sqlalchemy import text

    # 基础查询：按 person 聚合已完成工单
    base_q = db.session.query(
        WorkOrder.person,
        func.count(WorkOrder.id).label('total_orders'),
        func.sum(
            func.cast(
                func.julianday(WorkOrder.completed_at) - func.julianday(WorkOrder.created_at),
                db.Float
            )
        ).label('total_days')
    ).filter(
        WorkOrder.person != '',
        WorkOrder.person.isnot(None),
        WorkOrder.completed_at.isnot(None),
        WorkOrder.created_at.isnot(None),
    )

    # 医院过滤
    if hid:
        base_q = base_q.filter(WorkOrder.hospital_id == hid)

    # 团队过滤：通过 Person.team 查出该团队的 person 名单
    team_person_names = None
    if team:
        p_rows = db.session.execute(text(
            "SELECT display_name FROM users WHERE team = :team"
        ), {'team': team}).fetchall()
        team_person_names = {r[0] for r in p_rows}
        if team_person_names:
            base_q = base_q.filter(WorkOrder.person.in_(team_person_names))
        else:
            return jsonify(success=True, data=[], total=0, groups=[])

    # 分组过滤：通过 Person → User → RoleGroup 查出该组的 person 名单
    group_person_names = None
    if group_id:
        rows = db.session.execute(text(
            "SELECT display_name FROM users "
            "WHERE group_id = :gid"
        ), {'gid': group_id}).fetchall()
        group_person_names = {r[0] for r in rows}
        if group_person_names:
            base_q = base_q.filter(WorkOrder.person.in_(group_person_names))
        else:
            return jsonify(success=True, data=[], total=0)

    rows = base_q.group_by(WorkOrder.person).all()

    # 在岗人员名单（同条件过滤）
    active_q = "SELECT display_name FROM users WHERE is_active = 1"
    active_params = {}
    if hid:
        active_q += " AND hospital_id = :hid"
        active_params['hid'] = hid
    if group_person_names is not None:
        # 已经在 user group 范围内的 persons
        pass  # group_person_names already filtered
    p_rows = db.session.execute(text(active_q), active_params).fetchall()
    all_active_names = {r[0] for r in p_rows}
    if group_person_names is not None:
        all_active_names &= group_person_names
    if team_person_names is not None:
        all_active_names &= team_person_names

    stats = []
    for row in rows:
        name = row.person
        total = row.total_orders
        total_days = float(row.total_days or 0)
        avg_hours = round(total_days * 24 / total, 1) if total > 0 else 0

        # 子查询加过滤
        def _person_q():
            q = WorkOrder.query.filter(WorkOrder.person == name)
            if hid:
                q = q.filter(WorkOrder.hospital_id == hid)
            return q

        in_progress = _person_q().filter(WorkOrder.status == 'in_progress').count()
        pending = _person_q().filter(WorkOrder.status == 'pending').count()

        person_completed = _person_q().filter(WorkOrder.status == 'completed').all()
        sla_total = len(person_completed)
        sla_ok = sum(1 for wo in person_completed if not wo.is_overdue)
        sla_pct = round(sla_ok / sla_total * 100) if sla_total > 0 else 0

        stats.append({
            'name': name,
            'total_orders': total,
            'in_progress': in_progress,
            'pending': pending,
            'avg_hours': avg_hours,
            'active': name in all_active_names,
            'sla_total': sla_total,
            'sla_ok': sla_pct,
        })

    stats.sort(key=lambda x: x['total_orders'], reverse=True)

    groups = RoleGroup.query.order_by(RoleGroup.name).all()
    group_list = [{'id': rg.id, 'name': rg.name} for rg in groups]

    return jsonify(success=True, data=stats, total=len(stats), groups=group_list)


# ===================== 4. SLA 时限管理 =====================

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


@feature_bp.route('/sla/dashboard', methods=['GET'])
@login_required
def sla_dashboard():
    """SLA 监控页面"""
    return render_template('feature/sla_dashboard.html',
                           thresholds=_get_sla_thresholds())


@feature_bp.route('/sla/data', methods=['GET'])
@login_required
def sla_data():
    """SLA 数据 JSON（优化版：SQL 批量计算，不调 is_overdue 属性）"""
    now = datetime.now()
    thresholds = _get_sla_thresholds()

    # 只查最近3个月的工单，避免全表扫描
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

    # 用 SQL 聚合统计，不循环 Python
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


def _check_overdue(wo, thresholds, now):
    """直接判断工单是否超时，不调 is_overdue 属性（避免 N+1 查 SystemSetting）"""
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


@feature_bp.route('/sla/settings', methods=['POST'])
@login_required
def sla_settings():
    """保存 SLA 阈值设置"""
    if not current_user.is_admin:
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


# ===================== 5. 资产二维码 =====================

@feature_bp.route('/asset/qr', methods=['GET'])
@login_required
def asset_qr():
    """资产二维码列表页面"""
    assets = Asset.query.order_by(Asset.asset_no).all()
    return render_template('feature/asset_qr.html', assets=assets,
                           qr_base_url=QR_BASE_URL)


@feature_bp.route('/asset/qr/<int:asset_id>', methods=['GET'])
@login_required
def asset_qr_image(asset_id):
    """生成单个资产二维码图片"""
    asset = db.session.get(Asset, asset_id)
    if not asset:
        return jsonify(success=False, error='资产不存在'), 404

    import qrcode
    url = f'{QR_BASE_URL}{asset.id}'
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png',
                     download_name=f'asset_{asset.id}.png')


@feature_bp.route('/asset/qr/batch', methods=['POST'])
@login_required
def asset_qr_batch():
    """批量生成资产二维码（返回 ZIP）"""
    data = request.get_json(silent=True) or {}
    asset_ids = data.get('asset_ids', [])
    if not asset_ids:
        return jsonify(success=False, error='请选择资产'), 400

    import qrcode
    import zipfile

    assets = Asset.query.filter(Asset.id.in_(asset_ids)).all()
    if not assets:
        return jsonify(success=False, error='未找到资产'), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for asset in assets:
            url = f'{QR_BASE_URL}{asset.id}'
            img = qrcode.make(url)
            img_buf = io.BytesIO()
            img.save(img_buf, format='PNG')
            img_buf.seek(0)
            fname = f'{asset.asset_no or asset.id}_{asset.device_type}.png'
            zf.writestr(fname, img_buf.getvalue())

    buf.seek(0)
    return send_file(buf, mimetype='application/zip',
                     download_name='asset_qr_codes.zip',
                     as_attachment=True)


# ===================== 6. 耗材用量预测 =====================

@feature_bp.route('/consumable/forecast', methods=['GET'])
@login_required
def consumable_forecast():
    """耗材用量预测页面"""
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    consumables = Consumable.query.order_by(Consumable.name).all()

    forecasts = []
    chart_labels = []
    chart_data = []

    # 近30天每日消耗统计（前10名耗材）
    daily_stats = db.session.query(
        func.date(ConsumableRecord.created_at).label('d'),
        func.sum(ConsumableRecord.quantity).label('total_out')
    ).filter(
        ConsumableRecord.type == 'out',
        ConsumableRecord.created_at >= thirty_days_ago,
    ).group_by(
        func.date(ConsumableRecord.created_at)
    ).order_by('d').all()

    for row in daily_stats:
        chart_labels.append(row.d)
        chart_data.append(row.total_out or 0)

    for c in consumables:
        # 近30天出库总数
        result = db.session.query(
            func.coalesce(func.sum(ConsumableRecord.quantity), 0)
        ).filter(
            ConsumableRecord.consumable_id == c.id,
            ConsumableRecord.type == 'out',
            ConsumableRecord.created_at >= thirty_days_ago,
        ).scalar() or 0

        out_qty_30d = int(result)
        avg_daily = round(out_qty_30d / 30, 2) if out_qty_30d > 0 else 0

        balance = c.quantity

        if avg_daily > 0:
            days_remaining = round(balance / avg_daily, 1)
            if days_remaining <= 7:
                status = 'red'
            elif days_remaining <= 14:
                status = 'yellow'
            else:
                status = 'safe'
        else:
            days_remaining = None
            status = 'nodata'

        forecasts.append({
            'name': c.name,
            'spec': c.spec,
            'balance': balance,
            'out_qty_30d': out_qty_30d,
            'avg_daily': avg_daily,
            'days_remaining': days_remaining,
            'status': status,
        })

    # 按预警状态排序：红色→黄色→无数据→安全
    status_order = {'red': 0, 'yellow': 1, 'nodata': 2, 'safe': 3}
    forecasts.sort(key=lambda x: status_order.get(x['status'], 9))

    return render_template(
        'feature/consumable_forecast.html',
        forecasts=forecasts,
        chart_labels=json.dumps(chart_labels),
        chart_data=json.dumps(chart_data),
    )


# ===================== 7. 备件→工单联动 =====================

@feature_bp.route('/stock/link_to_order', methods=['POST'])
@login_required
def stock_link_to_order():
    """备件出库并关联到工单"""
    part_id = request.form.get('part_id', type=int)
    work_order_id = request.form.get('work_order_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)
    note = request.form.get('note', '').strip()

    if not part_id or not work_order_id:
        return jsonify(success=False, error='参数不完整'), 400

    part = db.session.get(SparePart, part_id)
    if not part:
        return jsonify(success=False, error='备件不存在'), 404

    work_order = db.session.get(WorkOrder, work_order_id)
    if not work_order:
        return jsonify(success=False, error='工单不存在'), 404

    if part.stock < quantity:
        return jsonify(success=False, error=f'库存不足（当前 {part.stock}）'), 400

    # 扣减库存
    part.stock -= quantity

    record = StockRecord(
        part_id=part.id,
        type='out',
        quantity=quantity,
        balance=part.stock,
        operator=current_user.display_name or current_user.username,
        work_order_id=work_order.id,
        department=work_order.department,
        note=note or f'关联工单 #{work_order.id}',
    )
    db.session.add(record)
    db.session.commit()

    return jsonify(success=True, message=f'已出库 {quantity} 个 {part.name} 并关联到工单 #{work_order.id}')


# ===================== 8. 供应商管理 =====================

@feature_bp.route('/suppliers', methods=['GET'])
@login_required
def suppliers():
    """供应商列表"""
    supplier_list = Supplier.query.order_by(Supplier.sort_order, Supplier.name).all()

    suppliers_json = []
    for s in supplier_list:
        d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat() if v else None
        suppliers_json.append(d)

    return render_template(
        'feature/supplier_list.html',
        suppliers=supplier_list,
        suppliers_json=json.dumps(suppliers_json, ensure_ascii=False),
    )


@feature_bp.route('/suppliers/save', methods=['POST'])
@login_required
def supplier_save():
    """创建/编辑供应商"""
    supplier_id = request.form.get('id', type=int)
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify(success=False, error='供应商名称不能为空'), 400

    if supplier_id:
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier:
            return jsonify(success=False, error='供应商不存在'), 404
    else:
        supplier = Supplier()

    supplier.name = name
    supplier.contact_person = request.form.get('contact_person', '').strip()
    supplier.phone = request.form.get('phone', '').strip()
    supplier.email = request.form.get('email', '').strip()
    supplier.address = request.form.get('address', '').strip()
    supplier.supply_type = request.form.get('supply_type', '综合')
    supplier.rating = request.form.get('rating', 3, type=int)
    supplier.service_scope = request.form.get('service_scope', '').strip()
    supplier.remark = request.form.get('remark', '').strip()
    supplier.is_active = request.form.get('is_active') == '1'

    if not supplier_id:
        db.session.add(supplier)
    db.session.commit()

    return jsonify(success=True, message='供应商已保存')


@feature_bp.route('/suppliers/<int:id>/delete', methods=['POST'])
@login_required
def supplier_delete(id):
    """删除供应商"""
    supplier = db.session.get(Supplier, id)
    if not supplier:
        return jsonify(success=False, error='供应商不存在'), 404
    db.session.delete(supplier)
    db.session.commit()
    return jsonify(success=True, message='供应商已删除')


# ===================== 9. 合同维保管理 =====================

@feature_bp.route('/contracts', methods=['GET'])
@login_required
def contracts():
    """合同列表"""
    contract_list = MaintenanceContract.query.order_by(
        MaintenanceContract.end_date.asc()
    ).all()

    # 即将到期的合同（30天内）
    today = date.today()
    expiring = [c for c in contract_list if c.expiring_soon]

    contracts_json = []
    for c in contract_list:
        d = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat() if v else None
        contracts_json.append(d)

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    assets = Asset.query.order_by(Asset.asset_no).all()

    return render_template(
        'feature/contract_list.html',
        contracts=contract_list,
        expiring_contracts=expiring,
        suppliers=suppliers,
        assets=assets,
        contracts_json=json.dumps(contracts_json, ensure_ascii=False),
    )


@feature_bp.route('/contracts/save', methods=['POST'])
@login_required
def contract_save():
    """创建/编辑合同"""
    contract_id = request.form.get('id', type=int)
    contract_name = request.form.get('contract_name', '').strip()
    if not contract_name:
        return jsonify(success=False, error='合同名称不能为空'), 400

    if contract_id:
        contract = db.session.get(MaintenanceContract, contract_id)
        if not contract:
            return jsonify(success=False, error='合同不存在'), 404
    else:
        contract = MaintenanceContract()

    contract.contract_no = request.form.get('contract_no', '').strip()
    contract.contract_name = contract_name
    contract.supplier_id = request.form.get('supplier_id', type=int) or None
    contract.asset_id = request.form.get('asset_id', type=int) or None

    start_date_str = request.form.get('start_date', '').strip()
    end_date_str = request.form.get('end_date', '').strip()
    contract.start_date = date.fromisoformat(start_date_str) if start_date_str else None
    contract.end_date = date.fromisoformat(end_date_str) if end_date_str else None

    contract.contract_amount = request.form.get('contract_amount', 0, type=float) or 0
    contract.payment_type = request.form.get('payment_type', '一次性')
    contract.status = request.form.get('status', 'active')
    contract.contact_person = request.form.get('contact_person', '').strip()
    contract.contact_phone = request.form.get('contact_phone', '').strip()
    contract.remark = request.form.get('remark', '').strip()

    if not contract_id:
        db.session.add(contract)
    db.session.commit()

    return jsonify(success=True, message='合同已保存')


@feature_bp.route('/contracts/<int:id>/delete', methods=['POST'])
@login_required
def contract_delete(id):
    """删除合同"""
    contract = db.session.get(MaintenanceContract, id)
    if not contract:
        return jsonify(success=False, error='合同不存在'), 404
    db.session.delete(contract)
    db.session.commit()
    return jsonify(success=True, message='合同已删除')


# ===================== 10. 设备折旧计算 =====================

@feature_bp.route('/asset/depreciation', methods=['GET'])
@login_required
def asset_depreciation():
    """设备折旧计算页面"""
    today = date.today()

    assets = Asset.query.filter(
        Asset.purchase_price.isnot(None),
        Asset.purchase_date.isnot(None),
        Asset.purchase_price > 0,
    ).order_by(Asset.asset_no).all()

    items = []
    total_purchase = 0
    total_depreciation = 0
    total_current = 0

    for a in assets:
        purchase_price = float(a.purchase_price or 0)
        lifespan = a.lifespan_years or 5
        purchase_date_val = a.purchase_date

        # 已用年数
        age_days = (today - purchase_date_val).days if purchase_date_val else 0
        age_years = max(0, age_days / 365.0)

        # 年折旧（直线法）
        annual_dep = purchase_price / lifespan if lifespan > 0 else 0

        current_value = purchase_price * max(0, (1 - age_years / lifespan)) if lifespan > 0 else 0

        # 折旧率
        dep_rate = min(1, age_years / lifespan) if lifespan > 0 else 1

        items.append({
            'id': a.id,
            'asset_no': a.asset_no,
            'device_type': a.device_type,
            'brand': a.brand,
            'purchase_price': purchase_price,
            'purchase_date_str': fmt_date(purchase_date_val),
            'purchase_date': purchase_date_val,
            'lifespan_years': lifespan,
            'age_years': round(age_years, 1),
            'annual_depreciation': round(annual_dep, 2),
            'current_value': round(current_value, 2),
            'depreciation_rate': round(dep_rate, 4),
        })

        total_purchase += purchase_price
        total_depreciation += purchase_price - current_value
        total_current += current_value

    # 按剩余价值降序排列
    items.sort(key=lambda x: x['current_value'], reverse=True)

    # 图表数据：Top 10 资产
    top10 = items[:10]
    chart_labels = [f"{a['asset_no']}" for a in top10]
    chart_values = [a['current_value'] for a in top10]
    chart_depreciated = [a['purchase_price'] - a['current_value'] for a in top10]

    return render_template(
        'feature/asset_depreciation.html',
        items=items,
        total={
            'purchase_total': round(total_purchase, 2),
            'depreciation_total': round(total_depreciation, 2),
            'current_total': round(total_current, 2),
        },
        chart_labels=json.dumps(chart_labels),
        chart_values=json.dumps(chart_values),
        chart_depreciated=json.dumps(chart_depreciated),
    )


# ===================== 11. NFC巡检签到 (Feature 1) =====================

@feature_bp.route('/inspection/checkin/<int:task_id>', methods=['GET'])
@login_required
def inspection_checkin_page(task_id):
    """巡检签到页面（扫码签到替代 NFC）"""
    plan = db.session.get(InspectionPlan, task_id)
    if not plan:
        return render_template('errors/404.html'), 404
    # 查询已有的签到记录
    checkin = InspectionCheckin.query.filter_by(inspection_plan_id=task_id).first()
    return render_template('feature/inspection_checkin.html', plan=plan, checkin=checkin)


@feature_bp.route('/inspection/checkin/<int:task_id>', methods=['POST'])
@login_required
def inspection_checkin_do(task_id):
    """执行巡检签到"""
    plan = db.session.get(InspectionPlan, task_id)
    if not plan:
        return jsonify(success=False, error='巡检计划不存在'), 404

    data = request.get_json(silent=True) or {}
    existing = InspectionCheckin.query.filter_by(inspection_plan_id=task_id).first()
    if existing:
        return jsonify(success=True, message='已签到', data={'checkin_time': fmt_dt(existing.checkin_time, '%Y-%m-%d %H:%M:%S')})

    checkin = InspectionCheckin(
        inspection_plan_id=task_id,
        checkin_time=datetime.now(),
        location=data.get('location', plan.location or ''),
        remark=data.get('remark', ''),
    )
    db.session.add(checkin)
    plan.status = 'completed'
    db.session.commit()

    return jsonify(success=True, message='签到成功', data={
        'checkin_time': checkin.checkin_time.strftime('%Y-%m-%d %H:%M:%S'),
        'location': checkin.location,
    })


@feature_bp.route('/inspection/checkin-status/<int:task_id>', methods=['GET'])
@login_required
def inspection_checkin_status(task_id):
    """获取签到状态"""
    checkin = InspectionCheckin.query.filter_by(inspection_plan_id=task_id).first()
    if checkin:
        return jsonify(success=True, checked_in=True, data={
            'checkin_time': fmt_dt(checkin.checkin_time, '%Y-%m-%d %H:%M:%S'),
            'location': checkin.location or '',
            'remark': checkin.remark or '',
        })
    return jsonify(success=True, checked_in=False)


# ===================== 12. 运维大屏 (Feature 2) =====================

@feature_bp.route('/ops-screen', methods=['GET'])
def ops_screen():
    """运维大屏页面（无需登录，用于墙面展示）"""
    return render_template('feature/ops_screen.html')


@feature_bp.route('/ops-screen/data', methods=['GET'])
def ops_screen_data():
    """运维大屏数据 API（支持 hospital_id 参数）"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    hid = request.args.get('hospital_id', type=int)

    def _filter(q):
        """如果指定了 hospital_id，加到查询上"""
        if hid:
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
    if hid:
        avg_time_row = avg_time_row.filter(WorkOrder.hospital_id == hid)
    avg_hours = round(avg_time_row.scalar() or 0, 1)

    # SLA 达标率（已完成工单中，未超时的比例）
    # 注意：is_overdue 是 @property（内存计算），不能在 SQL 里过滤
    all_completed = _filter(WorkOrder.query.filter(
        WorkOrder.status == 'completed',
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
        WorkOrder.created_at >= today_start,
        WorkOrder.status.in_(['in_progress', 'completed']),
    )
    if hid:
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
        WorkOrder.created_at >= month_start,
    )
    if hid:
        grouped_workers_raw = grouped_workers_raw.filter(WorkOrder.hospital_id == hid)
    grouped_workers_raw = grouped_workers_raw.group_by(RoleGroup.name, WorkOrder.person).order_by(RoleGroup.name, func.count(WorkOrder.id).desc()).all()

    from collections import OrderedDict
    grouped_map = OrderedDict()
    for r in grouped_workers_raw:
        if r.group_name not in grouped_map:
            grouped_map[r.group_name] = []
        grouped_map[r.group_name].append({'name': r.person, 'count': r.cnt})
    grouped_workers_list = [{'group': g, 'workers': w} for g, w in grouped_map.items()]

    ops_display = SystemSetting.query.filter_by(key='ops_display_groups', hospital_id=1).first()
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


# ===================== 13. 院领导驾驶舱 (Feature 3) =====================

@feature_bp.route('/leadership-dashboard', methods=['GET'])
@login_required
def leadership_dashboard():
    """院领导驾驶舱页面"""
    return render_template('feature/leadership_dashboard.html')


@feature_bp.route('/leadership-dashboard/data', methods=['GET'])
@login_required
def leadership_dashboard_data():
    """院领导驾驶舱数据 API"""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # 本月工单
    month_orders = WorkOrder.query.filter(WorkOrder.created_at >= month_start)
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
    ).scalar()
    avg_response_hours = round((avg_response or 0) * 24, 1)

    # 超时率
    all_month_orders = WorkOrder.query.filter(WorkOrder.created_at >= month_start).all()
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
        WorkOrder.created_at >= twelve_months_ago
    ).group_by(func.strftime('%Y-%m', WorkOrder.created_at)).order_by('month').all()

    trend_labels = [r.month for r in monthly_trend]
    trend_values = [r.cnt for r in monthly_trend]

    # 优先级分布
    priority_data = db.session.query(
        WorkOrder.priority,
        func.count(WorkOrder.id).label('cnt')
    ).filter(
        WorkOrder.created_at >= month_start
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
    ).group_by(WorkOrder.fault_type).order_by(func.count(WorkOrder.id).desc()).limit(5).all()

    fault_labels = [r.fault_type for r in fault_data]
    fault_values = [r.cnt for r in fault_data]

    # 最近10条工单
    recent = WorkOrder.query.order_by(WorkOrder.created_at.desc()).limit(10).all()
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


# ===================== 15. 自定义报表 (Feature 5) =====================

@feature_bp.route('/report-builder', methods=['GET'])
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


@feature_bp.route('/report-builder/generate', methods=['POST'])
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


# ===================== 16. 短信通知 (Feature 6) =====================

def _send_sms(to_phone, content):
    """实际发送短信（调用配置的 API）"""
    sms_enabled = SystemSetting.query.filter_by(key='sms_enabled').first()
    if not sms_enabled or sms_enabled.value != '1':
        return False, '短信功能未启用'

    api_url = SystemSetting.query.filter_by(key='sms_api_url').first()
    api_key = SystemSetting.query.filter_by(key='sms_api_key').first()

    if not api_url or not api_url.value:
        return False, '未配置短信API地址'

    try:
        import requests
        resp = requests.post(
            api_url.value,
            json={
                'phone': to_phone,
                'content': content,
                'api_key': api_key.value if api_key else '',
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True, '发送成功'
        else:
            return False, f'API返回错误: {resp.status_code}'
    except Exception as e:
        return False, str(e)


@feature_bp.route('/sms/settings', methods=['GET'])
@login_required
def sms_settings():
    """短信配置页面"""
    settings = {}
    for s in SystemSetting.query.filter(
        SystemSetting.key.in_(['sms_enabled', 'sms_api_url', 'sms_api_key'])
    ).all():
        settings[s.key] = s.value

    logs = SmsLog.query.order_by(SmsLog.created_at.desc()).limit(50).all()
    return render_template('feature/sms_settings.html', settings=settings, logs=logs)


@feature_bp.route('/sms/settings/save', methods=['POST'])
@login_required
def sms_settings_save():
    """保存短信配置"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可修改'), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    for key in ['sms_enabled', 'sms_api_url', 'sms_api_key']:
        val = data.get(key, '')
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = val
        else:
            setting = SystemSetting(key=key, value=val, label=key, category='短信')
            db.session.add(setting)
    db.session.commit()

    return jsonify(success=True, message='短信配置已保存')


@feature_bp.route('/sms/send', methods=['POST'])
@login_required
def sms_send():
    """发送短信"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可发送'), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    to_phone = data.get('to_phone', '').strip()
    content = data.get('content', '').strip()

    if not to_phone or not content:
        return jsonify(success=False, error='手机号和内容不能为空'), 400

    success, msg = _send_sms(to_phone, content)
    log = SmsLog(
        to_phone=to_phone,
        content=content,
        status='sent' if success else 'failed',
        error_msg='' if success else msg,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify(success=success, message=msg, log_id=log.id)


@feature_bp.route('/sms/test', methods=['POST'])
@login_required
def sms_test():
    """测试短信发送"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可测试'), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    to_phone = data.get('to_phone', '').strip()
    if not to_phone:
        return jsonify(success=False, error='请输入测试手机号'), 400

    content = f'【测试】这是一条来自医院工单系统的测试短信，发送时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    success, msg = _send_sms(to_phone, content)
    log = SmsLog(
        to_phone=to_phone,
        content=content,
        status='sent' if success else 'failed',
        error_msg='' if success else msg,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify(success=success, message=msg if success else f'发送失败: {msg}')


# ===== 数字孪生 =====

@feature_bp.route('/digital-twin')
def digital_twin():
    """数字孪生页面"""
    return render_template('feature/digital_twin.html',
        user_is_admin=getattr(current_user, 'is_admin', False),
        user_is_auth=current_user.is_authenticated
    )


@feature_bp.route('/digital-twin-3d')
def digital_twin_3d():
    """3D数字孪生页面"""
    return render_template('feature/digital_twin_3d.html')


@feature_bp.route('/digital-twin/data')
def digital_twin_data():
    """获取建筑故障热力数据"""
    from sqlalchemy import text as sa_text

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

    rows = db.session.execute(sa_text(query), params).fetchall()
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

    pos_setting = SystemSetting.query.filter_by(key='digital_twin_positions').first()
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
    map_setting = SystemSetting.query.filter_by(key='digital_twin_map_url').first()
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


@feature_bp.route('/digital-twin/save-positions', methods=['POST'])
@login_required
def digital_twin_save_positions():
    """保存建筑位置"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    positions = data.get('positions', {})
    setting = SystemSetting.query.filter_by(key='digital_twin_positions').first()
    if not setting:
        setting = SystemSetting(key='digital_twin_positions', value='{}')
        db.session.add(setting)
    setting.value = json.dumps(positions, ensure_ascii=False)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/digital-twin/save-map', methods=['POST'])
@login_required
def digital_twin_save_map():
    """保存地图背景URL"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    map_url = data.get('map_url', '')
    setting = SystemSetting.query.filter_by(key='digital_twin_map_url').first()
    if not setting:
        setting = SystemSetting(key='digital_twin_map_url', value='')
        db.session.add(setting)
    setting.value = map_url
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/digital-twin/upload-map', methods=['POST'])
@login_required
def digital_twin_upload_map():
    """上传地图背景图片"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可操作'), 403

    if 'file' not in request.files:
        return jsonify(success=False, error='未选择文件'), 400
    file = request.files['file']
    if not file.filename:
        return jsonify(success=False, error='文件名为空'), 400

    ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED:
        return jsonify(success=False, error='仅支持 png/jpg/gif/webp/svg 格式'), 400

    import uuid
    filename = f'hospital_map_{uuid.uuid4().hex[:8]}.{ext}'
    upload_dir = '/var/www/static/hospital_maps'
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))

    old_setting = SystemSetting.query.filter_by(key='digital_twin_map_url').first()
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
    setting = old_setting or SystemSetting(key='digital_twin_map_url', value='')
    if not old_setting:
        db.session.add(setting)
    setting.value = map_url
    db.session.commit()

    return jsonify(success=True, map_url=map_url)


# ===== 在线建模编辑器接口 =====

@feature_bp.route('/digital-twin/model/<building_id>', methods=['GET'])
@login_required
def get_building_model(building_id):
    """获取建筑的建模数据"""
    setting = SystemSetting.query.filter_by(key=f'dt_model_{building_id}').first()
    if setting and setting.value:
        try:
            return jsonify(success=True, model=json.loads(setting.value))
        except:
            pass
    return jsonify(success=True, model={'elements': [], 'textures': {}})


@feature_bp.route('/digital-twin/model/<building_id>', methods=['POST'])
@login_required
def save_building_model(building_id):
    """保存建筑的建模数据"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可操作'), 403
    data = request.get_json(silent=True) or {}
    model = data.get('model', {})
    setting = SystemSetting.query.filter_by(key=f'dt_model_{building_id}').first()
    if not setting:
        setting = SystemSetting(key=f'dt_model_{building_id}', value='{}')
        db.session.add(setting)
    setting.value = json.dumps(model, ensure_ascii=False)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/digital-twin/upload-texture', methods=['POST'])
@login_required
def upload_dt_texture():
    """上传自定义贴图"""
    if not current_user.is_admin:
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
# ==================== 新功能路由 ====================

# ==== 1. 自动派单 + 超时催办 快捷开关 ====

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

@feature_bp.route('/auto-assign/check', methods=['POST'])
@login_required
def auto_assign_check():
    """自动派单检查：检查订单是否应自动分配"""
    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')
    if not order_id:
        return jsonify(success=False, error='缺少工单ID'), 400
    if _get_feature_toggle('auto_assign') != 'true':
        return jsonify(success=True, assigned=False, reason='自动派单未启用')
    
    order = db.session.get(WorkOrder, order_id)
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


@feature_bp.route('/timeout-reminder/check', methods=['POST'])
@login_required
def timeout_reminder_check():
    """超时催办检查：检查超时工单并推送"""
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
            send_wecom_notification(order)
            order.wecom_timeout_notified = True
            notified += 1
        except Exception as e:
            current_app.logger.error(f'超时催办通知失败: {e}')
    
    if notified > 0:
        db.session.commit()
    
    return jsonify(success=True, notified=notified)


@feature_bp.route('/feature-toggles', methods=['GET'])
@login_required
def get_feature_toggles():
    """获取所有功能开关状态"""
    return jsonify(success=True, toggles={
        'auto_assign': _get_feature_toggle('auto_assign'),
        'timeout_reminder': _get_feature_toggle('timeout_reminder'),
    })


@feature_bp.route('/feature-toggle/save', methods=['POST'])
@login_required
def save_feature_toggle():
    """保存功能开关"""
    if not current_user.is_admin:
        return jsonify(success=False, error='仅管理员可操作'), 403
    key = request.form.get('key', '')
    value = request.form.get('value', 'false')
    if key not in ('auto_assign', 'timeout_reminder'):
        return jsonify(success=False, error='无效的开关'), 400
    _set_feature_toggle(key, value)
    return jsonify(success=True)


# ==== 2. 交接班日志 ====

@feature_bp.route('/shift-handover', methods=['GET'])
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


@feature_bp.route('/shift-handover/save', methods=['POST'])
@login_required
def shift_handover_save():
    """保存交接班记录"""
    if not current_user.is_admin:
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
    handover = ShiftHandover(
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


@feature_bp.route('/shift-handover/<int:hid>', methods=['GET'])
@login_required
def shift_handover_detail(hid):
    """获取交接班记录详情"""
    h = db.session.get(ShiftHandover, hid)
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


# ==== 3. 维修评价 ====

@feature_bp.route('/repair-ratings', methods=['GET'])
@login_required
def repair_ratings():
    """维修评价列表页"""
    page = request.args.get('page', 1, type=int)
    rating_filter = request.args.get('rating', type=int)
    q = RepairRating.query.order_by(RepairRating.created_at.desc())
    if rating_filter:
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


@feature_bp.route('/repair-rating/save', methods=['POST'])
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
        rr = RepairRating(
            work_order_id=order_id,
            rating=rating,
            comment=comment,
            created_by=current_user.display_name or current_user.username,
        )
        db.session.add(rr)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/repair-rating/<int:oid>/detail', methods=['GET'])
@login_required
def repair_rating_detail(oid):
    """评价详情"""
    rr = RepairRating.query.filter_by(work_order_id=oid).first()
    if not rr:
        return jsonify(success=False, error='未找到评价'), 404
    wo = db.session.get(WorkOrder, oid)
    return jsonify(success=True, data={
        'id': rr.id,
        'order_id': rr.work_order_id,
        'order_title': wo.title if wo else '',
        'rating': rr.rating,
        'comment': rr.comment,
        'reviewer': rr.created_by,
        'created_at': fmt_dt(rr.created_at, '%Y-%m-%d %H:%M'),
    })


# ==== 4. 投诉管理 ====

@feature_bp.route('/complaints', methods=['GET'])
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


@feature_bp.route('/complaint/save', methods=['POST'])
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
        c = db.session.get(Complaint, cid)
        if not c:
            return jsonify(success=False, error='投诉不存在'), 404
        c.title = title
        c.description = description
        c.complainant = complainant
        c.department = department
    else:
        c = Complaint(title=title, description=description,
                      complainant=complainant, department=department)
        db.session.add(c)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/complaint/handle', methods=['POST'])
@login_required
def complaint_handle():
    """处理投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    handler = data.get('handler', '').strip()
    resolution = data.get('resolution', '').strip()
    new_status = data.get('status', 'processing')
    c = db.session.get(Complaint, cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.handler = handler or current_user.display_name or current_user.username
    c.resolution = resolution
    c.status = new_status
    if new_status == 'resolved':
        c.resolved_at = datetime.now()
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/complaint/close', methods=['POST'])
@login_required
def complaint_close():
    """关闭投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    c = db.session.get(Complaint, cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.status = 'closed'
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/complaint/reopen', methods=['POST'])
@login_required
def complaint_reopen():
    """重新打开投诉"""
    data = request.get_json(silent=True) or {}
    cid = data.get('id')
    c = db.session.get(Complaint, cid)
    if not c:
        return jsonify(success=False, error='投诉不存在'), 404
    c.status = 'processing'
    db.session.commit()
    return jsonify(success=True)


# ==== 5. 领用审批 ====

@feature_bp.route('/stock-requests', methods=['GET'])
@login_required
def stock_requests():
    """领用审批列表页"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    q = StockRequest.query.order_by(StockRequest.created_at.desc())
    if status_filter:
        q = q.filter(StockRequest.status == status_filter)
    pagination = q.paginate(page=page, per_page=20, error_out=False)
    requests = pagination.items
    parts = SparePart.query.order_by(SparePart.name).all()
    departments = [d.name for d in Department.query.filter(Department.is_active == True).order_by(Department.name).all()]
    stats = {
        'pending': StockRequest.query.filter_by(status='pending').count(),
        'approved': StockRequest.query.filter_by(status='approved').count(),
        'rejected': StockRequest.query.filter_by(status='rejected').count(),
        'total': StockRequest.query.count(),
    }
    return render_template('feature/stock_requests.html',
                           requests=requests,
                           requests_json=json.dumps([{
                               'id': r.id, 'applicant': r.applicant,
                               'department': r.department,
                               'items': r.items or [],
                               'reason': r.reason,
                               'status': r.status,
                               'approver': r.approver,
                               'created_at': fmt_dt(r.created_at, '%Y-%m-%d %H:%M'),
                               'approved_at': fmt_dt(r.approved_at, '%Y-%m-%d %H:%M'),
                           } for r in requests], ensure_ascii=False),
                           parts=parts,
                           parts_json=json.dumps([{
                               'id': p.id, 'name': p.name,
                               'model_no': p.model_no or '',
                               'quantity': p.stock or 0,
                               'unit': p.unit or '个',
                           } for p in parts], ensure_ascii=False),
                           departments=departments,
                           stats=stats)


@feature_bp.route('/stock-request/save', methods=['POST'])
@login_required
def stock_request_save():
    """保存领用申请"""
    data = request.get_json(silent=True) or {}
    applicant = data.get('applicant', '').strip()
    department = data.get('department', '').strip()
    reason = data.get('reason', '').strip()
    items = data.get('items', [])
    if not applicant or not items:
        return jsonify(success=False, error='申请人和领用备件不能为空'), 400
    sr = StockRequest(
        applicant=applicant,
        department=department,
        items=items,
        reason=reason,
    )
    db.session.add(sr)
    db.session.commit()
    return jsonify(success=True, id=sr.id)


@feature_bp.route('/stock-request/approve', methods=['POST'])
@login_required
def stock_request_approve():
    """审批通过领用申请"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    sr = db.session.get(StockRequest, rid)
    if not sr:
        return jsonify(success=False, error='申请不存在'), 404
    sr.status = 'approved'
    sr.approver = current_user.display_name or current_user.username
    sr.approved_at = datetime.now()
    # 自动扣减库存
    if sr.items:
        for item in sr.items:
            part_id = item.get('part_id')
            qty = item.get('quantity', 1)
            if part_id:
                part = db.session.get(SparePart, part_id)
                if part and part.stock:
                    part.stock = max(0, (part.stock or 0) - qty)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/stock-request/reject', methods=['POST'])
@login_required
def stock_request_reject():
    """拒绝领用申请"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    sr = db.session.get(StockRequest, rid)
    if not sr:
        return jsonify(success=False, error='申请不存在'), 404
    sr.status = 'rejected'
    sr.approver = current_user.display_name or current_user.username
    db.session.commit()
    return jsonify(success=True)


# ==== 6. 备件库存预警 ====

@feature_bp.route('/spare-part-alerts', methods=['GET'])
@login_required
def spare_part_alerts():
    """备件预警列表页"""
    alerts = SparePartAlert.query.order_by(SparePartAlert.id).all()
    stats = {
        'total': len(alerts),
        'triggered': sum(1 for a in alerts if a.enabled and a.part and (a.part.stock or 0) <= a.min_threshold),
        'normal': sum(1 for a in alerts if not a.enabled or not a.part or (a.part.stock or 0) > a.min_threshold),
        'disabled': sum(1 for a in alerts if not a.enabled),
    }
    return render_template('feature/spare_part_alerts.html',
                           alerts=alerts,
                           alerts_json=json.dumps([{
                               'id': a.id, 'part_id': a.part_id,
                               'part_name': a.part.name if a.part else '已删除',
                               'part_model': a.part.model_no if a.part else '',
                               'current_qty': a.part.stock if a.part else 0,
                               'min_threshold': a.min_threshold,
                               'enabled': a.enabled,
                               'last_notified': fmt_dt(a.last_notified_at, '%Y-%m-%d %H:%M'),
                               'status': 'triggered' if (a.enabled and a.part and (a.part.stock or 0) <= a.min_threshold)
                                        else 'normal' if a.enabled else 'disabled',
                           } for a in alerts], ensure_ascii=False),
                           parts=SparePart.query.order_by(SparePart.name).all(),
                           stats=stats)


@feature_bp.route('/spare-part-alert/save', methods=['POST'])
@login_required
def spare_part_alert_save():
    """保存预警配置"""
    data = request.get_json(silent=True) or {}
    aid = data.get('id')
    part_id = data.get('part_id')
    min_threshold = data.get('min_threshold', 5)
    enabled = data.get('enabled', True)
    if not part_id:
        return jsonify(success=False, error='请选择备件'), 400
    if aid:
        a = db.session.get(SparePartAlert, aid)
        if a:
            a.part_id = part_id
            a.min_threshold = min_threshold
            a.enabled = enabled
    else:
        existing = SparePartAlert.query.filter_by(part_id=part_id).first()
        if existing:
            existing.min_threshold = min_threshold
            existing.enabled = enabled
        else:
            a = SparePartAlert(part_id=part_id, min_threshold=min_threshold, enabled=enabled)
            db.session.add(a)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/spare-part-alert/toggle', methods=['POST'])
@login_required
def spare_part_alert_toggle():
    """切换预警开关"""
    data = request.get_json(silent=True) or {}
    aid = data.get('id')
    a = db.session.get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    a.enabled = not a.enabled
    db.session.commit()
    return jsonify(success=True, enabled=a.enabled)


@feature_bp.route('/spare-part-alert-get', methods=['GET'])
@login_required
def spare_part_alert_get():
    """获取单条预警配置"""
    aid = request.args.get('id', type=int)
    a = db.session.get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    return jsonify(success=True, data={
        'id': a.id, 'part_id': a.part_id,
        'part_name': a.part.name if a.part else '',
        'part_model': a.part.model_no if a.part else '',
        'current_qty': a.part.quantity if a.part else 0,
        'min_threshold': a.min_threshold, 'enabled': a.enabled,
    })


@feature_bp.route('/spare-part-alert/<int:aid>/delete', methods=['POST'])
@login_required
def spare_part_alert_delete(aid):
    """删除预警配置"""
    a = db.session.get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/spare-part-alert/check', methods=['GET'])
@login_required
def spare_part_alert_check():
    """检查所有预警并返回触发列表"""
    triggered = []
    alerts = SparePartAlert.query.filter_by(enabled=True).all()
    for a in alerts:
        part = a.part
        if part and (part.stock or 0) <= a.min_threshold:
            triggered.append({
                'id': a.id, 'part_id': part.id,
                'part_name': part.name,
                'current_qty': part.stock or 0,
                'min_threshold': a.min_threshold,
            })
    return jsonify(success=True, triggered=triggered, count=len(triggered))


# ==== 7. 巡检路线规划 ====

@feature_bp.route('/inspection-routes', methods=['GET'])
@login_required
def inspection_routes():
    """巡检路线列表页"""
    routes = InspectionRoute.query.order_by(InspectionRoute.created_at.desc()).all()
    buildings = sorted(set(
        r[0] for r in db.session.query(Department.building).filter(
            Department.building != '', Department.building.isnot(None)
        ).distinct().all()
    ))
    floors = sorted(set(
        r[0] for r in db.session.query(Department.floor).filter(
            Department.floor != '', Department.floor.isnot(None)
        ).distinct().all()
    ))
    departments = [d.name for d in Department.query.filter(Department.is_active == True).order_by(Department.name).all()]
    return render_template('feature/inspection_routes.html', routes=routes,
                           routes_json=json.dumps([{
                               'id': r.id, 'name': r.name,
                               'points': r.points or [],
                               'is_active': r.is_active,
                               'created_by': r.created_by,
                               'created_at': fmt_dt(r.created_at, '%Y-%m-%d %H:%M'),
                           } for r in routes], ensure_ascii=False),
                           buildings=buildings, floors=floors, departments=departments)


@feature_bp.route('/inspection-route/save', methods=['POST'])
@login_required
def inspection_route_save():
    """保存巡检路线"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    name = data.get('name', '').strip()
    points = data.get('points', [])
    if not name:
        return jsonify(success=False, error='路线名称不能为空'), 400
    if rid:
        r = db.session.get(InspectionRoute, rid)
        if r:
            r.name = name
            r.points = points
    else:
        r = InspectionRoute(name=name, points=points,
                            created_by=current_user.display_name or current_user.username)
        db.session.add(r)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/inspection-route/toggle', methods=['POST'])
@login_required
def inspection_route_toggle():
    """切换路线启用状态"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id') or data.get('rid')
    r = db.session.get(InspectionRoute, rid)
    if not r:
        return jsonify(success=False, error='路线不存在'), 404
    r.is_active = not r.is_active
    db.session.commit()
    return jsonify(success=True, active=r.is_active)


@feature_bp.route('/inspection-route/delete', methods=['POST'])
@login_required
def inspection_route_delete():
    """删除巡检路线"""
    rid = request.form.get('rid', type=int) or request.args.get('rid', type=int)
    r = db.session.get(InspectionRoute, rid)
    if not r:
        return jsonify(success=False, error='路线不存在'), 404
    db.session.delete(r)
    db.session.commit()
    return jsonify(success=True)


@feature_bp.route('/inspection-route/<int:rid>/data', methods=['GET'])
@login_required
def inspection_route_data(rid):
    """获取单条路线数据"""
    r = db.session.get(InspectionRoute, rid)
    if not r:
        return jsonify(success=False, error='路线不存在'), 404
    return jsonify(success=True, data={
        'id': r.id, 'name': r.name,
        'points': r.points or [],
        'is_active': r.is_active,
    })


# ==== 8. 维保日历 ====

@feature_bp.route('/maintenance-calendar', methods=['GET'])
@login_required
def maintenance_calendar():
    """维保日历页面"""
    now = datetime.now()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)
    contracts = MaintenanceContract.query.all()
    import calendar
    cal = calendar.monthcalendar(year, month)
    calendar_grid = []
    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append({'day': 0, 'is_today': False, 'other_month': True, 'contracts': []})
            else:
                date_str = f'{year}-{month:02d}-{day:02d}'
                is_today = (now.year == year and now.month == month and now.day == day)
                day_contracts = []
                for c in contracts:
                    if c.end_date:
                        flag = 'expired' if c.end_date < now.date() else ('expiring' if (c.end_date - now.date()).days <= 30 else 'active')
                        if c.end_date.month == month and c.end_date.year == year and c.end_date.day == day:
                            day_contracts.append({
                                'id': c.id, 'contract_name': c.contract_name,
                                'supplier_name': c.supplier.name if c.supplier else '',
                                'end_date': c.end_date.strftime('%Y-%m-%d'),
                                'status_flag': flag,
                            })
                week_data.append({
                    'day': day, 'date_str': date_str,
                    'is_today': is_today, 'other_month': False,
                    'contracts': day_contracts[:5],
                })
        calendar_grid.append(week_data)
    # 当月合同列表
    month_contracts = []
    for c in contracts:
        if c.end_date and c.end_date.month == month and c.end_date.year == year:
            flag = 'expired' if c.end_date < now.date() else ('expiring' if (c.end_date - now.date()).days <= 30 else 'active')
            month_contracts.append({
                'id': c.id, 'contract_name': c.contract_name,
                'contract_no': c.contract_no or '',
                'supplier_name': c.supplier.name if c.supplier else '',
                'end_date': c.end_date.strftime('%Y-%m-%d'),
                'status_flag': flag,
            })
    stats = {
        'active': sum(1 for c in contracts if c.end_date and c.end_date >= now.date()),
        'expiring': sum(1 for c in contracts if c.end_date and (c.end_date - now.date()).days <= 30 and c.end_date >= now.date()),
        'expired': sum(1 for c in contracts if c.end_date and c.end_date < now.date()),
        'total': len(contracts),
    }
    return render_template('feature/maintenance_calendar.html',
                           year=year, month=month,
                           years=list(range(now.year - 5, now.year + 3)),
                           stats=stats,
                           calendar_grid=calendar_grid,
                           month_contracts=month_contracts,
                           contracts_json=json.dumps([{
                               'id': c.id, 'contract_name': c.contract_name,
                               'contract_no': c.contract_no or '',
                               'supplier_name': c.supplier.name if c.supplier else '',
                               'start_date': fmt_date(c.start_date),
                               'end_date': fmt_date(c.end_date),
                               'contract_amount': str(c.contract_amount) if c.contract_amount else '',
                               'payment_type': c.payment_type or '',
                               'contact_person': c.contact_person or '',
                               'contact_phone': c.contact_phone or '',
                               'remark': c.remark or '',
                               'status_flag': 'expired' if (c.end_date and c.end_date < now.date())
                                              else 'expiring' if (c.end_date and (c.end_date - now.date()).days <= 30)
                                              else 'active',
                           } for c in contracts], ensure_ascii=False))


# ==== 9. 设备履历 ====

@feature_bp.route('/asset-lifecycle', methods=['GET'])
@login_required
def asset_lifecycle():
    """设备履历页面"""
    asset_id = request.args.get('asset_id', type=int)
    if not asset_id:
        asset_id = request.args.get('id', type=int)
    asset = db.session.get(Asset, asset_id) if asset_id else None
    if not asset:
        return render_template('errors/404.html'), 404
    logs = AssetLog.query.filter_by(asset_id=asset.id).order_by(AssetLog.created_at.desc()).all()
    # 关联的工单
    work_orders = WorkOrder.query.filter(
        WorkOrder.device_type == asset.device_type,
        WorkOrder.department == asset.department,
        WorkOrder.created_at >= (asset.purchase_date or date(2000, 1, 1))
    ).order_by(WorkOrder.created_at.desc()).limit(20).all()
    # 合并时间线
    timeline = []
    for log in logs:
        timeline.append({
            'type': log.action, 'time': log.created_at,
            'operator': log.operator,
            'detail': f"{log.old_value or ''} → {log.new_value or ''}" if log.old_value or log.new_value else '',
            'source': 'asset_log',
        })
    for wo in work_orders:
        timeline.append({
            'type': 'repair' if wo.status == 'completed' else ('pending' if wo.status == 'pending' else 'processing'),
            'time': wo.created_at,
            'operator': wo.person or wo.created_by,
            'detail': f"工单#{wo.id}: {wo.title} ({wo.status})",
            'source': 'work_order',
        })
    timeline.sort(key=lambda x: x['time'], reverse=True)
    return render_template('feature/asset_lifecycle.html',
                           asset=asset, timeline=timeline,
                           asset_logs=logs)


# ==== 10. AI知识库问答 ====

@feature_bp.route('/ai-kb-qa', methods=['GET'])
@login_required
def ai_kb_qa():
    """AI知识库问答页面 — 已合并到知识库页面"""
    return redirect(url_for('data.list_knowledge', tab='ai'))


@feature_bp.route('/ai-kb-search', methods=['POST'])
@login_required
def ai_kb_search():
    """AI知识库搜索"""
    data = request.get_json(silent=True) or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify(success=False, error='请输入搜索内容'), 400
    # 关键词匹配搜索
    solutions = SolutionTemplate.query.filter(
        (SolutionTemplate.title.ilike(f'%{query}%')) |
        (SolutionTemplate.content.ilike(f'%{query}%')) |
        (SolutionTemplate.keywords.ilike(f'%{query}%'))
    ).order_by(SolutionTemplate.updated_at.desc()).limit(10).all()
    result = []
    for s in solutions:
        # 简单置信度计算
        score = 0
        if query.lower() in s.title.lower():
            score += 30
        if s.keywords:
            kw_list = [k.strip() for k in s.keywords.split(',')]
            match_count = sum(1 for kw in kw_list if kw.lower() in query.lower())
            score += match_count * 15
        if query.lower() in s.content.lower():
            score += 20
        score = min(score, 99)
        if len(query) > 4:
            score = min(score + 10, 99)
        result.append({
            'id': s.id, 'title': s.title,
            'content': s.content[:300] + ('...' if len(s.content) > 300 else ''),
            'keywords': s.keywords,
            'device_type': s.device_type,
            'fault_type': s.fault_type,
            'confidence': score,
        })
    result.sort(key=lambda x: x['confidence'], reverse=True)
    summary = f'找到 {len(result)} 个相关解决方案'
    if result and result[0]['confidence'] > 60:
        summary = result[0]['title']
    return jsonify(success=True, solutions=result, summary=summary)


# ==== 11. 运维成本核算 ====

@feature_bp.route('/cost-accounting', methods=['GET'])
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


# ==== 12. 多院区协同 ====

@feature_bp.route('/multi-hospital-collab', methods=['GET'])
@login_required
def multi_hospital_collab():
    """多院区协同页面"""
    hospitals = []
    try:
        from models import Hospital
        hospitals = Hospital.query.filter_by(is_active=True).all()
    except Exception as e:
        current_app.logger.error(f'查询医院列表失败: {e}')
    # 跨医院工单（已转交过来的）
    cross_orders = WorkOrder.query.filter(
        WorkOrder.transfer_from_hospital.isnot(None),
        WorkOrder.transfer_from_hospital != ''
    ).order_by(WorkOrder.created_at.desc()).limit(50).all()
    return render_template('feature/multi_hospital_collab.html',
                           hospitals=hospitals, cross_orders=cross_orders)


# ==== 13. 运维周报月报 ====

@feature_bp.route('/report-auto', methods=['GET'])
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
