"""故障类型管理子蓝图（从 routes/data.py 提取）"""

from utils.csrf import csrf_protect
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db
from routes.auth import admin_required
from utils.permissions import permission_required
from services import data_service
from services.data_service import get_team_options
from utils.time_helpers import resolve_team

data_fault_bp = Blueprint('data_fault', __name__, url_prefix='/data/fault')


@data_fault_bp.route('/')
@permission_required("system:config")
def index():
    """故障类型列表页"""
    team = resolve_team(request, current_user)
    all_teams = get_team_options()
    return render_template('data/fault_types.html', types=data_service.list_fault_types(team=team),
                           team=team, all_teams=all_teams)


@data_fault_bp.route('/add', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def add():
    ok, msg = data_service.add_fault_type(
        request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_fault.index'))


@data_fault_bp.route('/<int:fid>/edit', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def edit(fid):
    ok, msg = data_service.edit_fault_type(
        fid, request.form.get('name', '').strip(),
        request.form.get('keywords', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_fault.index'))


@data_fault_bp.route('/<int:fid>/delete', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def delete(fid):
    name = data_service.delete_fault_type(fid, current_user.display_name or current_user.username)
    flash(f'故障类型「{name}」已删除', 'success')
    return redirect(url_for('data_fault.index'))
