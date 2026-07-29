"""微信小程序 REST API - 手机端工单接单功能"""
import threading
import time
import urllib.request
import json as pyjson
from collections import defaultdict
from flask import Blueprint, request, jsonify, current_app
from models import db, User, WorkOrder, MobileToken, SubscribeUser, PaperForm, SystemSetting, WorkOrderTransferLog, WorkOrderPhoto, InventoryTask, InventoryItem, Asset, Exam, ExamQuestion, ExamSubmission
import random
from datetime import datetime, date
from sqlalchemy import func, case
from utils.time_helpers import fmt_dt

api_mobile_bp = Blueprint('api_mobile', __name__, url_prefix='/api/mobile')

# ===== 内存限流器（无外部依赖） =====
_rate_limit_lock = threading.Lock()
_rate_limit_store = defaultdict(list)  # key: "ip:endpoint" → [timestamp, ...]

def rate_limit(max_requests=5, window=60):
    """API 限流装饰器：每个 IP + 端点，window 秒内最多 max_requests 次"""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or '127.0.0.1'
            endpoint = request.path
            key = f'{ip}:{endpoint}'
            now = time.time()
            cutoff = now - window
            with _rate_limit_lock:
                timestamps = _rate_limit_store.get(key, [])
                # 清理过期记录
                timestamps = [t for t in timestamps if t > cutoff]
                if len(timestamps) >= max_requests:
                    retry_after = int(window - (now - timestamps[0]))
                    return jsonify({
                        'error': f'请求过于频繁，请 {retry_after} 秒后重试',
                        'code': 429,
                        'retry_after': retry_after
                    }), 429, {'Retry-After': str(retry_after)}
                timestamps.append(now)
                _rate_limit_store[key] = timestamps
            return f(*args, **kwargs)
        return wrapper
    return decorator

DEFAULT_AVATARS = [
    # 卡通人物
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Kitty&backgroundColor=b6e3f4',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Max&backgroundColor=ffd5dc',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Luna&backgroundColor=c0aede',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Charlie&backgroundColor=d1d4f9',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Molly&backgroundColor=ffdfbf',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Cooper&backgroundColor=fecaca',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Daisy&backgroundColor=bbf7d0',
    'https://api.dicebear.com/9.x/adventurer/svg?seed=Buddy&backgroundColor=fde68a',
    # 猫咪
    'https://api.dicebear.com/9.x/cat/svg?seed=Whiskers&backgroundColor=b6e3f4',
    'https://api.dicebear.com/9.x/cat/svg?seed=Mittens&backgroundColor=ffd5dc',
    'https://api.dicebear.com/9.x/cat/svg?seed=Snowball&backgroundColor=c0aede',
    'https://api.dicebear.com/9.x/cat/svg?seed=Oreo&backgroundColor=d1d4f9',
    'https://api.dicebear.com/9.x/cat/svg?seed=Simba&backgroundColor=ffdfbf',
    'https://api.dicebear.com/9.x/cat/svg?seed=Tiger&backgroundColor=fecaca',
    'https://api.dicebear.com/9.x/cat/svg?seed=Pumpkin&backgroundColor=bbf7d0',
    'https://api.dicebear.com/9.x/cat/svg?seed=Pepper&backgroundColor=fde68a',
]



def login_required_api(f):
    """API 认证装饰器：从 Authorization header 提取 token"""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import g
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': '未提供认证令牌', 'code': 401}), 401
        token_str = auth[7:]
        user = MobileToken.verify(token_str)
        if not user:
            return jsonify({'error': '令牌无效或已过期', 'code': 401}), 401
        assigned = user.get_assigned_hospitals()
        if user.is_admin:
            # 管理员：取第一个关联医院，没有则 None
            g.hospital_id = assigned[0].id if assigned else None
        elif len(assigned) > 1:
            # 多医院用户：小程序不设过滤，看到所有分配医院的数据
            g.hospital_id = None
        elif len(assigned) == 1:
            # 单医院用户（含 hospital_id=None 但有 user_hospitals 关联）：取该医院
            g.hospital_id = assigned[0].id
        else:
            # 无医院关联
            g.hospital_id = getattr(user, 'hospital_id', None)
        return f(user, *args, **kwargs)
    return decorated


import qrcode
from io import BytesIO
from flask import send_file
from utils.time_helpers import fmt_dt, now, fmt_date


@api_mobile_bp.route('/qr')
def generate_qr():
    data = request.args.get('data', '')
    size = request.args.get('size', 200, type=int)
    if not data:
        return 'missing data', 400
    size = max(28, min(600, size))
    qr = qrcode.QRCode(box_size=2, border=1)
    qr.add_data(data)
    img = qr.make_image(fill_color='black', back_color='white')
    img = img.resize((size, size))
    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', max_age=86400)


@api_mobile_bp.route('/login', methods=['POST'])
@rate_limit(max_requests=5, window=60)
def api_login():
    """用户登录（密码），返回 token"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码', 'code': 400}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'error': '用户名或密码错误', 'code': 401}), 401

    MobileToken.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    token = MobileToken.generate(user)

    return jsonify({
        'token': token.token,
        'user': {
            'id': user.id,
            'username': user.username,
            'display_name': user.display_name or user.username,
            'wx_bound': bool(user.wx_openid),
            'is_admin': user.is_admin,
            'avatar': user.avatar or '',
        }
    })




@api_mobile_bp.route('/avatars')
def list_avatars():
    """获取默认头像列表"""
    return jsonify({'avatars': DEFAULT_AVATARS})


@api_mobile_bp.route('/avatar/select', methods=['POST'])
@login_required_api
def select_avatar(user):
    """选择头像"""
    data = request.get_json(silent=True) or {}
    avatar = data.get('avatar', '').strip()
    if not avatar:
        return jsonify({'error': '缺少头像URL'}), 400
    user.avatar = avatar
    db.session.commit()
    return jsonify({'ok': True, 'avatar': avatar})

@api_mobile_bp.route('/wx_login', methods=['POST'])
@rate_limit(max_requests=5, window=60)
def wx_login():
    """微信自动登录：通过 wx.login code 换取 openid
    需先在 config.py 配置 WECHAT_APPID 和 WECHAT_SECRET
    """
    import urllib.request, json as pyjson
    from flask import current_app

    appid = current_app.config.get('WECHAT_APPID', '')
    secret = current_app.config.get('WECHAT_SECRET', '')

    if not appid or not secret:
        return jsonify({'error': '未配置微信登录', 'code': 400}), 400

    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'error': '缺少微信登录凭证', 'code': 400}), 400

    wx_url = f'https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code'
    try:
        req = urllib.request.Request(wx_url)
        resp = urllib.request.urlopen(req, timeout=5)
        wx_resp = pyjson.loads(resp.read().decode())
    except Exception as e:
        return jsonify({'error': '微信登录失败', 'detail': str(e), 'code': 502}), 502

    openid = wx_resp.get('openid', '')
    if not openid:
        err_msg = wx_resp.get('errmsg', '未知错误')
        return jsonify({'error': f'微信登录失败: {err_msg}', 'code': 401}), 401

    # 查找绑定了该 openid 的用户
    user = User.query.filter_by(wx_openid=openid).first()
    if not user:
        return jsonify({
            'error': '该微信号未绑定账号，请先使用密码登录并绑定',
            'code': 404,
            'openid': openid,  # 返回给小程序以便绑定
        }), 404

    MobileToken.query.filter_by(user_id=user.id).delete()
    token = MobileToken.generate(user)

    return jsonify({
        'token': token.token,
        'user': {
            'id': user.id,
            'username': user.username,
            'display_name': user.display_name or user.username,
            'wx_bound': True,
            'is_admin': user.is_admin,
        }
    })


@api_mobile_bp.route('/bind_wx', methods=['POST'])
@login_required_api
def bind_wx(user):
    """绑定微信号到当前用户"""
    import urllib.request, json as pyjson
    from flask import current_app

    appid = current_app.config.get('WECHAT_APPID', '')
    secret = current_app.config.get('WECHAT_SECRET', '')

    if not appid or not secret:
        return jsonify({'error': '未配置微信绑定功能', 'code': 400}), 400

    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'error': '缺少微信登录凭证', 'code': 400}), 400

    wx_url = f'https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code'
    try:
        req = urllib.request.Request(wx_url)
        resp = urllib.request.urlopen(req, timeout=5)
        wx_resp = pyjson.loads(resp.read().decode())
    except Exception as e:
        return jsonify({'error': '微信绑定失败', 'detail': str(e), 'code': 502}), 502

    openid = wx_resp.get('openid', '')
    if not openid:
        err_msg = wx_resp.get('errmsg', '未知错误')
        return jsonify({'error': f'微信绑定失败: {err_msg}', 'code': 401}), 401

    existing = User.query.filter(User.wx_openid == openid, User.id != user.id).first()
    if existing:
        return jsonify({'error': '该微信号已绑定其他账号', 'code': 409}), 409

    user.wx_openid = openid
    db.session.commit()

    return jsonify({'message': '微信绑定成功', 'wx_bound': True})


@api_mobile_bp.route('/profile')
@login_required_api
def profile(user):
    """获取当前用户信息"""
    return jsonify({
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'is_admin': user.is_admin,
    })


@api_mobile_bp.route('/orders')
@login_required_api
def orders(user):
    """获取工单列表

    规则：
    - status=pending  → 显示全部待接单工单（公共池）
    - status=in_progress  → 显示当前用户处理中的工单
    - status=completed  → 显示当前用户已完成的工单
    - status=completed_today  → 显示当前用户当天完成的工单
    - 不传 status  → 返回全部统计数据（供标签页显示数量）
    """
    person_name = user.display_name or user.username
    status_filter = request.args.get('status', '')
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if status_filter == 'pending':
        query = WorkOrder.query.filter_by(status='pending')
        # 公共池只显示用户可访问医院的工单
        hospital_ids = user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
    elif status_filter == 'in_progress':
        query = WorkOrder.query.filter_by(
            person=person_name,
            status='in_progress'
        )
        hospital_ids = user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
    elif status_filter == 'completed':
        query = WorkOrder.query.filter_by(
            person=person_name,
            status='completed'
        )
        hospital_ids = user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
    elif status_filter == 'completed_today':
        query = WorkOrder.query.filter(
            WorkOrder.person == person_name,
            WorkOrder.status == 'completed',
            WorkOrder.completed_at >= today_start
        )
        hospital_ids = user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
    else:
        # 不传 status → 只返回统计数据，不返回工单列表
        query = WorkOrder.query.filter(
            WorkOrder.person == person_name,
            WorkOrder.status.in_(['in_progress', 'completed'])
        )
        hospital_ids = user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))

    from sqlalchemy import case
    priority_order = case(
        (WorkOrder.priority == 'emergency', 0),
        (WorkOrder.priority == 'urgent', 1),
        else_=2
    )
    orders_list = query.order_by(priority_order, WorkOrder.created_at.desc()).all()

    result = {
        'orders': [{
            'id': o.id,
            'title': o.title,
            'device_type': o.device_type,
            'fault_type': o.fault_type,
            'fault_subcategory': o.fault_subcategory or '',
            'building': o.building,
            'floor': o.floor,
            'department': o.department,
            'person': o.person,
            'status': o.status,
            'priority': o.priority,
            'original_priority': o.original_priority,
            'work_type': o.work_type or 'normal',
            'created_at': fmt_dt(o.created_at),
        } for o in orders_list]
    }

    # 附加统计数据（一次查询完成4项统计，全部按医院过滤）
    from sqlalchemy import and_
    hospital_ids = user.get_assigned_hospital_ids()
    base_filter = []
    if hospital_ids:
        base_filter.append(WorkOrder.hospital_id.in_(hospital_ids))

    pending_filter = [WorkOrder.status == 'pending'] + base_filter
    in_progress_filter = [and_(WorkOrder.status == 'in_progress', WorkOrder.person == person_name)] + base_filter
    completed_filter = [and_(WorkOrder.status == 'completed', WorkOrder.person == person_name)] + base_filter
    completed_today_filter = [and_(
        WorkOrder.status == 'completed',
        WorkOrder.person == person_name,
        WorkOrder.completed_at >= today_start
    )] + base_filter

    stats_row = db.session.query(
        func.count(case(tuple(pending_filter), else_=None)).label('pending'),
        func.count(case(tuple(in_progress_filter), else_=None)).label('in_progress'),
        func.count(case(tuple(completed_filter), else_=None)).label('completed'),
        func.count(case(tuple(completed_today_filter), else_=None)).label('completed_today'),
    ).first()
    result['stats'] = {
        'pending': stats_row.pending or 0,
        'in_progress': stats_row.in_progress or 0,
        'completed': stats_row.completed or 0,
        'completed_today': stats_row.completed_today or 0,
    }

    return jsonify(result)


@api_mobile_bp.route('/orders/<int:order_id>')
@login_required_api
def order_detail(user, order_id):
    """获取工单详情（含关联电子表单）"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    result = {
        'order': {
            'id': order.id,
            'title': order.title,
            'description': order.description or order.title,
            'device_type': order.device_type,
            'fault_type': order.fault_type,
            'fault_subcategory': order.fault_subcategory or '',
            'building': order.building,
            'floor': order.floor,
            'department': order.department,
            'location': order.location,
            'person': order.person,
            'solution': order.solution or '',
            'status': order.status,
            'priority': order.priority,
            'work_type': order.work_type or 'normal',
            'inspection_data': order.inspection_data or None,
            'created_at': fmt_dt(order.created_at),
            'accepted_at': fmt_dt(order.accepted_at),
            'completed_at': fmt_dt(order.completed_at),
            'start_time': fmt_dt(order.start_time),
        }
    }

    # 附加关联的电子表单
    form = PaperForm.query.filter_by(work_order_id=order.id).first()
    if form:
        fd = form.to_dict()
        # 加上模板字段定义
        if form.template:
            fd['fields_json'] = form.template.fields_json or []
            fd['template_name'] = form.template.name
        else:
            fd['fields_json'] = []
        result['form'] = fd

    return jsonify(result)


@api_mobile_bp.route('/orders/<int:order_id>/accept', methods=['POST'])
@login_required_api
def accept_order(user, order_id):
    """接单：pending → in_progress

    从公共池接单，自动将 person 设置为当前用户
    """
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    if order.status != 'pending':
        return jsonify({'error': f'当前状态({order.status})不允许接单', 'code': 400}), 400

    hospital_ids = user.get_assigned_hospital_ids()
    if hospital_ids and order.hospital_id not in hospital_ids:
        return jsonify({'error': '无权接此医院的工单', 'code': 403}), 403

    # 如果已有人接单但状态还是 pending（数据异常），允许覆盖
    person_name = user.display_name or user.username
    order.status = 'in_progress'
    order.person = person_name  # 接单即认领
    order.accepted_at = datetime.now()
    db.session.commit()

    return jsonify({'message': '接单成功', 'status': 'in_progress'})


@api_mobile_bp.route('/orders/<int:order_id>/solve', methods=['POST'])
@login_required_api
def solve_order(user, order_id):
    """提交解决方案：in_progress → completed（表单工单请提交表单审批）"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    # 只有接单的人才能提交完成
    person_name = user.display_name or user.username
    if order.person != person_name:
        return jsonify({'error': '这不是你接的工单，无权完成', 'code': 403}), 403

    if order.status != 'in_progress':
        return jsonify({'error': f'当前状态({order.status})不允许提交完成', 'code': 400}), 400

    # 表单工单：不允许直接完结，必须通过电子表单提交审批
    form = PaperForm.query.filter_by(work_order_id=order.id).first()
    if form:
        return jsonify({'error': '此工单关联电子表单，请填写表单并提交审批', 'code': 400, 'form_id': form.id}), 400

    data = request.get_json(silent=True) or {}
    solution = data.get('solution', '').strip()
    if not solution:
        return jsonify({'error': '请填写解决方案', 'code': 400}), 400

    order.solution = solution
    order.status = 'completed'
    order.completed_at = datetime.now()
    db.session.commit()

    return jsonify({'message': '工单已完成', 'status': 'completed'})


@api_mobile_bp.route('/orders/<int:order_id>/inspection_submit', methods=['POST'])
@login_required_api
def submit_inspection(user, order_id):
    """提交巡检结果"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    if order.work_type != 'inspection':
        return jsonify({'error': '不是巡检工单', 'code': 400}), 400

    person_name = user.display_name or user.username
    if order.person != person_name:
        return jsonify({'error': '无权操作', 'code': 403}), 403

    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': '请完成巡检项', 'code': 400}), 400

    order.inspection_data = {
        'template_name': order.inspection_data.get('template_name', '巡检'),
        'items': items,
        'signature': data.get('signature', ''),
    }
    order.status = 'completed'
    order.completed_at = datetime.now()
    order.solution = '巡检完成'
    db.session.commit()

    return jsonify({'message': '巡检已完成', 'status': 'completed'})


@api_mobile_bp.route('/templates/match')
@login_required_api
def match_template(user):
    """根据标题模糊匹配方案模板（供小程序一键结单用）"""
    from services.matcher import get_solution_by_title
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'template': None})
    content = get_solution_by_title(title)
    if content:
        return jsonify({'template': {'title': title, 'content': content}})
    return jsonify({'template': None})


@api_mobile_bp.route('/logout', methods=['POST'])
@login_required_api
def logout(user):
    """退出登录，清除 token"""
    auth = request.headers.get('Authorization', '')
    token_str = auth[7:] if auth.startswith('Bearer ') else ''
    MobileToken.query.filter_by(token=token_str).delete()
    db.session.commit()
    return jsonify({'message': '已退出登录'})


# ==================== 订阅通知 ====================

@api_mobile_bp.route('/subscribe', methods=['POST'])
@login_required_api
def subscribe(user):
    """订阅新工单通知"""
    data = request.get_json(silent=True) or {}
    template_id = data.get('template_id', '').strip()
    if not template_id:
        return jsonify({'error': '缺少 template_id', 'code': 400}), 400

    # 需要有 openid 才能推送
    if not user.wx_openid:
        return jsonify({'error': '未绑定微信，无法订阅', 'code': 400}), 400

    # 保存订阅记录
    existing = SubscribeUser.query.filter_by(user_id=user.id).first()
    if existing:
        return jsonify({'message': '已订阅', 'subscribed': True})

    sub = SubscribeUser(user_id=user.id, openid=user.wx_openid)
    db.session.add(sub)
    db.session.commit()
    return jsonify({'message': '订阅成功', 'subscribed': True})


@api_mobile_bp.route('/subscribe/status')
@login_required_api
def subscribe_status(user):
    """查询当前用户的订阅状态"""
    existing = SubscribeUser.query.filter_by(user_id=user.id).first()
    return jsonify({'subscribed': bool(existing)})


@api_mobile_bp.route('/subscribe', methods=['DELETE'])
@login_required_api
def unsubscribe(user):
    """取消订阅"""
    SubscribeUser.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify({'message': '已取消订阅', 'subscribed': False})


def send_new_order_notification(order):
    """新工单发布时推送微信订阅消息给所有已订阅用户"""
    from flask import current_app
    import urllib.request, json as pyjson
    appid = current_app.config.get('WECHAT_APPID', '')
    secret = current_app.config.get('WECHAT_SECRET', '')
    template_id = current_app.config.get('WECHAT_TEMPLATE_ID', '')

    if not appid or not secret or not template_id:
        print('[NOTIFY] WECHAT_APPID/SECRET/TEMPLATE_ID 未配置', flush=True)
        return

    token_url = f'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}'
    try:
        req = urllib.request.Request(token_url)
        resp = urllib.request.urlopen(req, timeout=5)
        token_resp = pyjson.loads(resp.read().decode())
        access_token = token_resp.get('access_token', '')
        if not access_token:
            print(f'[NOTIFY] 获取 access_token 失败: {token_resp}', flush=True)
            return
    except Exception as e:
        print(f'[NOTIFY] 请求 access_token 异常: {e}', flush=True)
        return

    # 遍历所有订阅用户推送（后台线程，不阻塞工单发布）
    subscribers = SubscribeUser.query.limit(500).all()
    if not subscribers:
        print('[NOTIFY] 无订阅用户，跳过', flush=True)
        return

    print(f'[NOTIFY] 开始推送订阅通知: order_id={order.id}, subscribers={len(subscribers)}', flush=True)

    # 预先计算推送内容（闭包捕获）
    push_title = order.title[:20] if order.title else ''
    push_time = fmt_dt(order.created_at, '%Y-%m-%d %H:%M')
    push_note = f"{order.building} {order.department} · {order.device_type}"[:20]

    def _do_push(app):
        """后台线程推送（需要传入 app 实例以获取应用上下文）"""
        with app.app_context():
            success = 0
            for sub in subscribers:
                push_data = {
                    'touser': sub.openid,
                    'template_id': template_id,
                    'data': {
                        'thing1': {'value': push_title},
                        'time2': {'value': push_time},
                        'thing5': {'value': push_note},
                    }
                }
                push_url = f'https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}'
                try:
                    req = urllib.request.Request(push_url, data=pyjson.dumps(push_data).encode(), headers={'Content-Type': 'application/json'})
                    resp = urllib.request.urlopen(req, timeout=5)
                    result = pyjson.loads(resp.read().decode())
                    if result.get('errcode') == 0:
                        success += 1
                        print(f'[NOTIFY] 推送成功 user_id={sub.user_id}', flush=True)
                        # 一次性订阅已消耗，自动移除
                        db.session.delete(sub)
                        db.session.commit()
                    else:
                        print(f'[NOTIFY] 推送失败 user_id={sub.user_id} errcode={result.get("errcode")} errmsg={result.get("errmsg")}', flush=True)
                        # 40001=token失效, 43101=用户拒收/取消订阅 -> 移除订阅
                        if result.get('errcode') in (40001, 43101):
                            db.session.delete(sub)
                            db.session.commit()
                            print(f'[NOTIFY] 已移除失效订阅 user_id={sub.user_id}', flush=True)
                except Exception as e:
                    print(f'[NOTIFY] 推送异常 user_id={sub.user_id}: {e}', flush=True)
            print(f'[NOTIFY] 推送完成: order_id={order.id}, 成功={success}/{len(subscribers)}', flush=True)

    import threading
    app = current_app._get_current_object()
    t = threading.Thread(target=_do_push, args=(app,), daemon=True)
    t.start()


def send_wecom_notification(order, skip_time_check=False, is_urge=False):
    """企业微信群机器人推送工单通知（非阻塞）。is_urge=True 时使用催办加急模板"""
    import urllib.request, json as pyjson
    from flask import current_app
    from datetime import datetime

    hid = getattr(order, 'hospital_id', None) or 1

    # ====== 检查该医院是否启用了推送 ======
    enabled_setting = SystemSetting.query.filter_by(key='wecom_push_enabled', hospital_id=hid).first()
    if enabled_setting and enabled_setting.value == '0':
        print(f'[WECOM] 跳过推送 order_id={order.id} 医院#{hid} 已关闭推送', flush=True)
        return

    webhook_url = current_app.config.get('WECOM_WEBHOOK_URL', '')
    if not webhook_url:
        setting = SystemSetting.query.filter_by(key='wecom_webhook_url', hospital_id=hid).first()
        webhook_url = setting.value if setting else ''

    if not webhook_url:
        return

    # ====== 推送时间检查 ======
    now = datetime.now()
    schedule_setting = SystemSetting.query.filter_by(key='wecom_push_schedule', hospital_id=hid).first()
    schedule = schedule_setting.value if schedule_setting else 'all'
    if not skip_time_check and schedule == "workday" and now.weekday() >= 5:  # 5=周六 6=周日
        print(f'[WECOM] 跳过推送 order_id={order.id} 非工作日', flush=True)
        return

    ts_setting = SystemSetting.query.filter_by(key='wecom_push_time_start', hospital_id=hid).first()
    te_setting = SystemSetting.query.filter_by(key='wecom_push_time_end', hospital_id=hid).first()
    t_start = ts_setting.value if ts_setting else '08:00'
    t_end = te_setting.value if te_setting else '18:00'
    try:
        h_start, m_start = map(int, t_start.split(':'))
        h_end, m_end = map(int, t_end.split(':'))
        current_minutes = now.hour * 60 + now.minute
        start_minutes = h_start * 60 + m_start
        end_minutes = h_end * 60 + m_end
        if not skip_time_check and not (start_minutes <= current_minutes <= end_minutes):
            print(f'[WECOM] 跳过推送 order_id={order.id} 当前时间 {now.hour:02d}:{now.minute:02d} 不在推送时段 {t_start}-{t_end}', flush=True)
            return
    except (ValueError, TypeError):
        pass  # 格式异常时继续推送

    # ====== 构建推送内容 ======
    title = order.title[:40] if order.title else '未命名工单'
    building = order.building or '未指定'
    department = order.department or '未指定'
    created_at = fmt_dt(order.created_at, '%Y-%m-%d %H:%M')
    pri_label = {'normal': '普通', 'urgent': '加急', 'emergency': '紧急'}.get(order.priority, '普通')

    if is_urge:
        # ====== 催办加急模板 ======
        # 尝试从设置读取自定义催办模板（支持变量替换）
        urge_template_setting = SystemSetting.query.filter_by(key='wecom_push_template_urge', hospital_id=hid).first()
        if urge_template_setting and urge_template_setting.value:
            try:
                content = urge_template_setting.value.format(
                    title=title,
                    priority=order.priority or 'normal',
                    pri_label=pri_label,
                    building=building,
                    department=department,
                    created_at=created_at,
                )
            except (KeyError, ValueError):
                content = urge_template_setting.value
                print(f'[WECOM] warning: urge template has invalid placeholders, sending raw', flush=True)
        else:
            content = "## 🚨 工单催办通知\n" \
                      f"> **工单名称：**{title}\n" \
                      f"> **紧急程度：**{pri_label}\n" \
                      f"> **楼区：**{building}\n" \
                      f"> **科室：**{department}\n" \
                      f"> **发布时间：**{created_at}\n" \
                      f"> **状态：**待处理 ⏰ 请尽快安排人员处理！"
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
    else:
        # ====== 新工单通知模板 ======
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": "## 🔧 新工单通知\n"
                           f"> **工单名称：**{title}\n"
                           f"> **楼区：**{building}\n"
                           f"> **科室：**{department}\n"
                           f"> **发布时间：**{created_at}\n"
                           f"> **状态：**待接单"
            }
        }

    def _do_push(url, data):
        try:
            req = urllib.request.Request(url, data=pyjson.dumps(data).encode(), headers={'Content-Type': 'application/json'})
            resp = urllib.request.urlopen(req, timeout=5)
            result = pyjson.loads(resp.read().decode())
            if result.get('errcode') == 0:
                print(f'[WECOM] 推送成功 order_id={order.id}', flush=True)
            else:
                ec = result.get('errcode')
                em = result.get('errmsg')
                print(f'[WECOM] 推送失败 order_id={order.id} errcode={ec} errmsg={em}', flush=True)
        except Exception as e:
            print(f'[WECOM] 推送异常 order_id={order.id}: {e}', flush=True)

    import threading
    t = threading.Thread(target=_do_push, args=(webhook_url, payload), daemon=True)
    t.start()


# ==================== 电子表单手机端API ====================

@api_mobile_bp.route('/forms')
@login_required_api
def form_list_api(user):
    """获取当前用户相关表单列表"""
    person_name = user.display_name or user.username
    forms = PaperForm.query.filter(
        PaperForm.created_by == person_name
    ).order_by(PaperForm.updated_at.desc()).all()
    return jsonify({
        'forms': [f.to_dict() for f in forms]
    })


@api_mobile_bp.route('/forms/<int:fid>')
@login_required_api
def form_detail_api(user, fid):
    """获取表单详情（含模板字段定义）"""
    form = PaperForm.query.get(fid)
    if not form:
        return jsonify({'error': '表单不存在', 'code': 404}), 404
    fd = form.to_dict()
    if form.template:
        fd['fields_json'] = form.template.fields_json or []
    else:
        fd['fields_json'] = []
    return jsonify(fd)


@api_mobile_bp.route('/forms/<int:fid>/save', methods=['POST'])
@login_required_api
def form_save_api(user, fid):
    """保存表单字段值（手机端编辑）"""
    form = PaperForm.query.get(fid)
    if not form:
        return jsonify({'error': '表单不存在', 'code': 404}), 404
    if form.status != 'active':
        return jsonify({'error': '当前状态不允许修改', 'code': 400}), 400

    data = request.get_json(silent=True) or {}
    field_data = data.get('form_data', {})
    current = form.form_data or {}
    current.update(field_data)
    form.form_data = current
    db.session.commit()
    return jsonify({'message': '已保存'})


@api_mobile_bp.route('/forms/<int:fid>/sign', methods=['POST'])
@login_required_api
def form_sign_api(user, fid):
    """手机端手写签名"""
    form = PaperForm.query.get(fid)
    if not form:
        return jsonify({'error': '表单不存在', 'code': 404}), 404
    if form.status != 'active':
        return jsonify({'error': '当前状态不允许签名', 'code': 400}), 400

    data = request.get_json(silent=True) or {}
    field_id = data.get('field_id', '')
    signature_data = data.get('signature', '')
    if not field_id or not signature_data:
        return jsonify({'error': '参数不完整', 'code': 400}), 400

    fd = form.form_data or {}
    fd[field_id] = signature_data
    form.form_data = fd
    db.session.commit()
    return jsonify({'message': '签名已保存'})


@api_mobile_bp.route('/forms/<int:fid>/submit', methods=['POST'])
@login_required_api
def form_submit_api(user, fid):
    """手机端提交表单：active → submitted，等待审批"""
    form = PaperForm.query.get(fid)
    if not form:
        return jsonify({'error': '表单不存在', 'code': 404}), 404
    if form.status not in ('active', 'submitted'):
        return jsonify({'error': f'当前状态({form.status})不允许提交审批', 'code': 400}), 400

    form.status = 'submitted'
    form.updated_at = datetime.now()
    db.session.commit()
    return jsonify({'message': '已提交审批', 'status': 'submitted'})


@api_mobile_bp.route('/forms/<int:fid>/approve', methods=['POST'])
@login_required_api
def form_approve_api(user, fid):
    """审批通过表单：submitted → completed，同时完结关联工单"""
    form = PaperForm.query.get(fid)
    if not form:
        return jsonify({'error': '表单不存在', 'code': 404}), 404
    if form.status != 'submitted':
        return jsonify({'error': f'当前状态({form.status})不允许审批', 'code': 400}), 400

    form.status = 'completed'
    form.updated_at = datetime.now()

    # 完结关联工单
    if form.work_order_id:
        wo = WorkOrder.query.get(form.work_order_id)
        if wo and wo.status in ('in_progress', 'submitted'):
            wo.status = 'completed'
            wo.completed_at = datetime.now()
            wo.solution = f'电子表单已审批通过: {form.name}'
    db.session.commit()
    return jsonify({'message': '审批通过', 'status': 'completed'})


@api_mobile_bp.route('/forms/api/data-sources')
@login_required_api
def api_data_sources(user):
    """代理：将小程序的数据源请求转发到 forms 蓝图的数据源接口"""
    try:
        from routes.forms import form_data_sources
        resp = form_data_sources()
        return resp if isinstance(resp, tuple) else (resp, 200)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_mobile_bp.route('/orders/today-summary')
@login_required_api
def today_summary(user):
    """获取今日工作总结文本（已完成工单汇总），一键复制到剪贴板"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    person_name = user.display_name or user.username

    orders = WorkOrder.query.filter(
        WorkOrder.person == person_name,
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= today_start
    ).order_by(WorkOrder.completed_at.asc()).all()

    today = fmt_date(date.today())
    priority_map = {'normal': '普通', 'urgent': '加急', 'emergency': '紧急'}
    lines = [f'{today} 工作总结', f'员工：{person_name}', '']
    lines.append(f'今日完成工单：{len(orders)} 项')
    lines.append('')

    for i, o in enumerate(orders, 1):
        pri = priority_map.get(o.priority, '普通')
        time_str = fmt_dt(o.completed_at, '%H:%M')
        lines.append(f'{i}. [{pri}]{o.title}')
        parts = []
        if o.building: parts.append(o.building)
        if o.department: parts.append(o.department)
        loc = ' '.join(parts) if parts else '未指定'
        lines.append(f'   位置：{loc} | 类型：{o.fault_type or "未分类"}{" > " + o.fault_subcategory if o.fault_subcategory else ""}')
        lines.append(f'   完成时间：{time_str}')
        if o.solution:
            lines.append(f'   方案：{o.solution.strip()[:80]}')
        lines.append('')

    summary = '\n'.join(lines)
    return jsonify({'summary': summary, 'count': len(orders)})


@api_mobile_bp.route('/orders/<int:order_id>/transfers')
@login_required_api
def order_transfers(user, order_id):
    """获取工单流转记录"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404
    logs = WorkOrderTransferLog.query.filter_by(
        work_order_id=order.id
    ).order_by(WorkOrderTransferLog.created_at.desc()).all()
    return jsonify({
        'transfers': [{
            'id': log.id,
            'action': log.action,
            'from_person': log.from_person or '',
            'to_person': log.to_person or '',
            'operator_name': log.operator_name,
            'remark': log.remark or '',
            'created_at': fmt_dt(log.created_at),
        } for log in logs]
    })


@api_mobile_bp.route('/orders/<int:order_id>/return', methods=['POST'])
@login_required_api
def return_order(user, order_id):
    """退回到未接单"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404
    if order.status != 'in_progress':
        return jsonify({'error': '当前状态不允许退回', 'code': 400}), 400
    person_name = user.display_name or user.username
    if order.person != person_name:
        return jsonify({'error': '这不是你接的工单，无权退回', 'code': 403}), 403

    old_person = order.person
    order.status = 'pending'
    order.person = ''
    log = WorkOrderTransferLog(
        work_order_id=order.id,
        action='return',
        from_person=old_person,
        operator_name=person_name,
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({'message': '已退回至待接单', 'status': 'pending'})


@api_mobile_bp.route('/orders/<int:order_id>/transfer', methods=['POST'])
@login_required_api
def transfer_order(user, order_id):
    """转派工单给其他人"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404
    if order.status != 'in_progress':
        return jsonify({'error': '当前状态不允许转派', 'code': 400}), 400
    person_name = user.display_name or user.username
    if order.person != person_name:
        return jsonify({'error': '这不是你接的工单，无权转派', 'code': 403}), 403

    data = request.get_json(silent=True) or {}
    to_person = data.get('to_person', '').strip()
    if not to_person:
        return jsonify({'error': '请指定转派目标人', 'code': 400}), 400
    if to_person == person_name:
        return jsonify({'error': '不能转派给自己', 'code': 400}), 400

    old_person = order.person
    order.person = to_person
    log = WorkOrderTransferLog(
        work_order_id=order.id,
        action='transfer',
        from_person=old_person,
        to_person=to_person,
        operator_name=person_name,
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({'message': f'已转派给 {to_person}', 'status': 'in_progress'})


@api_mobile_bp.route('/orders/<int:order_id>/personnel')
@login_required_api
def order_personnel(user, order_id):
    """获取当前医院同组可选转派人选（排除当前接单人）"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    person_name = user.display_name or user.username
    hospital_id = order.hospital_id

    my_user = User.query.filter_by(id=user.id).first()
    my_team = my_user.team if my_user and my_user.team else None

    # 查询同医院同组且激活的人员（如果用户没有组，则查同医院所有激活人员）
    query = User.query.filter(
        User.hospital_id == hospital_id,
        User.is_active == True,
    )
    if my_team:
        query = query.filter(User.team == my_team)

    persons = query.order_by(User.sort_order, User.display_name).all()
    result = []
    seen = set()
    for p in persons:
        name = p.display_name
        if name == person_name or name in seen or not name:
            continue
        seen.add(name)
        result.append(name)

    return jsonify({'personnel': result})


@api_mobile_bp.route('/orders/create', methods=['POST'])
@login_required_api
def api_create_order(user):
    """小程序/手机端发布工单"""
    from services.address import extract_address_from_title
    from services.matcher import guess_fault_type, guess_device_type
    from services.fault_matcher import match_fault
    from datetime import datetime

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': '请输入工单名称', 'code': 400}), 400

    auto_fault = guess_fault_type(title)
    auto_device = guess_device_type(title)
    fm = match_fault(title)
    auto_fault = fm['category'] if fm['match_type'] == 'keyword' else auto_fault
    addr = extract_address_from_title(title)

    building = data.get('building', '') or addr['building']
    floor = data.get('floor', '') or addr['floor']
    department = data.get('department', '') or addr['department']
    location = data.get('location', '') or addr.get('location', '')
    now = datetime.now()
    priority = data.get('priority', 'normal')

    order = WorkOrder.new_with_hospital(
        title=title,
        device_type=auto_device,
        fault_type=auto_fault,
        fault_subcategory=data.get('fault_subcategory', '') or fm.get('subcategory', ''),
        description='',
        building=building,
        floor=floor,
        department=department,
        location=location,
        person='',
        solution='',
        start_time=now,
        status='pending',
        created_by=user.display_name or user.username,
        priority=priority,
        original_priority=priority,
    )
    db.session.add(order)
    db.session.commit()

    # 推送通知
    try:
        send_new_order_notification(order)
        send_wecom_notification(order)
    except Exception as e:
        current_app.logger.error(f'推送通知失败: {e}')

    return jsonify({
        'ok': True,
        'message': '工单已发布',
        'order': {'id': order.id, 'title': order.title},
    })


@api_mobile_bp.route('/guess')
@login_required_api
def api_guess(user):
    """小程序端自动识别工单标题"""
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({})

    from flask import g
    from services.address import extract_address_from_title
    from services.matcher import guess_fault_type, guess_device_type
    from services.fault_matcher import match_fault

    hid = getattr(g, 'hospital_id', None)
    addr = extract_address_from_title(title, hospital_id=hid)
    auto_fault = guess_fault_type(title)
    auto_device = guess_device_type(title)
    fm = match_fault(title)
    auto_fault = fm['category'] if fm['match_type'] == 'keyword' else auto_fault

    return jsonify({
        'fault': auto_fault,
        'device': auto_device,
        'fault_subcategory': fm.get('subcategory', ''),
        'building': addr.get('building', ''),
        'floor': addr.get('floor', ''),
        'department': addr.get('department', ''),
        'location': addr.get('location', ''),
    })


@api_mobile_bp.route('/addresses')
@login_required_api
def api_addresses(user):
    """小程序端获取当前医院地址数据"""
    from services.address import get_merged_addresses
    merged = get_merged_addresses()
    seen = set()
    result = []
    for a in merged:
        location = a.get('物理地址', '')
        building = a.get('楼区', '')
        floor = a.get('所属楼层', '')
        department = a.get('所属科室', '')
        key = f"{building}|{floor}|{location}"
        if key in seen:
            continue
        seen.add(key)
        if building and location:
            result.append({
                'building': building,
                'floor': floor or '',
                'location': location,
                'department': department or '',
            })
    # 按楼区+物理地址排序
    result.sort(key=lambda x: (x['building'], x['location']))
    return jsonify({'locations': result})


@api_mobile_bp.route('/orders/<int:order_id>/photos', methods=['GET'])
@login_required_api
def list_photos(user, order_id):
    """获取工单图片列表"""
    from utils.photo import get_photo_url
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404
    photos = WorkOrderPhoto.query.filter_by(
        work_order_id=order.id
    ).order_by(WorkOrderPhoto.created_at.desc()).all()
    return jsonify({
        'photos': [{
            'id': p.id,
            'url': get_photo_url(p.filepath),
            'filename': p.filename,
            'file_size': p.file_size,
            'width': p.width,
            'height': p.height,
            'uploaded_by': p.uploaded_by,
            'created_at': fmt_dt(p.created_at),
        } for p in photos]
    })


@api_mobile_bp.route('/orders/<int:order_id>/photos', methods=['POST'])
@login_required_api
def upload_photo(user, order_id):
    """上传工单图片（支持多图）"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404

    person_name = user.display_name or user.username
    files = request.files.getlist('photos') if request.files else []
    if not files:
        return jsonify({'error': '请选择图片', 'code': 400}), 400

    from utils.photo import save_photo, allowed_file, get_photo_url
    uploaded = []
    errors = []

    for f in files:
        if not f.filename or not allowed_file(f.filename):
            errors.append(f'{f.filename}: 不支持的格式')
            continue
        try:
            file_data = f.read()
            rel_path, w, h, size = save_photo(file_data, f.filename)
            photo = WorkOrderPhoto(
                work_order_id=order.id,
                filename=f.filename,
                filepath=rel_path,
                file_size=size,
                width=w,
                height=h,
                uploaded_by=person_name,
            )
            db.session.add(photo)
            db.session.flush()
            uploaded.append({
                'id': photo.id,
                'url': get_photo_url(rel_path),
                'filename': f.filename,
            })
        except Exception as e:
            errors.append(f'{f.filename}: {str(e)}')

    db.session.commit()
    return jsonify({
        'message': f'成功上传 {len(uploaded)} 张图片',
        'uploaded': uploaded,
        'errors': errors,
    })


@api_mobile_bp.route('/orders/<int:order_id>/photos/<int:photo_id>', methods=['DELETE'])
@login_required_api
def delete_photo(user, order_id, photo_id):
    """删除工单图片"""
    order = WorkOrder.query.get(order_id)
    if not order:
        return jsonify({'error': '工单不存在', 'code': 404}), 404
    photo = WorkOrderPhoto.query.get(photo_id)
    if not photo or photo.work_order_id != order.id:
        return jsonify({'error': '图片不存在', 'code': 404}), 404

    # 删文件
    from utils.photo import delete_photo_file
    if photo.filepath:
        delete_photo_file(photo.filepath)

    db.session.delete(photo)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ===================== 盘点相关 API =====================


@api_mobile_bp.route('/inventory/tasks')
@login_required_api
def inv_tasks(user):
    """获取盘点任务列表（auto-filter 按 g.hospital_id 隔离）"""
    tasks = InventoryTask.query.order_by(InventoryTask.created_at.desc()).limit(200).all()
    return jsonify({
        'tasks': [t.to_dict() for t in tasks],
    })


@api_mobile_bp.route('/inventory/create', methods=['POST'])
@login_required_api
def inv_create(user):
    """新建盘点任务（auto-filter 自动写 hospital_id）"""
    from flask import g
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '请输入盘点名称', 'code': 400}), 400

    now = datetime.now()
    count = InventoryTask.query.count() + 1
    task_no = f'PD{now.strftime("%Y%m%d")}-{count:03d}'

    # 使用 g.hospital_id（auto-filter 设置的值），不直接读 user.hospital_id
    hid = getattr(g, 'hospital_id', None)
    total = Asset.query.count()

    task = InventoryTask(
        task_no=task_no,
        name=name,
        status='pending',
        total_count=total,
        operator=user.display_name or user.username,
        start_time=now,
        hospital_id=hid,
    )
    db.session.add(task)
    db.session.commit()
    return jsonify({'ok': True, 'task': task.to_dict()})


@api_mobile_bp.route('/inventory/<int:task_id>')
@login_required_api
def inv_detail(user, task_id):
    """获取盘点详情：楼区/楼层列表 + 已扫描明细"""
    task = InventoryTask.query.get_or_404(task_id)
    if not user.is_admin and user.hospital_id != task.hospital_id:
        assigned = set(user.get_assigned_hospital_ids())
        if task.hospital_id not in assigned:
            return jsonify({'error': '无权限', 'code': 403}), 403

    # 从数据库中获取所有楼区楼层信息
    # 使用任务的院区查询资产，确保楼区/楼层数据正确
    buildings = db.session.query(Asset.building, Asset.floor).filter(
        Asset.hospital_id == task.hospital_id,
        Asset.building != '',
    ).distinct().all()

    # 按楼区分组楼层
    building_floors = {}
    for b, f in buildings:
        if b not in building_floors:
            building_floors[b] = set()
        if f:
            building_floors[b].add(f)

    result = []
    for b, floors in sorted(building_floors.items()):
        floors_list = sorted(floors, key=lambda x: (
            int(x.replace('F', '').replace('层', '')) if x.replace('F', '').replace('层', '').isdigit() else (
                0 if x == 'B1' else 999
            ),
            x
        ))
        floor_stats = {}
        for f in floors_list:
            scanned = InventoryItem.query.filter_by(task_id=task_id, building=b, floor=f).count()
            normal = InventoryItem.query.filter_by(task_id=task_id, building=b, floor=f, result='normal').count()
            total_assets = Asset.query.filter_by(hospital_id=task.hospital_id, building=b, floor=f).count()
            floor_stats[f] = {'scanned': scanned, 'normal': normal, 'total': total_assets}
        result.append({
            'building': b,
            'floors': floors_list,
            'stats': floor_stats,
        })

    # 已扫描明细
    items = InventoryItem.query.filter_by(task_id=task_id).order_by(InventoryItem.scanned_at.desc()).all()
    items_data = []
    for item in items:
        d = {
            'id': item.id,
            'asset_no': item.asset_no,
            'result': item.result,
            'building': item.building,
            'floor': item.floor,
            'department': item.department,
            'device_type': item.device_type,
            'brand': item.brand,
            'model_no': item.model_no,
            'notes': item.notes,
            'scanned_at': fmt_dt(item.scanned_at, '%m-%d %H:%M'),
        }
        if item.asset:
            d['asset_detail'] = {
                'id': item.asset.id,
                'asset_no': item.asset.asset_no,
                'device_type': item.asset.device_type,
                'brand': item.asset.brand,
                'model_no': item.asset.model_no,
                'sn': item.asset.sn,
                'department': item.asset.department,
                'building': item.asset.building,
                'floor': item.asset.floor,
                'location': item.asset.location,
                'status': item.asset.status,
                'ip_address': item.asset.ip_address,
                'mac_address': item.asset.mac_address,
                'cpu': item.asset.cpu,
                'memory': item.asset.memory,
                'disk_size': item.asset.disk_size,
            }
        items_data.append(d)

    return jsonify({
        'task': task.to_dict(),
        'buildings': result,
        'items': items_data,
    })


@api_mobile_bp.route('/inventory/scan', methods=['POST'])
@login_required_api
def inv_scan(user):
    """提交扫码盘点结果"""
    data = request.get_json() or {}
    task_id = data.get('task_id')
    asset_no = (data.get('asset_no') or '').strip()
    result = data.get('result', 'normal')  # normal / issue / new
    notes = (data.get('notes') or '').strip()
    building = (data.get('building') or '').strip()
    floor = (data.get('floor') or '').strip()

    if not task_id or not asset_no:
        return jsonify({'error': '参数不完整', 'code': 400}), 400

    task = InventoryTask.query.get(task_id)
    if not task:
        return jsonify({'error': '盘点任务不存在', 'code': 404}), 404
    if not user.is_admin and user.hospital_id != task.hospital_id:
        assigned = set(user.get_assigned_hospital_ids())
        if task.hospital_id not in assigned:
            return jsonify({'error': '盘点任务不存在', 'code': 404}), 404

    # 查找匹配的资产（按任务所属院区）
    asset = Asset.query.filter_by(asset_no=asset_no, hospital_id=task.hospital_id).first()

    existing = InventoryItem.query.filter_by(task_id=task_id, asset_no=asset_no).first()
    if existing:
        existing.result = result
        existing.notes = notes
        if building:
            existing.building = building
        if floor:
            existing.floor = floor
        if asset:
            existing.asset_id = asset.id
            existing.department = asset.department or existing.department
            existing.device_type = asset.device_type or existing.device_type
            existing.brand = asset.brand or existing.brand
            existing.model_no = asset.model_no or existing.model_no
            existing.sn = asset.sn or existing.sn
            if not building:
                existing.building = asset.building or existing.building
            if not floor:
                existing.floor = asset.floor or existing.floor
            existing.location = asset.location or existing.location
        existing.scanned_by = user.display_name or user.username
        if asset:
            if result == 'issue':
                asset.inventory_status = 'issue'
            elif result == 'normal' and asset.inventory_status != 'new':
                asset.inventory_status = ''
        db.session.commit()

        _refresh_task_stats(task)
        return jsonify({'ok': True, 'item': _item_to_dict(existing), 'updated': True})

    item = InventoryItem(
        task_id=task_id,
        asset_id=asset.id if asset else None,
        asset_no=asset_no,
        result=result,
        notes=notes,
        building=building or (asset.building if asset else ''),
        floor=floor or (asset.floor if asset else ''),
        department=asset.department if asset else '',
        location=asset.location if asset else '',
        device_type=asset.device_type if asset else '',
        brand=asset.brand if asset else '',
        model_no=asset.model_no if asset else '',
        sn=asset.sn if asset else '',
        scanned_by=user.display_name or user.username,
        scanned_at=now(),
        hospital_id=task.hospital_id,
    )
    if asset:
        item.asset_id = asset.id
    db.session.add(item)

    if asset:
        if result == 'issue':
            asset.inventory_status = 'issue'
        elif result == 'normal':
            asset.inventory_status = ''
    elif result in ('new', 'issue'):
        # 新盘：创建或更新资产记录
        existing_asset = Asset.query.filter_by(asset_no=asset_no, hospital_id=task.hospital_id).first()
        if existing_asset:
            existing_asset.inventory_status = 'new' if result == 'new' else 'issue'
            item.asset_id = existing_asset.id
        else:
            new_asset = Asset(
                asset_no=asset_no,
                device_type='',
                brand='',
                model_no='',
                sn='',
                department='',
                building=building,
                floor=floor,
                location='',
                hospital_id=task.hospital_id,
                inventory_status='new' if result == 'new' else 'issue',
            )
            db.session.add(new_asset)
            db.session.flush()
            item.asset_id = new_asset.id
    db.session.commit()

    _refresh_task_stats(task)

    return jsonify({'ok': True, 'item': _item_to_dict(item)})


@api_mobile_bp.route('/inventory/assets/<asset_no>')
@login_required_api
def inv_asset_lookup(user, asset_no):
    """扫码查询资产信息（按任务院区定位）"""
    if not asset_no:
        return jsonify({'error': '请输入资产编码', 'code': 400}), 400
    task_id = request.args.get('task_id', type=int)
    hid = None
    if task_id:
        task = InventoryTask.query.get(task_id)
        if task:
            hid = task.hospital_id
    if hid:
        asset = Asset.query.filter_by(asset_no=asset_no, hospital_id=hid).first()
    else:
        asset = Asset.query.filter_by(asset_no=asset_no).first()
    if not asset:
        return jsonify({'found': False, 'message': '未找到匹配资产，将作为新盘资产'})
    return jsonify({
        'found': True,
        'asset': {
            'id': asset.id,
            'asset_no': asset.asset_no,
            'device_type': asset.device_type,
            'brand': asset.brand,
            'model_no': asset.model_no,
            'sn': asset.sn,
            'department': asset.department,
            'building': asset.building,
            'floor': asset.floor,
            'location': asset.location,
            'status': asset.status,
            'ip_address': asset.ip_address,
            'mac_address': asset.mac_address,
            'cpu': asset.cpu,
            'memory': asset.memory,
            'disk_size': asset.disk_size,
            'operating_system': asset.operating_system,
            'notes': asset.notes,
        }
    })


def _refresh_task_stats(task):
    """刷新盘点任务统计"""
    task.scanned_count = InventoryItem.query.filter_by(task_id=task.id).count()
    task.normal_count = InventoryItem.query.filter_by(task_id=task.id, result='normal').count()
    task.issue_count = InventoryItem.query.filter_by(task_id=task.id, result='issue').count()
    task.new_asset_count = InventoryItem.query.filter_by(task_id=task.id, result='new').count()
    db.session.commit()


def _item_to_dict(item):
    return {
        'id': item.id,
        'task_id': item.task_id,
        'asset_no': item.asset_no,
        'result': item.result,
        'building': item.building,
        'floor': item.floor,
        'department': item.department,
        'device_type': item.device_type,
        'brand': item.brand,
        'model_no': item.model_no,
        'notes': item.notes,
        'scanned_at': fmt_dt(item.scanned_at, '%m-%d %H:%M'),
    }


# ======================== 考试系统 ========================
# 小程序端考试 API（复用 exam.py 逻辑）
# 路径前缀: /api/mobile/exam/...

@api_mobile_bp.route('/exam/list')
@login_required_api
def mobile_exam_list(user):
    """小程序 - 可用考试列表"""
    from models import can_access
    import json
    exams = Exam.query.filter(
        Exam.status.in_(['published', 'closed'])
    ).order_by(Exam.created_at.desc()).all()
    result = []
    for e in exams:
        if not e.check_access(user):
            continue
        d = e.to_dict()
        attempt_count = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=user.id, status='submitted'
        ).count()
        in_progress = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=user.id, status='in_progress'
        ).first()
        d['attempt_count'] = attempt_count
        d['max_attempts'] = e.max_attempts
        d['in_progress_id'] = in_progress.id if in_progress else None
        last_sub = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=user.id, status='submitted'
        ).order_by(ExamSubmission.submitted_at.desc()).first()
        d['last_score'] = last_sub.score if last_sub else None
        d['last_passed'] = last_sub.is_passed(e.pass_score) if last_sub else None
        d['can_start'] = e.status == 'published' and (
            e.max_attempts == 0 or attempt_count < e.max_attempts
        ) and not in_progress
        result.append(d)
    return jsonify({'exams': result})


@api_mobile_bp.route('/exam/<int:exam_id>/questions')
@login_required_api
def mobile_exam_questions(user, exam_id):
    """小程序 - 获取考试题目"""
    exam = Exam.query.get(exam_id)
    if not exam or exam.status not in ('published', 'closed'):
        return jsonify({'error': '考试不存在或未发布'}), 404
    if not exam.check_access(user):
        return jsonify({'error': '无权参加此考试'}), 403

    submission = ExamSubmission.query.filter_by(
        exam_id=exam.id, user_id=user.id, status='in_progress'
    ).first()

    if not submission:
        submission = ExamSubmission(exam_id=exam.id, user_id=user.id, total_count=0, total_possible=0)
        db.session.add(submission)
        db.session.flush()
        questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
        if exam.shuffle_questions:
            random.shuffle(questions)
        qlist = []
        total_score = 0
        for q in questions:
            opts = q.get_options()
            if exam.shuffle_options and opts:
                random.shuffle(opts)
            qlist.append({
                'id': q.id, 'sort_order': len(qlist) + 1,
                'question_type': q.question_type, 'question_text': q.question_text,
                'options': opts, 'score': q.score,
            })
            total_score += q.score
        submission.total_count = len(qlist)
        submission.total_possible = total_score
        submission.set_answers({})
        db.session.commit()
    else:
        questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
        qlist = []
        for q in questions:
            opts = q.get_options()
            qlist.append({
                'id': q.id, 'sort_order': len(qlist) + 1,
                'question_type': q.question_type, 'question_text': q.question_text,
                'options': opts, 'score': q.score,
            })

    saved_answers = submission.get_answers()
    elapsed = 0
    if submission.started_at:
        elapsed = int((datetime.now() - submission.started_at).total_seconds())

    return jsonify({
        'submission_id': submission.id,
        'exam': exam.to_dict(),
        'questions': qlist,
        'saved_answers': saved_answers,
        'time_limit': exam.duration_minutes * 60,
        'started_at': fmt_dt(submission.started_at, '%Y-%m-%d %H:%M:%S'),
        'elapsed_seconds': elapsed,
    })


@api_mobile_bp.route('/exam/<int:submission_id>/save_answer', methods=['POST'])
@login_required_api
def mobile_save_answer(user, submission_id):
    """小程序 - 保存答案"""
    submission = ExamSubmission.query.get(submission_id)
    if not submission or submission.user_id != user.id:
        return jsonify({'error': '答卷不存在'}), 404
    data = request.get_json(silent=True) or {}
    qid = str(data.get('question_id', ''))
    answer = data.get('answer', '')
    answers = submission.get_answers()
    answers[qid] = answer
    submission.set_answers(answers)
    db.session.commit()
    return jsonify({'success': True})


@api_mobile_bp.route('/exam/submit', methods=['POST'])
@login_required_api
def mobile_submit_exam(user):
    """小程序 - 提交答卷"""
    data = request.get_json(silent=True) or {}
    submission_id = data.get('submission_id')
    if not submission_id:
        return jsonify({'error': '缺少答卷ID'}), 400
    answers = data.get('answers', {})
    duration_seconds = data.get('duration_seconds', 0)

    submission = ExamSubmission.query.get(submission_id)
    if not submission or submission.user_id != user.id:
        return jsonify({'error': '答卷不存在'}), 404
    if submission.status != 'in_progress':
        return jsonify({'error': '答卷已提交'}), 400

    submission.set_answers(answers)
    submission.duration_seconds = duration_seconds

    exam = submission.exam
    if not exam:
        return jsonify({'error': '考试不存在'}), 404
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).all()
    q_map = {str(q.id): q for q in questions}

    total_score = 0.0
    correct_count = 0
    for qid_str, user_ans in answers.items():
        if not user_ans:
            continue
        q = q_map.get(qid_str)
        if q and q.check_answer(user_ans):
            total_score += q.score
            correct_count += 1

    submission.score = total_score
    submission.correct_count = correct_count
    submission.status = 'submitted'
    submission.submitted_at = datetime.now()
    db.session.commit()

    passed = submission.is_passed(exam.pass_score)
    return jsonify({
        'success': True,
        'submission': submission.to_dict(),
        'passed': passed,
    })


@api_mobile_bp.route('/exam/<int:submission_id>/result')
@login_required_api
def mobile_exam_result(user, submission_id):
    """小程序 - 查看考试结果"""
    submission = ExamSubmission.query.get(submission_id)
    if not submission or submission.user_id != user.id:
        return jsonify({'error': '答卷不存在'}), 404
    if submission.status != 'submitted':
        return jsonify({'error': '答卷尚未提交'}), 400

    exam = submission.exam
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
    user_answers = submission.get_answers()

    qlist = []
    for q in questions:
        qid_str = str(q.id)
        user_ans = user_answers.get(qid_str, '')
        qlist.append({
            'id': q.id, 'question_type': q.question_type,
            'question_text': q.question_text, 'options': q.get_options(),
            'score': q.score, 'answer': q.answer,
            'analysis': q.analysis, 'user_answer': user_ans,
            'is_correct': q.check_answer(user_ans) if user_ans else False,
        })

    return jsonify({
        'submission': submission.to_dict(),
        'questions': qlist,
        'passed': submission.is_passed(exam.pass_score),
    })


@api_mobile_bp.route('/exam/history')
@login_required_api
def mobile_exam_history(user):
    """小程序 - 考试历史"""
    submissions = ExamSubmission.query.filter_by(
        user_id=user.id, status='submitted'
    ).order_by(ExamSubmission.submitted_at.desc()).all()
    result = []
    for s in submissions:
        d = s.to_dict()
        d['passed'] = s.is_passed(s.exam.pass_score) if s.exam else False
        result.append(d)
    return jsonify({'submissions': result})


# ==================== 个人工作台 ====================

@api_mobile_bp.route('/workbench')
@login_required_api
def mobile_workbench(user):
    """个人工作台统计数据"""
    person_name = user.display_name or user.username
    today = date.today()
    month_start = today.replace(day=1)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    month_orders = WorkOrder.query.filter(
        WorkOrder.person == person_name,
        WorkOrder.created_at >= month_start
    ).all()
    month_total = len(month_orders)
    month_completed = sum(1 for o in month_orders if o.status == 'completed')
    month_overdue = sum(1 for o in month_orders if o.completed_at and o.created_at and
                        (o.completed_at - o.created_at).total_seconds() > 7200)

    today_pending = WorkOrder.query.filter(
        WorkOrder.person == person_name,
        WorkOrder.status.in_(['pending', 'in_progress']),
        WorkOrder.created_at >= today_start
    ).count()

    today_done = WorkOrder.query.filter(
        WorkOrder.person == person_name,
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= today_start
    ).count()

    unassigned_pending = WorkOrder.query.filter(
        WorkOrder.status == 'pending',
        (WorkOrder.person.is_(None)) | (WorkOrder.person == '')
    ).count()

    return jsonify({
        'person': person_name,
        'avatar': user.avatar or '',
        'month': {
            'total': month_total,
            'completed': month_completed,
            'overdue': month_overdue,
            'rate': round(month_completed / month_total * 100, 1) if month_total else 0,
        },
        'today': {
            'pending': today_pending,
            'completed': today_done,
            'unassigned': unassigned_pending,
        },
    })


# ==================== 值班排班 ====================

@api_mobile_bp.route('/duty-schedules')
@login_required_api
def mobile_duty_schedules(user):
    """值班排班表（手机端）"""
    from services.data_service import get_duty_schedules_api, get_duty_schedule_staff
    today = date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    records = get_duty_schedules_api(year, month)

    # 构建 team_map：人员名 → 所属组
    all_staff = get_duty_schedule_staff()
    team_map = {}
    for s in all_staff:
        team = s.team or ''
        if team not in team_map:
            team_map[team] = []
        team_map[team].append(s.name)

    # 按用户所属组筛选值班人员
    user_team = user.team or ''
    if user_team and user_team in team_map:
        allowed_names = set(team_map[user_team])
        filtered_records = {}
        for k, v in records.items():
            parts = k.split('_')
            if len(parts) == 2 and parts[0] in allowed_names:
                filtered_records[k] = v
        records = filtered_records

    # 今日值班人员
    today_duty = []
    for k, v in records.items():
        parts = k.split('_')
        if len(parts) == 2 and parts[1] == str(today.day):
            today_duty.append({'person_name': parts[0], 'shift': v})

    return jsonify({
        'records': records,
        'today': today_duty,
        'year': year,
        'month': month,
    })


# ==================== 交接班记录 ====================

@api_mobile_bp.route('/shift-handovers', methods=['GET'])
@login_required_api
def mobile_shift_handovers(user):
    """交接班记录列表（含未读计数 + 关联工单详情）"""
    from models import ShiftHandover, WorkOrder
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = ShiftHandover.query.order_by(ShiftHandover.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    handovers = pagination.items

    # 未读计数：用用户偏好存储上次阅读时间
    import json
    from datetime import datetime
    last_read_str = user.get_pref('shift_last_read_at', '')
    last_read = datetime.fromisoformat(last_read_str) if last_read_str else datetime(2000, 1, 1)
    unread_count = ShiftHandover.query.filter(ShiftHandover.created_at > last_read).count()

    # 只返回同医院同组的成员
    my_hids = set()
    assigned = user.get_assigned_hospitals()
    for h in assigned: my_hids.add(h.id)
    persons = User.query.filter(User.is_active == True).order_by(User.display_name).all()
    filtered = []
    for p in persons:
        if p.id == user.id: continue
        if p.team and user.team and p.team != user.team: continue
        phids = set()
        for h in p.get_assigned_hospitals(): phids.add(h.id)
        if my_hids and not phids.intersection(my_hids): continue
        filtered.append({'name': p.display_name or p.username})

    # 收集所有关联工单ID
    all_order_ids = set()
    for h in handovers:
        ids = h.work_order_ids or []
        for oid in ids: all_order_ids.add(int(oid))
    # 批量查询工单标题
    orders_map = {}
    if all_order_ids:
        orders = WorkOrder.query.filter(WorkOrder.id.in_(list(all_order_ids))).all()
        for o in orders:
            orders_map[o.id] = {'id': o.id, 'title': o.title or '工单#' + str(o.id), 'status': o.status or ''}

    return jsonify({
        'handovers': [{
            'id': h.id,
            'handover_person': h.handover_person,
            'receive_person': h.receive_person,
            'content': (h.content or '')[:100],
            'notes': h.notes or '',
            'status': h.status,
            'created_at': fmt_dt(h.created_at, '%Y-%m-%d %H:%M'),
            'photos': h.photos or [],
            'work_orders': [orders_map.get(oid, {'id': oid, 'title': '工单#' + str(oid), 'status': ''}) for oid in (h.work_order_ids or [])],
        } for h in handovers],
        'unread_count': unread_count,
        'total': pagination.total,
        'page': page,
        'has_more': pagination.has_next,
        'persons': filtered,
    })


@api_mobile_bp.route('/shift-handovers/mark-read', methods=['POST'])
@login_required_api
def mobile_shift_handover_mark_read(user):
    """标记交接班已读"""
    from datetime import datetime
    user.set_pref('shift_last_read_at', datetime.now().isoformat())
    db.session.commit()
    return jsonify({'ok': True})


@api_mobile_bp.route('/shift-handovers/my-orders', methods=['GET'])
@login_required_api
def mobile_shift_handover_my_orders(user):
    """获取当前用户可选的工单（已接单/处理中/已完成）"""
    from models import WorkOrder
    orders = WorkOrder.query.filter(
        WorkOrder.person == user.display_name,
        WorkOrder.status.in_(['processing', 'completed'])
    ).order_by(WorkOrder.created_at.desc()).limit(50).all()
    return jsonify({
        'orders': [{
            'id': o.id,
            'title': o.title or '工单#' + str(o.id),
            'status': o.status,
            'status_label': {'pending': '待接单', 'processing': '处理中', 'completed': '已完成'}.get(o.status, o.status),
            'location': o.location or '',
            'created_at': fmt_dt(o.created_at, '%m/%d'),
        } for o in orders]
    })


@api_mobile_bp.route('/shift-handovers', methods=['POST'])
@login_required_api
def mobile_shift_handover_create(user):
    """创建交接班记录（含关联工单）"""
    from models import ShiftHandover
    data = request.get_json(silent=True) or {}
    handover_person = data.get('handover_person', '').strip()
    receive_person = data.get('receive_person', '').strip()
    content = data.get('content', '').strip()
    notes = data.get('notes', '').strip()
    photos = data.get('photos', []) or []
    work_order_ids = data.get('work_order_ids', []) or []

    if not handover_person or not receive_person:
        return jsonify({'error': '交班人和接班人不能为空', 'code': 400}), 400

    handover = ShiftHandover.new_with_hospital(
        handover_person=handover_person,
        receive_person=receive_person,
        content=content,
        unfinished_orders=[],
        notes=notes,
        photos=photos,
        work_order_ids=[int(oid) for oid in work_order_ids if str(oid).isdigit()],
        status='completed',
    )
    db.session.add(handover)
    db.session.commit()

    return jsonify({'success': True, 'id': handover.id})


# ==================== 手机端聊天 ====================

@api_mobile_bp.route('/chat/conversations')
@login_required_api
def mobile_chat_conversations(user):
    from routes.chat import _serialize_conversation
    from models import ChatConversation, ChatParticipant
    participant_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == user.id, ChatParticipant.is_active == True
    ).subquery()
    conversations = ChatConversation.query.filter(
        ChatConversation.id.in_(participant_ids)
    ).order_by(ChatConversation.updated_at.desc()).all()
    return jsonify({'conversations': [_serialize_conversation(c, user.id) for c in conversations]})


@api_mobile_bp.route('/chat/leave', methods=['POST'])
@login_required_api
def mobile_chat_leave(user):
    from models import ChatParticipant
    data = request.get_json(silent=True) or {}
    conv_id = data.get('conversation_id')
    if not conv_id:
        return jsonify({'error': '缺少 conversation_id'}), 400
    participant = ChatParticipant.query.filter_by(
        conversation_id=conv_id, user_id=user.id, is_active=True
    ).first()
    if not participant:
        return jsonify({'error': '不在该群聊中'}), 404
    participant.is_active = False
    db.session.commit()
    return jsonify({'ok': True})


@api_mobile_bp.route('/chat/messages')
@login_required_api
def mobile_chat_messages(user):
    from models import ChatConversation, ChatParticipant, ChatMessage
    from datetime import datetime
    conv_id = request.args.get('conversation_id', type=int)
    before_id = request.args.get('before_id', type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)
    if not conv_id:
        return jsonify({'error': '缺少 conversation_id'}), 400
    participant = ChatParticipant.query.filter_by(conversation_id=conv_id, user_id=user.id, is_active=True).first()
    if not participant:
        return jsonify({'error': '无权访问'}), 403
    participant.last_read_at = datetime.now()
    db.session.commit()
    query = ChatMessage.query.filter_by(conversation_id=conv_id)
    if before_id:
        query = query.filter(ChatMessage.id < before_id)
    messages = query.order_by(ChatMessage.id.desc()).limit(limit).all()
    messages.reverse()
    return jsonify({'messages': [{
        'id': m.id, 'sender_id': m.sender_id, 'sender_name': m.sender_name,
        'sender_hospital': m.sender_hospital, 'content': m.content, 'msg_type': m.msg_type,
        'recalled': m.recalled, 'file_name': m.file_name, 'file_size': m.file_size,
        'created_at': m.created_at.isoformat(), 'is_self': m.sender_id == user.id,
        'sender_avatar': (User.query.get(m.sender_id).avatar or '') if User.query.get(m.sender_id) else ''
    } for m in messages]})




@api_mobile_bp.route('/chat/upload', methods=['POST'])
@login_required_api
def mobile_chat_upload(user):
    """聊天文件上传（图片走COS，非图片存本地）"""
    import uuid, os
    ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'mp3', 'wav', 'ogg'}
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': '文件为空'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    if ext not in ALLOWED_EXT:
        return jsonify({'error': '不支持的文件类型'}), 400
    is_image = ext in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}

    if is_image:
        # 图片用 photo.save_photo（支持COS/本地双模式）
        from utils.photo import save_photo
        file_data = file.read()
        try:
            relative_path, w, h, size = save_photo(file_data, file.filename)
            from utils.photo import get_photo_url
            url = get_photo_url(relative_path)
            return jsonify({'url': url, 'filename': os.path.basename(relative_path), 'is_image': True})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    else:
        # 非图片（音频等）存本地
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'chat')
        os.makedirs(upload_dir, exist_ok=True)
        filename = uuid.uuid4().hex + '.' + ext
        file.save(os.path.join(upload_dir, filename))
        url = '/static/uploads/chat/' + filename
        return jsonify({'url': url, 'filename': filename, 'is_image': False})
@api_mobile_bp.route('/chat/send', methods=['POST'])
@login_required_api
def mobile_chat_send(user):
    from models import ChatConversation, ChatParticipant, ChatMessage
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    conv_id = data.get('conversation_id')
    content = (data.get('content') or '').strip()
    if not conv_id or not content:
        return jsonify({'error': '缺少参数'}), 400
    participant = ChatParticipant.query.filter_by(conversation_id=conv_id, user_id=user.id, is_active=True).first()
    if not participant:
        return jsonify({'error': '无权访问'}), 403
    hospital_name = ''
    assigned = user.get_assigned_hospitals()
    if assigned:
        hospital_name = assigned[0].name
    msg_type = data.get('msg_type', 'text')
    msg = ChatMessage(
        conversation_id=conv_id, sender_id=user.id,
        sender_name=user.display_name or user.username,
        sender_hospital=hospital_name, content=content, msg_type=msg_type,
        file_name=data.get('file_name', ''), file_size=data.get('file_size')
    )
    db.session.add(msg)
    conv = ChatConversation.query.get(conv_id)
    if conv:
        conv.last_message = content
        conv.last_sender = user.display_name or user.username
        conv.last_time = datetime.now()
        conv.updated_at = datetime.now()
    db.session.commit()
    return jsonify({
        'id': msg.id, 'sender_id': msg.sender_id, 'sender_name': msg.sender_name,
        'sender_hospital': msg.sender_hospital, 'content': msg.content,
        'msg_type': msg.msg_type, 'created_at': msg.created_at.isoformat(), 'is_self': True
    })


@api_mobile_bp.route('/chat/users')
@login_required_api
def mobile_chat_users(user):
    from models import User, get_group_name_by_id
    my_team = user.team if user.team else None
    all_users = User.query.order_by(User.display_name).all()
    teams_map, teams_order = {}, []
    for u in all_users:
        if u.id == user.id: continue
        team_name = (u.team if u.team else '未分组')
        if my_team and team_name != my_team: continue
        hospital_name = ''
        assigned = u.get_assigned_hospitals()
        if assigned: hospital_name = assigned[0].name
        if team_name not in teams_map:
            teams_map[team_name] = []
            teams_order.append(team_name)
        teams_map[team_name].append({'id': u.id, 'name': u.display_name or u.username, 'hospital': hospital_name})
    result = []
    for tname in teams_order:
        if tname == '未分组': continue
        result.append({'team': tname, 'users': teams_map[tname]})
    if '未分组' in teams_map: result.append({'team': '未分组', 'users': teams_map['未分组']})
    return jsonify({'teams': result})


@api_mobile_bp.route('/chat/start', methods=['POST'])
@login_required_api
def mobile_chat_start(user):
    from models import User, ChatConversation, ChatParticipant
    data = request.get_json(silent=True) or {}
    target_id = data.get('user_id')
    if not target_id: return jsonify({'error': '缺少 user_id'}), 400
    target_id = int(target_id)
    if target_id == user.id: return jsonify({'error': '不能和自己聊天'}), 400
    target = User.query.get(target_id)
    if not target: return jsonify({'error': '用户不存在'}), 404
    my_conv_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == user.id, ChatParticipant.is_active == True
    ).subquery()
    existing = ChatConversation.query.filter(ChatConversation.id.in_(my_conv_ids), ChatConversation.type == 'single').all()
    for conv in existing:
        parts = ChatParticipant.query.filter_by(conversation_id=conv.id).all()
        part_ids = [p.user_id for p in parts]
        if target_id in part_ids:
            return jsonify({'conversation_id': conv.id, 'title': target.display_name or target.username})
    target_name = target.display_name or target.username
    my_name = user.display_name or user.username
    conv = ChatConversation(title=target_name, type='single')
    db.session.add(conv)
    db.session.flush()
    for uid, uname in [(user.id, my_name), (target.id, target_name)]:
        db.session.add(ChatParticipant(conversation_id=conv.id, user_id=uid, user_name=uname))
    db.session.commit()
    return jsonify({'conversation_id': conv.id, 'title': conv.title})


@api_mobile_bp.route('/chat/start_group', methods=['POST'])
@login_required_api
def mobile_chat_start_group(user):
    """创建群聊"""
    from models import User, ChatConversation, ChatParticipant
    data = request.get_json(silent=True) or {}
    user_ids = data.get('user_ids', [])
    if not user_ids or not isinstance(user_ids, list):
        return jsonify({'error': '请选择群聊成员'}), 400
    user_ids = list(set(int(uid) for uid in user_ids if uid and int(uid) != user.id))
    if not user_ids:
        return jsonify({'error': '除了自己至少需要一个人'}), 400
    my_name = user.display_name or user.username
    members = User.query.filter(User.id.in_(user_ids)).all()
    name_list = [m.display_name or m.username for m in members]
    title = ', '.join(name_list[:3])
    if len(name_list) > 3: title += ' 等人'
    conv = ChatConversation(title=title, type='group')
    db.session.add(conv)
    db.session.flush()
    db.session.add(ChatParticipant(conversation_id=conv.id, user_id=user.id, user_name=my_name))
    for m in members:
        db.session.add(ChatParticipant(conversation_id=conv.id, user_id=m.id, user_name=m.display_name or m.username))
    db.session.commit()
    return jsonify({'conversation_id': conv.id, 'title': conv.title})


@api_mobile_bp.route('/chat/unread-counts')
@login_required_api
def mobile_chat_unread(user):
    from models import ChatConversation, ChatParticipant, ChatMessage
    from datetime import datetime
    participant_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == user.id, ChatParticipant.is_active == True
    ).subquery()
    conversations = ChatConversation.query.filter(ChatConversation.id.in_(participant_ids)).all()
    total = 0
    for c in conversations:
        for p in c.participants:
            if p.user_id == user.id:
                unread = ChatMessage.query.filter(
                    ChatMessage.conversation_id == c.id,
                    ChatMessage.created_at > (p.last_read_at or datetime(2000, 1, 1)),
                    ChatMessage.sender_id != user.id
                ).count()
                total += unread
                break
    return jsonify({'total_unread': total})


@api_mobile_bp.route('/chat/mark-read', methods=['POST'])
@login_required_api
def mobile_chat_mark_read(user):
    from models import ChatParticipant
    from datetime import datetime
    participants = ChatParticipant.query.filter_by(user_id=user.id, is_active=True).all()
    now = datetime.now()
    for p in participants: p.last_read_at = now
    db.session.commit()
    return jsonify({'ok': True})




@api_mobile_bp.route('/chat/delete', methods=['POST'])
@login_required_api
def mobile_chat_delete(user):
    from models import ChatConversation, ChatParticipant, ChatMessage
    data = request.get_json(silent=True) or {}
    conv_id = data.get('conversation_id')
    if not conv_id: return jsonify({'error': '缺少 conversation_id'}), 400
    participant = ChatParticipant.query.filter_by(conversation_id=conv_id, user_id=user.id, is_active=True).first()
    if not participant: return jsonify({'error': '无权访问'}), 403
    # 软删除：标记为不活跃
    participant.is_active = False
    participant.last_read_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})
@api_mobile_bp.route('/chat/recall', methods=['POST'])
@login_required_api
def mobile_chat_recall(user):
    from models import ChatMessage
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    msg_id = data.get('message_id')
    if not msg_id: return jsonify({'error': '缺少 message_id'}), 400
    try: msg_id = int(msg_id)
    except: return jsonify({'error': 'message_id 必须为整数'}), 400
    msg = ChatMessage.query.get(msg_id)
    if not msg: return jsonify({'error': '消息不存在'}), 404
    if msg.sender_id != user.id: return jsonify({'error': '只能撤回自己的消息'}), 403
    delta = (datetime.now() - msg.created_at).total_seconds()
    if delta > 120: return jsonify({'error': '超过2分钟，无法撤回'}), 400
    msg.recalled = True
    msg.content = '消息已撤回'
    db.session.commit()
    return jsonify({'ok': True, 'message_id': msg.id, 'conversation_id': msg.conversation_id})
