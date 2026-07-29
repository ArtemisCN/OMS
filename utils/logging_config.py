"""
日志与监控系统配置模块

功能:
  1. 结构化 JSON 日志（文件按天滚动，保留30天）
  2. 请求链路追踪（request_id）
  3. 慢查询监控（SQLAlchemy after_cursor_execute）
  4. 错误告警（企业微信/钉钉 webhook，5分钟去重）

用法:
  from utils.logging_config import setup_logging
  setup_logging(app)

环境变量:
  LOG_LEVEL              日志级别 (DEBUG/INFO/WARNING/ERROR), 默认 INFO
  LOG_DIR                日志目录，默认 logs/
  WEBHOOK_URL            企业微信/钉钉机器人 Webhook URL（可选，留空跳过告警）
  WEBHOOK_TYPE           告警渠道: wecom (企业微信, 默认) / dingtalk (钉钉)
  SLOW_QUERY_THRESHOLD   慢查询阈值（毫秒），默认 500
  ENABLE_CONSOLE_LOG     是否输出控制台日志 (true/false), 默认 true
"""

import os
import json
import uuid
import hashlib
import logging
import logging.handlers
import threading
import traceback
from datetime import datetime, timezone, timedelta
from collections import OrderedDict

import requests
from flask import g, request, has_request_context

# =============================================================================
# 配置常量（可被环境变量覆盖）
# =============================================================================
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
LOG_DIR = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs'))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')
WEBHOOK_TYPE = os.environ.get('WEBHOOK_TYPE', 'wecom').lower()
SLOW_QUERY_THRESHOLD = int(os.environ.get('SLOW_QUERY_THRESHOLD', '500'))
ENABLE_CONSOLE_LOG = os.environ.get('ENABLE_CONSOLE_LOG', 'true').lower() == 'true'
LOG_RETENTION_DAYS = 30
LOG_FILE_MAX_BYTES = 100 * 1024 * 1024  # 100MB

# 确保日志目录存在
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件路径
APP_LOG_PATH = os.path.join(LOG_DIR, 'app.log')
ERROR_LOG_PATH = os.path.join(LOG_DIR, 'error.log')
SLOW_QUERY_LOG_PATH = os.path.join(LOG_DIR, 'slow_query.log')

# =============================================================================
# 请求ID生成与注入
# =============================================================================
def generate_request_id():
    """生成唯一请求ID，用于链路追踪"""
    return uuid.uuid4().hex[:16]


class RequestIdFilter(logging.Filter):
    """日志过滤器：自动注入 request_id / user_id / hospital_id / path / method"""

    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', '-')
            record.user_id = getattr(g, 'user_id', '-')
            record.hospital_id = getattr(g, 'hospital_id', '-')
            record.path = request.path if request else '-'
            record.method = request.method if request else '-'
        else:
            record.request_id = '-'
            record.user_id = '-'
            record.hospital_id = '-'
            record.path = '-'
            record.method = '-'
        return True


# =============================================================================
# JSON 格式化器
# =============================================================================
class JsonFormatter(logging.Formatter):
    """自定义JSON格式化器，输出结构化日志"""

    def format(self, record):
        log_entry = OrderedDict()
        log_entry['timestamp'] = datetime.fromtimestamp(record.created, tz=timezone(timedelta(hours=8))).isoformat()
        log_entry['level'] = record.levelname
        log_entry['logger'] = record.name
        log_entry['request_id'] = getattr(record, 'request_id', '-')
        log_entry['user_id'] = getattr(record, 'user_id', '-')
        log_entry['hospital_id'] = getattr(record, 'hospital_id', '-')
        log_entry['path'] = getattr(record, 'path', '-')
        log_entry['method'] = getattr(record, 'method', '-')
        log_entry['message'] = record.getMessage()

        # duration_ms（由 after_request 设置）
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms

        # status_code（由 after_request 设置）
        if hasattr(record, 'status_code'):
            log_entry['status_code'] = record.status_code

        # 额外字段
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in ('args', 'asctime', 'created', 'exc_info', 'exc_text',
                           'filename', 'funcName', 'id', 'levelname', 'levelno',
                           'lineno', 'module', 'msecs', 'message', 'msg',
                           'name', 'pathname', 'process', 'processName',
                           'relativeCreated', 'stack_info', 'thread', 'threadName',
                           'request_id', 'user_id', 'hospital_id', 'path',
                           'method', 'duration_ms', 'status_code'):
                try:
                    json.dumps(value)
                    extra_fields[key] = value
                except (TypeError, ValueError):
                    extra_fields[key] = str(value)
        if extra_fields:
            log_entry['extra'] = extra_fields

        # 异常堆栈
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = traceback.format_exception(*record.exc_info)
            # 截断至 500 字符用于告警
            log_entry['exception_summary'] = traceback.format_exception_only(
                record.exc_info[0], record.exc_info[1]
            )

        return json.dumps(log_entry, ensure_ascii=False)


# =============================================================================
# 告警处理器（企业微信 / 钉钉）
# =============================================================================
class AlertHandler(logging.Handler):
    """
    错误告警处理器：ERROR/CRITICAL 日志自动发送至企业微信/钉钉群机器人
    同一错误内容5分钟内最多告警1次，避免刷屏
    """

    def __init__(self, webhook_url='', webhook_type='wecom'):
        super().__init__(level=logging.ERROR)
        self.webhook_url = webhook_url or WEBHOOK_URL
        self.webhook_type = webhook_type or WEBHOOK_TYPE
        self._alert_cache = {}  # fingerprint -> timestamp
        self._cache_lock = threading.Lock()
        self._cooldown_seconds = 300  # 5分钟

    def _get_fingerprint(self, record):
        """根据日志内容生成指纹，相同错误视为重复"""
        message = record.getMessage()
        # 如果有异常，使用异常类型+首行作为指纹
        if record.exc_info and record.exc_info[0]:
            exc_type = record.exc_info[0].__name__
            exc_msg = str(record.exc_info[1])
            fingerprint = f"{exc_type}:{exc_msg}"
        else:
            # 取消息前100字符作为指纹
            fingerprint = message[:100]
        return hashlib.md5(fingerprint.encode('utf-8')).hexdigest()

    def _is_throttled(self, fingerprint):
        """检查是否在冷却期内"""
        now = datetime.now().timestamp()
        with self._cache_lock:
            last_time = self._alert_cache.get(fingerprint)
            if last_time and (now - last_time) < self._cooldown_seconds:
                return True
            self._alert_cache[fingerprint] = now
            # 清理过期缓存
            expired = [k for k, v in self._alert_cache.items()
                       if (now - v) > self._cooldown_seconds * 2]
            for k in expired:
                self._alert_cache.pop(k, None)
        return False

    def emit(self, record):
        if not self.webhook_url:
            return  # 未配置 webhook，跳过告警

        try:
            fingerprint = self._get_fingerprint(record)
            if self._is_throttled(fingerprint):
                return  # 冷却期内，跳过

            message = record.getMessage()
            timestamp = datetime.fromtimestamp(record.created, tz=timezone(timedelta(hours=8))).isoformat()
            user_id = getattr(record, 'user_id', '-')
            hospital_id = getattr(record, 'hospital_id', '-')
            path = getattr(record, 'path', '-')
            method = getattr(record, 'method', '-')
            request_id = getattr(record, 'request_id', '-')

            # 截取堆栈信息（500字符）
            stack_trace = ''
            if record.exc_info and record.exc_info[0]:
                tb_lines = traceback.format_exception(*record.exc_info)
                stack_trace = ''.join(tb_lines)[:500]

            if self.webhook_type == 'dingtalk':
                self._send_dingtalk(message, timestamp, user_id, hospital_id,
                                    path, method, request_id, stack_trace)
            else:
                self._send_wecom(message, timestamp, user_id, hospital_id,
                                 path, method, request_id, stack_trace)
        except Exception:
            self.handleError(record)

    def _send_wecom(self, message, timestamp, user_id, hospital_id,
                    path, method, request_id, stack_trace):
        """发送至企业微信机器人"""
        content = (
            f"🚨 **工单系统异常告警**\n"
            f"---\n"
            f"**时间**: {timestamp}\n"
            f"**用户**: {user_id} | **医院**: {hospital_id}\n"
            f"**请求**: [{method}] {path}\n"
            f"**请求ID**: {request_id}\n"
            f"**错误**: {message}\n"
        )
        if stack_trace:
            content += f"**堆栈**:\n```\n{stack_trace}\n```\n"
        content += f"---\n🔗 {request.host_url if has_request_context() else '-'}"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except requests.RequestException:
            pass  # 告警失败不中断主流程

    def _send_dingtalk(self, message, timestamp, user_id, hospital_id,
                       path, method, request_id, stack_trace):
        """发送至钉钉机器人"""
        text = (
            f"🚨 工单系统异常告警\n"
            f"---\n"
            f"时间: {timestamp}\n"
            f"用户: {user_id} | 医院: {hospital_id}\n"
            f"请求: [{method}] {path}\n"
            f"请求ID: {request_id}\n"
            f"错误: {message}\n"
        )
        if stack_trace:
            text += f"堆栈:\n{stack_trace}\n"

        payload = {
            "msgtype": "text",
            "text": {
                "content": text
            }
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except requests.RequestException:
            pass  # 告警失败不中断主流程


# =============================================================================
# 慢查询日志处理器（单独文件）
# =============================================================================
class SlowQueryHandler(logging.Handler):
    """慢查询日志写入专用文件"""

    def __init__(self, filepath):
        super().__init__(level=logging.WARNING)
        self._handler = logging.handlers.RotatingFileHandler(
            filepath,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_RETENTION_DAYS,
            encoding='utf-8'
        )
        self._handler.setFormatter(JsonFormatter())

    def emit(self, record):
        self._handler.emit(record)


# =============================================================================
# 日志配置入口
# =============================================================================
_logging_initialized = False


def setup_logging(app):
    """
    配置应用日志系统

    在 app.py 的 create_app() 中调用:
        from utils.logging_config import setup_logging
        setup_logging(app)
    """
    global _logging_initialized
    if _logging_initialized:
        app.logger.warning("日志系统已初始化，跳过重复配置")
        return

    # ----- 1. 创建根日志器 -----
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # 清除默认 handlers，避免重复
    root_logger.handlers.clear()

    # ----- 2. 应用日志器 -----
    app_logger = logging.getLogger('hospital')
    app_logger.setLevel(LOG_LEVEL)
    app_logger.handlers.clear()
    app_logger.propagate = False

    # 2a. 文件 handler（按天滚动，保留30天）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        APP_LOG_PATH, when='midnight', interval=1,
        backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(JsonFormatter())
    app_logger.addHandler(file_handler)

    # 2b. 错误专用文件 handler（仅 ERROR 及以上）
    error_file_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_PATH, maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(JsonFormatter())
    app_logger.addHandler(error_file_handler)

    # 2c. 控制台输出
    if ENABLE_CONSOLE_LOG:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(LOG_LEVEL)
        console_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        app_logger.addHandler(console_handler)

    # 2d. 告警处理器
    if WEBHOOK_URL:
        alert_handler = AlertHandler(WEBHOOK_URL, WEBHOOK_TYPE)
        app_logger.addHandler(alert_handler)

    # 2e. RequestIdFilter 对所有 handler 生效
    request_id_filter = RequestIdFilter()
    for handler in app_logger.handlers:
        handler.addFilter(request_id_filter)

    # ----- 3. 取代 Flask 默认日志器 -----
    app.logger.handlers.clear()
    app.logger.propagate = False
    for handler in app_logger.handlers:
        app.logger.addHandler(handler)

    # ----- 4. 配置 SQLAlchemy 日志器（不单独输出，由根日志器接管） -----
    sqlalchemy_logger = logging.getLogger('sqlalchemy.engine')
    sqlalchemy_logger.setLevel(logging.WARNING)  # 仅 WARNING 及以上
    sqlalchemy_logger.handlers.clear()

    # ----- 5. 配置慢查询日志 ----」
    slow_query_logger = logging.getLogger('hospital.slow_query')
    slow_query_logger.setLevel(logging.WARNING)
    slow_query_logger.handlers.clear()
    slow_query_logger.propagate = False

    slow_query_handler = SlowQueryHandler(SLOW_QUERY_LOG_PATH)
    slow_query_handler.setLevel(logging.WARNING)
    slow_query_handler.addFilter(RequestIdFilter())
    slow_query_logger.addHandler(slow_query_handler)

    slow_query_file_handler = logging.handlers.RotatingFileHandler(
        SLOW_QUERY_LOG_PATH, maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
    )
    slow_query_file_handler.setLevel(logging.WARNING)
    slow_query_file_handler.setFormatter(JsonFormatter())
    slow_query_file_handler.addFilter(RequestIdFilter())
    slow_query_logger.addHandler(slow_query_file_handler)

    # 同时输出到主日志文件（便于统一检索）
    main_slow_handler = logging.handlers.TimedRotatingFileHandler(
        APP_LOG_PATH, when='midnight', interval=1,
        backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
    )
    main_slow_handler.setLevel(logging.WARNING)
    main_slow_handler.setFormatter(JsonFormatter())
    main_slow_handler.addFilter(RequestIdFilter())
    slow_query_logger.addHandler(main_slow_handler)

    if ENABLE_CONSOLE_LOG:
        slow_console = logging.StreamHandler()
        slow_console.setLevel(logging.WARNING)
        slow_console.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s [SLOW_QUERY] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        slow_query_logger.addHandler(slow_console)

    # ----- 6. 把 logger 存入 app 方便其他模块使用 -----
    app.logger_inst = app_logger
    app.slow_query_logger = slow_query_logger

    _logging_initialized = True
    app.logger.info("日志系统初始化完成 → %s", APP_LOG_PATH)

    return app_logger


def get_logger(name=None):
    """获取应用日志器"""
    return logging.getLogger('hospital' + (f'.{name}' if name else ''))


def get_slow_query_logger():
    """获取慢查询日志器"""
    return logging.getLogger('hospital.slow_query')


# =============================================================================
# SQLAlchemy 慢查询监听
# =============================================================================
def register_slow_query_listener(app):
    """
    注册 SQLAlchemy 事件监听，记录慢查询日志

    在 app.py 中 setup_logging 之后调用:
        from utils.logging_config import register_slow_query_listener
        register_slow_query_listener(app)
    """
    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
    except ImportError:
        app.logger.warning("SQLAlchemy 不可用，跳过慢查询监听注册")
        return

    slow_logger = get_slow_query_logger()

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """SQL 执行后检查耗时"""
        # 跳过健康检查查询
        if has_request_context() and request.path == '/health':
            return

        # 计算执行时间（Flask-SQLAlchemy 在 connection 上设置 info）
        import time
        now = time.time()
        conn_info = conn.info
        start_time = conn_info.get('query_start_time', None)
        if start_time is None:
            return

        duration_ms = (now - start_time) * 1000
        del conn_info['query_start_time']

        if duration_ms >= SLOW_QUERY_THRESHOLD:
            # 截断超长 SQL
            sql = statement[:2000] if len(statement) > 2000 else statement
            params = str(parameters)[:500] if parameters else ''

            slow_logger.warning(
                "慢查询 %.0fms | SQL: %s | 参数: %s",
                duration_ms, sql, params,
                extra={
                    'duration_ms': round(duration_ms, 1),
                    'sql': sql,
                    'params': params,
                }
            )

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """SQL 执行前记录开始时间"""
        import time
        conn.info['query_start_time'] = time.time()
