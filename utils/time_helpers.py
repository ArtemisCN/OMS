"""时间日期处理工具函数"""
from datetime import datetime, date, timedelta
from typing import Optional, Union

def fmt_dt(dt: Optional[datetime], fmt: str = '%m/%d %H:%M') -> str:
    """安全格式化 datetime，None 返回空字符串"""
    return dt.strftime(fmt) if dt else ''

def fmt_date(d: Optional[Union[date, datetime]], fmt: str = '%Y-%m-%d') -> str:
    """安全格式化日期"""
    if not d:
        return ''
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(fmt)

def now() -> datetime:
    """当前时间"""
    return datetime.now()

def today_start() -> datetime:
    """今日零点"""
    return now().replace(hour=0, minute=0, second=0, microsecond=0)

def days_ago(days: int) -> datetime:
    """N天前的 datetime"""
    return now() - timedelta(days=days)

def fmt_duration(seconds: int) -> str:
    """将秒数格式化为可读时长"""
    if seconds < 60:
        return f'{seconds}秒'
    mins = seconds // 60
    if mins < 60:
        return f'{mins}分钟'
    hours = mins // 60
    return f'{hours}小时{mins % 60}分钟'


def resolve_team(request, user, setting_key='default_dashboard_team'):
    """解析当前用户的默认组别

    优先级:
    1. URL?team=参数（含team=''=全部组）
    2. User.team 字段
    3. 管理员取 SystemSetting（默认仪表盘组别）
    4. 返回空字符串=全部

    Usage:
        team = resolve_team(request, current_user)
    """
    team_param = request.args.get('team')
    if team_param is not None:
        return team_param
    from models import SystemSetting
    if user.team:
        return user.team
    s = SystemSetting.query.filter_by(key=setting_key).first()
    return s.value if s and s.value else ''
