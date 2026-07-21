"""系统参数设置 + 科室字典管理"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from models import db, SystemSetting, Department, Person
from routes.auth import admin_required

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')


# ==================== 系统参数 ====================

# 个人偏好设置（覆盖全局的同名参数）
PERSONAL_PREF_KEYS = [
    'primary_color', 'default_dark_mode', 'table_density',
    'sidebar_auto_hide_seconds', 'sidebar_default_expand', 'animation_enabled',
    'default_hospital_id', 'default_dashboard_team', 'order_page_size',
    'mobile_page_size', 'default_fault_type', 'default_priority',
    'person_sort_order', 'person_show_inactive',
    'search_default_days', 'order_attachment_limit', 'daily_order_limit',
    'hide_closed_orders', 'default_order_sort',
]


@settings_bp.route('/')
@admin_required
def index():
    """系统参数设置页"""
    from models import Hospital, FaultType
    categories = db.session.query(SystemSetting.category).distinct().order_by(SystemSetting.category).all()
    cat_list = [c[0] for c in categories] if categories else ['基本']
    # 后端过滤隐藏参数
    hidden_keys = ['wecom_webhook_url', 'wecom_push_enabled', 'module_permissions', 'order_prefix']
    all_settings = SystemSetting.query.order_by(SystemSetting.category, SystemSetting.id).all()
    settings = [s for s in all_settings if s.key not in hidden_keys]
    # 自动补全缺失的默认参数
    existing_keys = {s.key for s in all_settings}
    defaults = [
        ('person_teams', '信息科,后勤,外包服务', '可选人员组别', '人员管理里「组别」下拉菜单的可选项，回车添加新组，逗号分隔', '人员'),
        ('person_sort_order', 'team', '人员列表排序', '人员列表按什么顺序排：按组别分组显示，还是按姓名拼音排序，选一个方便的', '人员'),
        ('person_show_inactive', '0', '显示已离职人员', '人员列表要不要把离职或停用的人也列出来？默认不显示，列表更清爽', '人员'),
        ('person_default_team', '', '默认人员组别', '新增人员时自动分配到这个组别，省得每次手动选。留空就不自动填', '人员'),
        ('auto_refresh_interval', '30', '仪表盘自动刷新', '仪表盘每隔几秒自动刷一次数据，设30秒刚刚好。设0就只手动刷新，不会自动更新', '仪表盘'),
        ('default_dashboard_team', '', '仪表盘默认组别', '打开仪表盘时默认看哪个组的数据，留空就看全部组别', '仪表盘'),
        ('default_fault_type', '硬件', '新建工单默认故障类型', '新建工单时自动选中的故障类型，发单页可以随时换', '工单'),
        ('default_priority', 'normal', '新建工单默认紧急程度', '新工单的紧急等级：普通=一般报修不影响工作，加急=影响正常工作了，紧急=大面积故障停摆了', '工单'),
        ('order_page_size', '20', '工单列表每页条数', '工单列表一页显示多少条，设得越高加载越慢，一般20~50比较合适', '工单'),
        ('photo_quality', '50', '照片压缩质量', '上传照片的压缩质量，1~100，数值越大越清晰但文件也越大，建议50~70兼顾清晰度和上传速度', '工单'),
        ('auto_close_days', '0', '工单超时自动关闭', '工单超过多少天没人更新就自动标为已关闭，省得陈年老单占着列表。设0就不自动关', '工单'),
        ('order_prefix', '', '工单编号前缀', '工单编号前面加个自定义前缀，比如「七院-」或「2024-」，方便区分来源。留空就没前缀', '工单'),
        ('upload_max_mb', '20', '上传大小限制', '每张照片最大能传多少MB，设太大上传慢，一般10~20MB够用了', '工单'),
        ('default_order_sort', 'newest', '工单默认排序方式', '工单列表打开时默认按什么排：最新在前、最早在前、紧急优先、还是最近更新的排前面', '工单'),
        ('hide_closed_orders', '0', '默认隐藏已关闭工单', '工单列表默认是否隐藏已关闭的单子？建议打开，不然列表全是历史记录看不清', '工单'),
        ('editable_window_minutes', '30', '工单可编辑时长', '工单发出去之后多少分钟内还能修改，设30分钟够用。设0就任何时候都能改', '工单'),
        ('photo_max_dim', '1280', '照片最大边长', '上传照片时自动压缩到的最大边长（像素），1280=720p清晰度，1920=高清，设0就不压缩原图上传', '工单'),
        ('default_export_format', 'excel', '数据导出格式', '导出数据时默认保存成什么格式，Excel最常用，也可以选CSV', '工单'),
        ('mobile_page_size', '20', '手机端每页条数', '手机端一页显示多少条，手机屏幕小建议15~20条就够了，太多要划半天', '工单'),
        ('maintenance_reminder_days', '30', '保修到期提醒天数', '资产保修快到期时提前多少天标出来提醒你，设30天就是提前一个月提醒', '资产'),
        ('asset_page_size', '20', '资产列表每页条数', '资产台账列表一页显示多少条，根据资产总量来调，量大的可以设多些', '资产'),
        ('asset_code_prefix', '', '资产编号前缀', '资产编号前面加个前缀区分类别，比如「ZC-」代表资产、「SB-」代表设备。留空就没前缀', '资产'),
        ('asset_default_status', '在库', '默认资产状态', '新增资产时默认填什么状态，通常是「在库」。如果大部分在借用可以改成「使用中」', '资产'),
        ('sidebar_auto_hide_seconds', '0', '侧边栏自动收起', '鼠标不动后等几秒自动收起侧边栏，给屏幕腾地方。设0就不自动收', '界面'),
        ('default_hospital_id', '', '默认显示医院', '登录后默认看哪个医院的数据，留空就看全部或者记住上次选的', '界面'),
        ('default_dark_mode', 'light', '默认深色模式', '登录后默认用深色还是浅色主题，随时可以手动切换', '界面'),
        ('primary_color', '#4f46e5', '系统主色调', '系统的主题颜色，改了这个按钮、链接、高亮都会跟着变，选一个你们医院喜欢的颜色', '界面'),
        ('table_density', 'comfortable', '表格行密度', '表格的行间距：紧凑=一屏看更多行，适中=默认，宽松=更易阅读', '界面'),
        ('font_scale', '100', '字体缩放比例', '全局字体大小，100是默认，110略大，120更大。年纪大点的用户建议设110，调完刷新页面生效', '界面'),
        ('sidebar_default_expand', '1', '侧边栏默认展开', '登录后侧边栏默认是展开还是收起？展开看得全，收起屏幕更宽，看个人习惯', '界面'),
        ('animation_enabled', '1', '页面动画效果', '页面切换和点击时的动画效果开关，开着好看，关着更流畅，看个人喜好', '界面'),
        ('daily_order_limit', '0', '每日工单上限', '每个人每天最多能提交多少个工单，防止刷单。设0就是不限制', '工单'),
        ('order_attachment_limit', '9', '工单附件数量上限', '一个工单最多能传几张照片或附件，设太多上传会慢，一般9张够用了', '工单'),
        ('order_title_template', '{fault}{device}{location}', '工单标题自动生成', '工单发布时标题怎么自动拼，可用{fault}故障类型、{device}设备名、{location}位置。比如「{device}{fault}报修」', '工单'),
        ('order_remind_interval', '30', '催单最短间隔', '同一个工单催一次之后至少隔多少分钟才能再催，设太短容易招人烦，建议30分钟以上', '工单'),
        ('order_delete_window', '60', '工单可删除时长', '工单发出去后多少分钟内还能删掉，过了时间就只能关闭不能删了。设0就不让删', '工单'),
        ('default_device_type', '电脑', '默认设备类型', '新建工单时设备类型默认选什么，根据你们报修最多的设备来设，省得每次手动选', '工单'),
        ('daily_summary_enabled', '0', '每日工单汇总推送', '每天晚上自动把当天工单汇总推送到企业微信，让管理层一眼看清当天工作情况', '通知'),
        ('notify_order_complete', '1', '工单完成通知', '工单修好了标记完成的时候，要不要发通知告诉提交人一声？开着省得人家一直干等', '通知'),
        ('notify_order_assign', '1', '工单分配通知', '工单派给负责人的时候要不要通知一下？开着免得派了没人知道', '通知'),
        ('wecom_push_template_today',
         '## 📊 {date} 工单汇总\n\n> **今日工单：{total} 条**\n> ✅ 已完成：{done} 条\n> ⏳ 未完成：{unfinished} 条（待接单 {pending} · 处理中 {in_progress}）\n\n**工单类型**\n{faults_list}\n\n> ⚡ 紧急/加急：{urgent} 单\n\n**楼区分布**\n{buildings_list}',
         '今日工单推送模板',
         '每日工单汇总推送到企业微信的消息模板，支持变量：{total}总单数 {done}已完成 {pending}待接单 {in_progress}处理中 {unfinished}未完成 {urgent}紧急/加急 {date}日期 {faults_list}故障类型列表 {buildings_list}楼区分布',
         '通知'),
        ('wecom_push_template_unaccepted',
         '## 📋 未接单工单提醒\n\n> **当前未接单：{total} 条**\n> ⏰ 超24小时未接单：{overdue} 条\n\n**工单类型**\n{faults_list}\n\n> ⚡ 紧急/加急：{urgent} 单\n\n**楼区分布**\n{buildings_list}',
         '未接单工单提醒模板',
         '手动推送未接单工单时用的消息模板，额外支持变量：{overdue}超24小时未接单数，其他变量同上',
         '通知'),
        ('audit_log_retention_days', '365', '审计日志保留天数', '操作日志保留多少天，超过就自动清理省数据库空间。365天就是一年，设0就永远不删', '系统'),
        ('password_min_length', '6', '密码最小长度', '用户设密码最少要几位？建议至少6位，太短不安全，太长大家记不住', '系统'),
        ('timezone', 'Asia/Shanghai', '系统时区', '系统用的时区，国内一般就是Asia/Shanghai北京时间，改了这个所有时间显示都会跟着变', '系统'),
        ('maintenance_mode', '0', '维护模式', '系统维护时打开这个开关，普通用户就进不来了，只能看到维护提示，管理员不受影响', '系统'),
        ('show_system_version', '1', '显示版本号', '页面底部要不要显示系统版本号和运行时间？开着方便排查问题，关掉页面更清爽', '界面'),
        ('search_default_days', '30', '搜索默认时间范围', '搜索工单时默认只看最近多少天的，省得搜出来一堆老数据。30天够用，想查更早的再手动调', '工单'),
        ('confirm_destructive', '1', '破坏性操作确认', '删工单、删人员这种重要操作，要不要弹个框再确认一下？建议开着，防止手滑误删', '系统'),
        ('session_timeout_minutes', '480', '会话超时时间', '用户登录后一直没操作，过多少分钟自动登出。480分钟=8小时，够一个班次用了，范围60~1440', '系统'),
        ('ops_display_groups', '{}', '运维大屏分组配置', '运维大屏上怎么分组显示工单？用JSON配：{"default":"默认组名","merged":[{"label":"合并后名称","groups":["组1","组2"]}]}，可以把多个组合并成一个显示', '运维大屏'),
        # SLA 响应时限（小时）
        ('sla_response_emergency', '0.5', '特急响应时限', '特急工单从创建到接单不能超过多少小时？超时就违约了。默认0.5小时=30分钟', 'SLA'),
        ('sla_response_urgent', '2', '紧急响应时限', '紧急工单从创建到接单不能超过多少小时？默认2小时', 'SLA'),
        ('sla_response_normal', '4', '普通响应时限', '普通工单从创建到接单不能超过多少小时？默认4小时', 'SLA'),
        # SLA 解决时限（小时）
        ('sla_resolution_emergency', '2', '特急解决时限', '特急工单从接单到搞定不能超过多少小时？默认2小时', 'SLA'),
        ('sla_resolution_urgent', '8', '紧急解决时限', '紧急工单从接单到搞定不能超过多少小时？默认8小时=一个班次', 'SLA'),
        ('sla_resolution_normal', '24', '普通解决时限', '普通工单从接单到搞定不能超过多少小时？默认24小时=一天', 'SLA'),
    ]
    for key, val, label, desc, cat in defaults:
        if key not in existing_keys:
            db.session.add(SystemSetting(key=key, value=val, label=label, description=desc, category=cat))
    if len(defaults) > len([k for k in existing_keys if k in {d[0] for d in defaults}]):
        db.session.commit()
        # 刷新 settings 列表
        all_settings = SystemSetting.query.order_by(SystemSetting.category, SystemSetting.id).all()
        settings = [s for s in all_settings if s.key not in hidden_keys]
    # 每类可见条数
    cat_counts = {}
    for s in settings:
        cat_counts[s.category] = cat_counts.get(s.category, 0) + 1
    # 各医院的 webhook 配置
    hospitals = Hospital.query.order_by(Hospital.id).all()
    hospital_webhooks = {}
    hospital_push_enabled = {}
    for h in hospitals:
        wh = SystemSetting.query.filter_by(key='wecom_webhook_url', hospital_id=h.id).first()
        if wh:
            hospital_webhooks[h.id] = wh.value or ''
        pe = SystemSetting.query.filter_by(key='wecom_push_enabled', hospital_id=h.id).first()
        hospital_push_enabled[h.id] = (pe.value == '1') if pe else True
    # 各医院的编号前缀
    hospital_prefixes = {}
    for s in SystemSetting.query.filter_by(key='order_prefix').all():
        if s.hospital_id:
            hospital_prefixes[s.hospital_id] = s.value or ''
    # 组别列表（供 default_dashboard_team 下拉菜单使用）
    import re
    team_setting = SystemSetting.query.filter_by(key='person_teams').first()
    team_list = []
    if team_setting and team_setting.value:
        team_list = [t.strip() for t in re.split(r'[,，]', team_setting.value) if t.strip()]
    # 故障类型列表（去重）
    fault_types = sorted(set(f.name for f in FaultType.query.all()))
    return render_template('data/settings.html', settings=settings, categories=cat_list,
                           cat_counts=cat_counts,
                           hospitals=hospitals, hospital_webhooks=hospital_webhooks,
                           hospital_push_enabled=hospital_push_enabled,
                           hospital_prefixes=hospital_prefixes,
                           team_list=team_list,
                           fault_types=fault_types,
                           personal_pref_keys=PERSONAL_PREF_KEYS)


@settings_bp.route('/save_pref', methods=['POST'])
@admin_required
def save_pref():
    """保存个人偏好设置"""
    from flask_login import current_user
    import json
    key = request.form.get('key', '')
    value = request.form.get('value', '')
    if not key:
        return jsonify({'ok': False, 'msg': '参数名不能为空'}), 400
    current_user.set_pref(key, value)
    db.session.commit()
    return jsonify({'ok': True, 'personal': True})


@settings_bp.route('/save', methods=['POST'])
@admin_required
def save():
    """保存单个参数"""
    key = request.form.get('key', '')
    value = request.form.get('value', '')
    if not key:
        return jsonify({'ok': False, 'msg': '参数名不能为空'}), 400
    setting = SystemSetting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key=key, value=value, label=key)
        db.session.add(setting)
    db.session.commit()
    return jsonify({'ok': True})


@settings_bp.route('/save_webhook', methods=['POST'])
@admin_required
def save_webhook():
    """保存某医院的企业微信推送地址"""
    hospital_id = request.form.get('hospital_id', type=int)
    value = request.form.get('value', '').strip()
    if not hospital_id:
        return jsonify({'ok': False, 'msg': '医院ID不能为空'}), 400
    setting = SystemSetting.query.filter_by(key='wecom_webhook_url', hospital_id=hospital_id).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key='wecom_webhook_url', value=value,
                                label='企业微信推送地址',
                                description='新工单自动推送到企业微信群，粘贴机器人Webhook地址',
                                category='通知', hospital_id=hospital_id)
        db.session.add(setting)
    db.session.commit()
    return jsonify({'ok': True})


@settings_bp.route('/save_webhook_setting', methods=['POST'])
@admin_required
def save_webhook_setting():
    """保存某医院的企业微信推送相关设置（开关等）"""
    hospital_id = request.form.get('hospital_id', type=int)
    key = request.form.get('key', '').strip()
    value = request.form.get('value', '').strip()
    if not hospital_id or not key:
        return jsonify({'ok': False, 'msg': '参数不完整'}), 400
    setting = SystemSetting.query.filter_by(key=key, hospital_id=hospital_id).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key=key, value=value, label=key,
                                category='通知', hospital_id=hospital_id)
        db.session.add(setting)
    db.session.commit()
    return jsonify({'ok': True})


@settings_bp.route('/init', methods=['POST'])
@admin_required
def init_defaults():
    """初始化默认系统参数"""
    defaults = [
        ('auto_refresh_interval', '30', '仪表盘自动刷新', '每隔多少秒自动刷新仪表盘数据，0=关闭（仅手动刷新）', '仪表盘'),
        ('default_fault_type', '硬件', '新建工单默认故障类型', '创建工单时故障类型的默认值', '工单'),
        ('default_priority', 'normal', '新建工单默认紧急程度', 'normal=普通  urgent=加急  emergency=紧急', '工单'),
        ('person_teams', '信息科,后勤,外包服务', '人员组别选项', '人员管理中「组别」下拉菜单的可选值（用逗号分隔）', '人员'),
        ('order_page_size', '20', '工单列表每页条数', '一页显示多少条工单记录', '工单'),
        ('maintenance_reminder_days', '30', '保修到期提醒天数', '资产保修到期前多少天开始显示提醒标记', '资产'),
        ('asset_page_size', '20', '资产列表每页条数', '资产台账列表每页显示多少条记录', '资产'),
        ('asset_code_prefix', '', '资产编号前缀', '资产编码的自定义前缀（如"ZC-"），留空不使用', '资产'),
        ('asset_default_status', '在库', '默认资产状态', '新建资产时默认的资产状态', '资产'),
        ('wecom_webhook_url', '', '企业微信推送地址', '新工单自动推送到企业微信群，粘贴机器人Webhook地址即可', '通知'),
        ('sidebar_auto_hide_seconds', '0', '侧边栏自动收起', '鼠标静止几秒后自动收起侧边栏，0=关闭此功能', '界面'),
        ('default_dashboard_team', '', '仪表盘默认组别', '进入仪表盘时默认显示的组别（留空=显示全部），在「全部组」下拉中按名称填写', '仪表盘'),
        ('default_hospital_id', '', '默认显示医院', '管理员/用户登录后默认显示的医院ID（留空=全部医院或上次选择），1=七院 2=光明中医 3=公利 4=周浦 5=公卫临床 6=公卫-虹口 7=东明', '界面'),
        ('photo_quality', '50', '照片压缩质量', '上传照片的 JPEG 压缩质量，1~100，值越高越清晰但文件越大', '工单'),
        ('auto_close_days', '0', '工单超时自动关闭', '超过 N 天未更新的工单自动标记为已关闭，0=关闭此功能', '工单'),
        ('order_prefix', '', '工单编号前缀', '维修单编号的自定义前缀（如"七院-"），留空则不使用前缀', '工单'),
        ('default_dark_mode', 'light', '默认深色模式', '登录后默认使用的颜色主题', '界面'),
        ('upload_max_mb', '20', '上传大小限制', '单张照片最大允许上传的 MB 数', '工单'),
    ]
    count = 0
    for key, value, label, desc, cat in defaults:
        if not SystemSetting.query.filter_by(key=key).first():
            db.session.add(SystemSetting(key=key, value=value, label=label, description=desc, category=cat))
            count += 1
    db.session.commit()
    flash(f'已初始化 {count} 条默认参数', 'success')
    return redirect(url_for('settings.index'))


# ==================== 科室字典 ====================

@settings_bp.route('/departments')
@admin_required
def list_departments():
    """科室字典列表"""
    keyword = request.args.get('keyword', '')
    query = Department.query
    if keyword:
        query = query.filter(Department.name.contains(keyword))
    departments = query.order_by(Department.sort_order, Department.id).all()
    return render_template('data/departments.html', departments=departments, keyword=keyword)


@settings_bp.route('/departments/add', methods=['POST'])
@admin_required
def add_department():
    name = request.form.get('name', '').strip()
    if not name:
        flash('科室名称不能为空', 'danger')
        return redirect(url_for('settings.list_departments'))
    if Department.query.filter_by(name=name).first():
        flash(f'科室「{name}」已存在', 'warning')
        return redirect(url_for('settings.list_departments'))
    dept = Department(
        name=name,
        building=request.form.get('building', '').strip(),
        floor=request.form.get('floor', '').strip(),
        phone=request.form.get('phone', '').strip(),
    )
    db.session.add(dept)
    db.session.commit()
    flash(f'已添加科室「{name}」', 'success')
    return redirect(url_for('settings.list_departments'))


@settings_bp.route('/departments/<int:did>/edit', methods=['POST'])
@admin_required
def edit_department(did):
    dept = Department.query.get_or_404(did)
    old_name = dept.name
    name = request.form.get('name', '').strip()
    if not name:
        flash('科室名称不能为空', 'danger')
        return redirect(url_for('settings.list_departments'))
    existing = Department.query.filter(Department.name == name, Department.id != did).first()
    if existing:
        flash(f'科室「{name}」已存在', 'warning')
        return redirect(url_for('settings.list_departments'))
    dept.name = name
    dept.building = request.form.get('building', '').strip()
    dept.floor = request.form.get('floor', '').strip()
    dept.phone = request.form.get('phone', '').strip()

    # 同步到地址数据：科室改名 → 地址中对应科室也改
    if name != old_name:
        from models import AddressOverride
        from services.address import ADDRESS_LIST
        # 1. 更新已有覆盖记录
        for o in AddressOverride.query.filter_by(department=old_name).all():
            o.department = name
        # 2. 对基础地址中匹配的科室，创建覆盖记录
        existing_overrides = {o.base_index: o for o in AddressOverride.query.filter(
            AddressOverride.base_index >= 0
        ).all()}
        for i, addr in enumerate(ADDRESS_LIST):
            if addr.get('所属科室', '').strip() == old_name:
                if i in existing_overrides:
                    o = existing_overrides[i]
                    if not o.department:
                        o.department = name
                else:
                    db.session.add(AddressOverride(
                        base_index=i,
                        building='',
                        floor='',
                        department=name,
                        location='',
                    ))

    db.session.commit()
    flash(f'已更新科室「{name}」（地址数据已同步）', 'success')
    return redirect(url_for('settings.list_departments'))


@settings_bp.route('/departments/<int:did>/toggle', methods=['POST'])
@admin_required
def toggle_department(did):
    dept = Department.query.get_or_404(did)
    dept.is_active = not dept.is_active
    db.session.commit()
    flash(f'已{"启用" if dept.is_active else "禁用"}「{dept.name}」', 'success')
    return redirect(url_for('settings.list_departments'))


@settings_bp.route('/departments/<int:did>/delete', methods=['POST'])
@admin_required
def delete_department(did):
    dept = Department.query.get_or_404(did)
    db.session.delete(dept)
    db.session.commit()
    flash('科室已删除', 'success')
    return redirect(url_for('settings.list_departments'))


@settings_bp.route('/departments/import', methods=['POST'])
@admin_required
def import_departments():
    """从工单和地址数据中提取科室导入"""
    from models import WorkOrder
    from services.address import get_merged_addresses

    names = set()
    # 从工单提取
    depts = db.session.query(WorkOrder.department).distinct().filter(
        WorkOrder.department != ''
    ).all()
    for (name,) in depts:
        name = name.strip()
        if name:
            names.add(name)
    # 从地址数据提取
    merged = get_merged_addresses()
    for addr in merged:
        dept = addr.get('所属科室', '').strip()
        if dept:
            names.add(dept)

    imported = 0
    for name in sorted(names):
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
            imported += 1
    db.session.commit()
    flash(f'从工单和地址数据中导入 {imported} 个科室', 'success')
    return redirect(url_for('settings.list_departments'))
