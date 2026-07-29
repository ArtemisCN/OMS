"""医院故障工单管理系统 - Web 版入口"""
import os
import sys
import mimetypes
import time as _time
from flask import Flask, g, request
from flask_login import LoginManager
from utils.logging_config import setup_logging, register_slow_query_listener

# 注册 .woff2 / .svg MIME 类型（Flask 开发服务器默认没有）
mimetypes.add_type('font/woff2', '.woff2')
mimetypes.add_type('image/svg+xml', '.svg')

# 确保项目目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as app_config
from models import db, User


def create_app():
    app = Flask(__name__)
    app.config.from_object(app_config)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    if not app.config['SECRET_KEY']:
        # 尝试从 .secret 文件读取（由 config.py 生成）
        _secret_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret')
        if os.path.exists(_secret_file):
            with open(_secret_file) as _f:
                app.config['SECRET_KEY'] = _f.read().strip()
    if not app.config['SECRET_KEY']:
        raise RuntimeError(
            'SECRET_KEY 未设置！请通过环境变量 SECRET_KEY 或 .secret 文件设置密钥。'
        )

    # 微信小程序配置（从环境变量注入 app.config）
    app.config['WECHAT_APPID'] = os.environ.get('WECHAT_APPID', '')
    app.config['WECHAT_SECRET'] = os.environ.get('WECHAT_SECRET', '')
    app.config['WECOM_WEBHOOK_URL'] = os.environ.get('WECOM_WEBHOOK_URL', '')

    # Session 安全配置
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30分钟（会被系统参数覆盖，管理员可在设置页调长）
    app.config['REMEMBER_COOKIE_DURATION'] = 604800  # 7天

    db.init_app(app)

    # ===== 初始化日志与监控系统 =====
    setup_logging(app)

    # ===== 初始化 Swagger API 文档 =====
    # 配置自定义路由: /api/docs (UI) 和 /api/openapi.json (JSON)
    app.config['SWAGGER'] = {
        'specs_route': '/api/docs/',
        'specs': [
            {
                'endpoint': 'apispec',
                'route': '/api/openapi.json',
                'rule_filter': lambda rule: True,
            }
        ],
        'static_url_path': '/flasgger_static',
    }
    from flasgger import Swagger
    swagger_template = {
        "info": {
            "title": "智维工控 · 医院工单管理 API",
            "description": "多院区工单系统 API 文档，覆盖小程序接口、Web 接口、资产管理等。\n\n认证方式：在请求头中添加 `Authorization: Bearer <token>`（登录接口返回的 token 值）",
            "version": "2.1.0",
            "contact": {
                "email": "admin@demolin.cn"
            }
        },
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT"
                }
            }
        },
        "tags": [
            {"name": "Mobile API", "description": "微信小程序/H5 移动端接口"},
            {"name": "健康检查", "description": "服务状态与健康检测"},
            {"name": "Web 页面", "description": "Web 管理端页面路由（返回 HTML）", "x-web-page": True},
        ]
    }
    swagger = Swagger(app, template=swagger_template)

    # 初始化系统参数缓存（避免每次请求查询 SystemSetting）
    with app.app_context():
        try:
            from models import SystemSetting
            st = SystemSetting.query.filter_by(key='session_timeout_minutes').first()
            if st and st.value:
                timeout = max(60, min(1440, int(st.value)))
            else:
                timeout = 30
        except Exception:
            timeout = 30
        app.config['SESSION_TIMEOUT'] = timeout
        app.config['SESSION_TIMEOUT_DYNAMIC'] = True  # 标记为可动态刷新

        # 加载全部系统设置到缓存（避免每次请求查数据库）
        _system_settings = {}
        for s in SystemSetting.query.all():
            _system_settings[s.key] = s.value
        app.config['SYSTEM_SETTINGS'] = _system_settings

        # 用系统设置的日志参数覆盖环境变量默认值
        if 'log_level' in _system_settings:
            app.config['LOG_LEVEL_FROM_SETTINGS'] = _system_settings['log_level']
            # 动态更新日志级别
            import logging
            level_name = _system_settings['log_level'].upper()
            level = getattr(logging, level_name, logging.INFO)
            for handler in getattr(app, 'logger_inst', app.logger).handlers:
                handler.setLevel(level)
            app.logger_inst.setLevel(level)
            app.logger.info("日志级别已设为 %s (来自系统设置)", level_name)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.orders import orders_bp
    from routes.chat import chat_bp
    from routes.data import data_bp
    from routes.data_personnel import data_personnel_bp
    from routes.data_department import data_department_bp
    from routes.data_fault import data_fault_bp
    from routes.data_address import data_address_bp
    from routes.mobile import mobile_bp
    from routes.api_mobile import api_mobile_bp
    from routes.inspection import inspection_bp
    from routes.audit import audit_bp
    from routes.report import report_bp
    from routes.asset import asset_bp
    from routes.stock import stock_bp
    from routes.data_settings import settings_bp
    from routes.repair import repair_bp
    from routes.forms import forms_bp
    from routes.monitor import monitor_bp
    from routes.analysis import analysis_bp
    from routes.finance import finance_bp
    from routes.report_qr import scan_bp
    from routes.inventory import inv_bp
    from routes.exam import exam_bp
    from routes.miniapp import miniapp_bp
    from routes.feature_modules import feature_bp
    from routes.contracts import contracts_bp
    from routes.sla import sla_bp
    from routes.efficiency import efficiency_bp
    from routes.assets import assets_bp
    from routes.dashboard import dashboard_bp
    from routes.health import health_bp

    from routes.finance_asset import fin_bp as finance_asset_bp

    # 蓝图清单（逐个声明，url_prefix 已在各蓝图构造函数中定义）
    BLUEPRINTS = [
        auth_bp, main_bp, orders_bp, data_bp, data_personnel_bp,
        data_department_bp, data_fault_bp, data_address_bp,
        mobile_bp, api_mobile_bp, inspection_bp, audit_bp,
        report_bp, asset_bp, stock_bp, settings_bp, repair_bp,
        forms_bp, monitor_bp, analysis_bp, finance_bp,
        finance_asset_bp, scan_bp, chat_bp, inv_bp, exam_bp,
        miniapp_bp, feature_bp, contracts_bp, sla_bp,
        efficiency_bp, assets_bp, dashboard_bp, health_bp,
    ]
    for _bp in BLUEPRINTS:
        app.register_blueprint(_bp)

    # 注册 SQLAlchemy 慢查询监听
    register_slow_query_listener(app)

    # 上下文处理器
    @app.context_processor
    def inject_now_and_permissions():
        from datetime import datetime
        from flask import g
        from flask_login import current_user
        from models import can_access, Hospital
        # 注入当前医院信息（供模板切换显示）
        current_hospital = None
        hid = getattr(g, 'hospital_id', None)
        if hid:
            current_hospital = Hospital.query.get(hid)
        else:
            # 全部医院模式：构建一个虚拟对象用于显示
            class AllHospitals:
                id = 0
                name = '全部医院'
            current_hospital = AllHospitals()
        # 所有启用的医院（供管理员切换）
        all_hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
        user_assigned_hospitals = getattr(g, 'user_assigned_hospitals', [])
        # 从缓存读取系统设置（启动时加载，/settings/refresh-config 可刷新）
        sys_settings = dict(app.config.get('SYSTEM_SETTINGS', {}))
        # 个人偏好覆盖全局设置
        if current_user.is_authenticated:
            for pk in ['primary_color', 'default_dark_mode', 'sidebar_auto_hide_seconds']:
                pv = current_user.get_pref(pk)
                if pv is not None:
                    sys_settings[pk] = pv
        return {
            'now': datetime.now(),
            'can_access': can_access,
            'current_hospital': current_hospital,
            'all_hospitals': all_hospitals,
            'user_assigned_hospitals': user_assigned_hospitals,
            'system_name': sys_settings.get('system_name', '智维工控'),
            'system_subtitle': sys_settings.get('system_subtitle', '运维智脑 · 智维工控'),
            'system_title_suffix': sys_settings.get('system_title_suffix', '医院智慧工单系统'),
            'home_name': sys_settings.get('home_name', '工单总览'),
            'login_page_title': sys_settings.get('login_page_title', '运维智脑 · 智维工控'),
            'sidebar_auto_hide_seconds': sys_settings.get('sidebar_auto_hide_seconds', '0'),
            'default_dark_mode': sys_settings.get('default_dark_mode', 'light'),
            'primary_color': sys_settings.get('primary_color', '#4f46e5'),
            'font_scale': sys_settings.get('font_scale', '100'),
        }

    # 多院区支持：请求前置处理
    @app.before_request
    def set_hospital_context():
        """根据当前用户设置医院上下文"""
        from flask import g, session
        from flask_login import current_user

        # ----- 日志链路追踪 -----
        from utils.logging_config import generate_request_id
        g.request_id = generate_request_id()
        g.start_time = _time.time()
        g.user_id = current_user.id if current_user.is_authenticated else None

        # 从缓存读取会话超时（避免每次请求查数据库）
        try:
            timeout = app.config.get('SESSION_TIMEOUT', 30)
            app.config['PERMANENT_SESSION_LIFETIME'] = timeout * 60
        except Exception:
            pass
        g.hospital_id = None
        g.user_assigned_hospitals = []
        if current_user.is_authenticated:
            if current_user.is_admin:
                g.hospital_id = session.get('admin_hospital_id')
                # 如果 session 未设置，尝试从系统参数读默认医院
                if g.hospital_id is None:
                    from models import SystemSetting
                    default = SystemSetting.query.filter_by(key='default_hospital_id').first()
                    if default and default.value:
                        g.hospital_id = int(default.value)
            else:
                # 非管理员：检查多医院列表
                assigned = current_user.get_assigned_hospitals()
                g.user_assigned_hospitals = assigned
                if len(assigned) > 1:
                    # 多医院用户：从 session 取当前选中
                    g.hospital_id = session.get('user_hospital_id')
                    if g.hospital_id is None:
                        g.hospital_id = assigned[0].id
                        session['user_hospital_id'] = g.hospital_id
                else:
                    # 单医院或无分配：兼容旧数据
                    hid = getattr(current_user, 'hospital_id', None)
                    if hid is None and assigned:
                        # 优先用关联表医院
                        hid = assigned[0].id
                    if hid is None:
                        # 尝试从关联的 Person 记录获取医院
                        try:
                            from models import Person
                            person = Person.query.filter_by(user_id=current_user.id).first()
                            if person and person.hospital_id:
                                hid = person.hospital_id
                        except Exception:
                            pass
                    if hid is None:
                        # 仍然没有医院，设为 -1 使自动过滤返回空结果
                        hid = -1
                    g.hospital_id = hid

    # 请求日志（after_request）
    @app.after_request
    def log_request(response):
        """记录每个请求的日志"""
        if request.path.startswith('/static/'):
            return response  # 静态文件不记录
        # 计算耗时
        duration_ms = round((_time.time() - getattr(g, 'start_time', _time.time())) * 1000, 1)
        # 获取日志器
        logger = getattr(app, 'logger_inst', app.logger)
        # 状态码
        status_code = response.status_code
        # 跳过健康检查的日志（减少噪音）
        if request.path.startswith('/health'):
            return response
        # 记录 INFO 级别日志（ERROR 由 errorhandler 记录）
        if status_code < 400:
            logger.info(
                "%s %s → %s (%sms)",
                request.method, request.path, status_code, duration_ms,
                extra={
                    'duration_ms': duration_ms,
                    'status_code': status_code,
                }
            )
        else:
            # 4xx/5xx 已由 errorhandler 记录，此处仅补充 duration
            pass
        # 添加响应头便于调试
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '-')
        response.headers['X-Response-Time-Ms'] = str(duration_ms)
        return response

    # 错误处理器
    @app.errorhandler(404)
    def not_found(e):
        logger = getattr(app, 'logger_inst', app.logger)
        logger.warning("404 %s %s", request.method, request.path, extra={'status_code': 404})
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        logger = getattr(app, 'logger_inst', app.logger)
        logger.error("500 %s %s", request.method, request.path,
                     exc_info=True, extra={'status_code': 500})
        from flask import render_template
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template, jsonify, request
        if request.path.startswith('/api/'):
            logger = getattr(app, 'logger_inst', app.logger)
            logger.warning("403 %s %s", request.method, request.path, extra={'status_code': 403})
            return jsonify(error='无权访问'), 403
        return render_template('errors/403.html'), 403

    return app


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
        # 首次运行自动初始化默认数据
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("首次启动，初始化默认数据...")
            admin = User(username='admin', display_name='管理员', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)

            from models import SolutionTemplate
            for title, content in app_config.SOLUTION_TEMPLATES.items():
                db.session.add(SolutionTemplate(title=title, content=content))
            db.session.commit()
            print("✓ 初始化完成")
            print(f"  - 管理员: admin / admin123")
            print(f"  - 方案模板: {len(app_config.SOLUTION_TEMPLATES)} 条")
        else:
            from models import SolutionTemplate
            if SolutionTemplate.query.count() == 0:
                print("导入方案模板...")
                for title, content in app_config.SOLUTION_TEMPLATES.items():
                    db.session.add(SolutionTemplate(title=title, content=content))
                db.session.commit()
                print(f"✓ 导入了 {len(app_config.SOLUTION_TEMPLATES)} 条方案模板")

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    debug = '--debug' in sys.argv

    print(f"\n{'='*50}")
    print(f"  医院故障工单管理系统 已启动")
    print(f"  访问地址: http://127.0.0.1:{port}")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
