"""简单的内存缓存工具（30秒TTL）"""
import time
from functools import wraps


_cache = {}


def cached(ttl=30):
    """装饰器：缓存函数返回值，ttl秒后过期"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from flask import g
            try:
                hid = g.get('hospital_id', 'all')
            except RuntimeError:
                hid = 'all'
            key = (f.__name__, hid, args, frozenset(kwargs.items()))
            now = time.time()
            entry = _cache.get(key)
            if entry and (now - entry['time']) < ttl:
                return entry['value']
            result = f(*args, **kwargs)
            _cache[key] = {'value': result, 'time': now}
            return result
        return wrapper
    return decorator


def clear_cache(prefix=None):
    """清除缓存（可指定前缀）"""
    global _cache
    if prefix is None:
        _cache.clear()
    else:
        _cache = {k: v for k, v in _cache.items() if not k[0].startswith(prefix)}
