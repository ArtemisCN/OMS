from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import json
from flask import g
from sqlalchemy import orm

db = SQLAlchemy()


# ======================== 多院区支持 ========================

class Hospital(db.Model):
    """医院/院区"""
    __tablename__ = 'hospitals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.String(200), default='')
    phone = db.Column(db.String(50), default='')
    is_active = db.Column(db.Boolean, default=True)
    logo = db.Column(db.String(200), default='')  # 自定义头像文件名
    created_at = db.Column(db.DateTime, default=datetime.now)
    persons = db.relationship('Person', backref='hospital', lazy='dynamic', foreign_keys='Person.hospital_id')


class HospitalMixin:
    """为数据模型添加医院隔离字段"""
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospitals.id'), nullable=False, default=1)


# 需要按医院过滤的模型白名单（__name__）
HOSPITAL_FILTERED_MODELS = {
    'Person', 'WorkOrder', 'Department', 'FaultType', 'FaultCategory',
    'FaultSubcategory', 'FaultKeyword', 'InspectionTemplate', 'InspectionPlan',
    'SolutionTemplate', 'AddressOverride', 'FormTemplate', 'PaperForm',
    'Asset', 'AssetLog', 'SparePart', 'StorageLocation', 'StockRecord',
    'Supplier', 'Consumable', 'ConsumableRecord', 'DutySchedule', 'DutyStaff',
    'RepairOrder', 'KnowledgeBase', 'PartPrice', 'PriceHistory', 'FinanceBatch',
    'FinanceInvoice', 'FinanceDraft', 'FinanceDraftPart',
    'InventoryTask', 'InventoryItem', 'InspectionCheckin',
    'MaintenanceContract',
    'FinanceReceipt', 'FinanceReceiptItem', 'FinanceDelivery', 'FinanceDeliveryItem',
}

# 全院区共享模型（hospital_id=0，不参与自动过滤）
SHARED_MODELS = {'Exam', 'ExamQuestion', 'ExamSubmission'}

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Query as SAQuery
from flask_sqlalchemy.query import Query as FSQuery

# 同时注册到两个 Query 类，确保 Flask-SQLAlchemy 也能触发
@sa_event.listens_for(SAQuery, 'before_compile', retval=True)
@sa_event.listens_for(FSQuery, 'before_compile', retval=True)
def auto_hospital_filter(query):
    """自动为所有带 hospital_id 的模型添加医院过滤（跳过 SHARED_MODELS）"""
    try:
        hid = getattr(g, 'hospital_id', None)
    except RuntimeError:
        return None
    if hid is None or hid == 0:
        return None

    # 检测已有 LIMIT/OFFSET 的查询，用 enable_assertions(False) 绕过断言
    has_limit = getattr(query, '_limit_clause', None) is not None
    has_offset = getattr(query, '_offset_clause', None) is not None

    for ent in query.column_descriptions:
        model = ent.get('type')
        if model is None:
            continue
        name = getattr(model, '__name__', None)
        if name and name in SHARED_MODELS:
            return None  # 共享模型不过滤
        if name and name in HOSPITAL_FILTERED_MODELS:
            if hasattr(model, 'hospital_id'):
                if has_limit or has_offset:
                    # 创建不带断言的新查询再 filter
                    q = query._generate()
                    q._enable_assertions = False
                    q = q.filter(model.hospital_id == hid)
                    return q
                return query.filter(model.hospital_id == hid)
            return None

    # 聚合查询（无实体类型）：扫描表达式中的表引用
    seen = set()
    for ent in query.column_descriptions:
        expr = ent.get('expr')
        if expr is None:
            continue
        for col in _iter_cols(expr):
            table = getattr(col, 'table', None)
            if table is None:
                continue
            tname = getattr(table, 'name', None)
            if tname and tname not in seen:
                seen.add(tname)
                model = _table_to_model(tname)
                if not model or model.__name__ not in HOSPITAL_FILTERED_MODELS:
                    continue
                if hasattr(model, 'hospital_id'):
                    if has_limit or has_offset:
                        q = query._generate()
                        q._enable_assertions = False
                        q = q.filter(model.hospital_id == hid)
                        return q
                    return query.filter(model.hospital_id == hid)
                break
    return None


def _iter_cols(expr):
    """递归遍历表达式中的所有 Column 引用"""
    from sqlalchemy.sql import visitors
    try:
        for col in visitors.iterate(expr):
            yield col
    except (AttributeError, TypeError):
        return


def _table_to_model(tablename):
    """根据表名查找对应的 ORM 模型类"""
    # 扫描当前模块中所有 db.Model 子类
    import sys
    _mod = sys.modules[__name__]
    for name in dir(_mod):
        cls = getattr(_mod, name)
        if isinstance(cls, type) and issubclass(cls, db.Model) and hasattr(cls, '__tablename__'):
            if cls.__tablename__ == tablename:
                return cls
    return None


@sa_event.listens_for(db.Model, 'before_insert', propagate=True)
def auto_set_hospital_id(mapper, connection, target):
    """新建记录时自动设置 hospital_id"""
    name = target.__class__.__name__
    if name not in HOSPITAL_FILTERED_MODELS:
        return
    if hasattr(target, 'hospital_id') and target.hospital_id is None:
        try:
            hid = getattr(g, 'hospital_id', None)
            if hid:
                target.hospital_id = hid
        except RuntimeError:
            pass


class FaultType(HospitalMixin, db.Model):
    __tablename__ = 'fault_types'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_ft_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    keywords = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


class FaultCategory(HospitalMixin, db.Model):
    """故障一级分类：硬件/软件/打印机/协助"""
    __tablename__ = 'fault_categories'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_fc_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    subcategories = db.relationship('FaultSubcategory', backref='category', lazy='dynamic',
                                    order_by='FaultSubcategory.sort_order')


class FaultSubcategory(HospitalMixin, db.Model):
    """故障二级分类：电脑故障、键盘鼠标、Office..."""
    __tablename__ = 'fault_subcategories'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('fault_categories.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    keywords = db.relationship('FaultKeyword', backref='subcategory', lazy='dynamic',
                               order_by='FaultKeyword.sort_order')


class FaultKeyword(HospitalMixin, db.Model):
    """故障关键词：每个二级分类下的匹配词"""
    __tablename__ = 'fault_keywords'
    id = db.Column(db.Integer, primary_key=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('fault_subcategories.id'), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


# 用户-医院多对多关联表
user_hospitals = db.Table('user_hospitals',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('hospital_id', db.Integer, db.ForeignKey('hospitals.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(80), nullable=False, default='')
    phone = db.Column(db.String(20), nullable=True)
    group = db.Column(db.String(50), nullable=True)  # 保留旧字段兼容
    group_id = db.Column(db.Integer, db.ForeignKey('role_groups.id'), nullable=True)
    wx_openid = db.Column(db.String(128), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospitals.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    preferences = db.Column(db.Text, default='{}')  # JSON 个人偏好设置

    # 多医院关联
    hospitals = db.relationship('Hospital', secondary=user_hospitals,
                                backref=db.backref('assigned_users', lazy='dynamic'),
                                lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_assigned_hospitals(self):
        """获取用户所有可访问的医院列表（含单医院兼容）"""
        from flask import g
        multi = self.hospitals.all()
        if multi:
            return multi
        # 兼容旧数据：如果 user_hospitals 为空但 hospital_id 有值
        if self.hospital_id:
            h = db.session.get(Hospital, self.hospital_id)
            return [h] if h else []
        return []

    def get_assigned_hospital_ids(self):
        """获取用户所有可访问的医院 ID 列表"""
        return [h.id for h in self.get_assigned_hospitals()]

    def get_pref(self, key, default=None):
        """获取个人偏好设置"""
        import json
        try:
            prefs = json.loads(self.preferences or '{}')
            return prefs.get(key, default)
        except (json.JSONDecodeError, TypeError):
            return default

    def set_pref(self, key, value):
        """设置个人偏好"""
        import json
        try:
            prefs = json.loads(self.preferences or '{}')
        except (json.JSONDecodeError, TypeError):
            prefs = {}
        prefs[key] = value
        self.preferences = json.dumps(prefs, ensure_ascii=False)


class WorkOrder(HospitalMixin, db.Model):
    __tablename__ = 'work_orders'
    __table_args__ = (
        db.Index('idx_status', 'status'),
        db.Index('idx_created_at', 'created_at'),
        db.Index('idx_person_status', 'person', 'status'),
        db.Index('idx_completed_at', 'completed_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    device_type = db.Column(db.String(50), nullable=False, default='其他')
    fault_type = db.Column(db.String(50), nullable=False, default='硬件')
    description = db.Column(db.Text, nullable=False, default='')
    building = db.Column(db.String(50), nullable=False, default='')
    floor = db.Column(db.String(20), nullable=False, default='')
    department = db.Column(db.String(100), nullable=False, default='')
    location = db.Column(db.String(200), nullable=False, default='')
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    person = db.Column(db.String(50), nullable=False, default='')
    solution = db.Column(db.Text, nullable=False, default='')
    status = db.Column(db.String(20), nullable=False, default='pending')
    accepted_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.String(50), nullable=False, default='系统')
    priority = db.Column(db.String(20), nullable=False, default='normal')  # normal/urgent/emergency
    original_priority = db.Column(db.String(20), nullable=False, default='normal')  # initial priority at creation
    work_type = db.Column(db.String(20), nullable=False, default='normal')  # normal/inspection
    inspection_data = db.Column(db.JSON, nullable=True)  # inspection items & results
    fault_subcategory = db.Column(db.String(100), nullable=False, default='')
    wecom_timeout_notified = db.Column(db.Boolean, default=False)

    @property
    def is_overdue(self):
        """判断工单是否超时（SLA 超时），从 SystemSetting 读取用户配置的阈值"""
        from datetime import datetime
        from models import SystemSetting
        now = datetime.now()

        def _get_threshold(key, default):
            s = db.session.query(SystemSetting.value).filter_by(key=key).scalar()
            if s:
                try: return float(s)
                except: pass
            return default

        resp_th = _get_threshold(f'sla_response_{self.priority}',
                                 {'emergency': 0.5, 'urgent': 2, 'normal': 4}.get(self.priority, 4))
        resol_th = _get_threshold(f'sla_resolution_{self.priority}',
                                  {'emergency': 2, 'urgent': 8, 'normal': 24}.get(self.priority, 24))
        if self.status == 'completed' and (self.end_time or self.completed_at):
            # 用 end_time（实际结束时间）如果有，否则用 completed_at
            end = self.end_time or self.completed_at
            start = self.start_time or self.accepted_at or self.created_at
            if start:
                cost_hours = (end - start).total_seconds() / 3600
                return cost_hours > resol_th
            return False
        elif self.status == 'in_progress' and self.accepted_at:
            elapsed = (now - self.accepted_at).total_seconds() / 3600
            return elapsed > resol_th
        elif self.status == 'pending' and self.created_at:
            elapsed = (now - self.created_at).total_seconds() / 3600
            return elapsed > resp_th
        return False


class InspectionTemplate(HospitalMixin, db.Model):
    """巡检模板：预设的巡检内容项"""
    __tablename__ = 'inspection_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    items = db.Column(db.JSON, nullable=False, default=list)  # ["检查电源","检查温度",...]
    created_at = db.Column(db.DateTime, default=datetime.now)


class InspectionPlan(HospitalMixin, db.Model):
    """巡检计划：模板+位置+时间→生成巡检工单"""
    __tablename__ = 'inspection_plans'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('inspection_templates.id'), nullable=False)
    building = db.Column(db.String(50), nullable=False, default='')
    floor = db.Column(db.String(20), nullable=False, default='')
    department = db.Column(db.String(100), nullable=False, default='')
    location = db.Column(db.String(200), nullable=False, default='')
    scheduled_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/generated/completed
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    created_by = db.Column(db.String(50), nullable=False, default='系统')
    created_at = db.Column(db.DateTime, default=datetime.now)
    template = db.relationship('InspectionTemplate', backref='plans')
    work_order = db.relationship('WorkOrder', backref='inspection_plan')
    addresses = db.Column(db.JSON, nullable=True)
    work_order_ids = db.Column(db.JSON, nullable=True)
    schedule_type = db.Column(db.String(20), nullable=False, default='once')  # once/daily/workday/monthly
    schedule_time = db.Column(db.String(5), nullable=True, default='')  # HH:MM
    schedule_day = db.Column(db.Integer, nullable=True, default=0)  # 1-31 for monthly
    last_generated_at = db.Column(db.DateTime, nullable=True)


class Person(HospitalMixin, db.Model):
    """维护人员名单"""
    __tablename__ = 'persons'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_person_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    employee_id = db.Column(db.String(50), default='')
    phone = db.Column(db.String(50), default='')
    team = db.Column(db.String(50), default='')
    notes = db.Column(db.Text, default='')
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user = db.relationship('User', backref=db.backref('person', uselist=False))
    created_at = db.Column(db.DateTime, default=datetime.now)


class Department(HospitalMixin, db.Model):
    """科室字典"""
    __tablename__ = 'departments'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_dept_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    building = db.Column(db.String(50), default='')
    floor = db.Column(db.String(20), default='')
    phone = db.Column(db.String(50), default='')
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


# ======================== 权限系统（多角色组） ========================

# 所有模块的完整定义（按类别分组）—— 与 base.html 侧边栏完全对应
ALL_MODULES_DEFINITION = [
    ('工单管理', ['仪表盘', '工单列表', '发布工单', '新建工单', '批量生成', '工单转交', 'SLA监控', '历史追溯']),
    ('业务管理', ['巡检管理', '知识库', '电子表单', '维修管理', '巡检签到']),
    ('数据中心', ['数据管理', '资产台账', '资产二维码', '供应商管理', '合同维保', '设备折旧', '备件库存', '备件联动', '耗材管理', '耗材预测', '值班排班', '固定资产入库', '固定资产出库']),
    ('运维分析', ['效能看板', '运维大屏', '领导驾驶舱', '数字孪生', '自定义报表', '短信通知', '重复单分析']),
    ('财务做账', ['维修做账']),
    ('系统管理', ['审计日志', '月度报表', '权限管理', '服务器监控']),
    ('教育培训', ['考试系统']),
]

# 展平的模块名列表
ALL_MODULE_NAMES = [m for _, mods in ALL_MODULES_DEFINITION for m in mods]

# 默认的两个角色组
DEFAULT_GROUPS = {
    '管理员': {m: True for m in ALL_MODULE_NAMES},
    '普通用户': {
        '仪表盘': True, '工单列表': True, '发布工单': True, '新建工单': True,
        '批量生成': False,
        '工单转交': False, 'SLA监控': False, '历史追溯': True,
        '巡检管理': True, '知识库': True, '电子表单': False, '维修管理': False,
        '巡检签到': True,
        '数据管理': False, '资产台账': False, '资产二维码': False,
        '供应商管理': False, '合同维保': False, '设备折旧': False,
        '备件库存': False, '备件联动': False,
        '耗材管理': False, '耗材预测': False, '值班排班': False,
        '效能看板': False, '运维大屏': False, '领导驾驶舱': False,
        '数字孪生': False, '自定义报表': False, '短信通知': False,
        '审计日志': False, '月度报表': False, '权限管理': False,
        '考试系统': True,
        '重复单分析': False,
    },
}
_PERM_CACHE = {}  # hospital_id → data


def _migrate_old_perms(data):
    """将旧格式 {admin:{mod:bool}, user:{mod:bool}} 迁移到新格式"""
    if 'groups' in data and 'categories' in data:
        return data  # 已经是新格式
    # 旧格式迁移
    admin_perms = data.get('admin', {})
    user_perms = data.get('user', {})
    groups = {'管理员': {}, '普通用户': {}}
    for m in ALL_MODULE_NAMES:
        groups['管理员'][m] = admin_perms.get(m, True)
        groups['普通用户'][m] = user_perms.get(m, True)
    return {
        'categories': [list(c) for c in ALL_MODULES_DEFINITION],
        'groups': groups,
    }


def get_module_permissions(refresh=False):
    """获取模块权限配置（全局统一，所有医院通用）"""
    global _PERM_CACHE
    HID_GLOBAL = 0  # 全局统一缓存标记

    if not refresh and HID_GLOBAL in _PERM_CACHE:
        return _PERM_CACHE[HID_GLOBAL]

    # 所有医院共用一条配置记录（hospital_id=1）
    setting = SystemSetting.query.filter_by(key='module_permissions', hospital_id=1).first()
    if not setting:
        data = {
            'categories': [list(c) for c in ALL_MODULES_DEFINITION],
            'groups': {name: dict(perms) for name, perms in DEFAULT_GROUPS.items()},
        }
        setting = SystemSetting(key='module_permissions', value=json.dumps(data),
                                label='模块权限配置（全局统一）', category='系统',
                                hospital_id=1)
        db.session.add(setting)
        db.session.commit()
    else:
        try:
            loaded = json.loads(setting.value)
            data = _migrate_old_perms(loaded)
        except (json.JSONDecodeError, TypeError):
            data = {
                'categories': [list(c) for c in ALL_MODULES_DEFINITION],
                'groups': {name: dict(perms) for name, perms in DEFAULT_GROUPS.items()},
            }

    # 确保所有模块在groups中都存在
    for gname in list(data['groups'].keys()):
        g = data['groups'][gname]
        default_true = (gname == '管理员')
        for m in ALL_MODULE_NAMES:
            if m not in g:
                g[m] = default_true

    # 自动同步 role_groups 表中存在但权限配置中缺失的角色组
    # 新角色组默认继承「普通用户」的权限
    from flask import current_app
    if current_app:
        try:
            default_user_perms = data['groups'].get('普通用户', {})
            all_role_groups = RoleGroup.query.all()
            for rg in all_role_groups:
                if rg.name not in data['groups']:
                    data['groups'][rg.name] = dict(default_user_perms)
                    # 标记为缺失修复，提示管理员
                    current_app.logger.warning(
                        f'[权限自动同步] 角色组 "{rg.name}" 不存在于权限配置中，已自动继承普通用户权限'
                    )
        except Exception as e:
            # RoleGroup 表可能还不存在（首次迁移前），静默跳过
            if current_app:
                current_app.logger.warning(f'[权限自动同步] 跳过: {e}')

    # 同步categories与ALL_MODULES_DEFINITION
    stored_cats = {c[0]: c[1] for c in data.get('categories', [])}
    merged = []
    seen = set()
    for cat_name, mods in ALL_MODULES_DEFINITION:
        if cat_name in stored_cats:
            merged_mods = list(dict.fromkeys(stored_cats[cat_name] + mods))
        else:
            merged_mods = list(mods)
        merged.append([cat_name, merged_mods])
        seen.add(cat_name)
    for cat_name, mods in stored_cats.items():
        if cat_name not in seen:
            deduped = [m for m in mods if m not in ALL_MODULE_NAMES]
            if deduped:
                merged.append([cat_name, deduped])
                seen.add(cat_name)
    data['categories'] = merged

    _PERM_CACHE[HID_GLOBAL] = data
    return data

def save_module_permissions(data):
    """保存模块权限配置（全局统一）"""
    global _PERM_CACHE
    HID_GLOBAL = 0
    setting = SystemSetting.query.filter_by(key='module_permissions', hospital_id=1).first()
    if not setting:
        setting = SystemSetting(key='module_permissions', value='{}',
                                label='模块权限配置（全局统一）', category='系统',
                                hospital_id=1)
        db.session.add(setting)
    setting.value = json.dumps(data)
    _PERM_CACHE[HID_GLOBAL] = data
    db.session.commit()


def can_access(module_name, user=None):
    """判断用户是否有权访问某模块（基于 group_id）"""
    if user is None:
        from flask_login import current_user
        user = current_user
    if not user or not user.is_authenticated:
        return False
    if user.is_admin:
        return True  # 管理员全开
    # 根据用户所属角色组判断（优先 group_id）
    group_name = get_group_name_by_id(user.group_id) or user.group or '普通用户'
    perms = get_module_permissions()
    group_perms = perms.get('groups', {}).get(group_name, {})
    return group_perms.get(module_name, False)


class SystemSetting(db.Model):
    """系统参数"""
    __tablename__ = 'system_settings'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'key', name='uq_ss_hospital_key'),
    )
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospitals.id'), nullable=False, default=1)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, default='')
    label = db.Column(db.String(200), default='')
    description = db.Column(db.Text, default='')
    category = db.Column(db.String(50), default='基本')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @classmethod
    def get(cls, key, default=''):
        """获取系统参数值"""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default

    @classmethod
    def set(cls, key, value, label='', description='', category='基本', hospital_id=1):
        """设置系统参数值（不存在则创建）"""
        setting = cls.query.filter_by(key=key, hospital_id=hospital_id).first()
        if setting:
            setting.value = str(value)
            if label:
                setting.label = label
        else:
            setting = cls(key=key, value=str(value), label=label,
                          description=description, category=category,
                          hospital_id=hospital_id)
            db.session.add(setting)
        db.session.commit()


class SolutionTemplate(HospitalMixin, db.Model):
    """方案模板（可自定义）"""
    __tablename__ = 'solution_templates'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'title', name='uq_st_hospital_title'),
    )
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    keywords = db.Column(db.String(500), default='')
    device_type = db.Column(db.String(50), default='')
    fault_type = db.Column(db.String(50), default='')
    fault_subcategory = db.Column(db.String(100), default='')
    teams = db.Column(db.String(500), default='')  # 逗号分隔的组别列表
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class AddressOverride(HospitalMixin, db.Model):
    """地址数据覆盖/新增（优先于 address.py 中的硬编码数据）"""
    __tablename__ = 'address_overrides'
    id = db.Column(db.Integer, primary_key=True)
    base_index = db.Column(db.Integer, default=-1, nullable=False)
    building = db.Column(db.String(50), nullable=False, default='')
    floor = db.Column(db.String(20), nullable=False, default='')
    department = db.Column(db.String(100), nullable=False, default='')
    location = db.Column(db.String(200), nullable=False, default='')
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class MobileToken(db.Model):
    """微信小程序登录令牌"""
    __tablename__ = 'mobile_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user = db.relationship('User', backref='mobile_tokens')

    @classmethod
    def generate(cls, user):
        import secrets
        token_str = secrets.token_hex(48)
        record = cls(user_id=user.id, token=token_str)
        db.session.add(record)
        db.session.commit()
        return record

    @classmethod
    def verify(cls, token_str):
        record = cls.query.filter_by(token=token_str).first()
        if record:
            return record.user
        return None


class SubscribeUser(db.Model):
    """订阅新工单通知的用户"""
    __tablename__ = 'subscribe_users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    openid = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class AuditLog(db.Model):
    """操作审计日志"""
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(50), nullable=False)         # create/update/delete/login/logout
    target_type = db.Column(db.String(50), nullable=False)     # work_order/user/person/fault_type/...
    target_id = db.Column(db.Integer, nullable=True)
    target_desc = db.Column(db.String(200), nullable=True)     # 简要描述，如"删除工单#123"
    operator = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'target_type': self.target_type,
            'target_desc': self.target_desc,
            'operator': self.operator,
            'detail': self.detail,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
        }


def log_audit(action, target_type, operator, target_id=None, target_desc=None, detail=None):
    """便捷函数：记录操作日志"""
    log = AuditLog(
        action=action, target_type=target_type,
        target_id=target_id, target_desc=target_desc,
        operator=operator, detail=detail,
    )
    db.session.add(log)
    db.session.commit()
    return log


class FormTemplate(HospitalMixin, db.Model):
    """电子表单模板（统一模板，含A4画布布局）"""
    __tablename__ = 'form_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    fields_json = db.Column(db.JSON, default=list)  # [{id, label, type, x, y, w, h, required, options, placeholder, data_source}, ...]
    page_size = db.Column(db.String(20), default='A4')
    orientation = db.Column(db.String(10), default='portrait')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'fields_json': self.fields_json or [],
            'page_size': self.page_size,
            'orientation': self.orientation,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'field_count': len(self.fields_json or []),
        }


class PaperForm(HospitalMixin, db.Model):
    """电子表单实例"""
    __tablename__ = 'paper_forms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    form_type = db.Column(db.String(50), nullable=False)  # equipment_distribution / repair_acceptance / template
    form_data = db.Column(db.JSON, default=dict)  # 表单填写的数据
    status = db.Column(db.String(20), default='draft')  # draft(草稿) / active(进行中) / completed(已完成)
    template_id = db.Column(db.Integer, db.ForeignKey('form_templates.id'), nullable=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    created_by = db.Column(db.String(80), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    template = db.relationship('FormTemplate', backref='forms', foreign_keys=[template_id])
    work_order = db.relationship('WorkOrder', backref='paper_form', foreign_keys=[work_order_id])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'form_type': self.form_type,
            'form_data': self.form_data or {},
            'status': self.status,
            'template_id': self.template_id,
            'work_order_id': self.work_order_id,
            'created_by': self.created_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'template_name': self.template.name if self.template else '',
        }


class Asset(HospitalMixin, db.Model):
    """资产台账"""
    __tablename__ = 'assets'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'asset_no', name='uq_asset_hospital_asset_no'),
    )
    id = db.Column(db.Integer, primary_key=True)
    asset_no = db.Column(db.String(100), index=True, nullable=False)
    device_type = db.Column(db.String(50), default='PC')
    brand = db.Column(db.String(100), default='')
    category = db.Column(db.String(20), default='hardware')  # hardware/software
    sn = db.Column(db.String(100), default='')
    model_no = db.Column(db.String(100), default='')
    cpu = db.Column(db.String(100), default='')
    memory = db.Column(db.String(50), default='')
    disk_size = db.Column(db.String(50), default='')
    operating_system = db.Column(db.String(100), default='')
    ip_address = db.Column(db.String(50), default='')
    mac_address = db.Column(db.String(50), default='')
    department = db.Column(db.String(100), default='')
    building = db.Column(db.String(50), default='')
    floor = db.Column(db.String(20), default='')
    location = db.Column(db.String(200), default='')
    status = db.Column(db.String(20), default='in_use')  # in_use/spare/scrapped/lost
    inventory_status = db.Column(db.String(20), default='')  # ''正常 / issue异常,需关注 / new新盘资产
    vendor = db.Column(db.String(100), default='')
    price = db.Column(db.Float, nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    purchase_price = db.Column(db.Numeric(12, 2), nullable=True)  # 购入原值（用于折旧计算）
    lifespan_years = db.Column(db.Integer, default=5)            # 使用年限（用于折旧计算）
    warranty_start = db.Column(db.Date, nullable=True)
    warranty_end = db.Column(db.Date, nullable=True)
    financial_code = db.Column(db.String(100), default='')
    financial_name = db.Column(db.String(100), default='')
    license_key = db.Column(db.String(200), default='')
    license_seats = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, default='')
    # 借用管理
    borrow_status = db.Column(db.String(20), default='')  # ''正常 / borrowed借出
    borrowed_to = db.Column(db.String(100), default='')    # 借用人
    borrow_date = db.Column(db.Date, nullable=True)        # 借出日期
    return_date = db.Column(db.Date, nullable=True)        # 预计归还日期
    borrow_note = db.Column(db.String(200), default='')    # 借用备注
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def warranty_days_left(self):
        if not self.warranty_end:
            return None
        delta = (self.warranty_end - date.today()).days
        return max(delta, 0)

    @property
    def warranty_status(self):
        if not self.warranty_end:
            return 'expired'
        if self.warranty_end < date.today():
            return 'expired'
        if (self.warranty_end - date.today()).days <= 30:
            return 'expiring'
        return 'valid'

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class AssetLog(HospitalMixin, db.Model):
    """资产变更日志"""
    __tablename__ = 'asset_logs'
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # import/edit/transfer/relocate/recover
    old_value = db.Column(db.Text, default='')
    new_value = db.Column(db.Text, default='')
    operator = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    asset = db.relationship('Asset', backref=db.backref('logs', cascade='all, delete-orphan'))


class SparePart(HospitalMixin, db.Model):
    """备件库存"""
    __tablename__ = 'spare_parts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    model_no = db.Column(db.String(100), default='')
    brand = db.Column(db.String(100), default='')
    category = db.Column(db.String(50), default='')
    stock = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=5)
    unit = db.Column(db.String(20), default='个')
    location = db.Column(db.String(100), default='')
    notes = db.Column(db.Text, default='')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @property
    def is_low(self):
        return self.stock <= self.min_stock


class StorageLocation(HospitalMixin, db.Model):
    """存放位置字典"""
    __tablename__ = 'storage_locations'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_sl_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    building = db.Column(db.String(50), default='')
    floor = db.Column(db.String(20), default='')
    area = db.Column(db.String(100), default='')
    contact = db.Column(db.String(50), default='')
    phone = db.Column(db.String(50), default='')
    is_default = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class StockRecord(HospitalMixin, db.Model):
    """出入库记录"""
    __tablename__ = 'stock_records'
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id'), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # in/out
    quantity = db.Column(db.Integer, nullable=False)
    balance = db.Column(db.Integer, default=0)
    operator = db.Column(db.String(80), nullable=False)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    department = db.Column(db.String(100), default='')  # 出库目标科室
    note = db.Column(db.Text, default='')
    signature = db.Column(db.Text, default='')  # 签名图片 data URL
    created_at = db.Column(db.DateTime, default=datetime.now)
    part = db.relationship('SparePart', backref='records')


class StockSignRequest(HospitalMixin, db.Model):
    """出库签名请求（扫码签名后执行出库）"""
    __tablename__ = 'stock_sign_requests'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), default='')
    items_json = db.Column(db.Text, default='')  # JSON: [{"part_id":1,"qty":2}, ...]
    signature = db.Column(db.Text, default='')   # 签名 data URL
    status = db.Column(db.String(20), default='pending')  # pending/signed/completed
    operator = db.Column(db.String(80), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    signed_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)


class Supplier(HospitalMixin, db.Model):
    """供应商管理"""
    __tablename__ = 'suppliers'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_sup_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(50), default='')
    phone = db.Column(db.String(50), default='')
    email = db.Column(db.String(100), default='')
    address = db.Column(db.String(200), default='')
    supply_type = db.Column(db.String(20), default='综合')  # 备件/耗材/维修/综合
    rating = db.Column(db.Integer, default=3)               # 1-5 星
    service_scope = db.Column(db.String(200), default='')
    contract_end = db.Column(db.Date, nullable=True)
    remark = db.Column(db.Text, default='')
    notes = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class MaintenanceContract(HospitalMixin, db.Model):
    """合同维保管理"""
    __tablename__ = 'maintenance_contracts'
    id = db.Column(db.Integer, primary_key=True)
    contract_no = db.Column(db.String(100), default='')
    contract_name = db.Column(db.String(200), nullable=False, default='')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    contract_amount = db.Column(db.Numeric(12, 2), default=0)
    payment_type = db.Column(db.String(20), default='一次性')  # 一次性/分期
    status = db.Column(db.String(20), default='active')  # active/expired/terminated
    contact_person = db.Column(db.String(50), default='')
    contact_phone = db.Column(db.String(50), default='')
    file_path = db.Column(db.String(500), default='')
    remark = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    supplier = db.relationship('Supplier', backref='contracts', foreign_keys=[supplier_id])
    asset = db.relationship('Asset', backref='contracts', foreign_keys=[asset_id])

    @property
    def status_display(self):
        from datetime import date
        if not self.end_date:
            return 'active', '有效'
        if self.status == 'terminated':
            return 'terminated', '已终止'
        if self.end_date < date.today():
            return 'expired', '已过期'
        return 'active', '有效'

    @property
    def expiring_soon(self):
        from datetime import date, timedelta
        if not self.end_date:
            return False
        if self.end_date < date.today():
            return False
        return (self.end_date - date.today()).days <= 30


class Consumable(HospitalMixin, db.Model):
    """耗材库存管理"""
    __tablename__ = 'consumables'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    spec = db.Column(db.String(100), default='')
    unit = db.Column(db.String(20), default='个')
    quantity = db.Column(db.Integer, default=0)
    min_quantity = db.Column(db.Integer, default=5)
    location = db.Column(db.String(100), default='')
    supplier_name = db.Column(db.String(100), default='')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    compatible_printers = db.Column(db.String(500), default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def is_low(self):
        return self.min_quantity > 0 and self.quantity <= self.min_quantity


class ConsumableRecord(HospitalMixin, db.Model):
    """耗材出入库记录"""
    __tablename__ = 'consumable_records'
    id = db.Column(db.Integer, primary_key=True)
    consumable_id = db.Column(db.Integer, db.ForeignKey('consumables.id'), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # in/out
    quantity = db.Column(db.Integer, nullable=False)
    balance = db.Column(db.Integer, default=0)
    operator = db.Column(db.String(80), nullable=False)
    department = db.Column(db.String(100), default='')  # 出库目标科室
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    signature = db.Column(db.Text, default='')  # 签名图片 data URL
    note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    consumable = db.relationship('Consumable', backref='records')


class ConsumableSignRequest(HospitalMixin, db.Model):
    """耗材出库签名请求（扫码签名后执行出库）"""
    __tablename__ = 'consumable_sign_requests'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), default='')
    items_json = db.Column(db.Text, default='')  # JSON: [{"cid":1,"qty":2}, ...]
    signature = db.Column(db.Text, default='')   # 签名 data URL
    status = db.Column(db.String(20), default='pending')  # pending/signed/completed
    operator = db.Column(db.String(80), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    signed_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)


class DutySchedule(HospitalMixin, db.Model):
    """值班排班"""
    __tablename__ = 'duty_schedules'
    id = db.Column(db.Integer, primary_key=True)
    duty_date = db.Column(db.Date, nullable=False, index=True)
    person_name = db.Column(db.String(50), nullable=False)
    shift = db.Column(db.String(20), default='全天')  # 日班/夜班/24H/支援/病假/事假/年假/×
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class PartRequest(HospitalMixin, db.Model):
    """备件领用申请"""
    __tablename__ = 'part_requests'
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    requester = db.Column(db.String(50), nullable=False)  # 申请人
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)  # 关联工单
    reason = db.Column(db.Text, default='')  # 领用原因
    status = db.Column(db.String(20), default='pending')  # pending/approved/rejected
    approver = db.Column(db.String(50), nullable=True)  # 审批人
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    part = db.relationship('SparePart', backref='requests')
    work_order = db.relationship('WorkOrder', backref='part_requests')


class DutyStaff(HospitalMixin, db.Model):
    """值班人员"""
    __tablename__ = 'duty_staff'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'name', name='uq_ds_hospital_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class RepairOrder(HospitalMixin, db.Model):
    """维修单实例（模板使用统一的 FormTemplate）"""
    __tablename__ = 'repair_orders'
    __table_args__ = (
        db.UniqueConstraint('hospital_id', 'order_no', name='uq_ro_hospital_order_no'),
    )
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_templates.id'), nullable=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    order_no = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), default='')
    field_values = db.Column(db.JSON, default=dict)
    signatures = db.Column(db.JSON, default=dict)
    status = db.Column(db.String(20), default='draft')
    created_by = db.Column(db.String(80), default='')
    approved_by = db.Column(db.String(80), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    paper_form_id = db.Column(db.Integer, db.ForeignKey('paper_forms.id'), nullable=True)
    template = db.relationship('FormTemplate', backref='repair_orders')
    work_order = db.relationship('WorkOrder', backref='repair_orders')
    paper_form = db.relationship('PaperForm', backref='repair_orders', foreign_keys=[paper_form_id])

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'work_order_id': self.work_order_id,
            'order_no': self.order_no,
            'title': self.title,
            'field_values': self.field_values or {},
            'signatures': self.signatures or {},
            'status': self.status,
            'created_by': self.created_by,
            'approved_by': self.approved_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'template_name': self.template.name if self.template else '',
        }


class KnowledgeBase(HospitalMixin, db.Model):
    """知识库/公告"""
    __tablename__ = 'knowledge_base'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), default='公告')  # 公告/操作手册/常见问题
    content = db.Column(db.Text, default='')
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class PartPrice(HospitalMixin, db.Model):
    """零件价格库"""
    __tablename__ = 'part_prices'
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(200), nullable=False)
    unit = db.Column(db.String(20), default='个')
    unit_price = db.Column(db.Numeric(10, 2), default=0)
    category = db.Column(db.String(100), default='')
    spec = db.Column(db.String(200), default='')
    brand = db.Column(db.String(100), default='')           # 品牌
    model_no = db.Column(db.String(200), default='')        # 型号
    supplier = db.Column(db.String(200), default='')        # 供应商
    remark = db.Column(db.Text, default='')                 # 备注
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    price_histories = db.relationship('PriceHistory', backref='part', lazy='dynamic',
                                       order_by='PriceHistory.created_at.desc()')


class PriceHistory(HospitalMixin, db.Model):
    """零件价格变动历史"""
    __tablename__ = 'price_histories'
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part_prices.id'), nullable=False)
    old_price = db.Column(db.Numeric(10, 2), default=0)
    new_price = db.Column(db.Numeric(10, 2), default=0)
    change_type = db.Column(db.String(20), default='调价')  # 调价 / 初始
    operator = db.Column(db.String(50), default='')
    note = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)


class FinanceBatch(HospitalMixin, db.Model):
    """发票批次 - 维修做账主表"""
    __tablename__ = 'finance_batches'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='')
    payee = db.Column(db.String(200), default='')
    bank_name = db.Column(db.String(200), default='')
    bank_account = db.Column(db.String(100), default='')
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.String(80), default='')


class FinanceInvoice(HospitalMixin, db.Model):
    """发票明细"""
    __tablename__ = 'finance_invoices'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('finance_batches.id'))
    invoice_no = db.Column(db.String(100), default='')
    amount = db.Column(db.Numeric(12, 2), default=0)
    batch = db.relationship('FinanceBatch',
        backref=db.backref('invoices', lazy='dynamic', cascade='all, delete-orphan'),
        foreign_keys=[batch_id])


class FinanceDraft(HospitalMixin, db.Model):
    """维修清单草稿"""
    __tablename__ = 'finance_drafts'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('finance_batches.id'))
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=True)
    device_type = db.Column(db.String(50), default='')
    department = db.Column(db.String(100), default='')
    report_date = db.Column(db.DateTime, nullable=True)
    repair_content = db.Column(db.Text, default='')
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    sort_order = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='draft')
    batch = db.relationship('FinanceBatch',
        backref=db.backref('drafts', lazy='dynamic', cascade='all, delete-orphan'),
        foreign_keys=[batch_id])
    asset = db.relationship('Asset',
        backref=db.backref('finance_drafts', lazy='dynamic'),
        foreign_keys=[asset_id])


class FinanceDraftPart(HospitalMixin, db.Model):
    """清单配件明细"""
    __tablename__ = 'finance_draft_parts'
    id = db.Column(db.Integer, primary_key=True)
    draft_id = db.Column(db.Integer, db.ForeignKey('finance_drafts.id'))
    part_name = db.Column(db.String(200), default='')
    unit = db.Column(db.String(20), default='个')
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), default=0)
    amount = db.Column(db.Numeric(12, 2), default=0)
    draft = db.relationship('FinanceDraft',
        backref=db.backref('parts', lazy='dynamic', cascade='all, delete-orphan'),
        foreign_keys=[draft_id])


# ==================== 验收单模板 ====================

class AcceptanceTemplate(db.Model):
    """验收单在线设计模板"""
    __tablename__ = 'acceptance_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default='默认模板')
    hospital_id = db.Column(db.Integer, nullable=True)
    is_default = db.Column(db.Boolean, default=False)
    # JSON: {"cols":12, "rows":30, "page_width":196, "page_height":277,
    #        "fields":[{"key":"date","label":"维修日期","x":0,"y":0,"w":6,"h":1,"align":"left","font_size":9,"bold":false},...]}
    layout_json = db.Column(db.Text, default='{}')
    page_orientation = db.Column(db.String(10), default='portrait')  # portrait/landscape
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def get_layout(self):
        import json
        return json.loads(self.layout_json or '{}')

    def set_layout(self, layout):
        import json
        self.layout_json = json.dumps(layout, ensure_ascii=False)


# ==================== NFC巡检签到 ====================

class InspectionCheckin(db.Model):
    """巡检签到记录（替代 NFC，使用 QR 扫码签到）"""
    __tablename__ = 'inspection_checkins'
    id = db.Column(db.Integer, primary_key=True)
    inspection_plan_id = db.Column(db.Integer, db.ForeignKey('inspection_plans.id'), nullable=False)
    checkin_time = db.Column(db.DateTime, default=datetime.now)
    location = db.Column(db.String(200), default='')
    remark = db.Column(db.Text, default='')
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospitals.id'), nullable=False, default=1)
    plan = db.relationship('InspectionPlan', backref=db.backref('checkins', lazy='dynamic', cascade='all, delete-orphan'))


# ==================== 短信通知日志 ====================

class SmsLog(db.Model):
    """短信发送日志"""
    __tablename__ = 'sms_logs'
    id = db.Column(db.Integer, primary_key=True)
    to_phone = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='pending')  # pending/sent/failed
    error_msg = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)


# ==================== 角色组（权限组，用 ID 关联） ====================

class RoleGroup(db.Model):
    __tablename__ = 'role_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @classmethod
    def get_or_create(cls, name):
        """按名称查找或创建角色组"""
        rg = cls.query.filter_by(name=name).first()
        if not rg:
            rg = cls(name=name)
            db.session.add(rg)
            db.session.flush()
        return rg

    @classmethod
    def ensure_all_groups(cls):
        """确保所有在 module_permissions 中定义的角色组都有 RoleGroup 记录"""
        from models import get_module_permissions
        perms = get_module_permissions(refresh=True)
        groups = perms.get('groups', {})
        for gname in groups:
            cls.get_or_create(gname)
        # 确保默认组存在
        cls.get_or_create('管理员')
        cls.get_or_create('普通用户')
        db.session.commit()

    @classmethod
    def delete_group(cls, name):
        """删除角色组（名称查找）"""
        rg = cls.query.filter_by(name=name).first()
        if rg:
            db.session.delete(rg)
            db.session.commit()

    @classmethod
    def rename_group(cls, old_name, new_name):
        """重命名角色组"""
        rg = cls.query.filter_by(name=old_name).first()
        if rg:
            rg.name = new_name
            db.session.commit()
            return True
        return False


def get_group_name_by_id(group_id):
    """根据 group_id 获取角色组名称"""
    if group_id is None:
        return '普通用户'
    rg = RoleGroup.query.get(group_id)
    return rg.name if rg else '普通用户'


# ==================== 在线聊天 ====================

class ChatConversation(db.Model):
    """聊天会话"""
    __tablename__ = 'chat_conversations'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default='')
    type = db.Column(db.String(20), default='single')  # single, group
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospitals.id'), nullable=True)
    last_message = db.Column(db.Text, default='')
    last_sender = db.Column(db.String(50), default='')
    last_time = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    participants = db.relationship('ChatParticipant', backref='conversation',
        lazy='dynamic', cascade='all, delete-orphan')


class ChatParticipant(db.Model):
    """会话参与者"""
    __tablename__ = 'chat_participants'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('chat_conversations.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_name = db.Column(db.String(100), default='')
    hospital_id = db.Column(db.Integer, nullable=True)
    last_read_at = db.Column(db.DateTime, default=datetime.now)
    joined_at = db.Column(db.DateTime, default=datetime.now)
    is_active = db.Column(db.Boolean, default=True)


class ChatMessage(db.Model):
    """聊天消息"""
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('chat_conversations.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_name = db.Column(db.String(100), default='')
    sender_hospital = db.Column(db.String(100), default='')
    content = db.Column(db.Text, default='')
    msg_type = db.Column(db.String(20), default='text')  # text, image, system
    recalled = db.Column(db.Boolean, default=False)
    file_name = db.Column(db.String(255), default='')
    file_size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    conversation = db.relationship('ChatConversation',
        backref=db.backref('messages', lazy='dynamic', cascade='all, delete-orphan'),
        foreign_keys=[conversation_id])


class ChatToken(db.Model):
    """WebSocket 鉴权令牌"""
    __tablename__ = 'chat_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    user = db.relationship('User', backref='chat_tokens')

    @classmethod
    def generate(cls, user):
        import secrets
        token_str = secrets.token_hex(48)
        record = cls(user_id=user.id, token=token_str)
        # 清理旧 token
        cls.query.filter_by(user_id=user.id).delete()
        db.session.add(record)
        db.session.commit()
        return record


class WorkOrderChatMessage(db.Model):
    """工单关联聊天消息"""
    __tablename__ = 'work_order_chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_name = db.Column(db.String(100), default='')
    content = db.Column(db.Text, default='')
    msg_type = db.Column(db.String(20), default='text')  # text, image
    created_at = db.Column(db.DateTime, default=datetime.now)
    work_order = db.relationship('WorkOrder', backref=db.backref('chat_messages', lazy='dynamic', cascade='all, delete-orphan'))
    sender = db.relationship('User', backref='wo_chat_messages')


class WorkOrderTransferLog(db.Model):
    """工单流转记录（退回/转派）"""
    __tablename__ = 'work_order_transfer_logs'
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    action = db.Column(db.String(20), nullable=False)  # 'return' or 'transfer'
    from_person = db.Column(db.String(100), nullable=True, default='')
    to_person = db.Column(db.String(100), nullable=True, default='')
    operator_name = db.Column(db.String(100), nullable=False, default='')
    remark = db.Column(db.String(200), nullable=True, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    work_order = db.relationship('WorkOrder', backref=db.backref('transfer_logs', lazy='dynamic', cascade='all, delete-orphan'))


class WorkOrderPhoto(db.Model):
    """工单图片"""
    __tablename__ = 'work_order_photos'
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False, default='')
    filepath = db.Column(db.String(500), nullable=False, default='')
    thumbnail = db.Column(db.String(500), nullable=True, default='')  # 缩略图路径
    file_size = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    work_order = db.relationship('WorkOrder', backref=db.backref('photos', lazy='dynamic', cascade='all, delete-orphan'))


class FaultTemplateGroup(HospitalMixin, db.Model):
    """故障模板组：按组别绑定的故障类型模板"""
    __tablename__ = 'fault_template_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    teams = db.Column(db.String(500), default='')  # 逗号分隔的组别
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    items = db.relationship('FaultTemplateItem', backref='group', lazy='dynamic',
                            cascade='all, delete-orphan', order_by='FaultTemplateItem.sort_order')


class FaultTemplateItem(db.Model):
    """故障模板项：模板组中的单个故障类型"""
    __tablename__ = 'fault_template_items'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('fault_template_groups.id'), nullable=False, index=True)
    fault_type = db.Column(db.String(50), nullable=False, default='硬件')  # 软件/硬件/打印机/协助
    display_name = db.Column(db.String(100), default='')
    default_count = db.Column(db.Integer, default=1)
    sort_order = db.Column(db.Integer, default=0)


class InventoryTask(HospitalMixin, db.Model):
    """盘点任务"""
    __tablename__ = 'inventory_tasks'
    id = db.Column(db.Integer, primary_key=True)
    task_no = db.Column(db.String(50), nullable=False, default='')  # 盘点编号
    name = db.Column(db.String(200), nullable=False, default='')    # 盘点名称
    scope = db.Column(db.String(20), default='building')  # building(按楼区) / department(按科室)
    status = db.Column(db.String(20), default='pending')  # pending(进行中) / completed(已完成)
    total_count = db.Column(db.Integer, default=0)        # 应盘总数
    scanned_count = db.Column(db.Integer, default=0)      # 已盘数量
    normal_count = db.Column(db.Integer, default=0)       # 无问题数量
    issue_count = db.Column(db.Integer, default=0)        # 有异常数量
    new_asset_count = db.Column(db.Integer, default=0)    # 新盘资产数量
    start_time = db.Column(db.DateTime, nullable=True)    # 开始时间
    end_time = db.Column(db.DateTime, nullable=True)      # 结束时间
    operator = db.Column(db.String(80), default='')       # 盘点人
    notes = db.Column(db.Text, default='')                # 备注
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    items = db.relationship('InventoryItem', backref='task', lazy='dynamic',
                            cascade='all, delete-orphan')

    def to_dict(self):
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        if self.start_time:
            d['start_time'] = self.start_time.strftime('%Y-%m-%d %H:%M')
        if self.end_time:
            d['end_time'] = self.end_time.strftime('%Y-%m-%d %H:%M')
        d['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        return d


class InventoryItem(HospitalMixin, db.Model):
    """盘点明细"""
    __tablename__ = 'inventory_items'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('inventory_tasks.id'), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=True)  # 匹配到的资产ID
    asset_no = db.Column(db.String(100), default='')      # 资产编码（扫码结果）
    result = db.Column(db.String(20), default='normal')   # normal(正常) / issue(异常) / new(新盘)
    building = db.Column(db.String(50), default='')
    floor = db.Column(db.String(20), default='')
    department = db.Column(db.String(100), default='')
    location = db.Column(db.String(200), default='')
    device_type = db.Column(db.String(50), default='')
    brand = db.Column(db.String(100), default='')
    model_no = db.Column(db.String(100), default='')
    sn = db.Column(db.String(100), default='')
    notes = db.Column(db.Text, default='')                 # 异常说明
    scanned_by = db.Column(db.String(80), default='')      # 扫码人
    scanned_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    # 核对确认
    confirmed = db.Column(db.Boolean, default=False)        # 是否已核对确认
    confirmed_at = db.Column(db.DateTime, nullable=True)    # 确认时间
    confirmed_by = db.Column(db.String(80), default='')     # 确认人

    asset = db.relationship('Asset', backref=db.backref('inventory_items', lazy='dynamic'))


# ======================== 考试系统 ========================

class Exam(db.Model):
    """考试（全院区共享，hospital_id=0）"""
    __tablename__ = 'exams'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, default='')          # 考试标题
    description = db.Column(db.Text, default='')                           # 考试说明
    duration_minutes = db.Column(db.Integer, default=30)                   # 考试时长（分钟）
    pass_score = db.Column(db.Float, default=60.0)                         # 及格分数（百分比）
    total_score = db.Column(db.Float, default=100.0)                       # 总分
    shuffle_questions = db.Column(db.Boolean, default=True)                # 是否打乱题目
    shuffle_options = db.Column(db.Boolean, default=True)                  # 是否打乱选项
    show_result_immediately = db.Column(db.Boolean, default=True)          # 交卷后立即显示成绩
    status = db.Column(db.String(20), default='draft')                    # draft/published/closed
    allowed_groups = db.Column(db.Text, default='[]')                     # JSON数组：允许参加的角色组名列表
    allowed_teams = db.Column(db.Text, default='[]')                      # JSON数组：允许参加的人员组别列表（team字段）
    max_attempts = db.Column(db.Integer, default=0)                       # 最多尝试次数（0=不限）
    hospital_id = db.Column(db.Integer, default=0)                        # 0=全院区共享
    created_by = db.Column(db.String(80), default='')                     # 创建人
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    questions = db.relationship('ExamQuestion', backref='exam', lazy='dynamic',
                                cascade='all, delete-orphan',
                                order_by='ExamQuestion.sort_order')
    submissions = db.relationship('ExamSubmission', backref='exam', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def get_allowed_groups(self):
        try:
            return json.loads(self.allowed_groups) if self.allowed_groups else []
        except (json.JSONDecodeError, TypeError):
            return []

    def get_allowed_teams(self):
        try:
            return json.loads(self.allowed_teams) if self.allowed_teams else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_allowed_groups(self, groups):
        self.allowed_groups = json.dumps(groups)

    def set_allowed_teams(self, teams):
        self.allowed_teams = json.dumps(teams)

    def check_access(self, user=None):
        """检查用户是否有权考试（基于角色组 + 人员组别）"""
        from flask_login import current_user
        u = user or current_user
        if not u or not u.is_authenticated:
            return False
        if u.is_admin:
            return True

        # 角色组检查
        from models import get_group_name_by_id as _get_group_name
        group_name = _get_group_name(u.group_id) or u.group or '普通用户'
        groups = self.get_allowed_groups()
        if groups and group_name not in groups:
            return False

        # 人员组别检查
        teams = self.get_allowed_teams()
        if teams:
            from models import Person
            person = Person.query.filter_by(user_id=u.id).first()
            if not person or person.team not in teams:
                return False

        return True

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'duration_minutes': self.duration_minutes,
            'pass_score': self.pass_score,
            'total_score': self.total_score,
            'status': self.status,
            'shuffle_questions': self.shuffle_questions,
            'shuffle_options': self.shuffle_options,
            'show_result_immediately': self.show_result_immediately,
            'allowed_groups': self.get_allowed_groups(),
            'allowed_teams': self.get_allowed_teams(),
            'max_attempts': self.max_attempts,
            'created_by': self.created_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'question_count': self.questions.count(),
            'submission_count': self.submissions.count(),
        }


class ExamQuestion(db.Model):
    """试题"""
    __tablename__ = 'exam_questions'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False, index=True)
    question_type = db.Column(db.String(20), default='single')  # single/multi/judge/fill
    question_text = db.Column(db.Text, nullable=False, default='')
    options = db.Column(db.Text, default='[]')                  # JSON：[{label:'A', text:'...'}]
    answer = db.Column(db.Text, default='')                     # 正确答案（单选:A / 多选:A,B / 判断:T/F / 填空:自由文本）
    score = db.Column(db.Float, default=10.0)
    analysis = db.Column(db.Text, default='')                   # 答案解析
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def get_options(self):
        try:
            return json.loads(self.options) if self.options else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_options(self, opts):
        self.options = json.dumps(opts)

    def check_answer(self, user_answer):
        """检查答案是否正确（支持多种题型）"""
        if self.question_type == 'single':
            return user_answer.strip().upper() == self.answer.strip().upper()
        elif self.question_type == 'multi':
            ua = set(x.strip().upper() for x in user_answer.split(',') if x.strip())
            sa = set(x.strip().upper() for x in self.answer.split(',') if x.strip())
            return ua == sa
        elif self.question_type == 'judge':
            return user_answer.strip().upper() == self.answer.strip().upper()
        elif self.question_type == 'fill':
            # 填空题：包含匹配（不区分大小写，去除首尾空格）
            return self.answer.strip().lower() in user_answer.strip().lower() or \
                   user_answer.strip().lower() in self.answer.strip().lower()
        return False

    def to_dict(self, include_answer=True):
        opts = self.get_options()
        d = {
            'id': self.id,
            'exam_id': self.exam_id,
            'question_type': self.question_type,
            'question_text': self.question_text,
            'options': opts,
            'score': self.score,
            'sort_order': self.sort_order,
        }
        if include_answer:
            d['answer'] = self.answer
            d['analysis'] = self.analysis
        return d


class ExamSubmission(db.Model):
    """用户考试答卷"""
    __tablename__ = 'exam_submissions'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    score = db.Column(db.Float, default=0.0)
    total_possible = db.Column(db.Float, default=0.0)
    correct_count = db.Column(db.Integer, default=0)
    total_count = db.Column(db.Integer, default=0)
    answers = db.Column(db.Text, default='{}')                 # JSON: {qid: answer_text}
    status = db.Column(db.String(20), default='in_progress')   # in_progress/submitted/graded
    started_at = db.Column(db.DateTime, default=datetime.now)
    submitted_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, default=0)
    user = db.relationship('User', backref='exam_submissions')

    def get_answers(self):
        try:
            return json.loads(self.answers) if self.answers else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_answers(self, ans_dict):
        self.answers = json.dumps(ans_dict)

    def is_passed(self, pass_score):
        if self.total_possible <= 0:
            return False
        pct = (self.score / self.total_possible) * 100
        return pct >= pass_score

    def to_dict(self):
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'exam_title': self.exam.title if self.exam else '',
            'user_id': self.user_id,
            'user_name': self.user.display_name if self.user else '',
            'score': self.score,
            'total_possible': self.total_possible,
            'correct_count': self.correct_count,
            'total_count': self.total_count,
            'status': self.status,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M') if self.started_at else '',
            'submitted_at': self.submitted_at.strftime('%Y-%m-%d %H:%M') if self.submitted_at else '',
            'duration_seconds': self.duration_seconds,
            'passed': self.is_passed(self.exam.pass_score) if self.exam else False,
        }


# ==================== SQLite WAL 模式 ====================
# 所有 SQLite 引擎连接时自动设置 WAL + NORMAL，提升并发写入性能
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, 'connect')
def set_sqlite_wal(dbapi_connection, connection_record):
    if hasattr(dbapi_connection, 'cursor'):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
        except Exception:
            pass  # 非 SQLite 引擎忽略
        cursor.close()


class WorkOrderStar(db.Model):
    """工单星标（用户维度）"""
    __tablename__ = 'work_order_stars'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'order_id', name='uq_user_order_star'),)


# ==================== 财务资产 ====================

class FinanceReceipt(HospitalMixin, db.Model):
    """固定资产入库单"""
    __tablename__ = 'finance_receipts'
    id = db.Column(db.Integer, primary_key=True)
    doc_no = db.Column(db.String(80), unique=True, nullable=False, index=True)  # ZJCD20260604883
    title = db.Column(db.String(200), default='固定资产入库单')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    receipt_date = db.Column(db.Date, default=date.today)
    operator = db.Column(db.String(80), default='')
    warehouse = db.Column(db.String(100), default='')
    invoice_date = db.Column(db.Date, nullable=True)
    invoice_no = db.Column(db.String(100), default='')  # 发票号
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    amount_words = db.Column(db.String(200), default='')  # 大写金额
    manager = db.Column(db.String(80), default='')       # 主管
    inspector = db.Column(db.String(80), default='')     # 验收人
    purchaser = db.Column(db.String(80), default='')     # 采购人
    remark = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    supplier = db.relationship('Supplier', backref='receipts', foreign_keys=[supplier_id])


class FinanceReceiptItem(HospitalMixin, db.Model):
    """入库单明细"""
    __tablename__ = 'finance_receipt_items'
    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('finance_receipts.id', ondelete='CASCADE'), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    department = db.Column(db.String(100), default='')  # 领用科室
    item_name = db.Column(db.String(200), default='')    # 品名
    model_spec = db.Column(db.String(200), default='')   # 型号
    unit = db.Column(db.String(20), default='台')        # 单位
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(12, 2), default=0)
    amount = db.Column(db.Numeric(12, 2), default=0)
    receipt = db.relationship('FinanceReceipt',
        backref=db.backref('items', lazy='dynamic', cascade='all, delete-orphan', order_by='FinanceReceiptItem.sort_order'),
        foreign_keys=[receipt_id])


class FinanceDelivery(HospitalMixin, db.Model):
    """固定资产出库单"""
    __tablename__ = 'finance_deliveries'
    id = db.Column(db.Integer, primary_key=True)
    doc_no = db.Column(db.String(80), unique=True, nullable=False, index=True)  # KSCK20260604883
    title = db.Column(db.String(200), default='固定资产出库单')
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    delivery_date = db.Column(db.Date, default=date.today)
    recipient = db.Column(db.String(80), default='')     # 领用人员
    warehouse = db.Column(db.String(100), default='')     # 出库仓库
    invoice_type = db.Column(db.String(20), default='0001')  # 发票类型代码
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    amount_words = db.Column(db.String(200), default='')
    sender = db.Column(db.String(80), default='')         # 发货人
    receiver = db.Column(db.String(80), default='')        # 签收人
    remark = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    supplier = db.relationship('Supplier', backref='deliveries', foreign_keys=[supplier_id])


class FinanceDeliveryItem(HospitalMixin, db.Model):
    """出库单明细"""
    __tablename__ = 'finance_delivery_items'
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey('finance_deliveries.id', ondelete='CASCADE'), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    item_name = db.Column(db.String(200), default='')
    unit = db.Column(db.String(20), default='台')
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(12, 2), default=0)
    amount = db.Column(db.Numeric(12, 2), default=0)
    invoice_no = db.Column(db.String(100), default='')  # 发票号
    delivery = db.relationship('FinanceDelivery',
        backref=db.backref('items', lazy='dynamic', cascade='all, delete-orphan', order_by='FinanceDeliveryItem.sort_order'),
        foreign_keys=[delivery_id])

