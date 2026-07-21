"""导入热门打印机耗材数据"""
import sys
sys.path.insert(0, '/var/www/hospital-workorder')
from app import create_app
from models import db, Consumable

data = [
    {"name":"惠普原装黑色硒鼓","spec":"CC388A","unit":"支","compatible_printers":"HP P1007/P1008/P1106/P1108/M1136/M1213nf","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色硒鼓","spec":"Q2612A","unit":"支","compatible_printers":"HP 1010/1012/1015/1020/1022/M1005/M1319f","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色硒鼓","spec":"CE278A","unit":"支","compatible_printers":"HP P1566/P1606dn/M1536dnf","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色硒鼓","spec":"CF280A","unit":"支","compatible_printers":"HP P1102w/P1102/M1132/M1212nf","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色硒鼓","spec":"CF218A","unit":"支","compatible_printers":"HP M104a/M104w/M132a/M132nw","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色墨盒","spec":"HP 802 黑 (CH561ZZ)","unit":"个","compatible_printers":"HP Deskjet 1050/2050/3050","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色墨盒","spec":"HP 803 黑 (N9J66AA)","unit":"个","compatible_printers":"HP DeskJet 2132/3636/4538/5078","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色墨盒","spec":"HP 46 黑 (V2Z70AA)","unit":"个","compatible_printers":"HP OfficeJet 2029/2529/2629/3830","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色墨盒","spec":"HP 680 黑 (F6V26AA)","unit":"个","compatible_printers":"HP DeskJet 1112/2130/3630/4530","supplier_name":"惠普官方"},
    {"name":"惠普原装黑色墨盒","spec":"HP 63 黑 (F6U69AA)","unit":"个","compatible_printers":"HP DeskJet 2632/3630/4530/5070","supplier_name":"惠普官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-303","unit":"支","compatible_printers":"Canon LBP-2900/LBP-3000/MF-4010/MF-4120","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-912","unit":"支","compatible_printers":"Canon LBP-3108/LBP-3150/MF-4410/MF-4450","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-925","unit":"支","compatible_printers":"Canon LBP-6000/LBP-6018/MF-3010","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-328","unit":"支","compatible_printers":"Canon LBP-3250/MF-4710/MF-4750/MF-4890","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-337","unit":"支","compatible_printers":"Canon LBP-151dw/LBP-162dw/MF-232w/MF-249dw","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色硒鼓","spec":"CRG-045","unit":"支","compatible_printers":"Canon LBP113w/MF113w","supplier_name":"佳能官方"},
    {"name":"佳能原装黑色墨盒","spec":"PG-815 黑","unit":"个","compatible_printers":"Canon PIXMA MG2400/MG2500/MX490","supplier_name":"佳能官方"},
    {"name":"兄弟原装黑色硒鼓","spec":"DR-1035","unit":"支","compatible_printers":"Brother DCP-1519/DCP-1618W/MFC-1819","supplier_name":"兄弟官方"},
    {"name":"兄弟原装黑色碳粉盒","spec":"TN-1035","unit":"支","compatible_printers":"Brother DCP-1519/DCP-1618W/MFC-1819","supplier_name":"兄弟官方"},
    {"name":"兄弟原装黑色硒鼓","spec":"DR-2350","unit":"支","compatible_printers":"Brother DCP-7080/DCP-7180DN/MFC-7480D","supplier_name":"兄弟官方"},
    {"name":"兄弟原装黑色碳粉盒","spec":"TN-2312","unit":"支","compatible_printers":"Brother DCP-7080/DCP-7180DN","supplier_name":"兄弟官方"},
    {"name":"兄弟原装黑色碳粉盒","spec":"TN-2325","unit":"支","compatible_printers":"Brother DCP-7080/DCP-7180DN(高容)","supplier_name":"兄弟官方"},
    {"name":"联想原装黑色硒鼓","spec":"LD202","unit":"支","compatible_printers":"Lenovo LJ2000/LJ2200/M7205/M7250","supplier_name":"联想官方"},
    {"name":"联想原装黑色碳粉盒","spec":"LT202","unit":"支","compatible_printers":"Lenovo LJ2000/LJ2200/M7205/M7250","supplier_name":"联想官方"},
    {"name":"联想原装黑色硒鼓","spec":"LD2441","unit":"支","compatible_printers":"Lenovo LJ2400/LJ2600D/M7400/M7450F","supplier_name":"联想官方"},
    {"name":"联想原装黑色碳粉盒","spec":"LT2441","unit":"支","compatible_printers":"Lenovo LJ2400/LJ2600D/M7400/M7450F","supplier_name":"联想官方"},
    {"name":"联想原装黑色硒鼓","spec":"LD2451","unit":"支","compatible_printers":"Lenovo LJ2405D/LJ2605D/M7605D/M7615DNA","supplier_name":"联想官方"},
    {"name":"联想原装黑色碳粉盒","spec":"LT2451","unit":"支","compatible_printers":"Lenovo LJ2405D/LJ2605D/M7605D/M7615DNA","supplier_name":"联想官方"},
    {"name":"奔图原装黑色硒鼓","spec":"PD-200H","unit":"支","compatible_printers":"Pantum P2000/P2050/P2060","supplier_name":"奔图官方"},
    {"name":"奔图原装黑色硒鼓","spec":"PD-205","unit":"支","compatible_printers":"Pantum P2500/P2500W","supplier_name":"奔图官方"},
    {"name":"奔图原装黑色硒鼓","spec":"PD-210","unit":"支","compatible_printers":"Pantum P2200/P2200W","supplier_name":"奔图官方"},
    {"name":"奔图原装黑色碳粉盒","spec":"PT-200","unit":"支","compatible_printers":"Pantum P2000/P2050/P2060","supplier_name":"奔图官方"},
    {"name":"奔图原装黑色碳粉盒","spec":"PT-250","unit":"支","compatible_printers":"Pantum P2500/P2500W","supplier_name":"奔图官方"},
    {"name":"爱普生原装黑色墨盒","spec":"T6721","unit":"个","compatible_printers":"Epson L3118/L3119/L3158/L3168","supplier_name":"爱普生官方"},
    {"name":"爱普生原装维护箱","spec":"T6714","unit":"个","compatible_printers":"Epson L3118/L3119/L3158/L3168","supplier_name":"爱普生官方"},
]

app = create_app()
with app.app_context():
    count = 0
    for item in data:
        exists = Consumable.query.filter_by(name=item['name'], spec=item['spec']).first()
        if not exists:
            c = Consumable(
                name=item['name'],
                spec=item['spec'],
                unit=item['unit'],
                quantity=0,
                min_quantity=5,
                supplier_name=item.get('supplier_name', ''),
                compatible_printers=item.get('compatible_printers', ''),
            )
            db.session.add(c)
            count += 1
    db.session.commit()
    print(f'导入完成：新增 {count} 条，已有 {Consumable.query.count()} 条耗材')
