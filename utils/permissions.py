# utils/permissions.py
import json
from functools import wraps
from flask import jsonify, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_required


def _get_permission_defs():
    from models import PERMISSION_DEFINITIONS
    return PERMISSION_DEFINITIONS


def _get_role_permissions():
    from models import ROLE_PERMISSIONS
    return ROLE_PERMISSIONS


def _get_module_to_perm_map():
    from models import MODULE_TO_PERM_MAP
    return MODULE_TO_PERM_MAP


def has_permission(user, perm_key):
    """检查用户是否拥有指定操作级权限"""
    if not user:
        return False
    if user.is_admin:
        return True
    user_perms = json.loads(user.permissions or '{}')
    if perm_key in user_perms:
        return user_perms[perm_key]
    group_name = getattr(user, 'group', '普通用户')
    role_perms = _get_role_permissions().get(group_name, [])
    if role_perms == '*':
        return True
    if perm_key in role_perms:
        return True
    prefix = perm_key.split(':')[0] + ':*'
    if prefix in role_perms:
        return True
    # fallback: 自定义角色组不在 ROLE_PERMISSIONS 中时，回退到旧 module_permissions 系统
    if not role_perms and _get_role_permissions().get(group_name) is None:
        from models import get_module_permissions, get_group_name_by_id
        actual_group = get_group_name_by_id(user.group_id) or user.group or '普通用户'
        old_perms = get_module_permissions()
        old_group_perms = old_perms.get('groups', {}).get(actual_group, {})
        # 通过 MODULE_TO_PERM_MAP 将模块名映射为操作级权限
        module_map = _get_module_to_perm_map()
        # 反向查找：这个 perm_key 对应哪个模块名
        for module_name, mapped_perm in module_map.items():
            if mapped_perm == perm_key and old_group_perms.get(module_name, False):
                return True
        return False
    return False


def permission_required(perm_key):
    """Web 路由装饰器：要求指定操作级权限"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            if not has_permission(current_user, perm_key):
                flash(f'无权限执行此操作 (需要: {perm_key})', 'danger')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def api_permission_required(perm_key):
    """API 路由装饰器：要求指定操作级权限

    用法一（搭配 @login_required_api 使用，放在其下方）:
        @login_required_api
        @api_permission_required('order:create')
        def api_create_order(user): ...

    用法二（单独使用）:
        @api_permission_required('order:create')
        def some_api(): ...
        # 此时会自己解析 Authorization: Bearer <token>
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from models import User

            # 尝试获取 user：优先从 args[0]（搭配 login_required_api 时已传入）
            user = None
            if args and isinstance(args[0], User):
                user = args[0]
            else:
                # 单独使用：自己解析 token
                token = request.headers.get('Authorization', '').replace('Bearer ', '')
                if not token:
                    if request.is_json:
                        data = request.get_json(silent=True) or {}
                        token = data.get('token', '')
                    if not token:
                        token = request.args.get('token', '')
                if not token:
                    return jsonify({'error': '未登录', 'code': 401}), 401
                from models import MobileToken
                user = MobileToken.verify(token)
                if not user:
                    return jsonify({'error': 'token 无效或已过期', 'code': 401}), 401

            if not has_permission(user, perm_key):
                return jsonify({'error': f'无权限 (需要: {perm_key})', 'code': 403}), 403

            # 仅当 user 不在 args[0] 中时才注入 kwargs（兼容单独使用场景）
            user_from_args = args and isinstance(args[0], User)
            if not user_from_args and 'user' not in kwargs:
                kwargs['user'] = user
            return f(*args, **kwargs)
        return decorated
    return decorator
