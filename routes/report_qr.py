"""科室报修二维码 - 扫码报修系统"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from models import db, WorkOrder, Hospital, Department
from datetime import datetime
import io, os

scan_bp = Blueprint('scan', __name__, url_prefix='/scan')


@scan_bp.route('/')
def scan_index():
    """报修首页 - 选择医院"""
    hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
    return render_template('scan/index.html', hospitals=hospitals)


@scan_bp.route('/<int:hospital_id>')
def scan_department(hospital_id):
    """选科室页"""
    hospital = db.session.get(Hospital, hospital_id)
    if not hospital:
        return "医院不存在", 404
    # 获取该医院有工单的科室列表
    depts = db.session.query(WorkOrder.department).filter(
        WorkOrder.hospital_id == hospital_id,
        WorkOrder.department != '',
        WorkOrder.department.isnot(None),
    ).distinct().order_by(WorkOrder.department).all()
    departments = sorted(set(d[0] for d in depts if d[0]))
    return render_template('scan/department.html', hospital=hospital, departments=departments)


@scan_bp.route('/<int:hospital_id>/submit', methods=['GET', 'POST'])
def scan_submit(hospital_id):
    """提交报修"""
    hospital = db.session.get(Hospital, hospital_id)
    if not hospital:
        return "医院不存在", 404

    # 资产二维码扫码：取 asset_id 参数
    asset_id = request.args.get('asset_id', type=int)
    asset = None
    if asset_id:
        from models import Asset
        asset = db.session.get(Asset, asset_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        device_type = request.form.get('device_type', '其他').strip()

        if not name or not description:
            flash('请填写姓名和故障描述', 'danger')
            return render_template('scan/submit.html', hospital=hospital, departments=departments, asset=asset)

        order = WorkOrder(
            title=f'{department} {description[:30]}' if department else description[:50],
            device_type=device_type,
            fault_type='硬件',
            description=f'【扫码报修】报修人：{name}，电话：{phone}\n科室：{department} {location}\n故障：{description}',
            building='',
            floor='',
            department=department,
            location=location,
            status='pending',
            priority='normal',
            created_by=f'报修-{name}',
            hospital_id=hospital_id,
        )
        db.session.add(order)
        db.session.commit()

        # 推送通知
        try:
            from routes.api_mobile import send_new_order_notification
            send_new_order_notification(order)
        except Exception:
            pass

        return render_template('scan/success.html', order=order, hospital=hospital)

    # GET - 显示提交表单（科室从科室字典取）
    departments = Department.query.filter_by(
        hospital_id=hospital_id, is_active=True
    ).order_by(Department.sort_order, Department.name).all()
    return render_template('scan/submit.html', hospital=hospital, departments=departments, asset=asset)


@scan_bp.route('/qr/<int:hospital_id>')
@scan_bp.route('/qr/<int:hospital_id>/<path:department>')
def qr_page(hospital_id, department=None):
    """生成报修二维码页面"""
    hospital = db.session.get(Hospital, hospital_id)
    if not hospital:
        return "医院不存在", 404
    return render_template('scan/qr.html', hospital=hospital, department=department)


@scan_bp.route('/qr-image/<int:hospital_id>')
def qr_image(hospital_id):
    """生成报修二维码图片"""
    import qrcode
    hospital = db.session.get(Hospital, hospital_id)
    if not hospital:
        return "医院不存在", 404

    dept = request.args.get('department', '')
    base_url = request.host_url.rstrip('/')
    if dept:
        url = f'{base_url}/scan/{hospital_id}/submit?dept={dept}'
    else:
        url = f'{base_url}/scan/{hospital_id}/submit'

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')
