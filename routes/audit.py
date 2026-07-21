"""操作审计日志路由"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import AuditLog, db
from datetime import datetime

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


@audit_bp.route('/logs')
@login_required
def audit_logs():
    """审计日志列表页"""
    if not current_user.is_admin:
        return "无权访问", 403

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)
    action = request.args.get('action', '')
    target = request.args.get('target', '')
    keyword = request.args.get('keyword', '')

    query = AuditLog.query

    if action:
        query = query.filter(AuditLog.action == action)
    if target:
        query = query.filter(AuditLog.target_type == target)
    if keyword:
        query = query.filter(
            db.or_(
                AuditLog.operator.contains(keyword),
                AuditLog.target_desc.contains(keyword),
                AuditLog.detail.contains(keyword),
            )
        )

    query = query.order_by(AuditLog.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    action_counts = db.session.query(
        AuditLog.action, db.func.count(AuditLog.id)
    ).group_by(AuditLog.action).order_by(db.func.count(AuditLog.id).desc()).all()

    target_counts = db.session.query(
        AuditLog.target_type, db.func.count(AuditLog.id)
    ).group_by(AuditLog.target_type).order_by(db.func.count(AuditLog.id).desc()).all()

    return render_template('audit/logs.html',
                           logs=pagination.items,
                           pagination=pagination,
                           action=action,
                           target=target,
                           keyword=keyword,
                           action_counts=action_counts,
                           target_counts=target_counts,
                           now=datetime.now())


@audit_bp.route('/api/stats')
@login_required
def audit_stats():
    """审计统计 API"""
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = AuditLog.query.filter(AuditLog.created_at >= today_start).count()

    # 近7天趋势
    from datetime import timedelta
    trend = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        ds = day.replace(hour=0, minute=0, second=0, microsecond=0)
        de = ds + timedelta(days=1)
        c = AuditLog.query.filter(
            AuditLog.created_at >= ds,
            AuditLog.created_at < de
        ).count()
        trend.append({'date': day.strftime('%m/%d'), 'count': c})

    top_operators = db.session.query(
        AuditLog.operator, db.func.count(AuditLog.id).label('cnt')
    ).group_by(AuditLog.operator).order_by(db.desc('cnt')).limit(10).all()

    return jsonify({
        'total': AuditLog.query.count(),
        'today': today_count,
        'trend': trend,
        'top_operators': [{'name': o, 'count': int(c)} for o, c in top_operators],
    })
