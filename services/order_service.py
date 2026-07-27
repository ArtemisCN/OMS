"""
工单服务层 —— 所有工单业务逻辑收拢于此

职责：
  查询、创建、编辑、删除、批量、状态管理、统计
  路由层（orders.py）只负责 HTTP 请求/响应编排
"""
import json
import random
from datetime import datetime, timedelta
from collections import defaultdict

from models import db, WorkOrder, SolutionTemplate, User, WorkOrderPhoto
from models import log_audit
from services.address import get_merged_addresses, get_all_buildings
from services.fault_matcher import match_fault
from services import generator


# ==================== 查询 ====================

def build_order_query(filters, user=None):
    """构建工单查询（筛选条件复用，自动按 g.hospital_id 过滤）"""
    query = WorkOrder.query
    # 自动按当前医院过滤
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    if hid and hid != 0:
        query = query.filter(WorkOrder.hospital_id == hid)
    status = filters.get('status', '')
    if status in ('pending', 'in_progress', 'completed'):
        query = query.filter(WorkOrder.status == status)

    ft = filters.get('fault_type', '')
    if ft:
        query = query.filter(WorkOrder.fault_type == ft)

    person = filters.get('person', '')
    if person:
        query = query.filter(WorkOrder.person == person)

    keyword = filters.get('keyword', '')
    if keyword:
        query = query.filter(
            WorkOrder.title.contains(keyword) |
            WorkOrder.location.contains(keyword) |
            WorkOrder.floor.contains(keyword) |
            WorkOrder.description.contains(keyword) |
            WorkOrder.fault_subcategory.contains(keyword)
        )

    date_from = filters.get('date_from', '')
    if date_from:
        try:
            dt = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(WorkOrder.start_time >= dt)
        except ValueError:
            pass

    date_to = filters.get('date_to', '')
    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(WorkOrder.start_time < dt)
        except ValueError:
            pass

    building = filters.get('building', '')
    if building:
        query = query.filter(WorkOrder.building == building)

    floor_sel = filters.get('floor', '')
    if floor_sel:
        query = query.filter(WorkOrder.floor.contains(floor_sel))

    location_sel = filters.get('location', '')
    if location_sel:
        query = query.filter(WorkOrder.location.contains(location_sel))

    department = filters.get('department', '')
    if department:
        query = query.filter(WorkOrder.department == department)

    # 组别筛选
    team = filters.get('team', '')
    if team and status != 'pending':
        team_persons = User.query.filter(
            User.team == team, User.is_active == True
        ).all()
        team_names = [p.display_name for p in team_persons if p.display_name]
        if team_names:
            query = query.filter(WorkOrder.person.in_(team_names))
        else:
            query = query.filter(db.text('1=0'))  # 该组无人返回空

    from sqlalchemy import case
    priority_order = case(
        (WorkOrder.priority == 'emergency', 0),
        (WorkOrder.priority == 'urgent', 1),
        else_=2
    )

    # 排序
    sort_field = filters.get('sort', '')
    sort_order = filters.get('order', '')
    if sort_field and sort_order in ('asc', 'desc'):
        col = getattr(WorkOrder, sort_field, None)
        if col:
            order_fn = getattr(col, sort_order)
            query = query.order_by(order_fn())
            return query

    query = query.order_by(priority_order, WorkOrder.start_time.desc())
    return query


def get_order_or_404(order_id):
    """获取单个工单，不存在则抛出 404"""
    return WorkOrder.query.get_or_404(order_id)


def get_order_photos(order_id):
    """获取工单关联照片"""
    return WorkOrderPhoto.query.filter_by(
        work_order_id=order_id
    ).order_by(WorkOrderPhoto.created_at.desc()).all()


# ==================== 筛选辅助数据 ====================

def get_filter_data(team=None):
    """获取工单列表页所需的下拉数据（按当前医院和分组过滤人员）"""
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    q = User.query.filter(User.is_active == True)
    if hid and hid != 0:
        q = q.filter(User.hospital_id == hid)
    if team:
        q = q.filter(User.team == team)
    persons = q.order_by(User.sort_order, User.display_name).all()
    buildings = get_all_buildings()
    teams = [
        t[0] for t in
        User.query.with_entities(User.team)
        .filter(User.team != '', User.team.isnot(None))
        .distinct().order_by(User.team).all()
    ]
    return persons, buildings, teams


def get_order_stats():
    """三个池子的数量统计（按当前医院过滤）"""
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    base = WorkOrder.query
    if hid and hid != 0:
        base = base.filter(WorkOrder.hospital_id == hid)
    return {
        'pending': base.filter_by(status='pending').count(),
        'in_progress': base.filter_by(status='in_progress').count(),
        'completed': base.filter_by(status='completed').count(),
    }


# ==================== 创建 ====================

def create_order(form_data, created_by):
    """手动创建单条工单"""
    title = form_data.get('title', '').strip()
    if not title:
        raise ValueError('请输入工单名称')

    # 自动匹配故障分类
    fm = match_fault(title)
    order = WorkOrder(
        title=title,
        device_type=form_data.get('device_type', '其他'),
        fault_type=form_data.get('fault_type', '硬件'),
        fault_subcategory=fm.get('subcategory', ''),
        description=form_data.get('description', ''),
        building=form_data.get('building', ''),
        floor=form_data.get('floor', ''),
        department=form_data.get('department', ''),
        location=form_data.get('location', ''),
        person=form_data.get('person', ''),
        solution=form_data.get('solution', ''),
        created_by=created_by,
    )
    # 后台创建时直接指派人员视为已接单
    if order.person:
        order.accepted_at = datetime.now()

    # 解析时间
    _parse_times(order, form_data)

    db.session.add(order)
    db.session.commit()
    return order


def _parse_times(order, form_data):
    """解析表单中的时间字段"""
    st = form_data.get('start_time', '')
    et = form_data.get('end_time', '')
    if st:
        try:
            order.start_time = datetime.strptime(st, '%Y-%m-%d %H:%M')
        except ValueError:
            pass
    if et:
        try:
            order.end_time = datetime.strptime(et, '%Y-%m-%d %H:%M')
        except ValueError:
            pass


def publish_order(form_data, created_by, user_person=None):
    """发布工单（自动识别地址+故障）"""
    title = form_data.get('title', '').strip()
    if not title:
        raise ValueError('请输入工单名称')

    team = form_data.get('team', '')

    # 自动匹配
    from services.keyword_config import get_fault_keywords, get_device_keywords
    fault, device = _guess_fault_type(title, get_fault_keywords(), get_device_keywords())
    fm = match_fault(title, team=team)
    auto_fault = fm['category'] if fm['match_type'] == 'keyword' else fault

    # 自动提取地址（表单手动选择的优先）
    from services.address import extract_address_from_title
    addr = extract_address_from_title(title)
    building = form_data.get('building', '') or addr['building']
    floor = form_data.get('floor', '') or addr['floor']
    department = form_data.get('department', '') or addr['department']
    location = form_data.get('location', '') or addr.get('location', '')

    now = datetime.now()
    order = WorkOrder(
        title=title,
        device_type=device,
        fault_type=auto_fault,
        fault_subcategory=form_data.get('fault_subcategory', '') or fm.get('subcategory', ''),
        description='',
        building=building,
        floor=floor,
        department=department,
        location=location,
        person='',  # 不指派，手机端公共池接单
        solution='',
        start_time=now,
        status='pending',
        created_by=created_by,
        priority=form_data.get('priority', 'normal'),
        original_priority=form_data.get('priority', 'normal'),
    )
    db.session.add(order)
    db.session.commit()
    return order


def _guess_fault_type(title, fault_keywords, device_keywords):
    """根据工单名称匹配故障类型和设备类型"""
    title_lower = title.lower()
    for ftype, keywords in fault_keywords.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                return ftype, ''
    for dtype, keywords in device_keywords:
        for kw in keywords:
            if kw.lower() in title_lower:
                device_types = {
                    '电脑': '硬件', '网络设备': '硬件', '叫号设备': '硬件',
                    '自助机': '硬件', 'PDA': '硬件', '扫码设备': '硬件',
                    '切换器': '硬件', '显示器': '硬件', '键盘': '硬件', '鼠标': '硬件',
                    '打印机': '打印机', '软件': '软件',
                }
                return device_types.get(dtype, '硬件'), dtype
    return '硬件', '其他'


# ==================== 编辑/删除 ====================

def update_order(order_id, form_data):
    """编辑工单字段"""
    order = WorkOrder.query.get_or_404(order_id)
    order.title = form_data.get('title', order.title)
    order.fault_type = form_data.get('fault_type', order.fault_type)
    order.fault_subcategory = form_data.get('fault_subcategory', order.fault_subcategory or '')
    order.building = form_data.get('building', order.building)
    order.floor = form_data.get('floor', order.floor)
    order.department = form_data.get('department', order.department)
    order.location = form_data.get('location', order.location)
    order.person = form_data.get('person', order.person)
    if order.person and not order.accepted_at:
        order.accepted_at = datetime.now()
    order.status = form_data.get('status', order.status)
    order.solution = form_data.get('solution', order.solution)
    # 自动记录结单时间
    if order.status == 'completed' and not order.completed_at:
        order.completed_at = datetime.now()
        order.end_time = datetime.now()
    elif order.status != 'completed' and order.completed_at:
        order.completed_at = None
    # 已结单工单不允许修改紧急程度
    db_order = WorkOrder.query.with_entities(WorkOrder.status).filter_by(id=order_id).first()
    if db_order and db_order[0] != 'completed':
        order.priority = form_data.get('priority', order.priority or 'normal')
    if form_data.get('quick_complete'):
        order.status = 'completed'
    db.session.commit()
    return order


def delete_order(order_id, operator):
    """删除工单"""
    order = WorkOrder.query.get_or_404(order_id)
    title = order.title
    db.session.delete(order)
    db.session.commit()
    log_audit('delete', 'work_order', operator,
              target_id=order_id, target_desc=f'删除工单#{order_id}: {title}')


# ==================== 优先级 ====================

def toggle_priority(order_id):
    """轮换优先级 normal → urgent → emergency → normal"""
    order = WorkOrder.query.get_or_404(order_id)
    if order.status == 'completed':
        raise ValueError('已结单工单不允许修改紧急程度')
    cycle = {'normal': 'urgent', 'urgent': 'emergency', 'emergency': 'normal'}
    order.priority = cycle.get(order.priority or 'normal', 'normal')
    db.session.commit()
    return order.priority


# ==================== 批量生成 ====================

def get_batch_form_data(user, selected_team=None):
    """批量生成页面的表单辅助数据"""
    persons = User.query.filter(User.is_active==True).order_by(User.sort_order, User.display_name).all()
    _person = User.query.filter_by(id=user.id).first()

    # 按当前医院过滤（g.hospital_id，管理员切换医院后也适用）
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    if hid:
        persons = [p for p in persons if p.hospital_id == hid]
    
    # 如果指定了组，过滤人员和方案
    if selected_team and selected_team != 'all':
        query = SolutionTemplate.query.filter(
            db.or_(
                SolutionTemplate.teams == '',
                SolutionTemplate.teams.contains(selected_team),
            )
        )
        persons = [p for p in persons if p.team == selected_team]
    else:
        query = SolutionTemplate.query
        if _person and _person.team:
            query = query.filter(db.or_(
                SolutionTemplate.teams == '',
                SolutionTemplate.teams.contains(_person.team),
            ))
    templates = query.order_by(SolutionTemplate.title).all()

    # 故障模板组
    from models import FaultTemplateGroup, FaultTemplateItem
    fault_groups = FaultTemplateGroup.query.order_by(FaultTemplateGroup.id).all()
    fault_group_items = {}
    for g in fault_groups:
        fault_group_items[g.id] = FaultTemplateItem.query.filter_by(
            group_id=g.id
        ).order_by(FaultTemplateItem.sort_order).all()

    # 按组分
    team_groups = {}
    for p in persons:
        t = p.team or '未分组'
        if t not in team_groups:
            team_groups[t] = []
        team_groups[t].append(p)
    teams = sorted(team_groups.keys(), key=lambda x: (x == '未分组', x))

    # 默认组
    from models import SystemSetting
    default_team_setting = SystemSetting.query.filter_by(key='default_dashboard_team').first()
    default_team_val = default_team_setting.value if default_team_setting and default_team_setting.value else ''

    return persons, templates, fault_groups, fault_group_items, team_groups, teams, default_team_val


def batch_preview(form_data, user):
    """批量生成第一步：生成预览数据"""
    from models import FaultTemplateItem

    # 收集动态故障类型数量（支持新旧两种格式）
    fault_counts = {}
    fault_details = {}
    total = 0

    # 新格式：勾选方式，checkbox 传 item ID
    checked_items = form_data.getlist('fault_group_item')
    if checked_items:
        from models import FaultTemplateItem
        for item_id_str in checked_items:
            try:
                item_id = int(item_id_str)
                item = FaultTemplateItem.query.get(item_id)
                if item:
                    count = item.default_count or 1
                    fault_counts[item.id] = count
                    fault_details[item.id] = {
                        'fault_type': item.fault_type,
                        'display_name': item.display_name,
                    }
                    total += count
            except (ValueError, TypeError):
                pass

    # 旧格式兼容：fault_count_ 前缀
    if total == 0:
        for key, val in form_data.items():
            if key.startswith('fault_count_'):
                try:
                    item_id = int(key.replace('fault_count_', ''))
                    count = max(0, int(val))
                    if count > 0:
                        item = FaultTemplateItem.query.get(item_id)
                        if item:
                            fault_counts[item.id] = count
                            fault_details[item.id] = {
                                'fault_type': item.fault_type,
                                'display_name': item.display_name,
                            }
                            total += count
                except (ValueError, TypeError):
                    pass

    # 兼容旧格式
    if total == 0:
        software = max(0, int(form_data.get('software', 0)))
        hardware = max(0, int(form_data.get('hardware', 0)))
        printer = max(0, int(form_data.get('printer', 0)))
        assist = max(0, int(form_data.get('assist', 0)))
        total = software + hardware + printer + assist
        if total > 0:
            for _ in range(software):
                fault_counts[len(fault_counts)] = 1
                fault_details[len(fault_counts)] = {'fault_type': '软件', 'display_name': '软件故障'}
            for _ in range(hardware):
                fault_counts[len(fault_counts)] = 1
                fault_details[len(fault_counts)] = {'fault_type': '硬件', 'display_name': '硬件故障'}
            for _ in range(printer):
                fault_counts[len(fault_counts)] = 1
                fault_details[len(fault_counts)] = {'fault_type': '打印机', 'display_name': '打印机故障'}
            for _ in range(assist):
                fault_counts[len(fault_counts)] = 1
                fault_details[len(fault_counts)] = {'fault_type': '协助', 'display_name': '协助类'}

    if total == 0:
        raise ValueError('请至少生成一个工单')

    year = int(form_data.get('year', datetime.now().year))
    month = int(form_data.get('month', datetime.now().month))
    min_per_day = int(form_data.get('min_per_day', 20))
    max_per_day = int(form_data.get('max_per_day', 45))
    everyday = form_data.get('everyday') == 'on'

    # 解析指定日期
    specific_dates = None
    dates_str = form_data.get('specific_dates', '').strip()
    if dates_str:
        specific_dates = _parse_dates(dates_str)

    # 安全验证
    verify_username = form_data.get('verify_username', '').strip()
    verify_password = form_data.get('verify_password', '')
    if not verify_username or not verify_password:
        raise ValueError('请输入登录账号和密码进行安全验证')
    user_obj = User.query.filter_by(username=verify_username).first()
    if not user_obj or not user_obj.check_password(verify_password):
        raise ValueError('安全验证失败：账号或密码错误')

    names = form_data.getlist('selected_names')
    if not names:
        raise ValueError('请至少勾选一名人员')

    weights = {}
    for name in names:
        w = form_data.get(f'weight_{name}', '1').strip()
        try:
            wv = int(w)
            if wv >= 1:
                weights[name] = wv
        except ValueError:
            pass

    use_schedule = form_data.get('use_schedule') == 'on'

    orders_data = generator.create_batch_orders(
        fault_counts, fault_details,
        year, month, min_per_day, max_per_day, everyday, names,
        created_by=user.display_name or user.username,
        specific_dates=specific_dates,
        custom_title=form_data.get('custom_title', '').strip() or None,
        custom_solution=form_data.get('custom_solution', '').strip() or None,
        weights=weights,
        use_schedule=use_schedule,
    )

    # 序列化 datetime
    def serialize_order(o):
        row = dict(o)
        for key in ('start_time', 'end_time'):
            if isinstance(row.get(key), datetime):
                row[key] = row[key].strftime('%Y-%m-%d %H:%M')
        return row

    serialized = [serialize_order(o) for o in orders_data]

    # 按日期分组
    by_date = defaultdict(list)
    for o in serialized:
        d = o['start_time'][:10] if o['start_time'] else '未知日期'
        by_date[d].append(o)
    sorted_dates = sorted(by_date.keys())

    return serialized, by_date, sorted_dates, total


def batch_confirm(preview_json, user):
    """批量生成第二步：确认保存到数据库"""
    if not preview_json:
        raise ValueError('预览数据丢失，请重新生成')

    orders_data = json.loads(preview_json)
    total = len(orders_data)

    for od in orders_data:
        order = WorkOrder(
            title=od['title'],
            device_type=od['device_type'],
            fault_type=od['fault_type'],
            fault_subcategory=od.get('fault_subcategory', ''),
            description=od['description'],
            building=od['building'],
            floor=od['floor'],
            department=od['department'],
            location=od['location'],
            person=od['person'],
            solution=od['solution'],
            created_by=od['created_by'],
            priority=od.get('priority', 'normal'),
            original_priority=od.get('original_priority', od.get('priority', 'normal')),
            status='completed',
        )
        if od.get('person'):
            order.accepted_at = order.created_at
        if od.get('start_time'):
            try:
                st = datetime.strptime(od['start_time'], '%Y-%m-%d %H:%M')
                order.start_time = st
                order.created_at = st
            except ValueError:
                pass
        if od.get('end_time'):
            try:
                order.end_time = datetime.strptime(od['end_time'], '%Y-%m-%d %H:%M')
            except ValueError:
                pass
        base_t = order.end_time or order.start_time or datetime.now()
        order.completed_at = base_t + timedelta(minutes=random.randint(0, 10))
        db.session.add(order)
    db.session.commit()

    # 查询刚插入的工单ID
    recent = WorkOrder.query.filter_by(
        created_by=user.display_name or user.username
    ).order_by(WorkOrder.id.desc()).limit(total).all()

    return total, [o.id for o in recent]


def batch_undo(batch_ids):
    """撤回最近一次批量生成的工单"""
    if not batch_ids:
        raise ValueError('没有可撤回的批次')
    deleted = 0
    for oid in batch_ids:
        order = WorkOrder.query.get(oid)
        if order:
            db.session.delete(order)
            deleted += 1
    db.session.commit()
    return deleted


def _parse_dates(dates_str):
    """解析逗号分隔的日期表达式（支持 1,3,5-10,15,20 格式）"""
    dates = []
    for part in dates_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                a, b = part.split('-', 1)
                for d in range(int(a.strip()), int(b.strip()) + 1):
                    dates.append(d)
            except ValueError:
                pass
        else:
            try:
                dates.append(int(part))
            except ValueError:
                pass
    return sorted(set(dates)) if dates else None


# ==================== API 辅助 ====================

def api_guess_fault(title, team=''):
    """根据工单名称猜测故障类型+设备类型+地址"""
    if not title:
        return {
            'fault': '硬件', 'device': '其他',
            'building': '', 'floor': '', 'department': '', 'location': '',
        }
    from services.keyword_config import get_fault_keywords, get_device_keywords
    fault, device = _guess_fault_type(title, get_fault_keywords(), get_device_keywords())
    fm = match_fault(title, team=team)
    from services.address import extract_address_from_title
    addr = extract_address_from_title(title)
    return {
        'fault': fm['category'] if fm['match_type'] == 'keyword' else fault,
        'device': device,
        'fault_subcategory': fm.get('subcategory', ''),
        'building': addr['building'],
        'floor': addr['floor'],
        'department': addr['department'],
        'location': addr.get('location', ''),
    }


def api_solution_suggest(query, user):
    """根据关键字返回方案模板候选"""
    if not query or len(query) < 1:
        return []
    _person = User.query.filter_by(id=user.id).first()
    q = SolutionTemplate.query.filter(
        SolutionTemplate.title.contains(query)
    )
    if _person and _person.team:
        q = q.filter(db.or_(
            SolutionTemplate.teams == '',
            SolutionTemplate.teams.contains(_person.team),
        ))
    templates = q.order_by(SolutionTemplate.title).limit(20).all()
    seen = set()
    result = []
    for t in templates:
        if t.title not in seen:
            seen.add(t.title)
            result.append(t.title)
    return result


def api_address_all(team=''):
    """返回所有地址数据"""
    merged = get_merged_addresses(team=team)
    seen = set()
    result = []
    for a in merged:
        location = a.get('物理地址', '')
        building = a.get('楼区', '')
        floor = a.get('所属楼层', '')
        department = a.get('所属科室', '')
        key = f"{building}|{floor}|{location}"
        if location and key not in seen:
            seen.add(key)
            result.append({
                'location': location,
                'building': building,
                'floor': floor,
                'department': department,
            })
    return {'locations': result}


def api_address_options(building, floor, team=''):
    """返回级联下拉框选项"""
    from services.address import (
        get_floors_by_building, get_departments_by_floor,
        get_locations_by_floor, get_all_buildings,
    )
    if building == 'all':
        return {'buildings': get_all_buildings(team=team)}
    if not building:
        return []
    if floor:
        return {
            'departments': get_departments_by_floor(building, floor, team=team),
            'locations': get_locations_by_floor(building, floor, team=team),
        }
    return {'floors': get_floors_by_building(building, team=team)}


# ==================== 创建页辅助 ====================

def get_create_page_data(user):
    """获取新建工单页面的辅助数据"""
    persons = User.query.filter(User.is_active==True).order_by(User.sort_order, User.display_name).all()
    _person = User.query.filter_by(id=user.id).first()

    # 按当前医院过滤
    from flask import g
    hid = getattr(g, 'hospital_id', None)
    if hid:
        persons = [p for p in persons if p.hospital_id == hid]

    query = SolutionTemplate.query
    if _person and _person.team:
        query = query.filter(db.or_(
            SolutionTemplate.teams == '',
            SolutionTemplate.teams.contains(_person.team),
        ))
    templates = query.order_by(SolutionTemplate.title).all()
    return persons, templates
