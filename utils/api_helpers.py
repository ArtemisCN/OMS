"""通用工具函数：错误处理、分页、序列化"""
from functools import wraps
from flask import jsonify, request, g, current_app

def api_error_handler(default_status=500):
    """API 端点统一错误处理装饰器
    用法: @api_error_handler() 或 @api_error_handler(400)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except ValueError as e:
                return jsonify({'error': str(e), 'code': 400}), 400
            except KeyError as e:
                return jsonify({'error': f'缺少字段: {e}', 'code': 400}), 400
            except PermissionError as e:
                return jsonify({'error': str(e), 'code': 403}), 403
            except Exception as e:
                current_app.logger.error(f'{f.__name__}: {e}')
                return jsonify({'error': str(e), 'code': default_status}), default_status
        return wrapper
    return decorator

def paginate(query, page=None, per_page=20):
    """通用分页
    返回: {items, total, page, pages, has_next, has_prev}
    """
    page = page or request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', per_page, type=int)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': pagination.items,
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }
