"""重复单分析路由"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import WorkOrder, db, can_access, SystemSetting
from datetime import datetime, timedelta
from urllib.parse import urlencode

analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis')


@analysis_bp.route('/repeats')
@login_required
def repeats():
    """重复单分析页面"""
    if not can_access('重复单分析'):
        return "无权访问", 403
    return render_template('analysis/repeats.html', now=datetime.now())


@analysis_bp.route('/api/repeats')
@login_required
def api_repeats():
    """重复单分析 API"""
    if not can_access('重复单分析'):
        return jsonify({'error': '无权访问'}), 403

    mode = request.args.get('mode', 'month')  # year / month / week
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    week = request.args.get('week', 0, type=int)
    min_count = request.args.get('min', 2, type=int)

    # 计算时间范围
    if mode == 'year':
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
    elif mode == 'week':
        # 计算某年某月的第N周
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)
        # week 为0表示整个月
        if week <= 0:
            start = month_start
            end = month_end
        else:
            # 该月第一天所在周
            first_weekday = month_start.weekday()  # 0=周一
            week_start = month_start + timedelta(weeks=week - 1)
            # 修正：week_start取该周的周一
            days_from_monday = week_start.weekday()
            week_start = week_start - timedelta(days=days_from_monday)
            week_end = week_start + timedelta(weeks=1)
            # 限制在月内
            start = max(week_start, month_start)
            end = min(week_end, month_end)
    else:  # month
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

    # 查询重复单：按位置+故障分组，计数>=min_count
    rows = db.session.query(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
        WorkOrder.fault_type,
        WorkOrder.fault_subcategory,
        WorkOrder.device_type,
        db.func.count(WorkOrder.id).label('repeat_count'),
        db.func.min(WorkOrder.created_at).label('first_time'),
        db.func.max(WorkOrder.created_at).label('last_time'),
    ).filter(
        WorkOrder.created_at >= start,
        WorkOrder.created_at < end,
    ).group_by(
        WorkOrder.building,
        WorkOrder.floor,
        WorkOrder.location,
        WorkOrder.fault_type,
        WorkOrder.fault_subcategory,
    ).having(
        db.func.count(WorkOrder.id) >= min_count,
    ).order_by(
        db.desc('repeat_count'),
        db.desc('last_time'),
    ).all()

    # 汇总统计
    total_repeats = sum(r.repeat_count for r in rows)
    total_locations = len(rows)
    max_repeat = rows[0].repeat_count if rows else 0

    # 按楼栋分组统计
    building_stats = {}
    for r in rows:
        b = r.building or '未知'
        if b not in building_stats:
            building_stats[b] = {'count': 0, 'locations': 0}
        building_stats[b]['count'] += r.repeat_count
        building_stats[b]['locations'] += 1

    # 格式化为列表
    items = []
    for r in rows:
        # 拼接完整位置
        parts = [p for p in [r.building, r.floor, r.location] if p]
        full_location = '-'.join(parts) if parts else '未知'

        # 构造跳转链接：跳转到工单列表筛选该位置+故障的工单
        params = {}
        if r.building:
            params['building'] = r.building
        if r.fault_type:
            params['fault_type'] = r.fault_type
        if r.floor:
            params['floor'] = r.floor
        if r.location:
            params['location'] = r.location
        params['status'] = ''
        link_url = '/orders/?' + urlencode(params)

        items.append({
            'location': full_location,
            'building': r.building or '未知',
            'floor': r.floor,
            'detail_location': r.location,
            'fault_type': r.fault_type,
            'fault_subcategory': r.fault_subcategory,
            'device_type': r.device_type,
            'count': r.repeat_count,
            'first_time': r.first_time.strftime('%Y-%m-%d') if r.first_time else '',
            'last_time': r.last_time.strftime('%Y-%m-%d') if r.last_time else '',
            'link_url': link_url,
        })

    # 时间标签
    if mode == 'year':
        time_label = f'{year}年'
    elif mode == 'week' and week > 0:
        time_label = f'{year}年{month}月第{week}周'
    elif mode == 'week':
        time_label = f'{year}年{month}月'
    else:
        time_label = f'{year}年{month}月'

    return jsonify({
        'items': items,
        'stats': {
            'total_repeats': total_repeats,
            'total_locations': total_locations,
            'max_repeat': max_repeat,
            'time_label': time_label,
        },
        'building_stats': [
            {'name': k, 'count': v['count'], 'locations': v['locations']}
            for k, v in sorted(building_stats.items(),
                               key=lambda x: x[1]['count'], reverse=True)
        ],
    })


# ==================== 故障热力图 ====================

@analysis_bp.route('/heatmap')
@login_required
def heatmap():
    """故障热力图"""
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    q = WorkOrder.query
    if hid:
        q = q.filter_by(hospital_id=hid)
    orders = q.all()
    # 按楼栋统计
    building_stats = {}
    for o in orders:
        b = o.building or '未知'
        if b not in building_stats:
            building_stats[b] = {'count': 0, 'departments': {}}
        building_stats[b]['count'] += 1
        d = o.department or '未知'
        building_stats[b]['departments'][d] = building_stats[b]['departments'].get(d, 0) + 1
    heatmap_data = sorted(building_stats.items(), key=lambda x: -x[1]['count'])
    # 按楼层统计
    floor_data = {}
    for o in orders:
        fl = o.floor or '0'
        floor_data[fl] = floor_data.get(fl, 0) + 1
    floor_ranking = sorted(floor_data.items(), key=lambda x: -x[1])
    return render_template('analysis/heatmap.html', heatmap_data=heatmap_data,
                           floor_ranking=floor_ranking)
