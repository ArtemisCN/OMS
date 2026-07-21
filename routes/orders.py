"""工单管理路由（薄路由版 —— 业务逻辑委托给 services/order_service）"""
import io
import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, session
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from openpyxl import Workbook

from models import db, WorkOrder, Person, SystemSetting, WorkOrderStar
from services import order_service as svc
from services.fault_matcher import match_fault
from routes.auth import admin_required

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')


# ==================== 工单列表 ====================

@orders_bp.route('/')
@login_required
def list_orders():
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # 提取筛选条件
    filters = {
        'status': request.args.get('status', 'pending'),
        'fault_type': request.args.get('fault_type', ''),
        'person': request.args.get('person', ''),
        'keyword': request.args.get('keyword', ''),
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
        'building': request.args.get('building', ''),
        'department': request.args.get('department', ''),
        'floor': request.args.get('floor', ''),
        'location': request.args.get('location', ''),
        'team': request.args.get('team', ''),
        'sort': request.args.get('sort', ''),
        'order': request.args.get('order', 'desc'),
    }

    # 已完成池子默认只看当天，需要看其他日期再手动输入日期筛选
    if filters['status'] == 'completed' and not filters['date_from'] and not filters['date_to']:
        today_str = datetime.now().strftime('%Y-%m-%d')
        filters['date_from'] = today_str

    # 未指定组时按用户自身 Person.team 过滤（非管理员）
    if not filters['team']:
        if not current_user.is_admin:
            person = Person.query.filter_by(user_id=current_user.id).first()
            if person and person.team:
                filters['team'] = person.team

    query = svc.build_order_query(filters, current_user)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    filtered_all = query.all()

    persons, buildings, teams = svc.get_filter_data()
    stats = svc.get_order_stats()

    # 星标状态
    starred_ids = set()
    stars = WorkOrderStar.query.filter_by(user_id=current_user.id).all()
    starred_ids = {s.order_id for s in stars}

    # 计算工单球的颜色（按处理时长）
    from datetime import timedelta
    ball_map = {}
    for o in pagination.items:
        et = o.end_time or getattr(o, 'completed_at', None)
        st = o.start_time or getattr(o, 'accepted_at', None) or getattr(o, 'created_at', None)
        if et and st:
            delta = et - st
            mins = delta.total_seconds() / 60
            if mins <= 30:
                ball_map[o.id] = 'normal'      # 🟢
            elif mins <= 60:
                ball_map[o.id] = 'urgent'      # 🟡
            else:
                ball_map[o.id] = 'emergency'   # 🔴
        else:
            ball_map[o.id] = o.priority or 'normal'

    return render_template('orders/list.html',
                           pagination=pagination, orders=pagination.items,
                           persons=persons, buildings=buildings,
                           status=filters['status'], stats=stats,
                           fault_type=filters['fault_type'],
                           person_sel=filters['person'],
                           keyword=filters['keyword'],
                           date_from=filters['date_from'],
                           date_to=filters['date_to'],
                           building=filters['building'],
                           department=filters['department'],
                           floor_sel=filters['floor'],
                           location_sel=filters['location'],
                           team_sel=filters['team'], teams=teams,
                           sort=filters['sort'], order=filters['order'],
                           starred_ids=starred_ids, ball_map=ball_map)


# ==================== 新建工单 ====================

@orders_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_order():
    from services.address import get_merged_addresses, get_all_buildings

    if request.method == 'POST':
        try:
            order = svc.create_order(
                request.form,
                current_user.display_name or current_user.username,
            )
            flash('工单创建成功', 'success')
            return redirect(url_for('orders.list_orders'))
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template('orders/create.html',
                                   addr_list=get_merged_addresses(),
                                   buildings=get_all_buildings())

    persons, templates = svc.get_create_page_data(current_user)
    return render_template('orders/create.html',
                           addr_list=get_merged_addresses(),
                           persons=persons, templates=templates,
                           buildings=get_all_buildings())


# ==================== 发布工单（匿名/登录通用） ====================

@orders_bp.route('/publish', methods=['GET', 'POST'])
@login_required
def publish_order():
    if request.method == 'POST':
        try:
            order = svc.publish_order(
                request.form,
                current_user.display_name or current_user.username,
            )
            # 推送通知
            try:
                from routes.api_mobile import send_new_order_notification, send_wecom_notification
                send_new_order_notification(order)
                send_wecom_notification(order)
            except Exception:
                pass
            flash('✅ 工单已发布，等待手机端接单', 'success')
            return redirect(url_for('orders.list_orders'))
        except ValueError as e:
            flash(str(e), 'danger')

    return render_template('orders/publish.html')


# ==================== API 辅助 ====================

@orders_bp.route('/api/guess')
@login_required
def api_guess_fault():
    return jsonify(svc.api_guess_fault(request.args.get('title', '')))


@orders_bp.route('/api/solution_suggest')
@login_required
def api_solution_suggest():
    return jsonify(svc.api_solution_suggest(
        request.args.get('q', '').strip(), current_user
    ))


@orders_bp.route('/api/address/all')
@login_required
def api_address_all():
    return jsonify(svc.api_address_all())


@orders_bp.route('/api/address/options')
@login_required
def api_address_options():
    return jsonify(svc.api_address_options(
        request.args.get('building', ''),
        request.args.get('floor', ''),
    ))


# ==================== 批量生成 ====================

@orders_bp.route('/batch', methods=['GET', 'POST'])
@admin_required
def batch_create():
    persons, templates, fault_groups, fault_group_items, team_groups, teams, default_team = \
        svc.get_batch_form_data(current_user)

    if request.method == 'POST' and request.form.get('action') == 'preview':
        try:
            serialized, by_date, sorted_dates, total = svc.batch_preview(
                request.form, current_user
            )
            preview_json_obj = json.dumps(serialized, ensure_ascii=False)
            return render_template('orders/batch.html',
                                   persons=persons, team_groups=team_groups,
                                   teams=teams, default_team=default_team,
                                   preview_json=preview_json_obj,
                                   preview_orders=serialized,
                                   preview_total=total,
                                   templates=templates,
                                   fault_groups=fault_groups,
                                   fault_group_items=fault_group_items,
                                   by_date=dict(by_date),
                                   sorted_dates=sorted_dates,
                                   year=int(request.form.get('year', datetime.now().year)),
                                   month=int(request.form.get('month', datetime.now().month)),
                                   min_per_day=int(request.form.get('min_per_day', 20)),
                                   max_per_day=int(request.form.get('max_per_day', 45)),
                                   everyday=request.form.get('everyday') == 'on',
                                   selected_names=request.form.getlist('selected_names'),
                                   dates_str=request.form.get('specific_dates', '').strip())
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template('orders/batch.html', persons=persons,
                                   team_groups=team_groups, teams=teams,
                                   default_team=default_team,
                                   templates=templates, fault_groups=fault_groups,
                                   fault_group_items=fault_group_items)
        except Exception as e:
            flash(f'生成失败：{str(e)}', 'danger')
            return render_template('orders/batch.html', persons=persons,
                                   team_groups=team_groups, teams=teams,
                                   default_team=default_team,
                                   templates=templates, fault_groups=fault_groups,
                                   fault_group_items=fault_group_items)

    if request.method == 'POST' and request.form.get('action') == 'confirm':
        try:
            total, batch_ids = svc.batch_confirm(
                request.form.get('preview_json', ''), current_user
            )
            session['last_batch_time'] = datetime.now().isoformat()
            session['last_batch_count'] = total
            session['last_batch_ids'] = batch_ids
            flash(f'批量生成成功！共 {total} 条工单已保存到当月工单', 'success')
            return redirect(url_for('orders.list_orders'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            flash(f'保存失败：{str(e)}', 'danger')

    # GET：检查可反悔批次
    can_undo = False
    undo_count = 0
    last_batch_time = session.get('last_batch_time')
    if last_batch_time and session.get('last_batch_ids'):
        try:
            bt = datetime.fromisoformat(last_batch_time)
            if (datetime.now() - bt).total_seconds() < 300:
                can_undo = True
                undo_count = session.get('last_batch_count', 0)
            else:
                session.pop('last_batch_time', None)
                session.pop('last_batch_ids', None)
                session.pop('last_batch_count', None)
        except Exception:
            pass

    return render_template('orders/batch.html', persons=persons,
                           team_groups=team_groups, teams=teams,
                           default_team=default_team,
                           can_undo=can_undo, undo_count=undo_count,
                           templates=templates, fault_groups=fault_groups,
                           fault_group_items=fault_group_items)


@orders_bp.route('/batch/undo', methods=['POST'])
@login_required
def batch_undo():
    ids = session.get('last_batch_ids', [])
    if not ids:
        flash('没有可撤回的批次，或已超时（限5分钟内）', 'warning')
        return redirect(url_for('orders.batch_create'))
    try:
        deleted = svc.batch_undo(ids)
        session.pop('last_batch_time', None)
        session.pop('last_batch_ids', None)
        session.pop('last_batch_count', None)
        flash(f'已撤销最近一次批量生成的 {deleted} 条工单', 'success')
    except Exception as e:
        flash(f'撤销失败：{str(e)}', 'danger')
    return redirect(url_for('orders.list_orders'))


# ==================== 详情 / 编辑 / 删除 ====================

@orders_bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    order = svc.get_order_or_404(order_id)
    photos = []
    return render_template('orders/detail.html', order=order, photos=photos)


@orders_bp.route('/<int:order_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_order(order_id):
    order = svc.get_order_or_404(order_id)
    if request.method == 'POST':
        svc.update_order(order_id, request.form)
        flash('✅ 工单已更新', 'success')
        return redirect(url_for('orders.detail', order_id=order.id))
    persons = Person.query.filter_by(is_active=True).all()
    return render_template('orders/edit.html', order=order, persons=persons)


@orders_bp.route('/<int:order_id>/delete', methods=['POST'])
@login_required
def delete_order(order_id):
    svc.delete_order(order_id,
                     current_user.display_name or current_user.username)
    flash('工单已删除', 'success')
    return redirect(url_for('orders.list_orders'))


@orders_bp.route('/<int:order_id>/toggle_priority', methods=['POST'])
@login_required
def toggle_priority(order_id):
    try:
        priority = svc.toggle_priority(order_id)
        return jsonify({'priority': priority})
    except ValueError as e:
        order = svc.get_order_or_404(order_id)
        return jsonify({'error': str(e), 'priority': order.priority}), 403


# ==================== 星标 ====================

@orders_bp.route('/<int:order_id>/star', methods=['POST'])
@login_required
def toggle_star(order_id):
    """切换星标"""
    star = WorkOrderStar.query.filter_by(
        user_id=current_user.id, order_id=order_id
    ).first()
    if star:
        db.session.delete(star)
        db.session.commit()
        return jsonify({'starred': False})
    else:
        star = WorkOrderStar(user_id=current_user.id, order_id=order_id)
        db.session.add(star)
        db.session.commit()
        return jsonify({'starred': True})


# ==================== 催办 ====================

@orders_bp.route('/<int:order_id>/urge', methods=['POST'])
@login_required
def urge_order(order_id):
    """催办工单 -> 推送企业微信"""
    order = svc.get_order_or_404(order_id)
    try:
        from routes.api_mobile import send_wecom_notification, send_new_order_notification
        # 用催办专用消息
        title = f'🔔 工单催办通知'
        msg = f'工单 #{order.id}「{order.title}」已被催办！\n'
        msg += f'负责人：{order.person or "未指派"} | 状态：{order.status}\n'
        if order.building:
            msg += f'位置：{order.building}'
            if order.department:
                msg += f' - {order.department}'
            msg += '\n'
        msg += f'催办人：{current_user.display_name or current_user.username}\n'
        msg += f'请尽快处理！'

        # 推送到企业微信
        wecom_webhook = SystemSetting.get('wecom_webhook', '')
        if wecom_webhook:
            import requests
            payload = {"msgtype": "text", "text": {"content": msg}}
            try:
                requests.post(wecom_webhook, json=payload, timeout=5)
            except Exception:
                pass
        return jsonify({'success': True, 'message': '催办通知已发送'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 批量操作 ====================

@orders_bp.route('/api/batch', methods=['POST'])
@login_required
def batch_operations():
    """批量操作：assign / priority / star / unstar / delete"""
    data = request.get_json() or {}
    action = data.get('action', '')
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'success': False, 'error': '请选择工单'}), 400
    if not action:
        return jsonify({'success': False, 'error': '请指定操作类型'}), 400

    try:
        if action == 'delete':
            count = 0
            for oid in ids:
                order = WorkOrder.query.get(oid)
                if order:
                    db.session.delete(order)
                    count += 1
            db.session.commit()
            return jsonify({'success': True, 'message': f'已删除 {count} 条工单'})

        elif action == 'star':
            count = 0
            for oid in ids:
                if not WorkOrderStar.query.filter_by(user_id=current_user.id, order_id=oid).first():
                    s = WorkOrderStar(user_id=current_user.id, order_id=oid)
                    db.session.add(s)
                    count += 1
            db.session.commit()
            return jsonify({'success': True, 'message': f'已标星 {count} 条工单'})

        elif action == 'unstar':
            count = WorkOrderStar.query.filter(
                WorkOrderStar.user_id == current_user.id,
                WorkOrderStar.order_id.in_(ids)
            ).delete(synchronize_session=False)
            db.session.commit()
            return jsonify({'success': True, 'message': f'已取消星标 {count} 条工单'})

        elif action == 'assign':
            person = data.get('person', '')
            if not person:
                return jsonify({'success': False, 'error': '请选择人员'}), 400
            count = WorkOrder.query.filter(
                WorkOrder.id.in_(ids)
            ).update({'person': person}, synchronize_session=False)
            # 有指派视为接单
            now = datetime.now()
            for oid in ids:
                order = WorkOrder.query.get(oid)
                if order and order.status == 'pending':
                    order.status = 'in_progress'
                    order.accepted_at = now
            db.session.commit()
            return jsonify({'success': True, 'message': f'已指派 {count} 条工单给 {person}'})

        elif action == 'priority':
            priority = data.get('priority', 'normal')
            if priority not in ('normal', 'urgent', 'emergency'):
                return jsonify({'success': False, 'error': '无效优先级'}), 400
            count = WorkOrder.query.filter(
                WorkOrder.id.in_(ids)
            ).update({'priority': priority, 'original_priority': priority}, synchronize_session=False)
            db.session.commit()
            return jsonify({'success': True, 'message': f'已修改 {count} 条工单优先级为 {priority}'})

        else:
            return jsonify({'success': False, 'error': f'未知操作: {action}'}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 列配置 ====================

@orders_bp.route('/api/column_config', methods=['GET', 'POST'])
@login_required
def column_config():
    """保存/获取用户列配置"""
    if request.method == 'POST':
        data = request.get_json() or {}
        columns = data.get('columns', [])
        session['order_columns'] = columns
        return jsonify({'success': True})
    else:
        columns = session.get('order_columns')
        if columns:
            return jsonify({'columns': columns})
        return jsonify({'columns': None})


# ==================== 导出 Excel ====================

@orders_bp.route('/export')
@login_required
def export_excel():
    filters = {
        'status': request.args.get('status', ''),
        'fault_type': request.args.get('fault_type', ''),
        'person': request.args.get('person', ''),
        'keyword': request.args.get('keyword', ''),
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
    }
    query = svc.build_order_query(filters)
    orders = query.all()
    total = len(orders)

    wb = Workbook()
    ws = wb.active
    ws.title = '工单导出'
    headers = ['编号', '工单名称', '设备类型', '故障类型', '描述',
               '楼区', '楼层', '科室', '位置', '处理人',
               '开始时间', '结束时间', '状态', '解决方案', '创建人', '创建时间']
    ws.append(headers)
    for o in orders:
        ws.append([
            o.id, o.title, o.device_type, o.fault_type, o.description,
            o.building, o.floor, o.department, o.location, o.person,
            o.start_time.strftime('%Y-%m-%d %H:%M') if o.start_time else '',
            o.end_time.strftime('%Y-%m-%d %H:%M') if o.end_time else '',
            {'pending': '待接单', 'in_progress': '处理中', 'completed': '已完成'}.get(o.status, o.status),
            o.solution,
            o.created_by,
            o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else '',
        ])

    filename = f'工单导出_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


# ==================== 发布页面（无登录报修） ====================

@orders_bp.route('/anonymous_publish', methods=['GET', 'POST'])
def anonymous_publish():
    """匿名报修（无需登录）"""
    verification = session.get('publish_verified', False)

    if request.method == 'POST':
        # 验证码防刷
        if not verification:
            code = request.form.get('verify_code', '').strip()
            if code != '4567':
                flash('验证码错误', 'danger')
                return render_template('orders/publish.html', anonymous=True)
            session['publish_verified'] = True
            verification = True

        # 走正常的发布逻辑，但创建人为"匿名"
        from services.address import extract_address_from_title
        title = request.form.get('title', '').strip()
        if not title:
            flash('请输入故障描述', 'danger')
            return render_template('orders/publish.html', anonymous=True)

        from services.keyword_config import get_fault_keywords, get_device_keywords
        fk = get_fault_keywords()
        dk = get_device_keywords()
        fault, device = svc._guess_fault_type(title, fk, dk)
        fm = match_fault(title)
        auto_fault = fm['category'] if fm['match_type'] == 'keyword' else fault
        addr = extract_address_from_title(title)

        building = request.form.get('building', '') or addr['building']
        floor = request.form.get('floor', '') or addr['floor']
        department = request.form.get('department', '') or addr['department']
        location = request.form.get('location', '') or addr.get('location', '')

        order = WorkOrder(
            title=title,
            device_type=device,
            fault_type=auto_fault,
            fault_subcategory=fm.get('subcategory', ''),
            description=request.form.get('description', ''),
            building=building, floor=floor,
            department=department, location=location,
            person='', solution='',
            start_time=datetime.now(),
            status='pending',
            created_by='匿名',
            priority='normal', original_priority='normal',
        )
        db.session.add(order)
        db.session.commit()
        flash('✅ 报修已提交，请等待工程师联系', 'success')
        return redirect(url_for('orders.anonymous_publish'))

    return render_template('orders/publish.html', anonymous=True)


# ==================== Excel 导入工单 ====================

@orders_bp.route('/import/template')
@login_required
def download_import_template():
    """下载工单导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = "工单导入模板"
    headers = ['工单名称*', '设备类型', '故障类型', '故障描述',
               '楼区', '楼层', '科室', '位置',
               '经办人', '解决方案', '开始时间', '结束时间', '状态', '紧急程度']
    ws.append(headers)
    ws.append(['示例：电脑无法开机', '电脑', '硬件', '开机黑屏',
               '1号楼', '3层', '信息科', '301室',
               '张三', '更换电源线', '2026-07-01 09:00', '2026-07-01 09:30', 'completed', 'normal'])
    for col, w in zip('ABCDEFGHIJKLMN', [30, 10, 10, 20, 10, 8, 12, 12, 10, 20, 16, 16, 12, 10]):
        ws.column_dimensions[col].width = w
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='工单导入模板.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@orders_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_orders():
    """批量导入工单（Excel）"""
    from openpyxl import load_workbook

    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('请选择 Excel 文件', 'danger')
            return render_template('orders/import.html')
        try:
            wb = load_workbook(file, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True))
            if not rows:
                flash('Excel 文件为空', 'danger')
                return render_template('orders/import.html')
            imported = 0
            errors = []
            now = datetime.now()
            for idx, row in enumerate(rows, start=2):
                if not row or not row[0]:
                    continue
                title = str(row[0] or '').strip()
                if not title:
                    errors.append(f'第{idx}行：缺少工单名称')
                    continue
                try:
                    order = WorkOrder(
                        title=title, device_type=str(row[1] or '其他').strip()[:50],
                        fault_type=str(row[2] or '硬件').strip()[:50],
                        description=str(row[3] or '').strip(),
                        building=str(row[4] or '').strip()[:50],
                        floor=str(row[5] or '').strip()[:20],
                        department=str(row[6] or '').strip()[:100],
                        location=str(row[7] or '').strip()[:200],
                        person=str(row[8] or '').strip()[:50],
                        solution=str(row[9] or '').strip(),
                        status='pending', priority='normal',
                        created_by=current_user.display_name or current_user.username,
                    )
                    if row[10]:
                        try:
                            order.start_time = row[10] if isinstance(row[10], datetime) else datetime.strptime(str(row[10]).strip(), '%Y-%m-%d %H:%M')
                            order.created_at = order.start_time
                        except Exception:
                            pass
                    if row[11]:
                        try:
                            order.end_time = row[11] if isinstance(row[11], datetime) else datetime.strptime(str(row[11]).strip(), '%Y-%m-%d %H:%M')
                        except Exception:
                            pass
                    sv = str(row[12] or '').strip().lower()
                    if sv in ('pending', 'in_progress', 'completed'):
                        order.status = sv
                        if sv == 'completed' and not order.end_time:
                            order.completed_at = order.end_time or now
                        elif sv == 'in_progress':
                            order.accepted_at = now
                    pri = str(row[13] or '').strip().lower()
                    if pri in ('normal', 'urgent', 'emergency'):
                        order.priority = pri
                        order.original_priority = pri
                    if order.person and not order.accepted_at:
                        order.accepted_at = order.created_at or now
                    db.session.add(order)
                    imported += 1
                except Exception as e:
                    errors.append(f'第{idx}行：{str(e)}')
            db.session.commit()
            msg = f'✅ 成功导入 {imported} 条工单'
            if errors:
                msg += f'，{len(errors)} 条错误（见下方）'
            flash(msg, 'success' if not errors else 'warning')
            return render_template('orders/import.html', imported=imported, errors=errors[:50])
        except Exception as e:
            flash(f'导入失败：{str(e)}', 'danger')
            return render_template('orders/import.html')
    return render_template('orders/import.html')


# ==================== 工单日历 ====================

@orders_bp.route('/calendar')
@login_required
def calendar_view():
    """工单日历视图"""
    from calendar import monthrange
    from collections import defaultdict
    now = datetime.now()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)

    month_start = datetime(year, month, 1)
    _, days_in_month = monthrange(year, month)
    month_end = datetime(year, month, days_in_month, 23, 59, 59)

    # 组别筛选
    team = ''
    if not current_user.is_admin:
        _person = Person.query.filter_by(user_id=current_user.id).first()
        if _person and _person.team:
            team = _person.team
    team_persons = set()
    if team:
        tp = Person.query.filter(Person.team == team, Person.is_active == True).all()
        team_persons = {p.name for p in tp if p.name}

    orders = WorkOrder.query.filter(
        WorkOrder.created_at >= month_start,
        WorkOrder.created_at <= month_end,
    )
    if team_persons:
        orders = orders.filter(WorkOrder.person.in_(team_persons))
    orders = orders.order_by(WorkOrder.created_at).all()

    cal_data = defaultdict(list)
    for o in orders:
        cal_data[o.created_at.day].append(o)

    weekdays = ['一', '二', '三', '四', '五', '六', '日']
    first_weekday = month_start.weekday()

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    return render_template('orders/calendar.html',
                           year=year, month=month,
                           days_in_month=days_in_month,
                           first_weekday=first_weekday,
                           weekdays=weekdays,
                           cal_data=dict(cal_data),
                           prev_month=prev_month, prev_year=prev_year,
                           next_month=next_month, next_year=next_year,
                           now=now)


@orders_bp.route('/api/calendar-day')
@login_required
def calendar_day_api():
    """返回某一天的工单列表（日历弹窗JSON API）"""
    date_str = request.args.get('date', '')
    if not date_str:
        return jsonify([])
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        next_dt = dt + timedelta(days=1)
    except ValueError:
        return jsonify([])
    orders = WorkOrder.query.filter(
        WorkOrder.created_at >= dt,
        WorkOrder.created_at < next_dt,
    )
    if not current_user.is_admin:
        _person = Person.query.filter_by(user_id=current_user.id).first()
        if _person and _person.team:
            tp = Person.query.filter(
                Person.team == _person.team, Person.is_active == True
            ).all()
            team_names = {p.name for p in tp if p.name}
            if team_names:
                orders = orders.filter(WorkOrder.person.in_(team_names))
    orders = orders.order_by(WorkOrder.created_at).all()
    return jsonify([{
        'id': o.id,
        'title': o.title,
        'status': o.status,
        'priority': o.priority,
        'person': o.person,
        'start_time': o.start_time.strftime('%H:%M') if o.start_time else '',
        'detail_url': url_for('orders.detail', order_id=o.id),
    } for o in orders])


# ==================== 工单照片上传/删除 ====================

@orders_bp.route('/<int:order_id>/photos/upload', methods=['POST'])
@login_required
def upload_photo(order_id):
    """上传工单照片"""
    order = WorkOrder.query.get_or_404(order_id)
    files = request.files.getlist('photos')
    if not files:
        flash('请选择图片', 'warning')
        return redirect(url_for('orders.detail', order_id=order.id))

    from utils.photo import save_photo, allowed_file
    person_name = current_user.display_name or current_user.username
    count = 0
    for f in files:
        if not f.filename or not allowed_file(f.filename):
            continue
        try:
            file_data = f.read()
            rel_path, w, h, size = save_photo(file_data, f.filename)
            photo = WorkOrderPhoto(
                work_order_id=order.id, filename=f.filename,
                filepath=rel_path, file_size=size, width=w, height=h,
                uploaded_by=person_name,
            )
            db.session.add(photo)
            count += 1
        except Exception:
            pass
    db.session.commit()
    flash(f'✅ 上传成功 {count} 张图片', 'success')
    return redirect(url_for('orders.detail', order_id=order.id))


@orders_bp.route('/<int:order_id>/photos/<int:photo_id>/delete', methods=['POST'])
@login_required
def delete_photo(order_id, photo_id):
    """删除工单照片"""
    from models import WorkOrderPhoto
    photo = db.session.get(WorkOrderPhoto, photo_id)
    if photo and photo.work_order_id == int(order_id):
        import os
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
        if photo.filepath:
            fp = os.path.join(base, photo.filepath)
            if os.path.exists(fp):
                os.remove(fp)
        db.session.delete(photo)
        db.session.commit()
    flash('✅ 已删除', 'success')
    return redirect(url_for('orders.detail', order_id=order_id))


# ==================== 工单搜索 API ====================

@orders_bp.route('/api/search')
@login_required
def search_orders_api():
    """JSON API: 搜索工单（供知识库引用）"""
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 10)), 20)
    if not q:
        return jsonify([])
    orders = WorkOrder.query.filter(
        db.or_(
            WorkOrder.title.ilike(f'%{q}%'),
            WorkOrder.id.ilike(f'%{q}%'),
        )
    ).order_by(WorkOrder.id.desc()).limit(limit).all()
    return jsonify([{
        'id': o.id,
        'title': o.title,
        'detail_url': url_for('orders.detail', order_id=o.id),
        'person': o.person or '',
        'building': o.building or '',
        'floor': o.floor or '',
        'status': o.status,
    } for o in orders])
