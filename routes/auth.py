"""认证相关路由"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, AuditLog, RegistrationRequest, Hospital, RoleGroup
from datetime import datetime
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


@auth_bp.route('/api/user-brief')
def api_user_brief():
    """返回用户名对应的显示名称（供登录页保存账号用）"""
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({'error': 'no username'}), 400
    user = User.query.filter_by(username=username).first()
    if user:
        return jsonify({'username': user.username, 'display_name': user.display_name or user.username})
    return jsonify({'error': 'not found'}), 404


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册页面"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
    role_groups = RoleGroup.query.order_by(RoleGroup.id).all()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        display_name = request.form.get('display_name', '').strip()
        phone = request.form.get('phone', '').strip()
        hospital_id = request.form.get('hospital_id', type=int)
        group_id = request.form.get('group_id', type=int)
        reason = request.form.get('reason', '').strip()
        errors = []
        if not username or len(username) < 2:
            errors.append('用户名至少2位')
        if User.query.filter_by(username=username).first():
            errors.append('用户名已被占用')
        if not password or len(password) < 4:
            errors.append('密码至少4位')
        if password != confirm:
            errors.append('两次密码不一致')
        if not display_name:
            errors.append('请输入姓名')
        existing = RegistrationRequest.query.filter_by(username=username).first()
        if existing and existing.status == 'pending':
            errors.append('该用户名已有待审批的注册申请')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('register.html', hospitals=hospitals, role_groups=role_groups, form=request.form)
        # 如果有已拒绝的旧申请，删除它以便重新申请
        if existing and existing.status == 'rejected':
            db.session.delete(existing)
            db.session.flush()
        req = RegistrationRequest(
            username=username,
            display_name=display_name,
            phone=phone,
            hospital_id=hospital_id,
            group_id=group_id,
            reason=reason,
        )
        req.set_password(password)
        try:
            db.session.add(req)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('注册失败，用户名可能已被占用，请重试', 'danger')
            return render_template('register.html', hospitals=hospitals, role_groups=role_groups, form=request.form)
        log_audit('register_apply', 'registration', username,
                  target_id=req.id, target_desc=f'注册申请: {username}')
        flash('注册申请已提交，请等待管理员审批', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html', hospitals=hospitals, role_groups=role_groups, form={})
