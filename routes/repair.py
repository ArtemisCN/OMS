"""维修单管理蓝图 - 仅保留流程(创建/查看/审核/打印)，模板统一由电子表单管理"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models import db, FormTemplate, RepairOrder, WorkOrder
from datetime import datetime, timedelta
from sqlalchemy import func, extract
import json

repair_bp = Blueprint('repair', __name__, url_prefix='/repair')


def login_required_repair(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


# ============ 维修单管理 ============

@repair_bp.route('/')
@login_required_repair
def order_list():
    orders = RepairOrder.query.order_by(RepairOrder.created_at.desc()).all()
    return render_template('repair/orders.html', orders=orders)


# ============ 统计报表 ============


def _get_stats_data(period='month'):
    """Build comprehensive stats dictionary for repair orders."""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- determine date range and grouping formula ---
    if period == 'week':
        start_date = today - timedelta(days=6)
        trend_label = 'date'
    elif period == 'quarter':
        start_date = today - timedelta(days=89)
        trend_label = 'week'
    elif period == 'year':
        start_date = today - timedelta(days=364)
        trend_label = 'month'
    else:  # month
        start_date = today - timedelta(days=29)
        trend_label = 'date'

    # base query filter for date range
    in_range = RepairOrder.created_at >= start_date

    # --- summary ---
    summary_counts = db.session.query(
        RepairOrder.status,
        func.count(RepairOrder.id)
    ).group_by(RepairOrder.status).all()

    summary = {'draft': 0, 'pending': 0, 'approved': 0, 'rejected': 0}
    total = 0
    for status, cnt in summary_counts:
        summary[status] = cnt
        total += cnt
    summary['total'] = total
    summary['approval_rate'] = round(
        (summary['approved'] / (summary['approved'] + summary['rejected']) * 100), 1
    ) if (summary['approved'] + summary['rejected']) > 0 else 0.0

    # --- status_distribution (same shape but without total/approval_rate) ---
    status_distribution = {'draft': summary['draft'], 'pending': summary['pending'],
                           'approved': summary['approved'], 'rejected': summary['rejected']}

    # --- trend ---
    trend = []
    if trend_label == 'date':
        # daily buckets for last N days
        cursor = start_date
        while cursor <= today:
            day_end = cursor + timedelta(days=1)
            created = RepairOrder.query.filter(
                RepairOrder.created_at >= cursor,
                RepairOrder.created_at < day_end
            ).count()
            approved = RepairOrder.query.filter(
                RepairOrder.approved_at >= cursor,
                RepairOrder.approved_at < day_end,
                RepairOrder.status == 'approved'
            ).count()
            trend.append({
                'date': cursor.strftime('%m/%d'),
                'created': created,
                'approved': approved,
            })
            cursor += timedelta(days=1)

    elif trend_label == 'week':
        # weekly buckets (Mon-Sun) for last ~13 weeks
        cursor = start_date
        while cursor <= today:
            week_end = cursor + timedelta(days=7)
            created = RepairOrder.query.filter(
                RepairOrder.created_at >= cursor,
                RepairOrder.created_at < week_end
            ).count()
            approved = RepairOrder.query.filter(
                RepairOrder.approved_at >= cursor,
                RepairOrder.approved_at < week_end,
                RepairOrder.status == 'approved'
            ).count()
            trend.append({
                'date': cursor.strftime('W%W'),
                'created': created,
                'approved': approved,
            })
            cursor += timedelta(days=7)

    elif trend_label == 'month':
        # monthly buckets for last 12 months
        cursor = start_date.replace(day=1)
        while cursor <= today:
            if cursor.month == 12:
                month_end = cursor.replace(year=cursor.year + 1, month=1)
            else:
                month_end = cursor.replace(month=cursor.month + 1)
            created = RepairOrder.query.filter(
                RepairOrder.created_at >= cursor,
                RepairOrder.created_at < month_end
            ).count()
            approved = RepairOrder.query.filter(
                RepairOrder.approved_at >= cursor,
                RepairOrder.approved_at < month_end,
                RepairOrder.status == 'approved'
            ).count()
            trend.append({
                'date': cursor.strftime('%Y-%m'),
                'created': created,
                'approved': approved,
            })
            cursor = month_end

    # --- monthly (full calendar months, not limited by period) ---
    monthly_raw = db.session.query(
        func.strftime('%Y-%m', RepairOrder.created_at).label('month'),
        func.count(RepairOrder.id).label('created'),
    ).filter(in_range).group_by('month').order_by('month').all()

    monthly_approved_raw = db.session.query(
        func.strftime('%Y-%m', RepairOrder.approved_at).label('month'),
        func.count(RepairOrder.id).label('approved'),
    ).filter(
        RepairOrder.approved_at >= start_date,
        RepairOrder.status == 'approved'
    ).group_by('month').order_by('month').all()

    monthly_map = {}
    for m, c in monthly_raw:
        monthly_map[m] = {'month': m, 'created': c, 'approved': 0}
    for m, c in monthly_approved_raw:
        if m in monthly_map:
            monthly_map[m]['approved'] = c
        else:
            monthly_map[m] = {'month': m, 'created': 0, 'approved': c}

    monthly = sorted(monthly_map.values(), key=lambda x: x['month'])

    # --- top_creators ---
    top_raw = db.session.query(
        RepairOrder.created_by,
        func.count(RepairOrder.id).label('cnt')
    ).filter(in_range).group_by(RepairOrder.created_by).order_by(func.count(RepairOrder.id).desc()).limit(10).all()

    top_creators = [{'name': name or '未知', 'count': cnt} for name, cnt in top_raw]

    # --- avg_approval_hours ---
    avg_hours_row = db.session.query(
        func.avg(
            func.julianday(RepairOrder.approved_at) - func.julianday(RepairOrder.created_at)
        ) * 24
    ).filter(
        RepairOrder.status == 'approved',
        RepairOrder.approved_at.isnot(None)
    ).scalar()

    avg_approval_hours = round(float(avg_hours_row), 1) if avg_hours_row else 0.0

    return {
        'summary': summary,
        'trend': trend,
        'status_distribution': status_distribution,
        'monthly': monthly,
        'top_creators': top_creators,
        'avg_approval_hours': avg_approval_hours,
    }


@repair_bp.route('/stats')
@login_required_repair
def order_stats():
    """渲染维修单统计报表页面"""
    period = request.args.get('period', 'month')
    if period not in ('week', 'month', 'quarter', 'year'):
        period = 'month'
    data = _get_stats_data(period)
    return render_template('repair/reports.html', data=data, period=period)


@repair_bp.route('/api/stats')
@login_required_repair
def order_stats_api():
    """维修单统计 JSON API"""
    period = request.args.get('period', 'month')
    if period not in ('week', 'month', 'quarter', 'year'):
        period = 'month'
    data = _get_stats_data(period)
    return jsonify(data)


# ============ 维修单查看/操作 ============

@repair_bp.route('/<int:oid>')
@login_required_repair
def order_view(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        flash('维修单不存在', 'danger')
        return redirect(url_for('repair.order_list'))
    return render_template('repair/order_view.html', order=order)


@repair_bp.route('/<int:oid>/print')
@login_required_repair
def order_print(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        flash('维修单不存在', 'danger')
        return redirect(url_for('repair.order_list'))
    return render_template('repair/order_print.html', order=order)


@repair_bp.route('/<int:oid>/save_fields', methods=['POST'])
@login_required_repair
def order_save_fields(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    order.field_values = data.get('field_values', order.field_values)
    order.signatures = data.get('signatures', order.signatures)
    db.session.commit()
    return jsonify({'message': '已保存'})


@repair_bp.route('/<int:oid>/submit', methods=['POST'])
@login_required_repair
def order_submit(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    order.status = 'pending'
    db.session.commit()
    return jsonify({'message': '已提交审核', 'status': 'pending'})


@repair_bp.route('/<int:oid>/approve', methods=['POST'])
@login_required_repair
def order_approve(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    order.status = 'approved'
    order.approved_by = current_user.display_name or current_user.username
    order.approved_at = datetime.now()
    db.session.commit()
    return jsonify({'message': '已审核通过', 'status': 'approved'})


@repair_bp.route('/<int:oid>/reject', methods=['POST'])
@login_required_repair
def order_reject(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    order.status = 'draft'
    db.session.commit()
    return jsonify({'message': '已驳回，返回草稿', 'status': 'draft'})


@repair_bp.route('/<int:oid>/delete', methods=['POST'])
@login_required_repair
def order_delete(oid):
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    if order.status != 'draft':
        return jsonify({'error': '仅草稿状态可删除'}), 400
    db.session.delete(order)
    db.session.commit()
    return jsonify({'message': '已删除', 'redirect': url_for('repair.order_list')})


@repair_bp.route('/<int:oid>/sign', methods=['POST'])
@login_required_repair
def order_sign(oid):
    """保存签名图片"""
    order = db.session.get(RepairOrder, oid)
    if not order:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    field_id = data.get('field_id', '')
    signature_data = data.get('signature', '')
    if not field_id or not signature_data:
        return jsonify({'error': '参数不完整'}), 400
    sigs = order.signatures or {}
    sigs[field_id] = signature_data
    order.signatures = sigs
    db.session.commit()
    return jsonify({'message': '签名已保存'})
