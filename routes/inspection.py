"""巡检管理路由"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from models import db, InspectionTemplate, InspectionPlan, WorkOrder, Person
from routes.auth import admin_required
from services.address import get_all_buildings, get_floors_by_building, get_departments_by_building, get_locations_by_building_dept

# 创建巡检管理蓝图，URL 前缀为 /inspection
inspection_bp = Blueprint('inspection', __name__, url_prefix='/inspection')


@inspection_bp.route('/templates')
@login_required
def list_templates():
    """巡检模板列表"""
    # 查询所有模板，按 ID 升序排列
    templates = InspectionTemplate.query.order_by(InspectionTemplate.id).all()
    return render_template('inspection/templates.html', templates=templates)


@inspection_bp.route('/templates/create', methods=['GET'])
@login_required
def create_template_page():
    """新建巡检模板页面"""
    # 返回模板创建表单页面
    return render_template('inspection/create_template.html')


@inspection_bp.route('/templates/create', methods=['POST'])
@admin_required
def create_template():
    """新建巡检模板（POST 处理）"""
    # 获取表单提交的模板名称，去除首尾空白
    name = request.form.get('name', '').strip()
    # 获取巡检项文本，按行分割
    items_raw = request.form.get('items', '').strip()
    # 校验：模板名称不能为空
    if not name:
        flash('请输入模板名称', 'danger')
        return redirect(url_for('inspection.list_templates'))
    # 解析巡检项：按换行符分割，过滤空行
    items = [i.strip() for i in items_raw.split('\n') if i.strip()]
    # 校验：至少需要一项巡检内容
    if len(items) < 1:
        flash('请至少输入一项巡检内容', 'danger')
        return redirect(url_for('inspection.list_templates'))
    # 创建模板记录并写入数据库
    tpl = InspectionTemplate(name=name, items=items)
    db.session.add(tpl)
    db.session.commit()
    flash(f'✅ 巡检模板「{name}」已创建', 'success')
    return redirect(url_for('inspection.list_templates'))


@inspection_bp.route('/templates/<int:tid>/edit', methods=['POST'])
@admin_required
def edit_template(tid):
    """编辑巡检模板（POST 处理）"""
    # 根据 ID 获取待编辑的模板，不存在则 404
    tpl = InspectionTemplate.query.get_or_404(tid)
    # 获取表单数据
    name = request.form.get('name', '').strip()
    items_raw = request.form.get('items', '').strip()
    # 校验模板名称
    if not name:
        flash('请输入模板名称', 'danger')
        return redirect(url_for('inspection.list_templates'))
    # 解析并校验巡检项列表
    items = [i.strip() for i in items_raw.split('\n') if i.strip()]
    if len(items) < 1:
        flash('请至少输入一项巡检内容', 'danger')
        return redirect(url_for('inspection.list_templates'))
    # 更新模板字段并保存
    tpl.name = name
    tpl.items = items
    db.session.commit()
    flash(f'✅ 巡检模板「{name}」已更新', 'success')
    return redirect(url_for('inspection.list_templates'))


@inspection_bp.route('/templates/<int:tid>/delete', methods=['POST'])
@admin_required
def delete_template(tid):
    """删除巡检模板"""
    # 查询模板并删除
    tpl = InspectionTemplate.query.get_or_404(tid)
    db.session.delete(tpl)
    db.session.commit()
    flash('模板已删除', 'success')
    return redirect(url_for('inspection.list_templates'))


@inspection_bp.route('/publish', methods=['GET', 'POST'])
@login_required
def publish_plan():
    """发布巡检计划"""
    # POST 请求：处理表单提交，创建巡检计划
    if request.method == 'POST':
        # 从表单提取计划参数：模板、楼栋、楼层、科室、具体位置、计划时间
        template_id = request.form.get('template_id', type=int)
        building = request.form.get('building', '').strip()
        floor = request.form.get('floor', '').strip()
        department = request.form.get('department', '').strip()
        location = request.form.get('location', '').strip()
        scheduled = request.form.get('scheduled_time', '').strip()
        schedule_type = request.form.get('schedule_type', 'once')
        schedule_time = request.form.get('schedule_time', '').strip()
        schedule_day = request.form.get('schedule_day', type=int, default=0)

        # 校验：必须选择模板
        if not template_id:
            flash('请选择巡检模板', 'danger')
            return redirect(url_for('inspection.publish_plan'))
        # 校验：模板必须存在于数据库
        tpl = InspectionTemplate.query.get(template_id)
        if not tpl:
            flash('模板不存在', 'danger')
            return redirect(url_for('inspection.publish_plan'))
        # 校验：必须设定计划巡检时间
        if not scheduled:
            flash('请设定巡检时间', 'danger')
            return redirect(url_for('inspection.publish_plan'))

        # 解析时间：将 HTML datetime-local 格式转换为 datetime 对象
        try:
            scheduled = scheduled.replace('T', ' ')  # datetime-local 提交的是 YYYY-MM-DDTHH:MM
            scheduled_time = datetime.strptime(scheduled, '%Y-%m-%d %H:%M')
        except:
            flash('时间格式错误，请使用 YYYY-MM-DD HH:MM', 'danger')
            return redirect(url_for('inspection.publish_plan'))

        # 构造巡检计划对象
        plan = InspectionPlan(
            template_id=template_id,
            building=building,
            floor=floor,
            department=department,
            location=location,
            scheduled_time=scheduled_time,
            schedule_type=schedule_type,
            schedule_time=schedule_time,
            schedule_day=schedule_day or 0,
            created_by=current_user.display_name or current_user.username
        )
        # 如果设定时间已经过了，立即生成工单
        if scheduled_time <= datetime.now():
            _generate_inspection_order(plan)

        # 保存计划到数据库
        db.session.add(plan)
        db.session.commit()
        flash(f'✅ 巡检计划已发布，时间: {scheduled}', 'success')
        return redirect(url_for('inspection.list_plans'))

    # GET 请求：渲染发布页面，附带模板列表、活跃人员和医院地址数据
    templates = InspectionTemplate.query.order_by(InspectionTemplate.id).all()
    persons = Person.query.filter_by(is_active=True).all()
    buildings = get_all_buildings()
    return render_template('inspection/publish.html', templates=templates, persons=persons, buildings=buildings)


@inspection_bp.route('/plans')
@login_required
def list_plans():
    """巡检计划列表"""
    # 先检查有没有到期未生成的计划，自动生成对应工单
    now = datetime.now()
    pending = InspectionPlan.query.filter(
        InspectionPlan.status == 'pending',
        InspectionPlan.scheduled_time <= now
    ).all()
    for plan in pending:
        _generate_inspection_order(plan)
    if pending:
        db.session.commit()

    # 查询所有计划，按计划时间倒序排列
    plans = InspectionPlan.query.order_by(InspectionPlan.scheduled_time.desc()).all()
    return render_template('inspection/plans.html', plans=plans)


@inspection_bp.route('/export_csv')
@login_required
def export_plans_csv():
    """导出巡检计划列表为 CSV"""
    import csv, io
    plans = InspectionPlan.query.order_by(InspectionPlan.scheduled_time.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', '巡检内容', '楼区', '楼层', '科室', '位置', '计划类型', '设定时间', '状态', '关联工单数', '创建人'])
    for p in plans:
        schedule_label = '单次'
        if p.schedule_type == 'daily': schedule_label = f'每日 {p.schedule_time}'
        elif p.schedule_type == 'workday': schedule_label = f'工作日 {p.schedule_time}'
        elif p.schedule_type == 'monthly': schedule_label = f'每月{p.schedule_day}号 {p.schedule_time}'
        status_label = {'pending': '等待执行', 'generated': '已生成工单', 'completed': '已完成'}.get(p.status, p.status)
        order_count = len(p.work_order_ids or []) + (1 if p.work_order_id else 0)
        writer.writerow([
            p.id, p.template.name if p.template else '',
            p.building, p.floor, p.department, p.location,
            schedule_label,
            p.scheduled_time.strftime('%Y-%m-%d %H:%M') if p.scheduled_time else '',
            status_label, order_count, p.created_by
        ])
    data = output.getvalue()
    # 用 BytesIO 包装 UTF-8 BOM 以便 Excel 正确识别中文
    buf = io.BytesIO()
    buf.write(b'\xef\xbb\xbf')
    buf.write(data.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/csv', as_attachment=True,
                     download_name=f'巡检计划_{datetime.now().strftime("%Y%m%d")}.csv')


@inspection_bp.route('/plans/<int:pid>/export')
@login_required
def export_plan(pid):
    """巡检确认单导出/打印"""
    # 查询指定巡检计划
    plan = InspectionPlan.query.get_or_404(pid)
    # 根据计划关联的工单 ID 查询对应工单
    orders = []
    if plan.work_order_id:
        order = db.session.get(WorkOrder, plan.work_order_id)
        if order:
            orders = [order]
    elif plan.work_order_ids:
        orders = WorkOrder.query.filter(WorkOrder.id.in_(plan.work_order_ids)).all()
    return render_template('inspection/export.html', plan=plan, orders=orders)


@inspection_bp.route('/plans/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
def edit_plan(pid):
    """编辑巡检计划"""
    plan = InspectionPlan.query.get_or_404(pid)
    if request.method == 'POST':
        plan.template_id = request.form.get('template_id', type=int)
        plan.building = request.form.get('building', '').strip()
        plan.floor = request.form.get('floor', '').strip()
        plan.department = request.form.get('department', '').strip()
        plan.location = request.form.get('location', '').strip()
        scheduled = request.form.get('scheduled_time', '').strip()
        plan.schedule_type = request.form.get('schedule_type', 'once')
        plan.schedule_time = request.form.get('schedule_time', '').strip()
        plan.schedule_day = request.form.get('schedule_day', type=int, default=0)
        if scheduled:
            try:
                scheduled = scheduled.replace('T', ' ')
                plan.scheduled_time = datetime.strptime(scheduled, '%Y-%m-%d %H:%M')
            except:
                flash('时间格式错误', 'danger')
                return redirect(url_for('inspection.edit_plan', pid=pid))
        db.session.commit()
        flash('✅ 巡检计划已更新', 'success')
        return redirect(url_for('inspection.list_plans'))
    # GET: 预填表单
    templates = InspectionTemplate.query.order_by(InspectionTemplate.id).all()
    buildings = get_all_buildings()
    return render_template('inspection/publish.html', templates=templates, buildings=buildings, plan=plan,
                           now=datetime.now())


@inspection_bp.route('/plans/<int:pid>/delete', methods=['POST'])
@login_required
def delete_plan(pid):
    """删除巡检计划"""
    plan = InspectionPlan.query.get_or_404(pid)
    db.session.delete(plan)
    db.session.commit()
    flash('🗑️ 巡检计划已删除', 'success')
    return redirect(url_for('inspection.list_plans'))


def _generate_inspection_order(plan):
    """根据巡检计划生成工单"""
    # 如果计划已生成工单，则跳过
    if plan.status != 'pending':
        return
    # 获取关联模板，构造工单标题
    tpl = plan.template
    title = f'🔍巡检: {tpl.name} - {plan.building} {plan.department}'.strip()
    if title.endswith('-'):
        title = title[:-2]

    # 创建巡检工单，写入巡检检查项数据
    order = WorkOrder(
        title=title,
        work_type='inspection',
        fault_type='巡检',
        device_type='巡检',
        description=f'巡检区域: {plan.building} {plan.floor} {plan.department} {plan.location}',
        building=plan.building,
        floor=plan.floor,
        department=plan.department,
        location=plan.location,
        start_time=datetime.now(),
        status='pending',
        inspection_data={'template_name': tpl.name, 'items': [{'name': item, 'result': None} for item in tpl.items]},
        created_by='系统(巡检)'
    )
    db.session.add(order)
    db.session.flush()
    # 将工单 ID 回填到计划，标记为已生成
    plan.work_order_id = order.id
    plan.status = 'generated'


@inspection_bp.route('/api/check_due')
@login_required
def api_check_due():
    """手动触发检查到期的巡检计划（前端可以定时调用）"""
    # 查询所有到期未生成的巡检计划
    now = datetime.now()
    pending = InspectionPlan.query.filter(
        InspectionPlan.status == 'pending',
        InspectionPlan.scheduled_time <= now
    ).all()
    count = 0
    # 逐项生成工单
    for plan in pending:
        _generate_inspection_order(plan)
        count += 1
    if pending:
        db.session.commit()
    # 返回本次生成的工单数量
    return jsonify({'generated': count})


@inspection_bp.route('/api/address_data')
@login_required
def api_address_data():
    """返回所选楼区的楼层/科室/位置数据，供前端联动"""
    building = request.args.get('building', '').strip()
    department = request.args.get('department', '').strip()
    if not building:
        return jsonify({'floors': [], 'departments': [], 'locations': []})
    floors = get_floors_by_building(building)
    departments = get_departments_by_building(building)
    # 若指定了科室，只返回该科室的位置；否则返回全部
    if department:
        locations = get_locations_by_building_dept(building, department)
    else:
        locations = get_locations_by_building_dept(building, departments[0]) if departments else []
    return jsonify({
        'floors': floors,
        'departments': departments,
        'locations': locations
    })
