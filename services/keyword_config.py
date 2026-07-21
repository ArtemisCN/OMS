"""
关键词配置入库 —— 提供从 DB 读取关键词的工具函数
兜底逻辑：优先读 SystemSetting，空则回退 config.py
"""
import json

# ==================== 读取函数（DB优先，config兜底） ====================

def get_fault_keywords():
    """获取故障类型关键词映射 {故障类型: [关键词列表]}"""
    from models import SystemSetting
    setting = SystemSetting.query.filter_by(key='fault_keywords').first()
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            pass
    import config
    return getattr(config, 'FAULT_KEYWORDS', {})


def get_device_keywords():
    """获取设备类型关键词列表 [(设备类型, [关键词列表])]"""
    from models import SystemSetting
    setting = SystemSetting.query.filter_by(key='device_keywords').first()
    if setting and setting.value:
        try:
            data = json.loads(setting.value)
            # 兼容 dict 格式 {keywords: [...], default_device: '其他'}
            if isinstance(data, dict) and 'keywords' in data:
                return data['keywords']
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    import config
    return getattr(config, 'DEVICE_KEYWORDS_PRIORITY', [])


def get_default_device_type():
    """获取默认设备类型"""
    from models import SystemSetting
    setting = SystemSetting.query.filter_by(key='device_keywords').first()
    if setting and setting.value:
        try:
            data = json.loads(setting.value)
            if isinstance(data, dict) and 'default_device' in data:
                return data['default_device']
        except (json.JSONDecodeError, TypeError):
            pass
    import config
    return getattr(config, 'DEFAULT_DEVICE_TYPE', '其他')


def get_solution_templates():
    """获取方案模板字典（已有 DB 模型，但重置依赖 config 种子数据）"""
    from models import SolutionTemplate
    templates = SolutionTemplate.query.order_by(SolutionTemplate.title).all()
    if templates:
        return {t.title: t.content for t in templates}
    import config
    return getattr(config, 'SOLUTION_TEMPLATES', {})


# ==================== 写入函数（用于设置页面保存） ====================

def save_fault_keywords(data):
    """保存故障类型关键词到 DB"""
    from models import SystemSetting, db
    setting = SystemSetting.query.filter_by(key='fault_keywords').first()
    if not setting:
        setting = SystemSetting(
            key='fault_keywords',
            label='故障类型关键词',
            description='根据工单名称自动匹配故障类型。格式：{ "故障类型": ["关键词1", "关键词2"] }',
            category='关键词',
        )
        db.session.add(setting)
    setting.value = json.dumps(data, ensure_ascii=False)
    db.session.commit()


def save_device_keywords(data):
    """保存设备类型关键词到 DB（含默认设备类型）"""
    from models import SystemSetting, db
    setting = SystemSetting.query.filter_by(key='device_keywords').first()
    if not setting:
        setting = SystemSetting(
            key='device_keywords',
            label='设备类型关键词（含默认设备类型）',
            description='设备类型识别及默认值。格式：{ "keywords": [["设备类型", ["关键词"]], ...], "default_device": "其他" }',
            category='关键词',
        )
        db.session.add(setting)
    if isinstance(data, list):
        data = {'keywords': data, 'default_device': '其他'}
    setting.value = json.dumps(data, ensure_ascii=False)
    db.session.commit()


# ==================== 种子数据迁移 ====================

def seed_keywords_from_config():
    """首次运行时从 config.py 迁移关键词数据到 DB（仅在 DB 为空时执行）"""
    from models import SystemSetting, db

    if not SystemSetting.query.filter_by(key='fault_keywords').first():
        import config
        save_fault_keywords(getattr(config, 'FAULT_KEYWORDS', {}))

    if not SystemSetting.query.filter_by(key='device_keywords').first():
        import config
        save_device_keywords(getattr(config, 'DEVICE_KEYWORDS_PRIORITY', []))


def get_fault_keywords_for_config():
    """返回适配 config 格式的数据（用于 __init__ 中的导入兼容）"""
    raw = get_fault_keywords()
    return raw


def get_device_keywords_for_config():
    """返回适配 config 格式的数据"""
    raw = get_device_keywords()
    if isinstance(raw, dict) and 'keywords' in raw:
        return raw['keywords']
    return raw
