"""为上海市第七人民医院填充科室模拟数据"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from app import create_app
from models import db, Department, Hospital

app = create_app()
with app.app_context():
    # 找到七院
    qiyuan = Hospital.query.filter(Hospital.name.contains('第七人民医院')).first()
    if not qiyuan:
        print('❌ 未找到上海市第七人民医院')
        exit(1)
    hid = qiyuan.id
    print(f'✅ 七院 ID={hid}')

    # 清空旧数据
    Department.query.filter_by(hospital_id=hid).delete()
    db.session.flush()

    mock = [
        # (name, floor, category, building)
        # 门诊楼 (building=1)
        ('急诊科', '1', '急诊', '1'),
        ('门诊', '1', '门诊', '1'),
        ('收费处', '1', '行政', '1'),
        ('药房', '1', '行政', '1'),
        ('内科', '2', '内科', '1'),
        ('外科', '2', '外科', '1'),
        ('检验科', '2', '检验', '1'),
        ('影像科', '3', '影像', '1'),
        ('妇产科', '3', '妇儿', '1'),
        ('儿科', '3', '妇儿', '1'),
        ('耳鼻喉科', '4', '外科', '1'),
        ('眼科', '4', '外科', '1'),
        ('皮肤科', '4', '门诊', '1'),
        ('口腔科', '5', '门诊', '1'),
        ('中医科', '5', '其他', '1'),
        ('行政办公', '5', '行政', '1'),
        # 住院楼 (building=2)
        ('心血管内科', '1', '内科', '2'),
        ('呼吸内科', '2', '内科', '2'),
        ('消化内科', '2', '内科', '2'),
        ('内分泌科', '3', '内科', '2'),
        ('神经内科', '3', '内科', '2'),
        ('普外科', '4', '外科', '2'),
        ('骨科', '4', '外科', '2'),
        ('泌尿外科', '5', '外科', '2'),
        ('神经外科', '5', '外科', '2'),
        ('胸外科', '6', '外科', '2'),
        ('妇产科病房', '6', '妇儿', '2'),
        ('儿科病房', '7', '妇儿', '2'),
        ('ICU', '7', '急诊', '2'),
        ('手术室', '8', '急诊', '2'),
        ('康复科', '8', '其他', '2'),
        ('病理科', '9', '检验', '2'),
        ('输血科', '9', '检验', '2'),
        ('住院药房', '10', '行政', '2'),
        ('营养科', '10', '其他', '2'),
        ('供应室', '11', '行政', '2'),
        ('设备科', '11', '行政', '2'),
        ('信息科', '12', '行政', '2'),
        ('病案室', '12', '行政', '2'),
    ]

    for name, floor, category, building in mock:
        d = Department(
            hospital_id=hid,
            name=name,
            floor=floor,
            category=category,
            building=building,
            is_active=True,
        )
        db.session.add(d)

    db.session.commit()
    print(f'✅ 已添加 {len(mock)} 个科室')
    b1 = 0
    b2 = 0
    for _, _, _, b in mock:
        if b == '1':
            b1 += 1
        elif b == '2':
            b2 += 1
    print(f'   门诊楼: {b1} 个科室，住院楼: {b2} 个科室')

    # 验证
    depts = Department.query.filter_by(hospital_id=hid).order_by(Department.building, Department.floor).all()
    print(f'\n📋 科室列表:')
    for d in depts:
        print(f'  {d.building}号楼 {d.floor}F [{d.category}] {d.name}')
