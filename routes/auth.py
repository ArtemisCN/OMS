"""认证相关路由"""
import secrets
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from utils.csrf import csrf_protect
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, AuditLog, RegistrationRequest, Hospital, RoleGroup
from datetime import datetime
from models import log_audit

# --- 创建认证蓝图，注册 /login 和 /logout 路由 ---
auth_bp = Blueprint('auth', __name__)


def generate_csrf_token():
    """生成并存储 CSRF token 到 session"""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validate_csrf():
    """验证 CSRF token，失败返回 False"""
    token = request.form.get('_csrf_token', '')
    stored = session.pop('_csrf_token', None)  # 一次性使用
    if not stored or not secrets.compare_digest(stored, token):
        return False
    return True


# 注册 CSRF 生成器为 Jinja2 全局函数
auth_bp.add_app_template_global(generate_csrf_token, '_csrf')



@auth_bp.route('/login', methods=['GET', 'POST'])
@csrf_protect
def login():
    """Web 登录页面
    ---
    tags:
      - Web 页面
    summary: 登录页面（GET 返回 HTML 表单，POST 提交登录）
    x-web-page: true
    parameters:
      - name: username
        in: formData
        type: string
        required: true
        description: 用户名
      - name: password
        in: formData
        type: string
        required: true
        description: 密码
    responses:
      200:
        description: 登录页面（GET）或登录成功重定向（POST）
      401:
        description: 登录失败
    """
    # --- 已认证用户直接跳转首页，无需重复登录 ---
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    # --- 处理 POST 登录提交 ---
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # --- 查询用户并检查锁定状态 ---
        from datetime import datetime, timedelta
        user = User.query.filter_by(username=username).first()
        if user and user.locked_until and user.locked_until > datetime.now():
            remaining = int((user.locked_until - datetime.now()).total_seconds() // 60)
            flash(f'账号已锁定，请{remaining}分钟后再试', 'danger')
            return render_template('login.html')
        # --- 校验密码 ---
        if user and user.check_password(password):
            # --- 登录成功，重置尝试次数 ---
            if user.login_attempts != 0 or user.locked_until is not None:
                user.login_attempts = 0
                user.locked_until = None
                db.session.commit()
            login_user(user)
            log_audit('login', 'user', user.display_name or user.username,
                      target_id=user.id, target_desc=f'用户登录: {user.username}')
            return redirect(url_for('main.dashboard'))
        # --- 密码错误，增加尝试次数（P1-2：99次→5次锁定15分钟） ---
        if user:
            user.login_attempts = (user.login_attempts or 0) + 1
            if user.login_attempts >= 5:
                user.locked_until = datetime.now() + timedelta(minutes=15)
                flash('密码错误次数过多，账号已锁定15分钟', 'danger')
            else:
                remaining = 5 - user.login_attempts
                flash(f'用户名或密码错误，还剩{remaining}次尝试机会', 'danger')
            db.session.commit()
        else:
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
        if not validate_csrf():
            flash('表单已过期，请重新提交', 'danger')
            return render_template('register.html', hospitals=hospitals, role_groups=role_groups, form=request.form)
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
        if not password or len(password) < 8:
            errors.append('密码至少8位')
        elif not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
            errors.append('密码必须同时包含字母和数字')
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
