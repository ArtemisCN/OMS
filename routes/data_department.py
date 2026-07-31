"""科室字典管理子蓝图（从 routes/data.py 提取）"""

from utils.csrf import csrf_protect
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db
from routes.auth import admin_required
from utils.permissions import permission_required
from services import data_service

data_department_bp = Blueprint('data_department', __name__, url_prefix='/data/department')


@data_department_bp.route('/')
@permission_required("system:config")
def index():
    """科室列表页"""
    return render_template('data/departments.html', departments=data_service.list_departments())


@data_department_bp.route('/add', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def add():
    ok, msg = data_service.add_department(
        request.form.get('name', '').strip(),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('phone', '').strip(),
        current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_department.index'))


@data_department_bp.route('/<int:id>/edit', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def edit(id):
    ok, msg = data_service.edit_department(
        id,
        request.form.get('name', '').strip(),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('phone', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_department.index'))


@data_department_bp.route('/<int:id>/delete', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def delete(id):
    ok, msg = data_service.delete_department(id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_department.index'))
