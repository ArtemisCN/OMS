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
    """生成 API Token
    ---
    tags:
      - Mobile API
    summary: 生成 API Bearer Token
    description: 为当前 Web 登录用户生成 /api/mobile/* 接口的 Bearer Token
    responses:
      200:
        description: Token
        schema:
          type: object
          properties:
            token:
              type: string
    """
    token_str = MobileToken.generate(current_user)
    return jsonify({'token': token_str})
