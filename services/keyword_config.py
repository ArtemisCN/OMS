"""
关键词配置入库 —— 提供从 DB 读取关键词的工具函数
现在统一从 FaultType.keywords 读取，不再依赖独立的 SystemSetting
"""
import json


def _get_fault_type_keywords():
    """从 FaultType.keywords 提取所有故障类型→关键词映射"""
    from models import FaultType
    try:
        types = FaultType.query.filter(
            FaultType.keywords.isnot(None),
            FaultType.keywords != ''
        ).all()
        result = {}
        for ft in types:
            kws = [kw.strip() for kw in ft.keywords.split(',') if kw.strip()]
            if ft.name not in result:
                result[ft.name] = []
            for kw in kws:
                if kw not in result[ft.name]:
                    result[ft.name].append(kw)
        return result
    except Exception:
        return {}


def get_fault_keywords():
    """获取故障类型关键词映射 {故障类型: [关键词列表]}
    从 FaultType.keywords 读取，兼容 format_Settings 中已有的旧数据"""
    result = _get_fault_type_keywords()
    if result:
        return result
    # 兜底：从旧系统设置读
    from models import get_cached_setting
    kw_val = get_cached_setting('fault_keywords')
    if kw_val:
        try:
            return json.loads(kw_val)
        except (json.JSONDecodeError, TypeError):
            pass
    import config
    return getattr(config, 'FAULT_KEYWORDS', {})


def get_device_keywords():
    """获取设备类型关键词列表
    从 FaultType.keywords 读取"""
    result = _get_fault_type_keywords()
    if result:
        # 转成 [(设备类型, [关键词列表])] 格式
        return [[name, kws] for name, kws in result.items()]
    # 兜底
    from models import get_cached_setting
    kw_val = get_cached_setting('device_keywords')
    if kw_val:
        try:
            data = json.loads(kw_val)
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


# ==================== 种子数据迁移 ====================

def seed_keywords_from_config():
    """首次运行时从 config.py 迁移关键词数据到 DB（仅在 DB 为空时执行）"""
    from models import FaultType, db
    import config
    # 如果 FaultType 表还没有关键词，从 config.py 的 FAULT_KEYWORDS 写入
    has_kw = FaultType.query.filter(
        FaultType.keywords.isnot(None),
        FaultType.keywords != ''
    ).first()
    if not has_kw:
        from_config = getattr(config, 'FAULT_KEYWORDS', {})
        for name, kws in from_config.items():
            ft = FaultType.query.filter_by(name=name).first()
            if ft and not ft.keywords:
                ft.keywords = ','.join(kws)
        db.session.commit()
