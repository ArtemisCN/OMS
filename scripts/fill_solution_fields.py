"""自动填充方案模板的关键词和设备类型"""
import sys, re
sys.path.insert(0, '/var/www/hospital-workorder')
from app import create_app
from models import db, SolutionTemplate

def infer_device_type(title):
    """根据标题推断设备类型"""
    t = title.strip()
    # NB
    if re.match(r'^NB', t) or '笔记本' in t:
        return 'NB'
    # 一体机
    if '一体机' in t:
        return '一体机'
    # 打印机相关
    if re.match(r'^打印机', t) or re.match(r'^打印', t) or \
       '墨盒' in t or '搓纸轮' in t or '废墨' in t or '定影' in t or \
       '共享打印机' in t or '连接打印机' in t or '更换打印机' in t or \
       '维修打印机' in t:
        return 'PR'
    # 网络相关
    if '网络' in t or '入网' in t or '断网' in t or '网速' in t or \
       '跳网' in t or '换网线' in t or '更换网线' in t or '更换路由器' in t or \
       '安装路由器' in t or '叫号' in t or '取号' in t:
        return '网络'
    # 服务器
    if '服务器' in t:
        return '服务器'
    # 自助机
    if '自助机' in t:
        return '其他'
    # PDA
    if 'PDA' in t:
        return '其他'
    # 默认 PC
    return 'PC'

def infer_keywords(title):
    """根据标题生成关键词"""
    keywords = []
    t = title.strip()
    # 提取核心名词词组
    known_phrases = [
        '电脑死机', '电脑蓝屏', '电脑黑屏', '电脑花屏', '电脑闪屏',
        '电脑无法开机', '电脑开不了机', '电脑不开机', '电脑无法启动',
        '电脑断网', '电脑没网', '电脑无法上网', '电脑连不上网',
        '电脑卡顿', '电脑太慢', '电脑自动关机', '电脑自动重启',
        '电脑系统损坏', '电脑中病毒', '电脑中毒', '电脑更换位置',
        '电脑更换电源', '更换电脑', '新增电脑', '回收电脑',
        '打印机脱机', '打印机无法打印', '打印机打不了', '打印机打不出',
        '打印机无法使用', '打印机不打印', '打印机打印无反应',
        '打印无反应', '打印机没反应', '打印机卡纸', '打印机报错',
        '打印机异响', '打印机故障', '打印机闪红灯', '打印机不通电',
        '打印不清晰', '打印模糊', '打印质量差', '打印有横条',
        '打印全黑', '打印白纸', '打印机吸不上纸', '打印机不吸纸',
        '更换墨盒', '打印机共享', '共享打印机', '连接打印机',
        '更换打印机', '维修打印机', '更换搓纸轮', '更换废墨盒',
        '配置网络', '安装路由器', '更换路由器', '更换网线',
        '自助机故障', '叫号屏', '取号机', '无法叫号',
        '安装软件', '安装系统', '重装系统', '软件无法打开', '软件闪退',
        '程序闪退', '网页打不开', '内网网站打不开', '账号无法登录',
        '键盘失灵', '更换键盘', '鼠标失灵', '鼠标不好用', '鼠标不灵敏',
        '鼠标无法使用', '更换鼠标', '扫码墩', '扫码枪', '更换扫码枪',
        '读卡器故障', '读卡器无法使用', '读卡器失灵', '读卡器不读卡',
        '显示器打不开', '显示屏打不开', '显示器不通电', '连接显示屏',
        '更换显示器', '切屏器', '更换切屏器', 'U盘读不出', '接触不良',
        '指导操作', '联系厂家',
    ]
    # 优先匹配长短语
    remaining = t
    for phrase in known_phrases:
        if phrase in remaining:
            keywords.append(phrase)
            remaining = remaining.replace(phrase, '', 1)
    # 再分解剩余内容为单独关键词
    remaining = remaining.strip()
    if remaining:
        # 按常见分隔符拆分
        parts = re.split(r'[，,、]', remaining)
        for p in parts:
            p = p.strip()
            if p and p not in keywords:
                keywords.append(p)
    # 如果还是没有关键词，把整个标题当关键词
    if not keywords:
        keywords.append(t)
    return ','.join(keywords)

app = create_app()
with app.app_context():
    total = SolutionTemplate.query.count()
    updated_dt = 0
    updated_kw = 0
    for s in SolutionTemplate.query.all():
        changes = []
        if not s.device_type:
            dt = infer_device_type(s.title)
            s.device_type = dt
            changes.append(f'device_type={dt}')
            updated_dt += 1
        if not s.keywords:
            kw = infer_keywords(s.title)
            s.keywords = kw
            changes.append(f'keywords={kw}')
            updated_kw += 1
        if changes:
            print(f'  #{s.id:3d} {s.title:20s} → {", ".join(changes)}')
    db.session.commit()
    print(f'\n完成！{total} 条方案模板：更新设备类型 {updated_dt} 条，更新关键词 {updated_kw} 条')
