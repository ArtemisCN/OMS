"""H5 仿小程序 SPA - 独立手机端界面（替代微信小程序用于浏览器调试）"""
from flask import Blueprint, render_template, jsonify, redirect, url_for
from flask_login import login_required, current_user
from models import MobileToken

miniapp_bp = Blueprint('miniapp', __name__, url_prefix='/miniapp')


@miniapp_bp.route('/')
@login_required
def index():
    """渲染 H5 仿小程序 SPA 页面"""
    return render_template('miniapp/index.html', user=current_user)


@miniapp_bp.route('/token')
@login_required
def get_token():
    """为当前登录用户生成 API Bearer Token（供 SPA 调用 /api/mobile/*）"""
    token_str = MobileToken.generate(current_user)
    return jsonify({'token': token_str})
