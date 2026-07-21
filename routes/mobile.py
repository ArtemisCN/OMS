"""手机端路由 - 双池子模式（同步小程序）"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from models import db, WorkOrder, PaperForm, WorkOrderPhoto

mobile_bp = Blueprint('mobile', __name__, url_prefix='/mobile')


@mobile_bp.route('/')
@login_required
def dashboard():
    """工单列表：三个标签（同步小程序）"""
    from sqlalchemy import func, case, and_
    person_name = current_user.display_name or current_user.username
    tab = request.args.get('tab', 'pending')
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if tab == 'pending':
        query = WorkOrder.query.filter_by(status='pending')
        # 公共池只显示用户可访问医院的工单
        hospital_ids = current_user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
        orders = query.order_by(WorkOrder.created_at.desc()).all()
    elif tab == 'in_progress':
        query = WorkOrder.query.filter_by(
            person=person_name, status='in_progress'
        )
        hospital_ids = current_user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
        orders = query.order_by(WorkOrder.created_at.desc()).all()
    elif tab == 'completed_today':
        query = WorkOrder.query.filter(
            WorkOrder.person == person_name,
            WorkOrder.status == 'completed',
            WorkOrder.completed_at >= today_start
        )
        hospital_ids = current_user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
        orders = query.order_by(WorkOrder.completed_at.desc()).all()
    else:
        # 默认 pending
        tab = 'pending'
        query = WorkOrder.query.filter_by(status='pending')
        hospital_ids = current_user.get_assigned_hospital_ids()
        if hospital_ids:
            query = query.filter(WorkOrder.hospital_id.in_(hospital_ids))
        orders = query.order_by(WorkOrder.created_at.desc()).all()

    # 统计数据（一次查询4项，全部按医院过滤）
    hospital_ids = current_user.get_assigned_hospital_ids()
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
    stats = {
        'pending': stats_row.pending or 0,
        'in_progress': stats_row.in_progress or 0,
        'completed': stats_row.completed or 0,
        'completed_today': stats_row.completed_today or 0,
    }

    return render_template('mobile/dashboard.html',
                           orders=orders, tab=tab, stats=stats)


@mobile_bp.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    """工单详情"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        flash('工单不存在', 'danger')
        return redirect(url_for('mobile.dashboard'))

    # 查询关联的电子表单
    form = PaperForm.query.filter_by(work_order_id=order.id).first()
    # 查询照片
    photos = WorkOrderPhoto.query.filter_by(
        work_order_id=order.id
    ).order_by(WorkOrderPhoto.created_at.desc()).all()
    return render_template('mobile/detail.html', order=order, paper_form=form, photos=photos)


@mobile_bp.route('/order/<int:order_id>/accept', methods=['POST'])
@login_required
def accept_order(order_id):
    """接单：pending → in_progress，认领到当前用户"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        flash('工单不存在', 'danger')
        return redirect(url_for('mobile.dashboard'))

    if order.status != 'pending':
        flash('工单状态不允许接单', 'warning')
        return redirect(url_for('mobile.dashboard'))

    # 校验医院权限：只能接自己可访问医院的工单
    hospital_ids = current_user.get_assigned_hospital_ids()
    if hospital_ids and order.hospital_id not in hospital_ids:
        flash('无权接此医院的工单', 'danger')
        return redirect(url_for('mobile.dashboard'))

    person_name = current_user.display_name or current_user.username
    order.status = 'in_progress'
    order.person = person_name  # 接单即认领
    order.accepted_at = datetime.now()
    db.session.commit()
    flash('✅ 已接单，请前往处理', 'success')
    return redirect(url_for('mobile.order_detail', order_id=order_id))


@mobile_bp.route('/order/<int:order_id>/solve', methods=['POST'])
@login_required
def solve_order(order_id):
    """提交解决方案：in_progress → completed（表单工单请填表提交）"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        flash('工单不存在', 'danger')
        return redirect(url_for('mobile.dashboard'))

    person_name = current_user.display_name or current_user.username
    if order.person != person_name:
        flash('这不是你接的工单', 'warning')
        return redirect(url_for('mobile.dashboard'))

    # 表单工单：不允许直接填写文本完结，必须通过电子表单
    form = PaperForm.query.filter_by(work_order_id=order.id).first()
    if form:
        flash('请填写并提交电子表单来完成此工单', 'warning')
        return redirect(url_for('mobile.order_detail', order_id=order_id))

    solution = request.form.get('solution', '').strip()
    if not solution:
        flash('请填写解决方案', 'warning')
        return redirect(url_for('mobile.order_detail', order_id=order_id))

    order.solution = solution
    order.status = 'completed'
    order.completed_at = datetime.now()
    db.session.commit()
    flash('✅ 工单已完成！', 'success')
    return redirect(url_for('mobile.dashboard'))


@mobile_bp.route('/order/<int:order_id>/quick-solve', methods=['POST'])
@login_required
def quick_solve(order_id):
    """一键结单：自动匹配方案模板直接完成"""
    from services.matcher import get_solution_by_title
    order = db.session.get(WorkOrder, order_id)
    if not order:
        flash('工单不存在', 'danger')
        return redirect(url_for('mobile.dashboard'))

    person_name = current_user.display_name or current_user.username
    if order.person != person_name:
        flash('这不是你接的工单', 'warning')
        return redirect(url_for('mobile.dashboard'))
    if order.status != 'in_progress':
        flash('工单状态不允许操作', 'warning')
        return redirect(url_for('mobile.dashboard'))

    # 自动匹配模板或生成兜底方案
    solution = get_solution_by_title(order.title)
    if not solution:
        solution = f'经现场处理，{order.title}，问题已解决。'

    order.solution = solution
    order.status = 'completed'
    order.completed_at = datetime.now()
    db.session.commit()
    flash('✅ 一键结单成功！', 'success')
    return redirect(url_for('mobile.dashboard'))


@mobile_bp.route('/order/<int:order_id>/inspection-submit', methods=['POST'])
@login_required
def submit_inspection(order_id):
    """提交巡检结果（含签名）"""
    order = db.session.get(WorkOrder, order_id)
    if not order:
        flash('工单不存在', 'danger')
        return redirect(url_for('mobile.dashboard'))

    person_name = current_user.display_name or current_user.username
    if order.person != person_name:
        flash('这不是你接的工单', 'warning')
        return redirect(url_for('mobile.dashboard'))

    if order.work_type != 'inspection':
        flash('不是巡检工单', 'warning')
        return redirect(url_for('mobile.dashboard'))

    items = request.form.getlist('items')
    if not items:
        flash('请至少完成一项巡检', 'warning')
        return redirect(url_for('mobile.order_detail', order_id=order_id))

    # 构建巡检数据
    current_items = (order.inspection_data or {}).get('items', [])
    submitted = []
    for item in current_items:
        if item.get('name') in items:
            submitted.append({'name': item['name'], 'result': True})
        else:
            submitted.append({'name': item['name'], 'result': False})

    signature = request.form.get('signature', '')
    order.inspection_data = {
        'template_name': order.inspection_data.get('template_name', '巡检'),
        'items': submitted,
        'signature': signature,
    }
    order.status = 'completed'
    order.completed_at = datetime.now()
    order.solution = '巡检完成'
    db.session.commit()
    flash('✅ 巡检完成！', 'success')
    return redirect(url_for('mobile.dashboard'))


@mobile_bp.route('/publish', methods=['GET', 'POST'])
@login_required
def publish():
    """手机端发布工单（复用 PC 端发布逻辑）"""
    from services.address import extract_address_from_title
    from services.matcher import guess_fault_type, guess_device_type
    from services.fault_matcher import match_fault

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('请输入工单名称', 'danger')
            return render_template('mobile/publish.html')

        # 自动识别
        auto_fault = guess_fault_type(title)
        auto_device = guess_device_type(title)
        fm = match_fault(title)
        auto_fault = fm['category'] if fm['match_type'] == 'keyword' else auto_fault
        addr = extract_address_from_title(title)

        building = request.form.get('building', '') or addr['building']
        floor = request.form.get('floor', '') or addr['floor']
        department = request.form.get('department', '') or addr['department']
        location = request.form.get('location', '') or addr.get('location', '')
        now = datetime.now()

        order = WorkOrder(
            title=title,
            device_type=auto_device,
            fault_type=auto_fault,
            fault_subcategory=request.form.get('fault_subcategory', '') or fm.get('subcategory', ''),
            description='',
            building=building,
            floor=floor,
            department=department,
            location=location,
            person='',
            solution='',
            start_time=now,
            status='pending',
            created_by=current_user.display_name or current_user.username,
            priority=request.form.get('priority', 'normal'),
            original_priority=request.form.get('priority', 'normal')
        )
        db.session.add(order)
        db.session.commit()

        # 推送通知
        try:
            from routes.api_mobile import send_new_order_notification, send_wecom_notification
            send_new_order_notification(order)
            send_wecom_notification(order)
        except Exception:
            pass

        flash('✅ 工单已发布，等待接单', 'success')
        return redirect(url_for('mobile.dashboard'))

    return render_template('mobile/publish.html')


@mobile_bp.route('/exams')
@login_required
def exam_list():
    """手机端考试列表（服务端渲染）"""
    from models import Exam, ExamSubmission
    exams = Exam.query.filter(
        Exam.status.in_(['published', 'closed'])
    ).order_by(Exam.created_at.desc()).all()
    result = []
    for e in exams:
        if not e.check_access():
            continue
        d = e.to_dict()
        attempt_count = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='submitted'
        ).count()
        in_progress = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='in_progress'
        ).first()
        d['attempt_count'] = attempt_count
        d['in_progress_id'] = in_progress.id if in_progress else None
        last_sub = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='submitted'
        ).order_by(ExamSubmission.submitted_at.desc()).first()
        d['last_score'] = last_sub.score if last_sub else None
        d['last_passed'] = last_sub.is_passed(e.pass_score) if last_sub else None
        d['can_start'] = e.status == 'published' and (
            e.max_attempts == 0 or attempt_count < e.max_attempts
        ) and not in_progress
        result.append(d)
    return render_template('mobile/exam_list.html', exams=result)


@mobile_bp.route('/today-summary')
@login_required
def today_summary():
    """今日工作总结（Web版，session auth）"""
    from datetime import date
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    person_name = current_user.display_name or current_user.username

    orders = WorkOrder.query.filter(
        WorkOrder.person == person_name,
        WorkOrder.status == 'completed',
        WorkOrder.completed_at >= today_start
    ).order_by(WorkOrder.completed_at.asc()).all()

    today = date.today().strftime('%Y-%m-%d')
    priority_map = {'normal': '普通', 'urgent': '加急', 'emergency': '紧急'}
    lines = [f'{today} 工作总结', f'员工：{person_name}', '']
    lines.append(f'今日完成工单：{len(orders)} 项')
    lines.append('')

    for i, o in enumerate(orders, 1):
        pri = priority_map.get(o.priority, '普通')
        time_str = o.completed_at.strftime('%H:%M') if o.completed_at else ''
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
