"""
健康检查端点

提供 /health 路由，返回服务状态信息，供 Nginx 或外部监控系统使用。

响应格式:
    GET /health -> 200 OK
    {
        "status": "ok",
        "timestamp": "2026-07-14T10:30:00+08:00",
        "database": "ok",
        "version": "v2.1"
    }
"""

from flask import Blueprint, jsonify
from datetime import datetime, timezone, timedelta

health_bp = Blueprint('health', __name__)

VERSION = 'v2.1'


@health_bp.route('/health')
def health_check():
    """健康检查端点
    ---
    tags:
      - 健康检查
    summary: 综合健康检查
    description: 验证数据库连接并返回服务状态。供 Nginx 或外部监控系统使用。
    responses:
      200:
        description: 服务正常
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
            timestamp:
              type: string
              example: "2026-07-14T10:30:00+08:00"
            database:
              type: string
              example: ok
            version:
              type: string
              example: v2.1
      503:
        description: 数据库异常
    """
    db_status = 'ok'
    try:
        from flask import current_app
        from models import db
        # 执行轻量查询验证数据库连接
        db.session.execute(db.text('SELECT 1'))
        db.session.commit()
    except Exception as e:
        db_status = f'error: {str(e)[:100]}'

    return jsonify({
        'status': 'ok' if db_status == 'ok' else 'degraded',
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'database': db_status,
        'version': VERSION,
    }), 200 if db_status == 'ok' else 503


@health_bp.route('/health/readiness')
def readiness_check():
    """就绪检查
    ---
    tags:
      - 健康检查
    summary: 就绪检查
    description: 验证数据库连接和应用状态，判断是否准备好处理请求
    responses:
      200:
        description: 就绪
        schema:
          type: object
          properties:
            status:
              type: string
              example: ready
            timestamp:
              type: string
      503:
        description: 未就绪
    """
    try:
        from flask import current_app
        from models import db
        db.session.execute(db.text('SELECT 1'))
        db.session.commit()
        return jsonify({
            'status': 'ready',
            'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'not_ready',
            'error': str(e)[:100],
        }), 503


@health_bp.route('/health/liveness')
def liveness_check():
    """存活检查
    ---
    tags:
      - 健康检查
    summary: 存活检查
    description: 验证进程是否在运行，不依赖数据库
    responses:
      200:
        description: 存活
        schema:
          type: object
          properties:
            status:
              type: string
              example: alive
            timestamp:
              type: string
    """
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }), 200
