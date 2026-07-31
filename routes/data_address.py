"""地址覆盖管理子蓝图（从 routes/data.py 提取）"""

from utils.csrf import csrf_protect
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db
from utils.permissions import permission_required
from services import data_service
from services.data_service import get_team_options
from utils.time_helpers import resolve_team

data_address_bp = Blueprint('data_address', __name__, url_prefix='/data/address')


@data_address_bp.route('/')
@permission_required("system:config")
def index():
    """地址数据页"""
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


@data_address_bp.route('/edit', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def edit():
    ok, msg = data_service.edit_address(
        request.form.get('override_id', type=int),
        request.form.get('base_index', type=int),
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_address.index', building=request.form.get('building', '')))


@data_address_bp.route('/add', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def add():
    ok, msg = data_service.add_address(
        request.form.get('building', '').strip(),
        request.form.get('floor', '').strip(),
        request.form.get('department', '').strip(),
        request.form.get('location', '').strip(),
        teams=request.form.get('teams', '').strip())
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_address.index', building=request.form.get('building', '')))


@data_address_bp.route('/<int:oid>/delete', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def delete(oid):
    building = data_service.delete_address(oid)
    flash('地址已删除', 'success')
    return redirect(url_for('data_address.index', building=building))


@data_address_bp.route('/delete-base', methods=['POST'])
@csrf_protect
@permission_required("system:config")
def delete_base():
    ok, msg = data_service.delete_base_address(
        request.form.get('base_index', type=int),
        request.form.get('building', ''))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('data_address.index', building=request.form.get('building', '')))
