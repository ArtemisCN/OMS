"""带多院区隔离的主键查询工具

背景：SQLAlchemy 的 `Model.query.get(id)` / `Model.query.get_or_404(id)` 按主键
直查，**不触发** `auto_hospital_filter` 的 before_compile 事件，导致多院区隔离被绕过
（任何登录用户可读取/操作其他医院的工单、资产等，即 IDOR 越权漏洞）。

本模块提供 `safe_get` / `safe_get_or_404`，用 `filter_by(id=...)` 替代 `.get()`
（filter_by 返回 Query 对象，执行时走 before_compile 事件，会被自动追加
hospital_id 条件）。

规则：
- 模型在 `HOSPITAL_FILTERED_MODELS` 白名单 且 `g.hospital_id` 有效
  （非 None 且非 0）→ 附加 hospital_id 条件（双保险：显式 filter + before_compile）
- 白名单模型但 hid 为 None（匿名请求/脚本）或 0（集团看板全局视图）
  → 保持原 `.query.get()` 行为（与 auto_hospital_filter 的跳过逻辑一致）
- 非白名单模型（User / SystemSetting / RoleGroup 等）→ 透传原 `.query.get()`
  注意：User.hospital_id 可空（如无归属医院用户），不应强制过滤
"""
from flask import g, abort

# 延迟导入避免循环依赖（models 是核心模块，不依赖 utils）
def _filtered_names():
    from models import HOSPITAL_FILTERED_MODELS
    return HOSPITAL_FILTERED_MODELS


def safe_get(model, id):
    """带多院区隔离的主键查询。找不到返回 None（与原 .query.get() 语义一致）。"""
    if model.__name__ in _filtered_names() and hasattr(model, 'hospital_id'):
        hid = getattr(g, 'hospital_id', None)
        if hid is not None and hid != 0:
            return model.query.filter_by(id=id, hospital_id=hid).first()
    return model.query.get(id)


def safe_get_or_404(model, id):
    """safe_get + 404 兜底（替代 Model.query.get_or_404(id)）。"""
    obj = safe_get(model, id)
    if obj is None:
        abort(404)
    return obj
