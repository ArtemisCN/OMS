"""Contracts Blueprint: 合同维保管理"""

from utils.csrf import csrf_protect

from utils.helpers import safe_get
import json
from datetime import datetime, date

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from sqlalchemy import func

from models import db, MaintenanceContract, Supplier, Asset

contracts_bp = Blueprint('contracts', __name__, url_prefix='/contracts')


@contracts_bp.route('/', methods=['GET'])
@login_required
def contract_list():
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


@contracts_bp.route('/save', methods=['POST'])
@csrf_protect
@login_required
def contract_save():
    """创建/编辑合同"""
    contract_id = request.form.get('id', type=int)
    contract_name = request.form.get('contract_name', '').strip()
    if not contract_name:
        return jsonify(success=False, error='合同名称不能为空'), 400

    if contract_id:
        contract = safe_get(MaintenanceContract, contract_id)
        if not contract:
            return jsonify(success=False, error='合同不存在'), 404
    else:
        contract = MaintenanceContract.new_with_hospital()

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


@contracts_bp.route('/<int:id>/delete', methods=['POST'])
@csrf_protect
@login_required
def contract_delete(id):
    """删除合同"""
    contract = safe_get(MaintenanceContract, id)
    if not contract:
        return jsonify(success=False, error='合同不存在'), 404
    db.session.delete(contract)
    db.session.commit()
    return jsonify(success=True, message='合同已删除')
