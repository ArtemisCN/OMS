"""补充耗材数据：得实、京瓷、补充惠普/佳能/爱普生热门款"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wsgi import app
from models import db, Consumable

NEW_CONSUMABLES = [
    # ========== 得实 Dascom (针式打印机) ==========
    ("得实80D-8色带架", "80D-8", "个", "Dascom DS-5400/DS-5400H/DS-5400PRO", "仓库A区"),
    ("得实80D-10色带架", "80D-10", "个", "Dascom DS-600/DS-650/DS-700", "仓库A区"),
    ("得实80D-3色带架", "80D-3", "个", "Dascom DS-1100/DS-1100II/DS-1700", "仓库A区"),
    ("得实M16-1色带架", "M16-1", "个", "Dascom DS-200/DS-2100/DS-2100H", "仓库A区"),
    ("得实AR-400色带架", "AR-400", "个", "Dascom AR-400/AR-500/AR-550", "仓库A区"),
    ("得实AR-800色带架", "AR-800", "个", "Dascom AR-800/AR-900", "仓库A区"),
    ("得实DS-100打印头", "DS-100-1", "个", "Dascom DS-100/DS-600/DS-700", "仓库A区"),
    ("得实DS-5400打印头", "DS-5400-01", "个", "Dascom DS-5400/DS-5400H", "仓库A区"),
    ("得实DS-1100打印头", "DS-1100-01", "个", "Dascom DS-1100/DS-1100II/DS-1700", "仓库A区"),
    ("得实AR-500打印头", "AR-500-01", "个", "Dascom AR-500/AR-550", "仓库A区"),
    ("得实DS-200进纸传感器", "DS-200-S1", "个", "Dascom DS-200/DS-2100", "仓库A区"),
    ("得实DS-5400进纸传感器", "DS-5400-S1", "个", "Dascom DS-5400/DS-5400H", "仓库A区"),
    ("得实DS-600进纸传感器", "DS-600-S1", "个", "Dascom DS-600/DS-650", "仓库A区"),

    # ========== 京瓷 Kyocera (打印机/复印机) ==========
    ("京瓷原装碳粉盒TK-1113", "TK-1113", "支", "Kyocera FS-1040/FS-1060DN/FS-1020MFP", "仓库B区"),
    ("京瓷原装碳粉盒TK-1123", "TK-1123", "支", "Kyocera FS-1120MFP/FS-1025MFP", "仓库B区"),
    ("京瓷原装碳粉盒TK-1128", "TK-1128", "支", "Kyocera FS-1060DN/FS-1325", "仓库B区"),
    ("京瓷原装碳粉盒TK-1144", "TK-1144", "支", "Kyocera ECOSYS P2040dn/P2235dn", "仓库B区"),
    ("京瓷原装碳粉盒TK-1150", "TK-1150", "支", "Kyocera ECOSYS P2235dn/P2040dn", "仓库B区"),
    ("京瓷原装碳粉盒TK-1160", "TK-1160", "支", "Kyocera ECOSYS M2540dw/M2635dw", "仓库B区"),
    ("京瓷原装碳粉盒TK-1630", "TK-1630", "支", "Kyocera KM-1635/KM-2035/FS-1118MFP", "仓库B区"),
    ("京瓷原装碳粉盒TK-4100", "TK-4100", "支", "Kyocera TASKalfa 180/1800/220/2200", "仓库B区"),
    ("京瓷原装碳粉盒TK-4200", "TK-4200", "支", "Kyocera TASKalfa 1801/2201", "仓库B区"),
    ("京瓷原装碳粉盒TK-448", "TK-448", "支", "Kyocera TASKalfa 2020/2320", "仓库B区"),
    ("京瓷原装碳粉盒TK-5220", "TK-5220", "支", "Kyocera ECOSYS M5520cdn/M5521cdn", "仓库B区"),
    ("京瓷原装碳粉盒TK-5230彩B", "TK-5230 B", "支", "Kyocera ECOSYS P5020cdn/P5020cdw", "仓库B区"),
    ("京瓷原装碳粉盒TK-5230彩C", "TK-5230 C", "支", "Kyocera ECOSYS P5020cdn/P5020cdw", "仓库B区"),
    ("京瓷原装碳粉盒TK-5230彩M", "TK-5230 M", "支", "Kyocera ECOSYS P5020cdn/P5020cdw", "仓库B区"),
    ("京瓷原装碳粉盒TK-5230彩Y", "TK-5230 Y", "支", "Kyocera ECOSYS P5020cdn/P5020cdw", "仓库B区"),
    ("京瓷原装硒鼓FK-1040", "FK-1040", "个", "Kyocera FS-1040/FS-1060DN", "仓库B区"),
    ("京瓷原装硒鼓FK-1120", "FK-1120", "个", "Kyocera FS-1120MFP/FS-1025MFP", "仓库B区"),
    ("京瓷原装硒鼓FK-1144", "FK-1144", "个", "Kyocera ECOSYS P2040dn", "仓库B区"),
    ("京瓷原装显影组件DV-1100", "DV-1100", "套", "Kyocera KM-1635/KM-2035", "仓库B区"),

    # ========== 惠普补充 (热卖机型) ==========
    ("惠普原装黑色硒鼓CF230A", "CF230A", "个", "HP M203d/M203dn/M203dw/M227d/M227fdw", "仓库C区"),
    ("惠普原装黑色硒鼓CF232A(成像鼓)", "CF232A", "个", "HP M203d/M203dn/M227d/M227fdw", "仓库C区"),
    ("惠普原装黑色硒鼓CF226A", "CF226A", "个", "HP M402dn/M402dw/M403dn/M403dw", "仓库C区"),
    ("惠普原装黑色硒鼓CF283A", "CF283A", "个", "HP LaserJet Pro M203/M227", "仓库C区"),
    ("惠普原装黑色硒鼓CF287A", "CF287A", "个", "HP M506dn/M506dw/M527dn/M527f", "仓库C区"),
    ("惠普原装黑色硒鼓CE285A", "CE285A", "个", "HP P1102w/M1132/M1212nf", "仓库C区"),
    ("惠普原装黑色硒鼓CE310A(彩)", "CE310A", "个", "HP CP1025/M175a/M175nw", "仓库C区"),
    ("惠普原装彩色硒鼓CE311A(蓝)", "CE311A", "个", "HP CP1025/M175a/M175nw", "仓库C区"),
    ("惠普原装彩色硒鼓CE312A(黄)", "CE312A", "个", "HP CP1025/M175a/M175nw", "仓库C区"),
    ("惠普原装彩色硒鼓CE313A(红)", "CE313A", "个", "HP CP1025/M175a/M175nw", "仓库C区"),
    ("惠普原装黑色墨盒HP 61(黑)", "CH561WN", "个", "HP Deskjet 1000/1050/2000/2050/3000/3050", "仓库C区"),
    ("惠普原装彩色墨盒HP 61(彩)", "CH562WN", "个", "HP Deskjet 1000/1050/2000/2050/3000/3050", "仓库C区"),
    ("惠普原装黑色墨盒HP 901(黑)", "CZ637AA", "个", "HP OfficeJet 6100/6600/6700/7110/7610", "仓库C区"),
    ("惠普原装黑色墨盒HP 902(黑)", "3YM76AA", "个", "HP OfficeJet Pro 6970/7720/7730", "仓库C区"),

    # ========== 爱普生补充 (墨仓式+针打+投影) ==========
    ("爱普生原装墨水T6721(黑)", "T6721", "瓶", "Epson L3118/L3119/L3158/L3168/L3106/L1300", "仓库C区"),
    ("爱普生原装墨水T6722(青)", "T6722", "瓶", "Epson L3118/L3119/L3158/L3168", "仓库C区"),
    ("爱普生原装墨水T6723(红)", "T6723", "瓶", "Epson L3118/L3119/L3158/L3168", "仓库C区"),
    ("爱普生原装墨水T6724(黄)", "T6724", "瓶", "Epson L3118/L3119/L3158/L3168", "仓库C区"),
    ("爱普生原装墨水T6741(黑)", "T6741", "瓶", "Epson L805/L1800/R330/R330", "仓库C区"),
    ("爱普生原装墨水T6742(青)", "T6742", "瓶", "Epson L805/L1800", "仓库C区"),
    ("爱普生原装墨水T6743(红)", "T6743", "瓶", "Epson L805/L1800", "仓库C区"),
    ("爱普生原装墨水T6744(黄)", "T6744", "瓶", "Epson L805/L1800", "仓库C区"),
    ("爱普生原装墨水T6745(浅青)", "T6745", "瓶", "Epson L805/L1800", "仓库C区"),
    ("爱普生原装墨水T6746(浅红)", "T6746", "瓶", "Epson L805/L1800", "仓库C区"),
    ("爱普生原装黑色墨盒T1731", "T1731", "个", "Epson ME33/ME330/ME35/ME340", "仓库C区"),
    ("爱普生LQ色带架S015583", "S015583", "个", "Epson LQ-590K/LQ-595K/LQ-680KII/LQ-680KPro", "仓库C区"),
    ("爱普生LQ色带架S015336", "S015336", "个", "Epson LQ-630K/LQ-635K/LQ-730K/LQ-735K", "仓库C区"),
    ("爱普生LQ色带架S015313", "S015313", "个", "Epson LQ-1600KIIIH/LQ-2090/LQ-2600K", "仓库C区"),
    ("爱普生LQ-590K打印头", "LQ590K-01", "个", "Epson LQ-590K/LQ-595K", "仓库C区"),
    ("爱普生LQ-630K打印头", "LQ630K-01", "个", "Epson LQ-630K/LQ-635K", "仓库C区"),
    ("爱普生维护箱T2950", "T2950", "个", "Epson WorkForce WF-100/WF-110", "仓库C区"),

    # ========== 佳能补充 (G系列墨仓/激光/彩机) ==========
    ("佳能原装墨水GI-890(黑)", "GI-890 BK", "瓶", "Canon PIXMA G1810/G2810/G3810/G4810", "仓库C区"),
    ("佳能原装墨水GI-890(青)", "GI-890 C", "瓶", "Canon PIXMA G1810/G2810/G3810/G4810", "仓库C区"),
    ("佳能原装墨水GI-890(红)", "GI-890 M", "瓶", "Canon PIXMA G1810/G2810/G3810/G4810", "仓库C区"),
    ("佳能原装墨水GI-890(黄)", "GI-890 Y", "瓶", "Canon PIXMA G1810/G2810/G3810/G4810", "仓库C区"),
    ("佳能原装墨水GI-81(黑)", "GI-81 BK", "瓶", "Canon PIXMA G6080/G7080", "仓库C区"),
    ("佳能原装墨水GI-81(青)", "GI-81 C", "瓶", "Canon PIXMA G6080/G7080", "仓库C区"),
    ("佳能原装墨水GI-81(红)", "GI-81 M", "瓶", "Canon PIXMA G6080/G7080", "仓库C区"),
    ("佳能原装墨水GI-81(黄)", "GI-81 Y", "瓶", "Canon PIXMA G6080/G7080", "仓库C区"),
    ("佳能原装黑色硒鼓CRG-054(黑)", "CRG-054 BK", "个", "Canon LBP621Cw/LBP623Cdn/MF641Cw/MF645Cx", "仓库C区"),
    ("佳能原装彩色硒鼓CRG-054(青)", "CRG-054 C", "个", "Canon LBP621Cw/LBP623Cdn/MF641Cw/MF645Cx", "仓库C区"),
    ("佳能原装彩色硒鼓CRG-054(红)", "CRG-054 M", "个", "Canon LBP621Cw/LBP623Cdn/MF641Cw/MF645Cx", "仓库C区"),
    ("佳能原装彩色硒鼓CRG-054(黄)", "CRG-054 Y", "个", "Canon LBP621Cw/LBP623Cdn/MF641Cw/MF645Cx", "仓库C区"),
    ("佳能原装黑色硒鼓CRG-045(黑高容)", "CRG-045H BK", "个", "Canon LBP113w/MF113w(高容)", "仓库C区"),
    ("佳能原装黑色墨盒PG-48", "PG-48", "个", "Canon PIXMA MP236/MP237/MP259/MP287", "仓库C区"),
    ("佳能原装彩色墨盒CL-58", "CL-58", "个", "Canon PIXMA MP236/MP237/MP259/MP287", "仓库C区"),

    # ========== 得实补充 (更多色带型号) ==========
    ("得实LQ-1600K色带架", "LQ-1600K", "个", "Dascom 兼容/LQ-1600KIIIH", "仓库A区"),
    ("得实DS-1100II色带架", "DS-1100II-1", "个", "Dascom DS-1100II/DS-1700", "仓库A区"),
]

def run():
    with app.app_context():
        # 检查是否已存在相同数据
        existing = set()
        for c in Consumable.query.all():
            key = (c.name, c.spec)
            existing.add(key)

        added = 0
        skipped = 0
        for name, spec, unit, printers, location in NEW_CONSUMABLES:
            key = (name, spec)
            if key in existing:
                skipped += 1
                continue
            c = Consumable(
                name=name,
                spec=spec,
                unit=unit,
                quantity=0,
                min_quantity=5,
                location=location,
                compatible_printers=printers,
                notes=''
            )
            db.session.add(c)
            added += 1
        db.session.commit()
        total = Consumable.query.count()
        print(f'✅ 新增 {added} 条, 跳过 {skipped} 条(已存在), 总计 {total} 条')

if __name__ == '__main__':
    run()
