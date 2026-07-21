"""认证相关路由"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from models import log_audit
from functools import wraps

# --- 创建认证蓝图，注册 /login 和 /logout 路由 ---
auth_bp = Blueprint('auth', __name__)


def admin_required(f):
    """管理员权限装饰器"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # --- 检查当前用户是否为管理员，非管理员重定向到首页 ---
        if not current_user.is_admin:
            flash('无权限访问，仅管理员可用', 'danger')
            return redirect(url_for('main.dashboard'))
        # --- 管理员用户正常放行 ---
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # --- 已认证用户直接跳转首页，无需重复登录 ---
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    # --- 处理 POST 登录提交 ---
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # --- 查询用户并校验密码 ---
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # --- 密码验证成功，执行登录并记录审计日志 ---
            login_user(user)
            log_audit('login', 'user', user.display_name or user.username,
                      target_id=user.id, target_desc=f'用户登录: {user.username}')
            return redirect(url_for('main.dashboard'))
        # --- 用户名或密码错误，提示用户 ---
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    # --- 退出当前用户登录，跳转到登录页 ---
    logout_user()
    return redirect(url_for('auth.login'))
