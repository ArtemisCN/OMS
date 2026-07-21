"""
故障二级分类匹配引擎
从标题中匹配关键词 → 返回 (category, subcategory)
关键词按长度降序匹配，长词优先（更精确）
"""
from functools import lru_cache
from models import db, FaultCategory, FaultSubcategory, FaultKeyword


@lru_cache(maxsize=256)
def _load_all_keywords():
    """加载全量关键词，按长度降序"""
    rows = db.session.query(
        FaultKeyword.keyword,
        FaultSubcategory.name.label('sub_name'),
        FaultCategory.name.label('cat_name')
    ).join(FaultSubcategory, FaultKeyword.subcategory_id == FaultSubcategory.id
    ).join(FaultCategory, FaultSubcategory.category_id == FaultCategory.id
    ).all()
    # 按关键词长度降序（长词优先精确匹配）
    result = sorted([
        {'keyword': r.keyword, 'subcategory': r.sub_name, 'category': r.cat_name}
        for r in rows
    ], key=lambda x: -len(x['keyword']))
    return result


def match_fault(title):
    """
    从标题匹配故障分类
    返回: {'category': '硬件', 'subcategory': '电脑', 'match_type': 'keyword'}
          或 {'category': '硬件', 'subcategory': '', 'match_type': 'fallback'}
    """
    if not title:
        return {'category': '硬件', 'subcategory': '', 'match_type': 'empty'}

    title_lower = title.lower()

    # 1. 关键词匹配（长词优先）
    all_kw = _load_all_keywords()
    for item in all_kw:
        if item['keyword'].lower() in title_lower:
            return {
                'category': item['category'],
                'subcategory': item['subcategory'],
                'match_type': 'keyword',
            }

    # 2. fallback：使用 DB 或 config 的关键词规则
    from services.keyword_config import get_fault_keywords
    fk = get_fault_keywords()
    for ftype, keywords in fk.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                return {'category': ftype, 'subcategory': '', 'match_type': 'fallback'}

    # 3. 完全没匹配时读默认值
    from services.keyword_config import get_device_keywords
    dk = get_device_keywords()
    default_fault = '硬件'
    if isinstance(dk, dict) and 'default_device' in dk:
        # 从设备关键词的默认值推断
        pass
    return {'category': default_fault, 'subcategory': '', 'match_type': 'fallback'}


def get_categories():
    """获取全部分类（含子分类），用于管理页面"""
    cats = FaultCategory.query.order_by(FaultCategory.sort_order).all()
    result = []
    for c in cats:
        subs = FaultSubcategory.query.filter_by(category_id=c.id)\
            .order_by(FaultSubcategory.sort_order).all()
        result.append({
            'id': c.id,
            'name': c.name,
            'subcategories': [{'id': s.id, 'name': s.name} for s in subs],
        })
    return result


def get_subcategories_by_category(category_id):
    """获取指定一级分类下的所有二级分类"""
    subs = FaultSubcategory.query.filter_by(category_id=category_id)\
        .order_by(FaultSubcategory.sort_order).all()
    return [{'id': s.id, 'name': s.name} for s in subs]


def get_keywords_by_subcategory(subcategory_id):
    """获取指定二级分类的所有关键词"""
    kws = FaultKeyword.query.filter_by(subcategory_id=subcategory_id)\
        .order_by(FaultKeyword.sort_order).all()
    return [{'id': k.id, 'keyword': k.keyword} for k in kws]
