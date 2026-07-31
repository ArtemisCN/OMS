"""CSRF 防护工具

背景：项目原仅有注册表单的 CSRF 校验（routes/auth.py 的 validate_csrf，一次性 token）。
本模块提供通用的非一次性 token 校验装饰器，覆盖关键 POST 路由。

token 机制（与 auth.py 的 generate_csrf_token 共用 session['_csrf_token']）：
- GET 页面渲染时经 context_processor 的 csrf_token() 生成并写入 session
- base.js 全局注入：所有 form 自动加 hidden input + fetch 自动加 X-CSRF-Token header
- csrf_protect 装饰器校验请求携带的 token 与 session 中一致

注意：
- 非一次性（不 pop）：token 在会话期间有效，攻击者无法获得受害者 session
- 与 auth.py 的 validate_csrf（一次性 pop，仅注册用）并存，互不干扰
- API 路由（api_mobile / global_dashboard）不走本装饰器——token 认证 + JSON 天然防护
"""
from functools import wraps
import secrets
from flask import session, request, abort


def generate_csrf_token():
    """生成 CSRF token 并存入 session（存在则复用）"""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def get_csrf_token():
    """获取当前会话 CSRF token（模板全局函数用）"""
    return generate_csrf_token()


def csrf_protect(f):
    """CSRF 校验装饰器：POST/PUT/DELETE 请求必须携带有效 token

    用法：
        @csrf_protect
        @orders_bp.route('/create', methods=['POST'])
        def create_order(): ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = (request.form.get('_csrf_token')
                     or request.headers.get('X-CSRF-Token')
                     or request.headers.get('X-Csrf-Token'))
            if not token or token != session.get('_csrf_token'):
                abort(403, 'CSRF token 无效，请刷新页面后重试')
        return f(*args, **kwargs)
    return decorated
