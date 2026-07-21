"""工单生成服务"""
import random
from datetime import datetime, timedelta
import calendar
from services import matcher
from services.address import ADDRESS_LIST


# ==================== 故障描述库 ====================
SOFTWARE_DESC = [
    "门诊医生站双击病人报错", "住院医生站系统卡顿", "电子病历无法保存",
    "HIS系统登录超时", "PACS图像加载失败", "LIS检验数据不同步",
    "护士工作站软件无响应", "医保结算系统报错", "排队叫号系统显示异常",
    "卫宁系统弹窗数据类型报错", "血糖尿糖系统无法登录", "医嘱内容被自动修改",
    "保存处方闪退", "电子票据打印报错", "预约单无法打印",
    "物资管理系统无法安装", "绩效考核系统安装报错", "医生工作站找不到路径",
    "Office Word打不开文档", "浏览器网页无法访问"
]

HARDWARE_DESC = [
    "电脑无法开机", "电脑开不了机", "电脑死机蓝屏", "电脑卡顿严重",
    "鼠标失灵", "键盘按键不灵", "电脑断网", "电脑打不开",
    "内存条报错", "硬盘读写报错", "USB接口无反应", "电脑散热风扇异常",
    "电脑引导丢失", "电脑开机嘀嘀嘀报警", "CPU风扇噪音大",
    "电脑花屏", "机箱开关脱落", "电脑频繁重启", "电脑通电但黑屏",
    "扫码墩无法扫码", "读卡器刷卡没反应", "显示器黑屏无显示"
]

PRINTER_DESC = [
    "打印机卡纸", "打印字迹模糊", "缺墨碳粉", "打印机脱机",
    "打印乱码", "打印任务卡住", "标签打印机走纸偏移", "条码打印机无法识别",
    "共享打印机连接失败", "打印报告缺失内容", "打印机异响", "打印机无法吸纸",
    "打印有黑边横线", "定影膜损坏", "硒鼓漏粉", "打印机报错代码",
    "打印速度慢", "打印机一直打白纸", "喷墨打印机堵头", "打印内容不全"
]

ASSIST_DESC = [
    "电脑搬迁", "科室移位电脑重连", "资产回收处理一批旧设备",
    "新增设备到货需要安装", "发放新电脑给新员工",
    "开机房门锁坏了进不去", "更换办公位置重新布线",
    "清理系统盘空间", "连接外设扫码墩读卡器", "调试叫号系统",
    "安装远程控制软件", "设置共享文件夹", "更换内存硬盘",
    "指导使用OA系统", "会议技术支持", "数据备份恢复",
]

# 按故障类型的处理时长分布（分钟）
DURATION_RANGES = {
    '软件': [(3, 15, 20), (15, 40, 60), (40, 90, 20)],     # (min, max, weight%)
    '硬件': [(3, 10, 15), (10, 30, 55), (30, 60, 30)],
    '打印机': [(5, 15, 20), (15, 35, 55), (35, 90, 25)],
    '协助': [(15, 30, 25), (30, 60, 50), (60, 120, 25)],
}

# 优先级分布权重（normal/urgent/emergency）
PRIORITY_WEIGHTS = [('normal', 75), ('urgent', 18), ('emergency', 7)]


def _pick_duration(fault_type):
    """按故障类型随机生成处理时长"""
    ranges = DURATION_RANGES.get(fault_type, DURATION_RANGES['硬件'])
    weights = [w for _, _, w in ranges]
    chosen = random.choices(ranges, weights=weights, k=1)[0]
    return random.randint(chosen[0], chosen[1])


def _pick_priority():
    """随机生成紧急程度"""
    priorities = [p for p, _ in PRIORITY_WEIGHTS]
    weights = [w for _, w in PRIORITY_WEIGHTS]
    return random.choices(priorities, weights=weights, k=1)[0]


def _random_start_time(day_date):
    """生成随机开始时间，含自然分布：上午多、午休少、下午多"""
    base = random.random()
    if base < 0.45:
        # 上午高峰 7:00-11:30
        hour = random.uniform(7, 11.5)
    elif base < 0.55:
        # 午休 11:30-13:30（工单稀疏）
        hour = random.uniform(11.5, 13.5)
    else:
        # 下午 13:30-18:00
        hour = random.uniform(13.5, 18.0)
    
    minutes = int(hour * 60)
    return day_date.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)


def _has_lunch_gap(start, end):
    """检查时间段是否跨午休"""
    lunch_start = 11.5 * 60  # 11:30
    lunch_end = 13.5 * 60    # 13:30
    s_min = start.hour * 60 + start.minute
    e_min = end.hour * 60 + end.minute
    return s_min < lunch_end and e_min > lunch_start


def generate_time_person_pairs(total, year, month, min_per_day, max_per_day,
                                everyday, names, specific_dates=None,
                                weights=None, use_schedule=False):
    """生成时间-人员配对（更逼真的时间分布）
    
    如果 specific_dates 不为空，只在这些日期生成；
    否则沿用原有的 everyday/auto 逻辑。
    weights: dict {人员名: 权重}，默认每人权重=1
    use_schedule: 根据排班表分配人员，只给当班人生成
    """
    if weights is None:
        weights = {}
    _, days_in_month = calendar.monthrange(year, month)
    
    # ===== 确定哪些天有工单 =====
    if specific_dates:
        days = sorted(set(d for d in specific_dates if 1 <= d <= days_in_month))
        if not days:
            raise ValueError("指定的日期无效，请选择1-{}之间的日期".format(days_in_month))
        per_day = max(min_per_day, min(max_per_day, (total + len(days) - 1) // len(days)))
        daily_counts = {d: per_day for d in days}
        allocated = sum(daily_counts.values())
        if allocated < total:
            extra = total - allocated
            for d in reversed(days):
                if extra <= 0:
                    break
                add = min(extra, max_per_day - daily_counts[d])
                daily_counts[d] += add
                extra -= add
        elif allocated > total:
            over = allocated - total
            for d in reversed(days):
                if over <= 0:
                    break
                sub = min(over, daily_counts[d] - min_per_day)
                daily_counts[d] -= sub
                over -= sub
    elif everyday:
        if total < min_per_day * days_in_month:
            raise ValueError(f"总数过小：至少需要 {min_per_day * days_in_month} 条工单才能填满每天 {min_per_day} 单")
        if total > max_per_day * days_in_month:
            raise ValueError(f"总数过大：最多只能 {max_per_day * days_in_month} 条（每天 {max_per_day} 单）")
        days = list(range(1, days_in_month + 1))
        base = [min_per_day] * days_in_month
        remaining = total - min_per_day * days_in_month
        max_inc = max_per_day - min_per_day
        inc = [0] * days_in_month
        for _ in range(remaining):
            while True:
                idx = random.randrange(days_in_month)
                if inc[idx] < max_inc:
                    inc[idx] += 1
                    break
        daily_counts = {d: base[i] + inc[i] for i, d in enumerate(days)}
    else:
        min_days = (total + max_per_day - 1) // max_per_day
        max_days = min(total // min_per_day, days_in_month)
        if min_days > max_days:
            raise ValueError("无法在指定天数内生成，请调整每天单数范围或总数")
        day_count = random.randint(min_days, max_days)
        days = sorted(random.sample(range(1, days_in_month + 1), day_count))
        base = [min_per_day] * day_count
        remaining = total - min_per_day * day_count
        max_inc = max_per_day - min_per_day
        inc = [0] * day_count
        for _ in range(remaining):
            while True:
                idx = random.randrange(day_count)
                if inc[idx] < max_inc:
                    inc[idx] += 1
                    break
        daily_counts = {d: base[i] + inc[i] for i, d in enumerate(days)}
    
    # ===== 为每个有工单的日期生成时间-人员配对 =====
    start_date = datetime(year, month, 1)
    all_pairs = []
    
    for day_num in sorted(daily_counts.keys()):
        current_date = start_date + timedelta(days=day_num - 1)
        if current_date.month != month:
            continue
        
        weekday = current_date.weekday()
        cnt = daily_counts[day_num]
        
        if use_schedule:
            # ===== 按排班表分配 =====
            from models import DutySchedule, db
            schedules = DutySchedule.query.filter(
                DutySchedule.duty_date == current_date.date(),
                DutySchedule.hospital_id == 1,  # 当前医院ID
            ).all()
            # 过滤出有效班次（排除病假/事假/年假/×）
            valid_shifts = {'白班', '日班', '夜班', '24H'}
            on_duty = [s for s in schedules if s.shift in valid_shifts]
            if not on_duty:
                # 当天没人排班，跳过
                continue
            
            # 按班次分组
            day_workers = [s.person_name for s in on_duty if s.shift in ('白班', '日班', '24H')]
            night_workers = [s.person_name for s in on_duty if s.shift in ('夜班', '24H')]
            
            # 每个工单随机分配一个当班人员
            pool = day_workers if day_workers else night_workers
            person_orders = {p: [] for p in pool}
            pool_weights_s = [weights.get(p, 1) for p in pool]
            for i in range(cnt):
                person = random.choices(pool, weights=pool_weights_s, k=1)[0]
                person_orders[person].append(i)
            
            for person, indices in person_orders.items():
                if not indices:
                    continue
                
                # 判断该人员今天的班次
                person_sched = [s for s in on_duty if s.person_name == person]
                if person_sched:
                    shift_type = person_sched[0].shift
                else:
                    shift_type = '24H'
                
                # 按班次确定时间范围
                if shift_type in ('白班', '日班'):
                    day_start_hour = 8
                    day_end_hour = 17
                elif shift_type == '夜班':
                    day_start_hour = 19
                    day_end_hour = 23  # 夜班到第二天7点，但时间限制到23:00前生成
                else:  # 24H
                    day_start_hour = 7
                    day_end_hour = 18
                
                current_start = current_date.replace(hour=day_start_hour, minute=random.randint(0, 59))
                day_end = current_date.replace(hour=day_end_hour, minute=0)
                
                for _ in indices:
                    duration_min = _pick_duration('硬件')
                    current_end = current_start + timedelta(minutes=duration_min)
                    
                    if current_end > day_end:
                        current_end = day_end
                    
                    if current_start >= day_end:
                        break
                    
                    all_pairs.append({
                        'start': current_start,
                        'end': current_end,
                        'person': person,
                    })
                    
                    gap = random.randint(0, 40)
                    current_start = current_end + timedelta(minutes=gap)
        else:
            # ===== 原逻辑：按星期确定人员池 =====
            if weekday < 5:
                pool = random.sample(names, min(max(2, len(names)), len(names)))
            else:
                pool = [random.choice(names)]
                if len(names) >= 2 and random.random() < 0.3:
                    pool.append(random.choice([n for n in names if n != pool[0]]))
            
            person_orders = {p: [] for p in pool}
            pool_weights = [weights.get(p, 1) for p in pool]
            for i in range(cnt):
                person = random.choices(pool, weights=pool_weights, k=1)[0]
                person_orders[person].append(i)
            
            for person, indices in person_orders.items():
                if not indices:
                    continue
                current_start = _random_start_time(current_date)
                day_end = current_date.replace(hour=18, minute=0)
                
                for _ in indices:
                    duration_min = _pick_duration('硬件')
                    current_end = current_start + timedelta(minutes=duration_min)
                    
                    if _has_lunch_gap(current_start, current_end):
                        lunch_end = current_date.replace(hour=13, minute=30)
                        if current_end < lunch_end:
                            current_end = lunch_end + timedelta(minutes=random.randint(0, 15))
                    
                    if current_end > day_end:
                        current_end = day_end
                    
                    if current_start >= day_end:
                        break
                    
                    all_pairs.append({
                        'start': current_start,
                        'end': current_end,
                        'person': person,
                    })
                    
                    gap = random.randint(0, 40)
                    current_min = current_end.hour * 60 + current_end.minute
                    if 690 <= current_min <= 750:
                        gap += random.randint(20, 50)
                    current_start = current_end + timedelta(minutes=gap)
    
    all_pairs.sort(key=lambda x: x['start'])
    
    if len(all_pairs) > total:
        all_pairs = all_pairs[:total]
    elif len(all_pairs) < total and all_pairs:
        diff = total - len(all_pairs)
        last_date = all_pairs[-1]['start']
        for _ in range(diff):
            cp = random.choice(all_pairs)
            all_pairs.append({
                'start': cp['start'] + timedelta(minutes=random.randint(5, 60)),
                'end': cp['end'] + timedelta(minutes=random.randint(5, 60)),
                'person': cp['person'],
            })
        all_pairs.sort(key=lambda x: x['start'])
    
    return [(p['start'], p['end'], p['person']) for p in all_pairs]


def create_batch_orders(fault_counts, fault_details,
                        year, month, min_per_day, max_per_day, everyday, names,
                        created_by='系统', specific_dates=None,
                        custom_title=None, custom_solution=None,
                        weights=None, use_schedule=False):
    """批量生成工单（支持动态故障类型）"""
    desc_pools = {
        '软件': SOFTWARE_DESC,
        '硬件': HARDWARE_DESC,
        '打印机': PRINTER_DESC,
        '协助': ASSIST_DESC,
    }
    descriptions = []
    for item_id, count in fault_counts.items():
        info = fault_details.get(item_id, {})
        ft = info.get('fault_type', '硬件')
        display = info.get('display_name', ft)
        pool = desc_pools.get(ft, HARDWARE_DESC)
        for _ in range(count):
            desc = random.choice(pool)
            descriptions.append({
                'title': display,
                'fault_type': ft,
                'device_type': {'软件': '软件', '硬件': '电脑', '打印机': '打印机', '协助': '其他'}.get(ft, '其他'),
                'desc': desc
            })

    random.shuffle(descriptions)
    total = len(descriptions)

    time_pairs = generate_time_person_pairs(
        total, year, month, min_per_day, max_per_day, everyday, names,
        specific_dates=specific_dates, weights=weights, use_schedule=use_schedule
    )

    from services.fault_matcher import match_fault
    from models import SolutionTemplate  # 从数据管理方案模板匹配

    def _match_solution_from_db(title, fault_type):
        """从 SolutionTemplate 匹配方案，优先级：精确标题 > 关键词 > 故障类型+二级 > 设备类型 > fallback"""
        # 1. 精确标题匹配
        st = SolutionTemplate.query.filter_by(title=title).first()
        if st and st.content:
            return st.content
        # 2. 关键词匹配（keywords 逗号分隔，任意关键词出现在标题中）
        for st in SolutionTemplate.query.all():
            if not st.content:
                continue
            if st.keywords:
                for kw in st.keywords.split(','):
                    kw = kw.strip()
                    if kw and kw.lower() in title.lower():
                        return st.content
        # 3. 故障类型 + 二级匹配
        for st in SolutionTemplate.query.filter_by(fault_type=fault_type).all():
            if st.content and st.fault_subcategory:
                for sub_kw in st.fault_subcategory.split(','):
                    sub_kw = sub_kw.strip()
                    if sub_kw and sub_kw.lower() in title.lower():
                        return st.content
        # 4. 设备类型匹配
        for st in SolutionTemplate.query.filter_by(device_type=fault_type).all():
            if st.content:
                return st.content
        return None

    orders = []
    import random as rnd_mod
    addr_copy = list(ADDRESS_LIST)
    rnd_mod.shuffle(addr_copy)
    
    for idx, (ticket, (start, end, person)) in enumerate(zip(descriptions, time_pairs)):
        addr = addr_copy[idx % len(addr_copy)]
        sol = custom_solution  # 优先使用自定义结单方案
        if not sol:
            sol = _match_solution_from_db(ticket['title'], ticket['fault_type'])
        if not sol:
            sol = matcher.get_solution_by_title(ticket['title'])
        if not sol:
            sol = matcher.generate_fallback_solution(ticket['title'], ticket['fault_type'])
        fm = match_fault(ticket['title'])
        
        # 按实际故障类型计算处理时长（仅用于记录，不覆盖结束时间避免重叠）
        actual_ft = fm['category'] if fm['match_type'] == 'keyword' else ticket['fault_type']
        
        priority = _pick_priority()

        # 自定义工单名称：使用前缀+随机序号或直接使用自定义名称
        order_title = ticket['title']
        if custom_title:
            order_title = custom_title

        orders.append({
            'title': order_title,
            'device_type': ticket['device_type'],
            'fault_type': actual_ft,
            'fault_subcategory': fm.get('subcategory', ''),
            'description': ticket['desc'],
            'building': addr['楼区'],
            'floor': addr['所属楼层'],
            'department': addr['所属科室'],
            'location': addr['物理地址'],
            'start_time': start,
            'end_time': end,
            'person': person,
            'solution': sol,
            'created_by': created_by,
            'priority': priority,
            'original_priority': priority,
        })
    return orders
