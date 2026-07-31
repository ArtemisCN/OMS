"""操作审计日志路由"""

from utils.csrf import csrf_protect
from datetime import datetime
from flask import Blueprint, render_template, jsonify, redirect, url_for
from flask_login import login_required, current_user
from models import db, AuditLog
from utils.permissions import has_permission

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


@audit_bp.route('/logs')
@login_required
def audit_logs():
    """已合并到服务器监控页面"""
    return redirect(url_for('monitor.index'))


@audit_bp.route('/api/stats')
@login_required
def audit_stats():
    """审计统计 API"""
    if not has_permission(current_user, 'system:audit_log'):
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
