"""故障二级分类 - 初始化脚本
用法: python3 scripts/init_fault_categories.py [--prod]
注意: 先在 dev 上跑，确认无误后再 --prod 跑生产库
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from models import db, FaultCategory, FaultSubcategory, FaultKeyword, WorkOrder
from datetime import datetime

def create_app(sqlite_path=None):
    app = Flask(__name__)
    if sqlite_path:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{sqlite_path}'
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///workorders.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app

def init_data():
    """植入种子数据"""
    # === 1. 一级分类 ===
    cats = {
        '软件': 1,
        '硬件': 2,
        '打印机': 3,
        '协助': 4,
    }
    cat_objects = {}
    for name, order in cats.items():
        c = FaultCategory.query.filter_by(name=name).first()
        if not c:
            c = FaultCategory(name=name, sort_order=order)
            db.session.add(c)
        cat_objects[name] = c
    db.session.flush()

    # === 2. 二级分类 + 关键词 ===
    sub_data = [
        # ---- 软件 ----
        ('软件', '住院医生站', 1, [
            '住院医生站', '住院医生', '住院医站', '住院系统', '住院医系统',
        ]),
        ('软件', '门诊医生站', 2, [
            '门诊医生站', '门诊医生', '门诊医站', '门诊系统', '门诊工作站',
        ]),
        ('软件', 'PACS', 3, [
            'pacs', 'PACS', '影像系统', '放射系统', '影像归档',
        ]),
        ('软件', '看片系统', 4, [
            '看片', '阅片', '影像浏览', '影像查看',
        ]),
        ('软件', 'LIS', 5, [
            'lis', 'LIS', '检验系统', '检验信息', 'lis系统',
        ]),
        ('软件', '手术系统', 6, [
            '手术系统', '手术麻醉', '手术管理',
        ]),
        ('软件', '麻醉系统', 7, [
            '麻醉系统', '麻醉机软件',
        ]),
        ('软件', 'Office', 8, [
            'office', 'Office', 'word', 'excel', 'ppt', 'WPS',
            '办公软件', '办公套件',
        ]),
        ('软件', '解压缩软件', 9, [
            '解压', '压缩', '解压缩', 'winrar', 'winzip', '7z', '好压',
            '360压缩',
        ]),
        # ---- 硬件 ----
        ('硬件', '电脑', 1, [
            '电脑', '主机', '笔记本', '台式机', '计算机',
            '无法开机', '开不了机', '蓝屏', '花屏', '黑屏',
            '死机', '卡顿', '系统损坏', '重装系统',
            '无法打开', '打不开', '进不了系统',
            '不通电', '电源', '内存', '硬盘', '风扇', '主板',
        ]),
        ('硬件', '扫码墩', 2, [
            '扫码墩', '扫码枪', '扫描枪', '扫码器', '扫码',
        ]),
        ('硬件', '读卡器', 3, [
            '读卡器', '刷卡器', '刷卡', '医保卡读卡',
        ]),
        ('硬件', '键鼠', 4, [
            '键盘', '鼠标', '键鼠', '无线键鼠', '键鼠套',
        ]),
        ('硬件', '显示器', 5, [
            '显示器', '显示屏', '屏幕', '监控屏', '液晶屏',
        ]),
        # ---- 打印机 ----
        ('打印机', '激光打印机', 1, [
            '激光打印机', '激光', '打印机', '打印',
        ]),
        ('打印机', '喷墨打印机', 2, [
            '喷墨打印机', '喷墨',
        ]),
        ('打印机', '针式打印机', 3, [
            '针式打印机', '针式', '针打',
        ]),
        ('打印机', '热敏打印机', 4, [
            '热敏打印机', '热敏', '热敏纸',
        ]),
        ('打印机', '一体式打印机', 5, [
            '一体式打印机', '一体机', '打印一体机',
        ]),
        # ---- 协助 ----
        ('协助', '电脑搬家', 1, [
            '电脑搬家', '搬迁电脑', '电脑迁移', '移机',
        ]),
        ('协助', '科室移位', 2, [
            '科室移位', '科室搬迁', '搬科室', '科室调整',
        ]),
        ('协助', '资产回收', 3, [
            '资产回收', '设备回收', '回收资产',
        ]),
        ('协助', '新增设备', 4, [
            '新增设备', '新设备', '设备新增', '添置设备',
        ]),
        ('协助', '发放设备', 5, [
            '发放设备', '设备发放', '领用', '领取设备',
        ]),
        ('协助', '开机房门', 6, [
            '开机房门', '开门', '开房门', '门打不开',
        ]),
    ]

    for cat_name, sub_name, sub_order, keywords in sub_data:
        cat = cat_objects[cat_name]
        sub = FaultSubcategory.query.filter_by(category_id=cat.id, name=sub_name).first()
        if sub:
            sub.sort_order = sub_order
        else:
            sub = FaultSubcategory(category_id=cat.id, name=sub_name, sort_order=sub_order)
            db.session.add(sub)
        db.session.flush()

        # 删除旧关键词，重新插入
        FaultKeyword.query.filter_by(subcategory_id=sub.id).delete()
        for i, kw in enumerate(keywords):
            k = FaultKeyword(subcategory_id=sub.id, keyword=kw, sort_order=i)
            db.session.add(k)

    db.session.commit()
    print(f'✓ 种子数据植入成功: {len(cats)} 分类, {len(sub_data)} 子分类')

def create_tables():
    """创建新表 + 加字段"""
    with app.app_context():
        db.create_all()
        try:
            db.session.execute(db.text('ALTER TABLE work_orders ADD COLUMN fault_subcategory VARCHAR(100) NOT NULL DEFAULT \'\''))
            db.session.commit()
            print('✓ work_orders.fault_subcategory 字段已添加')
        except Exception as e:
            if 'duplicate column' in str(e).lower():
                print('~ work_orders.fault_subcategory 字段已存在')
            else:
                print(f'~ ALTER TABLE work_orders: {e}')
            db.session.rollback()

def backfill_existing():
    """回填已有工单的 fault_subcategory（用关键词匹配）"""
    from services.fault_matcher import match_fault
    orders = WorkOrder.query.filter(
        (WorkOrder.fault_subcategory == '') | (WorkOrder.fault_subcategory.is_(None))
    ).all()
    count = 0
    for o in orders:
        if o.title:
            result = match_fault(o.title)
            if result and result['subcategory']:
                o.fault_subcategory = result['subcategory']
                count += 1
    db.session.commit()
    print(f'✓ 回填 {count} 条工单')

if __name__ == '__main__':
    prod = '--prod' in sys.argv
    db_path = '/var/www/hospital-workorder/instance/workorders.db' if prod else None
    app = create_app(db_path)
    with app.app_context():
        print(f'运行模式: {"生产库" if prod else "开发库"}')
        create_tables()
        init_data()
        backfill_existing()
