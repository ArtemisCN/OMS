"""Assets Blueprint: 资产二维码, 耗材用量预测, 备件→工单联动,
供应商管理, 设备折旧计算, 领用审批, 备件库存预警,
维保日历, 设备履历"""

from utils.csrf import csrf_protect

from utils.helpers import safe_get
import io
import json
import os
import calendar
from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, jsonify, request, send_file, Response, g
from flask_login import login_required, current_user
from sqlalchemy import func

from utils.time_helpers import fmt_dt, fmt_date
from models import (
    db, Asset, Consumable, ConsumableRecord, WorkOrder, StockRecord,
    SparePart, Supplier, StockRequest, Department, SparePartAlert,
    MaintenanceContract, AssetLog, User, FaultType, SolutionTemplate,
)

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')

QR_BASE_URL = 'https://demolin.cn/scan/1/submit?asset_id='


@assets_bp.route('/asset/search', methods=['GET'])
@login_required
def asset_search():
    """资产搜索 JSON API（供工单创建页面的资产选择器使用）"""
    q = request.args.get('q', '').strip()
    hid = getattr(g, 'hospital_id', 0)
    if not q:
        return jsonify(success=True, assets=[])
    query = Asset.query.filter(
        db.or_(
            Asset.asset_no.ilike(f'%{q}%'),
            Asset.brand.ilike(f'%{q}%'),
            Asset.model_no.ilike(f'%{q}%'),
            Asset.sn.ilike(f'%{q}%'),
            Asset.department.ilike(f'%{q}%'),
        )
    )
    if hid and hid != 0:
        query = query.filter(Asset.hospital_id == hid)
    assets = query.order_by(Asset.asset_no).limit(20).all()
    return jsonify(success=True, assets=[{
        'id': a.id,
        'asset_no': a.asset_no,
        'device_type': a.device_type or '',
        'brand': a.brand or '',
        'model_no': a.model_no or '',
        'department': a.department or '',
        'location': a.location or '',
    } for a in assets])


# ===================== 5. 资产二维码 =====================

@assets_bp.route('/asset/qr', methods=['GET'])
@login_required
def asset_qr():
    """资产二维码列表页面"""
    assets = Asset.query.order_by(Asset.asset_no).all()
    return render_template('feature/asset_qr.html', assets=assets,
                           qr_base_url=QR_BASE_URL)


@assets_bp.route('/asset/qr/<int:asset_id>', methods=['GET'])
@login_required
def asset_qr_image(asset_id):
    """生成单个资产二维码图片"""
    asset = safe_get(Asset, asset_id)
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


@assets_bp.route('/asset/qr/batch', methods=['POST'])
@csrf_protect
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

@assets_bp.route('/consumable/forecast', methods=['GET'])
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

@assets_bp.route('/stock/link_to_order', methods=['POST'])
@csrf_protect
@login_required
def stock_link_to_order():
    """备件出库并关联到工单"""
    part_id = request.form.get('part_id', type=int)
    work_order_id = request.form.get('work_order_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)
    note = request.form.get('note', '').strip()

    if not part_id or not work_order_id:
        return jsonify(success=False, error='参数不完整'), 400

    part = safe_get(SparePart, part_id)
    if not part:
        return jsonify(success=False, error='备件不存在'), 404

    work_order = safe_get(WorkOrder, work_order_id)
    if not work_order:
        return jsonify(success=False, error='工单不存在'), 404

    if part.stock < quantity:
        return jsonify(success=False, error=f'库存不足（当前 {part.stock}）'), 400

    # 扣减库存
    part.stock -= quantity

    record = StockRecord.new_with_hospital(
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

@assets_bp.route('/suppliers', methods=['GET'])
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


@assets_bp.route('/suppliers/save', methods=['POST'])
@csrf_protect
@login_required
def supplier_save():
    """创建/编辑供应商"""
    supplier_id = request.form.get('id', type=int)
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify(success=False, error='供应商名称不能为空'), 400

    if supplier_id:
        supplier = safe_get(Supplier, supplier_id)
        if not supplier:
            return jsonify(success=False, error='供应商不存在'), 404
    else:
        supplier = Supplier.new_with_hospital()

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


@assets_bp.route('/suppliers/<int:id>/delete', methods=['POST'])
@csrf_protect
@login_required
def supplier_delete(id):
    """删除供应商"""
    supplier = safe_get(Supplier, id)
    if not supplier:
        return jsonify(success=False, error='供应商不存在'), 404
    db.session.delete(supplier)
    db.session.commit()
    return jsonify(success=True, message='供应商已删除')


# ===================== 10. 设备折旧计算 =====================

@assets_bp.route('/asset/depreciation', methods=['GET'])
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


# ==== 5. 领用审批 ====

@assets_bp.route('/stock-requests', methods=['GET'])
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


@assets_bp.route('/stock-request/save', methods=['POST'])
@csrf_protect
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
    hid = getattr(g, 'hospital_id', None) or 1
    sr = StockRequest(
        applicant=applicant,
        department=department,
        items=items,
        reason=reason,
        hospital_id=hid,
    )
    db.session.add(sr)
    db.session.commit()
    return jsonify(success=True, id=sr.id)


@assets_bp.route('/stock-request/approve', methods=['POST'])
@csrf_protect
@login_required
def stock_request_approve():
    """审批通过领用申请"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    sr = safe_get(StockRequest, rid)
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
                part = safe_get(SparePart, part_id)
                if part and part.stock:
                    part.stock = max(0, (part.stock or 0) - qty)
    db.session.commit()
    return jsonify(success=True)


@assets_bp.route('/stock-request/reject', methods=['POST'])
@csrf_protect
@login_required
def stock_request_reject():
    """拒绝领用申请"""
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    sr = safe_get(StockRequest, rid)
    if not sr:
        return jsonify(success=False, error='申请不存在'), 404
    sr.status = 'rejected'
    sr.approver = current_user.display_name or current_user.username
    db.session.commit()
    return jsonify(success=True)


# ==== 6. 备件库存预警 ====

@assets_bp.route('/spare-part-alerts', methods=['GET'])
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


@assets_bp.route('/spare-part-alert/save', methods=['POST'])
@csrf_protect
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
        a = safe_get(SparePartAlert, aid)
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
            a = SparePartAlert(part_id=part_id, min_threshold=min_threshold, enabled=enabled, hospital_id=getattr(g, 'hospital_id', None) or 1)
            db.session.add(a)
    db.session.commit()
    return jsonify(success=True)


@assets_bp.route('/spare-part-alert/toggle', methods=['POST'])
@csrf_protect
@login_required
def spare_part_alert_toggle():
    """切换预警开关"""
    data = request.get_json(silent=True) or {}
    aid = data.get('id')
    a = safe_get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    a.enabled = not a.enabled
    db.session.commit()
    return jsonify(success=True, enabled=a.enabled)


@assets_bp.route('/spare-part-alert-get', methods=['GET'])
@login_required
def spare_part_alert_get():
    """获取单条预警配置"""
    aid = request.args.get('id', type=int)
    a = safe_get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    return jsonify(success=True, data={
        'id': a.id, 'part_id': a.part_id,
        'part_name': a.part.name if a.part else '',
        'part_model': a.part.model_no if a.part else '',
        'current_qty': a.part.quantity if a.part else 0,
        'min_threshold': a.min_threshold, 'enabled': a.enabled,
    })


@assets_bp.route('/spare-part-alert/<int:aid>/delete', methods=['POST'])
@csrf_protect
@login_required
def spare_part_alert_delete(aid):
    """删除预警配置"""
    a = safe_get(SparePartAlert, aid)
    if not a:
        return jsonify(success=False, error='预警配置不存在'), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify(success=True)


@assets_bp.route('/spare-part-alert/check', methods=['GET'])
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


# ==== 8. 维保日历 ====

@assets_bp.route('/maintenance-calendar', methods=['GET'])
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

@assets_bp.route('/asset-lifecycle', methods=['GET'])
@login_required
def asset_lifecycle():
    """设备履历页面"""
    hid = getattr(g, 'hospital_id', 0)
    asset_id = request.args.get('asset_id', type=int)
    asset_no = request.args.get('asset_no', '').strip()
    q = request.args.get('q', '').strip()

    asset = None
    # 按数据库ID查找
    if asset_id:
        asset = Asset.query.filter(Asset.id == asset_id).first()
    # 按资产编号查找
    if not asset and asset_no:
        asset = Asset.query.filter(Asset.asset_no == asset_no).first()
    if not asset and q:
        asset = Asset.query.filter(
            db.or_(
                Asset.asset_no.ilike(f'%{q}%'),
                Asset.brand.ilike(f'%{q}%'),
                Asset.model_no.ilike(f'%{q}%'),
                Asset.sn.ilike(f'%{q}%'),
                Asset.department.ilike(f'%{q}%'),
            )
        ).first()

    if not asset and (asset_id or asset_no or q):
        # 输入了但没找到 → 显示资产搜索列表
        query = Asset.query
        if hid and hid != 0:
            query = query.filter(Asset.hospital_id == hid)
        assets = query.order_by(Asset.asset_no).all()
        return render_template('feature/asset_lifecycle.html',
                               asset=None, timeline=[],
                               assets=assets, search_hint=asset_no or q)

    # 首次进入无输入 → 显示全部资产列表
    if not asset:
        query = Asset.query
        if hid and hid != 0:
            query = query.filter(Asset.hospital_id == hid)
        assets = query.order_by(Asset.asset_no).all()
        return render_template('feature/asset_lifecycle.html',
                               asset=None, timeline=[], asset_logs=[],
                               assets=assets, search_hint='')

    logs = AssetLog.query.filter(
        AssetLog.asset_id == asset.id,
        AssetLog.hospital_id == hid
    ).order_by(AssetLog.created_at.desc()).all()

    # 关联的工单（按 asset_id 直接匹配）
    work_orders = WorkOrder.query.filter(
        WorkOrder.asset_id == asset.id,
        WorkOrder.hospital_id == hid
    ).order_by(WorkOrder.created_at.desc()).all()

    # 如果没有直接关联的工单，回退：按标题中搜索资产编号
    if not work_orders and asset.asset_no:
        work_orders = WorkOrder.query.filter(
            WorkOrder.title.ilike(f'%{asset.asset_no}%'),
            WorkOrder.hospital_id == hid
        ).order_by(WorkOrder.created_at.desc()).limit(20).all()

    # 如果没有匹配到任何工单，最后按 device_type+department 匹配（旧数据兼容）
    if not work_orders:
        work_orders = WorkOrder.query.filter(
            WorkOrder.device_type == asset.device_type,
            WorkOrder.department == asset.department,
            WorkOrder.created_at >= (asset.purchase_date or date(2000, 1, 1)),
            WorkOrder.hospital_id == hid
        ).order_by(WorkOrder.created_at.desc()).limit(20).all()

    # 合并统一时间线
    timeline = []
    for log in logs:
        timeline.append({
            'action': log.action,
            'time': log.created_at,
            'created_at': log.created_at,  # 兼容模板 log.created_at
            'operator': log.operator,
            'old_value': log.old_value,
            'new_value': log.new_value,
            'source': 'asset_log',
        })
    for wo in work_orders:
        # 判断是维修还是巡检
        action = 'inspection' if wo.work_type == 'inspection' else 'repair'
        new_val = {
            'id': wo.id,
            'title': wo.title,
            'status': wo.status,
            'person': wo.person or '',
            'department': wo.department or '',
        }
        if action == 'repair':
            new_val['fault_desc'] = wo.title
            new_val['repair_result'] = wo.solution or ''
        else:
            new_val['result'] = wo.solution or '已完成'
            # 如果有 inspection_data，取出来做详细备注
            if wo.inspection_data:
                if isinstance(wo.inspection_data, dict):
                    items = wo.inspection_data.get('items', [])
                    if items:
                        passed = sum(1 for i in items if i.get('passed'))
                        new_val['notes'] = f"巡检项 {passed}/{len(items)} 通过"
        timeline.append({
            'action': action,
            'time': wo.created_at,
            'created_at': wo.created_at,  # 兼容模板 log.created_at
            'operator': wo.person or wo.created_by or '系统',
            'old_value': '',
            'new_value': json.dumps(new_val, ensure_ascii=False),
            'source': 'work_order',
        })

    timeline.sort(key=lambda x: x['time'], reverse=True)
    return render_template('feature/asset_lifecycle.html',
                           asset=asset, timeline=timeline,
                           assets=[], search_hint='')


@assets_bp.route('/api/asset-lifecycle/<int:asset_id>')
@login_required
def api_asset_lifecycle(asset_id):
    """设备履历 JSON API（供资产台账页面模态框使用）"""
    hid = getattr(g, 'hospital_id', 0)
    asset = Asset.query.filter(Asset.id == asset_id).first()
    if not asset:
        return jsonify(success=False, error='资产不存在'), 404

    logs = AssetLog.query.filter(
        AssetLog.asset_id == asset.id,
    )
    if hid and hid != 0:
        logs = logs.filter(AssetLog.hospital_id == hid)
    logs = logs.order_by(AssetLog.created_at.desc()).all()

    work_orders = WorkOrder.query.filter(
        WorkOrder.asset_id == asset.id,
    )
    if hid and hid != 0:
        work_orders = work_orders.filter(WorkOrder.hospital_id == hid)
    work_orders = work_orders.order_by(WorkOrder.created_at.desc()).all()

    if not work_orders and asset.asset_no:
        work_orders = WorkOrder.query.filter(
            WorkOrder.title.ilike(f'%{asset.asset_no}%'),
        )
        if hid and hid != 0:
            work_orders = work_orders.filter(WorkOrder.hospital_id == hid)
        work_orders = work_orders.order_by(WorkOrder.created_at.desc()).limit(20).all()

    timeline = []
    for log in logs:
        timeline.append({
            'action': log.action,
            'time': log.created_at.isoformat() if log.created_at else '',
            'operator': log.operator or '',
            'old_value': log.old_value or '',
            'new_value': log.new_value or '',
            'source': 'asset_log',
        })
    for wo in work_orders:
        action = 'inspection' if wo.work_type == 'inspection' else 'repair'
        new_val = {
            'id': wo.id,
            'title': wo.title,
            'status': wo.status,
            'person': wo.person or '',
            'department': wo.department or '',
        }
        if action == 'repair':
            new_val['fault_desc'] = wo.title
            new_val['repair_result'] = wo.solution or ''
        else:
            new_val['result'] = wo.solution or '已完成'
        timeline.append({
            'action': action,
            'time': wo.created_at.isoformat() if wo.created_at else '',
            'operator': wo.person or wo.created_by or '系统',
            'old_value': '',
            'new_value': json.dumps(new_val, ensure_ascii=False),
            'source': 'work_order',
        })

    timeline.sort(key=lambda x: x['time'], reverse=True)

    asset_data = {
        'id': asset.id,
        'asset_no': asset.asset_no,
        'brand': asset.brand or '',
        'model_no': asset.model_no or '',
        'sn': asset.sn or '',
        'department': asset.department or '',
        'building': asset.building or '',
        'floor': asset.floor or '',
        'location': asset.location or '',
        'status': asset.status or '',
        'device_type': asset.device_type or '',
        'purchase_date': fmt_date(asset.purchase_date),
        'warranty_end': fmt_date(asset.warranty_end),
        'category': asset.category or '',
        'financial_code': asset.financial_code or '',
        'cpu': asset.cpu or '',
        'memory': asset.memory or '',
        'disk_size': asset.disk_size or '',
        'ip_address': asset.ip_address or '',
    }

    return jsonify(success=True, data={
        'asset': asset_data,
        'timeline': timeline,
    })
