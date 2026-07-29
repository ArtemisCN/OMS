"""科室字典管理子蓝图（从 routes/data.py 提取）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db
from routes.auth import admin_required
from services import data_service

data_department_bp = Blueprint('data_department', __name__, url_prefix='/data/department')


@data_department_bp.route('/')
@admin_required
def index():
    """科室列表页"""
    return render_template('data/departments.html', departments=data_service.list_departments())


@data_department_bp.route('/add', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
def delete(id):
    ok, msg = data_service.delete_department(id, current_user.display_name or current_user.username)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_department.index'))
