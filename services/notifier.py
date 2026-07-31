"""通知服务 — 微信订阅消息 + 企业微信机器人推送

从 routes/api_mobile.py 抽取（2026-07-31 P1e），消除 6 处跨路由导入。
"""
import json as pyjson
import threading
import urllib.request
from datetime import datetime

from flask import current_app

from models import db, SystemSetting, SubscribeUser
from utils.time_helpers import fmt_dt


def send_new_order_notification(order):
    """新工单发布时推送微信订阅消息给所有已订阅用户"""
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
            to_remove = []  # 批量收集待移除订阅，循环后统一 commit（P1-13 性能优化）
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
                        to_remove.append(sub)
                    else:
                        print(f'[NOTIFY] 推送失败 user_id={sub.user_id} errcode={result.get("errcode")} errmsg={result.get("errmsg")}', flush=True)
                        # 40001=token失效, 43101=用户拒收/取消订阅 -> 移除订阅
                        if result.get('errcode') in (40001, 43101):
                            to_remove.append(sub)
                            print(f'[NOTIFY] 已移除失效订阅 user_id={sub.user_id}', flush=True)
                except Exception as e:
                    print(f'[NOTIFY] 推送异常 user_id={sub.user_id}: {e}', flush=True)
            # 批量移除（一次 commit，避免每次推送都 fsync）
            for s in to_remove:
                db.session.delete(s)
            if to_remove:
                db.session.commit()
            print(f'[NOTIFY] 推送完成: order_id={order.id}, 成功={success}/{len(subscribers)}', flush=True)

    app = current_app._get_current_object()
    t = threading.Thread(target=_do_push, args=(app,), daemon=True)
    t.start()


def send_wecom_notification(order, skip_time_check=False, is_urge=False):
    """企业微信群机器人推送工单通知（非阻塞）。is_urge=True 时使用催办加急模板"""
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
    floor = order.floor or ''
    department = order.department or '未指定'
    location_str = f'{building}{" " + floor if floor else ""}'.strip()
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
                    floor=floor,
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
                      f"> **位置：**{location_str}\n" \
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
                           f"> **位置：**{location_str}\n"
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

    t = threading.Thread(target=_do_push, args=(webhook_url, payload), daemon=True)
    t.start()
