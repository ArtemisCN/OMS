"""医院故障工单管理系统 - Web 版入口"""
import os
import sys
from flask import Flask
from flask_login import LoginManager

# 确保项目目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as app_config
from models import db, User


def create_app():
    app = Flask(__name__)
    app.config.from_object(app_config)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'hospital-workorder-secret-2026')

    # 微信小程序配置（从环境变量注入 app.config）
    app.config['WECHAT_APPID'] = os.environ.get('WECHAT_APPID', '')
    app.config['WECHAT_SECRET'] = os.environ.get('WECHAT_SECRET', '')
    app.config['WECOM_WEBHOOK_URL'] = os.environ.get('WECOM_WEBHOOK_URL', '')

    # Session 安全配置
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 28800  # 8小时（会被系统参数覆盖）
    app.config['REMEMBER_COOKIE_DURATION'] = 604800  # 7天

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # 注册蓝图
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.orders import orders_bp
    from routes.chat import chat_bp
    from routes.data import data_bp
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

    from routes.finance_asset import fin_bp as finance_asset_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(mobile_bp)
    app.register_blueprint(api_mobile_bp)
    app.register_blueprint(inspection_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(asset_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(repair_bp)
    app.register_blueprint(forms_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(finance_asset_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(inv_bp)
    app.register_blueprint(exam_bp)
    app.register_blueprint(miniapp_bp)
    app.register_blueprint(feature_bp)

    # 上下文处理器
    @app.context_processor
    def inject_now_and_permissions():
        from datetime import datetime
        from flask import g
        from flask_login import current_user
        from models import can_access, Hospital, SystemSetting
        # 注入当前医院信息（供模板切换显示）
        current_hospital = None
        hid = getattr(g, 'hospital_id', None)
        if hid:
            current_hospital = db.session.get(Hospital, hid)
        else:
            # 全部医院模式：构建一个虚拟对象用于显示
            class AllHospitals:
                id = 0
                name = '全部医院'
            current_hospital = AllHospitals()
        # 所有启用的医院（供管理员切换）
        all_hospitals = Hospital.query.filter_by(is_active=True).order_by(Hospital.id).all()
        # 当前用户可访问的医院列表（多医院用户使用）
        user_assigned_hospitals = getattr(g, 'user_assigned_hospitals', [])
        # 加载系统参数（带缓存优化：只查一次）
        sys_settings = {}
        for s in SystemSetting.query.filter(
            SystemSetting.key.in_(['system_name','system_subtitle','system_title_suffix','home_name','login_page_title','sidebar_auto_hide_seconds','default_dark_mode','primary_color','font_scale'])
        ).all():
            sys_settings[s.key] = s.value
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
        # 动态读取会话超时
        try:
            from models import SystemSetting
            st = SystemSetting.query.filter_by(key='session_timeout_minutes').first()
            if st and st.value:
                mins = int(st.value)
                app.config['PERMANENT_SESSION_LIFETIME'] = max(60, min(1440, mins)) * 60
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

    # 错误处理器
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        from flask import render_template
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template, jsonify, request
        if request.path.startswith('/api/'):
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

            from models import Person, SolutionTemplate
            default_names = ['徐天麟', '姚毫', '张程', '季张欢', '代茂霖']
            for name in default_names:
                if not Person.query.filter_by(name=name).first():
                    db.session.add(Person(name=name, is_active=True))
            for title, content in app_config.SOLUTION_TEMPLATES.items():
                db.session.add(SolutionTemplate(title=title, content=content))
            db.session.commit()
            print("✓ 初始化完成")
            print(f"  - 管理员: admin / admin123")
            print(f"  - 人员: {', '.join(default_names)}")
            print(f"  - 方案模板: {len(app_config.SOLUTION_TEMPLATES)} 条")
        else:
            # 检查方案模板是否已导入
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
    print(f"  管理员账号: admin / admin123")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
