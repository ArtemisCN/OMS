"""方案匹配服务"""
from functools import lru_cache
from fuzzywuzzy import process, fuzz
import config


@lru_cache(maxsize=512)
def _fuzzy_match(title):
    """缓存模糊匹配结果（标题→模板内容）"""
    if not title or len(title) < 3:
        return None
    best_match = process.extractOne(
        title,
        config.SOLUTION_TEMPLATES.keys(),
        scorer=fuzz.token_sort_ratio
    )
    if best_match and best_match[1] >= 55:
        return config.SOLUTION_TEMPLATES[best_match[0]]
    return None


def get_solution_by_title(title):
    """根据工单名称模糊匹配解决方案模板"""
    return _fuzzy_match(title)


def generate_fallback_solution(title, fault_type):
    """兜底方案"""
    if '打印机' in fault_type or '打印机' in title:
        return f'经现场检查，{title}，已进行常规维护并测试，打印机恢复正常工作。'
    elif '软件' in fault_type or '软件' in title:
        return f'经检查软件环境，{title}，已重装相关组件，软件功能恢复正常。'
    elif '硬件' in fault_type or any(k in title for k in ['电脑', '网络', '键盘', '鼠标', '显示器']):
        return f'经现场处理，{title}，已完成相关修复操作，设备恢复正常使用。'
    else:
        return f'经现场处理，{title}，问题已解决，设备恢复正常运行。'


def get_all_solution_titles():
    return list(config.SOLUTION_TEMPLATES.keys())


def get_solution_content(title):
    return config.SOLUTION_TEMPLATES.get(title, '')


def guess_fault_type(title, desc=''):
    """根据标题和描述猜测故障类型"""
    text = (title + ' ' + desc).lower()
    # 按优先级匹配
    for fault_type, keywords in config.FAULT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return fault_type
    return config.DEFAULT_FAULT_TYPE


def guess_device_type(title, desc=''):
    """根据标题和描述猜测设备类型"""
    text = (title + ' ' + desc)
    for device_type, keywords in config.DEVICE_KEYWORDS_PRIORITY:
        for kw in keywords:
            if kw in text:
                return device_type
    return config.DEFAULT_DEVICE_TYPE
