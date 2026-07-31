from utils.csrf import csrf_protect
from utils.permissions import has_permission
"""仪表盘路由（优化版：合并查询+缓存）"""
from flask import current_app,  Blueprint, render_template, request, g, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, case
from datetime import datetime, timedelta
from models import WorkOrder, User, db, SystemSetting
from services.cache import cached

main_bp = Blueprint('main', __name__)


@main_bp.route('/user/avatars')
@login_required
def list_avatars():
    """返回默认头像列表"""
    avatars = [
        # 🎨 卡通冒险 - Adventurer 风格
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Kitty&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Max&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Luna&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Charlie&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Molly&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Cooper&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Daisy&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Buddy&backgroundColor=fde68a',
        # ✨ 可爱动漫 - Lorelei 风格
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Alice&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Bob&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Coral&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Dean&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Eve&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Finn&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Gina&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Hank&backgroundColor=fde68a',
        # 🐾 动物表情 - Fun Emoji 风格
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Cat&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Dog&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Fox&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Bear&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Panda&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Rabbit&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Lion&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Koala&backgroundColor=fde68a',
        # 👾 像素角色 - Pixel Art 风格
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Hero&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Ninja&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Wizard&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Knight&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Elf&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Dwarf&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Dragon&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Robot&backgroundColor=fde68a',
        # 🎭 卡通角色 - Avataaars 风格
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Sunny&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Rain&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Star&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Cloud&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Moon&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Wave&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Flame&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Storm&backgroundColor=fde68a',
        # 🎪 趣味插画 - Open Peeps 风格
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Happy&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Smile&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Chill&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Wink&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Cozy&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Bliss&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Dream&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Zen&backgroundColor=fde68a',
    ]
    return jsonify({'avatars': avatars})


@main_bp.route('/user/avatar/select', methods=['POST'])
@csrf_protect
@login_required
def select_avatar():
    """保存用户头像选择"""
    from flask import request, jsonify
    data = request.get_json(silent=True) or {}
    avatar_url = (data.get('avatar') or '').strip()
    if not avatar_url:
        return jsonify({'error': '请选择头像'}), 400
    current_user.avatar = avatar_url
    db.session.commit()
    return jsonify({'ok': True, 'avatar': avatar_url})


@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供上传的图片文件（本地 → COS 回退）"""
    import os
    from flask import current_app, send_from_directory, redirect
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
    local_path = os.path.join(upload_dir, filename)
    if os.path.exists(local_path):
        return send_from_directory(upload_dir, filename, max_age=86400)
    # 本地没有 → 尝试 COS
    try:
        from utils.photo import get_photo_url
        cos_url = get_photo_url(filename)
        if cos_url and cos_url.startswith('http'):
            return redirect(cos_url, code=302)
    except Exception:
        pass
    return send_from_directory(upload_dir, filename, max_age=86400)


@main_bp.route('/')
@login_required
def dashboard():
    now = datetime.now()
    # 支持 ?date=2026-03-15 查看历史日期仪表盘
    today_str = now.strftime('%Y-%m-%d')
    dashboard_date = request.args.get('date', '').strip()
    if dashboard_date:
        try:
            now = datetime.strptime(dashboard_date, '%Y-%m-%d')
        except ValueError:
            dashboard_date = today_str
    else:
        dashboard_date = today_str
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # 组别筛选（非管理员自动按 User.team 过滤，管理员可切换）
    # request.args.get('team'): None=URL没有team参数(首次进入) / ''=用户选了全部组
    team_param = request.args.get('team')  # 不加默认值，以区分None和空字符串
    if team_param is None:
        # 首次进入（URL没有?team=），应用默认组别
        if has_permission(current_user, 'system:config'):
            _def_setting = SystemSetting.query.filter_by(key='default_dashboard_team').first()
            team = _def_setting.value if _def_setting and _def_setting.value else ''
        else:
            team = current_user.team if current_user.team else ''
    else:
        # URL带了?team=，用户主动切换了组别（包括''=全部组）
        team = team_param
    team_persons = set()
    if team:
        tp = User.query.filter(User.team == team, User.is_active == True).all()
        team_persons = {p.display_name for p in tp if p.display_name}

    teams = [t[0] for t in User.query.with_entities(User.team).filter(User.team!='', User.team!=None).distinct().order_by(User.team).all()]

    # 医院过滤函数
    hid = getattr(g, 'hospital_id', None)
    hospital_filter = (lambda q: q.filter(WorkOrder.hospital_id == hid)) if hid and hid != 0 else None

    # ---------- 批量统计（一次查询聚合多项） ----------
    monthly_stats = _get_monthly_stats(first_of_month, today_start, today_end, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 本月故障分布 ----------
    type_stats = _get_type_stats(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 本月故障复现（≥3次） ----------
    repeat_faults = _get_repeat_faults(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 本月人员处理排行（排除admin和空白） ----------
    person_stats = _get_person_stats(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 近7天趋势 ----------
    daily_stats = _get_daily_trend(now, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 响应时长趋势 ----------
    response_trend = _get_response_trend(person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 今日工单动态 ----------
    today_orders = _get_today_orders(today_start, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 楼区热度 ----------
    building_stats = _get_building_stats(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 热门报修位置 Top 5 ----------
    hot_locations = _get_hot_locations(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 科室排行 ----------
    dept_stats = _get_dept_stats(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)

    # ---------- 待处理加急/紧急（pending工单不过滤人员） ----------
    base_pending = WorkOrder.query.filter(WorkOrder.status == 'pending')
    base_pending = hospital_filter(base_pending) if hospital_filter else base_pending
    pending_urgent = base_pending.filter(WorkOrder.priority == 'urgent').count()
    pending_emergency = base_pending.filter(WorkOrder.priority == 'emergency').count()

    # ---------- 紧急程度分布 ----------
    priority_q = WorkOrder.query.filter(WorkOrder.created_at >= first_of_month)
    if team_persons:
        priority_q = priority_q.filter(WorkOrder.person.in_(team_persons))
    if hospital_filter:
        priority_q = hospital_filter(priority_q)
    priority_dist = {}
    for row in priority_q.with_entities(
        WorkOrder.priority, func.count(WorkOrder.id)
    ).group_by(WorkOrder.priority).all():
        priority_dist[row[0]] = row[1]

    # ---------- 上月对比 ----------
    last_month_start = (first_of_month - timedelta(days=1)).replace(day=1)
    last_month_q = WorkOrder.query.filter(
        WorkOrder.created_at >= last_month_start,
        WorkOrder.created_at < first_of_month,
    )
    if team_persons:
        last_month_q = last_month_q.filter(WorkOrder.person.in_(team_persons))
    if hospital_filter:
        last_month_q = hospital_filter(last_month_q)
    last_month_count = last_month_q.count()
    month_change = monthly_stats['monthly_count'] - last_month_count

    # ---------- SLA 统计 ----------
    sla_stats = _get_sla_stats(first_of_month, person_filter=team_persons if team else None, hospital_filter=hospital_filter)
    overdue_count = sla_stats.get('overdue_count', 0)
    sla_items = sla_stats.get('items', [])
    sla_distribution = sla_stats.get('distribution', {})

    # 今日平均响应时长
    today_resp_q = WorkOrder.query.filter(
        WorkOrder.created_at >= first_of_month,
        WorkOrder.completed_at.isnot(None),
        WorkOrder.completed_at > WorkOrder.created_at,
        func.julianday(WorkOrder.completed_at) <= func.julianday(WorkOrder.created_at) + 1
    )
    if team_persons:
        today_resp_q = today_resp_q.filter(WorkOrder.person.in_(team_persons))
    if hospital_filter:
        today_resp_q = hospital_filter(today_resp_q)
    today_resp = today_resp_q.with_entities(
        func.avg(
            (func.julianday(WorkOrder.completed_at) - func.julianday(WorkOrder.created_at)) * 24 * 60
        )
    ).scalar()
    today_avg_resp = round(today_resp, 1) if today_resp else 0

    return render_template('dashboard.html',
                           dashboard_date=dashboard_date,
                           today_str=today_str,
                           monthly_count=monthly_stats['monthly_count'],
                           total_all=monthly_stats['total_all'],
                           type_stats=type_stats,
                           repeat_faults=repeat_faults,
                           person_stats=person_stats,
                           daily_stats=daily_stats,
                           today_orders=today_orders,
                           building_stats=building_stats,
                           hot_locations=hot_locations,
                           dept_stats=dept_stats,
                           response_trend=response_trend,
                           today_completed=monthly_stats['today_completed'],
                           today_in_progress=monthly_stats['today_in_progress'],
                           today_pending=monthly_stats['today_pending'],
                           today_rate=monthly_stats['today_rate'],
                           pending_urgent=pending_urgent,
                           pending_emergency=pending_emergency,
                           sla_stats=sla_stats,
                           sla_items=sla_items,
                           overdue_count=overdue_count,
                           sla_distribution=sla_distribution,
                           today_avg_resp=today_avg_resp,
                           priority_dist=priority_dist,
                           last_month_count=last_month_count,
                           month_change=month_change,
                           now=now,
                           team_sel=team,
                           teams=teams)


def _hf(q):
    """按当前医院过滤"""
    hid = getattr(g, 'hospital_id', None)
    if hid and hid != 0:
        return q.filter(WorkOrder.hospital_id == hid)
    return q

def _get_monthly_stats(first_of_month, today_start, today_end, person_filter=None, hospital_filter=None):
    """一站式获取本月/今日各类统计"""
    def _pf(q):
        q = q.filter(WorkOrder.person.in_(person_filter)) if person_filter else q
        return hospital_filter(q) if hospital_filter else q
    # 本月总数
    monthly_count = _pf(WorkOrder.query.filter(
        WorkOrder.created_at >= first_of_month
    )).count()

    # 当年总工单数（非全部累计）
    now = datetime.now()
    year_start = datetime(now.year, 1, 1)
    total_all = _pf(WorkOrder.query.filter(
        WorkOrder.created_at >= year_start
    )).count()

    # 今日状态统计（一次查询完成）
    today_row = _pf(WorkOrder.query).with_entities(
        func.count(case((WorkOrder.status == 'completed', 1), else_=None)).filter(
            WorkOrder.completed_at >= today_start,
            WorkOrder.completed_at < today_end,
        ).label('today_completed'),
        func.count(case((WorkOrder.status == 'in_progress', 1), else_=None)).label('today_in_progress'),
    ).first()

    today_completed = today_row.today_completed or 0
    today_in_progress = today_row.today_in_progress or 0

    # 待接单不过滤人员（pending 工单 person='' 无人认领）
    pending_base = WorkOrder.query.filter(WorkOrder.status == 'pending')
    pending_base = hospital_filter(pending_base) if hospital_filter else pending_base
    today_pending = pending_base.filter(
        WorkOrder.created_at >= today_start,
    ).count()
    total_completed_all = _pf(WorkOrder.query.filter_by(status='completed')).count()
    today_rate = round(total_completed_all / total_all * 100, 1) if total_all > 0 else 0

    return {
        'monthly_count': monthly_count,
        'total_all': total_all,
        'today_completed': today_completed,
        'today_in_progress': today_in_progress,
        'today_pending': today_pending,
        'today_rate': today_rate,
    }


def _get_type_stats(first_of_month, person_filter=None, hospital_filter=None):
    """本月各故障类型分布"""
    q = WorkOrder.query
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    rows = q.with_entities(
        WorkOrder.fault_type, func.count(WorkOrder.id)
    ).filter(WorkOrder.created_at >= first_of_month).group_by(WorkOrder.fault_type).all()
    return {ft: cnt for ft, cnt in rows}


def _get_repeat_faults(first_of_month, person_filter=None, hospital_filter=None):
    """本月故障复现：同地址+同类型≥3次（与重复单分析逻辑一致）"""
    rows = db.session.query(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
        WorkOrder.fault_type,
        WorkOrder.fault_subcategory,
        db.func.count(WorkOrder.id).label('repeat_count'),
    ).filter(
        WorkOrder.created_at >= first_of_month,
    )
    if person_filter:
        rows = rows.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        rows = hospital_filter(rows)
    rows = rows.group_by(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
        WorkOrder.fault_type,
        WorkOrder.fault_subcategory,
    ).having(
        db.func.count(WorkOrder.id) >= 2,
    ).order_by(
        db.desc('repeat_count'),
    ).all()
    items = []
    for r in rows:
        parts = [p for p in [r.building, r.floor, r.location] if p]
        full_location = '-'.join(parts) if parts else '未知'
        # 跳转到工单列表筛选该位置+故障
        params = {}
        if r.building: params['building'] = r.building
        if r.floor: params['floor'] = r.floor
        if r.location: params['location'] = r.location
        if r.fault_type: params['fault_type'] = r.fault_type
        params['status'] = ''
        from urllib.parse import urlencode
        link_url = '/orders/?' + urlencode(params)
        items.append({
            'location': full_location,
            'fault_type': r.fault_type or '未知',
            'count': r.repeat_count,
            'link_url': link_url,
        })
    return items


def _get_person_stats(first_of_month, person_filter=None, hospital_filter=None):
    """本月人员处理排行（排除admin和空白），按当前医院+组别过滤"""
    from flask import current_app,  g
    active_person_names = set()
    try:
        hid = getattr(g, 'hospital_id', None)
        query = User.query.filter(User.is_active == True)
        if hid:
            query = query.filter(User.hospital_id == hid)
        if person_filter:
            query = query.filter(User.display_name.in_(person_filter))
        active_person_names = {p.display_name for p in query.all() if p.display_name}
    except Exception as e:
        current_app.logger.error(f'查询活跃人员失败: {e}')

    admin_names = {'管理员'}
    valid_names = active_person_names - admin_names

    if not valid_names:
        return {}

    q = WorkOrder.query
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    rows = q.with_entities(
        WorkOrder.person, func.count(WorkOrder.id)
    ).filter(
        WorkOrder.created_at >= first_of_month,
        WorkOrder.person.in_(valid_names),
    ).group_by(WorkOrder.person).order_by(
        func.count(WorkOrder.id).desc()
    ).limit(10).all()
    return {p: cnt for p, cnt in rows}


def _get_daily_trend(now, person_filter=None, hospital_filter=None):
    """近7天每日工单数"""
    daily_stats = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        q = WorkOrder.query.filter(
            WorkOrder.created_at >= day_start,
            WorkOrder.created_at < day_end
        )
        if person_filter:
            q = q.filter(WorkOrder.person.in_(person_filter))
        if hospital_filter:
            q = hospital_filter(q)
        count = q.count()
        daily_stats.append({
            'date': day.strftime('%m/%d'),
            'count': count
        })
    return daily_stats


def _get_today_orders(today_start, person_filter=None, hospital_filter=None):
    """今日工单动态（最新20条）"""
    q = WorkOrder.query.filter(
        WorkOrder.created_at >= today_start
    )
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    return q.order_by(WorkOrder.created_at.desc()).limit(20).all()


def _get_building_stats(first_of_month, person_filter=None, hospital_filter=None):
    """各楼区本月工单分布"""
    q = WorkOrder.query
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    rows = q.with_entities(
        WorkOrder.building, func.count(WorkOrder.id)
    ).filter(
        WorkOrder.created_at >= first_of_month,
        WorkOrder.building != '',
        WorkOrder.building.isnot(None)
    ).group_by(WorkOrder.building).order_by(
        func.count(WorkOrder.id).desc()
    ).all()
    return {b: cnt for b, cnt in rows}


def _get_hot_locations(first_of_month, person_filter=None, hospital_filter=None):
    """本月热门报修位置 Top 5：building+floor+location 维度"""
    q = WorkOrder.query
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    rows = q.with_entities(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
        db.func.count(WorkOrder.id).label('loc_count'),
    ).filter(
        WorkOrder.created_at >= first_of_month,
        WorkOrder.building != '',
        WorkOrder.building.isnot(None),
    ).group_by(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
    ).order_by(
        db.desc('loc_count'),
    ).limit(5).all()
    return [(r.building or '', r.floor or '', r.location or '', r.loc_count) for r in rows]


def _get_dept_stats(first_of_month, person_filter=None, hospital_filter=None):
    """本月各科室工单排行"""
    q = WorkOrder.query
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    rows = q.with_entities(
        WorkOrder.department, func.count(WorkOrder.id)
    ).filter(
        WorkOrder.created_at >= first_of_month,
        WorkOrder.department != '',
        WorkOrder.department.isnot(None)
    ).group_by(WorkOrder.department).order_by(
        func.count(WorkOrder.id).desc()
    ).all()
    return {d: cnt for d, cnt in rows}


def _get_response_trend(person_filter=None, hospital_filter=None):
    """最近32条已完成工单的响应时长（分钟，过滤超过160分钟的异常数据）"""
    q = WorkOrder.query.with_entities(
        WorkOrder.id, WorkOrder.created_at, WorkOrder.completed_at
    ).filter(
        WorkOrder.completed_at.isnot(None),
    )
    if person_filter:
        q = q.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q = hospital_filter(q)
    orders = q.order_by(
        WorkOrder.completed_at.desc()
    ).all()

    trend = []
    for o in orders:
        minutes = round((o.completed_at - o.created_at).total_seconds() / 60, 1)
        if minutes > 160:
            continue  # 过滤异常数据（种子数据/跨天测试）
        trend.append({
            'month': o.completed_at.strftime('%m/%d %H:%M'),
            'count': 0,
            'avg_minutes': minutes,
        })
        if len(trend) >= 32:
            break

    trend.reverse()  # 时间正序
    overall_avg = round(sum(t['avg_minutes'] for t in trend) / len(trend), 1) if trend else 0
    return {'items': trend, 'overall_avg': overall_avg}


# ============ SLA 看板 ============

# SLA 阈值（小时）：{优先级: (响应阈值, 解决阈值)}
SLA_THRESHOLDS = {
    'emergency': (0.5, 2),
    'urgent': (2, 8),
    'normal': (4, 24),
}

def _get_sla_label(minutes):
    """根据分钟数返回响应评级"""
    if minutes <= 0: return "暂无数据"
    if minutes <= 30: return "响应极速"
    if minutes <= 60: return "响应快速"
    if minutes <= 120: return "响应较快"
    if minutes <= 240: return "响应一般"
    if minutes <= 480: return "响应较慢"
    return "响应很慢"

def _get_sla_stats(first_of_month, person_filter=None, hospital_filter=None):
    """获取本月 SLA 统计：人均响应/处理时长 + 超时工单数"""
    from flask import current_app,  g
    now = datetime.now()

    local_persons = set()
    try:
        hid = getattr(g, 'hospital_id', None)
        if hid:
            from models import User
            rows = User.query.filter(
                User.hospital_id == hid,
                User.is_active == True,
            ).all()
            local_persons = {r.display_name for r in rows if r.display_name}
    except Exception as e:
        current_app.logger.error(f'查询本地人员失败: {e}')

    # 本月工单
    q_sla = WorkOrder.query.filter(
        WorkOrder.created_at >= first_of_month,
    )
    if person_filter:
        q_sla = q_sla.filter(WorkOrder.person.in_(person_filter))
    if hospital_filter:
        q_sla = hospital_filter(q_sla)
    completed = q_sla.all()

    person_sla = {}
    overdue_count = 0

    for o in completed:
        p = o.person
        if not p or p == '管理员':
            continue
        # 只统计本院人员
        if local_persons and p not in local_persons:
            continue
        if p not in person_sla:
            person_sla[p] = {"total": 0, "resp": 0, "resol": 0, "resp_sum": 0.0, "resol_sum": 0.0, "overdue": 0}

        person_sla[p]["total"] += 1

        # 响应时长（创建 → 接单）
        resp_min = None
        if o.accepted_at and o.created_at:
            if o.completed_at and o.accepted_at > o.completed_at:
                # 接单时间在完成时间之后（数据异常），改用完成时间
                resp_min = abs((o.completed_at - o.created_at).total_seconds() / 60)
            else:
                resp_min = abs((o.accepted_at - o.created_at).total_seconds() / 60)
        elif o.completed_at and o.created_at:
            # 没有接单时间则用完成时间
            resp_min = abs((o.completed_at - o.created_at).total_seconds() / 60)
        if resp_min is not None and resp_min >= 0:
            person_sla[p]["resp_sum"] += resp_min
            person_sla[p]["resp"] += 1

        resol_min = None
        if o.completed_at and o.created_at:
            resol_min = abs((o.completed_at - o.created_at).total_seconds() / 60)
        elif o.accepted_at and o.created_at and o.status == 'in_progress':
            resol_min = abs((datetime.now() - o.accepted_at).total_seconds() / 60)
        if resol_min is not None and resol_min >= 0:
            person_sla[p]["resol_sum"] += resol_min
            person_sla[p]["resol"] += 1

        # 是否超时
        if o.status == "completed" and o.created_at and o.completed_at:
            cost_hours = (o.completed_at - o.created_at).total_seconds() / 3600
            resp_th, resol_th = SLA_THRESHOLDS.get(o.priority, (4, 24))
            if cost_hours > resol_th:
                person_sla[p]["overdue"] += 1
                overdue_count += 1
        elif o.status == "in_progress" and o.accepted_at:
            # 已接单处理中：对比处理时限
            elapsed_hours = (now - o.accepted_at).total_seconds() / 3600
            resp_th, resol_th = SLA_THRESHOLDS.get(o.priority, (4, 24))
            if elapsed_hours > resol_th:
                person_sla[p]["overdue"] += 1
                overdue_count += 1
        elif o.status == "pending" and o.created_at:
            # 未接单：对比响应时限
            elapsed_hours = (now - o.created_at).total_seconds() / 3600
            resp_th, resol_th = SLA_THRESHOLDS.get(o.priority, (4, 24))
            if elapsed_hours > resp_th:
                person_sla[p]["overdue"] += 1
                overdue_count += 1

    sla_items = []
    dist = {"极速":0, "快速":0, "较快":0, "一般":0, "较慢":0, "很慢":0, "暂无数据":0}
    for p, d in sorted(person_sla.items(), key=lambda x: x[1]["total"], reverse=True):
        avg_resp = round(d["resp_sum"] / d["resp"], 1) if d["resp"] else 0
        lbl = _get_sla_label(avg_resp)
        for k in dist:
            if k in lbl:
                dist[k] += 1
                break
        sla_items.append({
            "name": p,
            "total": d["total"],
            "avg_resp": avg_resp,
            "avg_resol": round(d["resol_sum"] / d["resol"], 1) if d["resol"] else 0,
            "overdue": d["overdue"],
            "sla_label": lbl,
        })

    return {
        "items": sla_items[:10],
        "overdue_count": overdue_count,
        "distribution": dist,
    }


# ====== 🥚 Easter Egg: 打砖块小游戏 ======
@main_bp.route('/easter-egg')
def easter_egg():
    """隐藏小游戏页面"""
    return render_template('easter_egg.html')
