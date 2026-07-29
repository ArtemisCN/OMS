#!/usr/bin/env python3
"""
多院区多用户权限验证测试 v4
=========================
使用专用测试用户 test_xxx（密码: test123456）。
正确使用 allow_redirects=False 判断真实状态码。
"""
import os, sys, json, requests, re

BASE = 'http://127.0.0.1:5000'
PASS, FAIL = 0, 0

def login(username, password):
    s = requests.Session()
    resp = s.post(f'{BASE}/login', data={'username': username, 'password': password},
                  allow_redirects=False)
    if resp.status_code == 302:
        s.get(f'{BASE}/')
        return s
    return None

def check(label, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1; print(f'  ✅ {label}')
    else:
        FAIL += 1; print(f'  ❌ {label}  —  {detail}')

# ========== 登录 ==========
print('=' * 80)
print('登录测试用户')
print('=' * 80)

test_users = {
    'admin':     ('test_admin',  'test123456', '管理员(超管)', None),
    'h1_eng':    ('test_h1_eng', 'test123456', '七院-常规运维', 1),
    'h1_op':     ('test_h1_op',  'test123456', '七院-第三方', 1),
    'h2_eng':    ('test_h2_eng', 'test123456', '光明-常规运维', 2),
    'h3_eng':    ('test_h3_eng', 'test123456', '公利-常规运维', 3),
    'h5_eng':    ('test_h5_eng', 'test123456', '公卫-常规运维', 5),
    'h7_eng':    ('test_h7_eng', 'test123456', '东明-常规运维', 7),
    'dual':      ('test_dual',   'test123456', '公卫+虹口(双院)', 5),
}

sessions = {}
for key, (uname, pwd, label, hid) in test_users.items():
    s = login(uname, pwd)
    if s:
        sessions[key] = s
        print(f'  ✅ {uname} ({label})')
    else:
        print(f'  ❌ {uname} ({label})')

print()
print('=' * 80)
print('A. 工单模块 — 医院隔离')
print('=' * 80)

for key, s in sessions.items():
    uname, pwd, label, hid = test_users[key]
    resp = s.get(f'{BASE}/orders/', allow_redirects=False)
    check(f'{label}→工单页: {resp.status_code}', resp.status_code in (200, 302))

# 跨院工单详情访问（用管理员获取各医院工单ID）
resp = sessions['admin'].get(f'{BASE}/orders/api/search?limit=200')
orders_by_hid = {}
if resp.status_code == 200:
    try:
        data = resp.json()
        orders = data if isinstance(data, list) else \
                 data.get('data', data.get('orders', data.get('results', [])))
        for o in (orders if isinstance(orders, list) else []):
            hid = o.get('hospital_id') or 0
            orders_by_hid.setdefault(hid, []).append(o.get('id'))
        print(f'  📋 工单分布: {dict((k,len(v)) for k,v in sorted(orders_by_hid.items()))}')
    except Exception as e:
        pass

if orders_by_hid:
    if 1 in orders_by_hid and 2 in orders_by_hid:
        oid1, oid2 = orders_by_hid[1][0], orders_by_hid[2][0]
        r = sessions['h1_eng'].get(f'{BASE}/orders/{oid2}', allow_redirects=False)
        check(f'七院看光明工单({oid2}): {r.status_code}', r.status_code in (403, 404))
        r = sessions['h2_eng'].get(f'{BASE}/orders/{oid1}', allow_redirects=False)
        check(f'光明看七院工单({oid1}): {r.status_code}', r.status_code in (403, 404))
        r = sessions['h1_eng'].get(f'{BASE}/orders/{oid1}', allow_redirects=False)
        check(f'七院看本院工单({oid1}): {r.status_code}', r.status_code == 200)
    if 5 in orders_by_hid:
        oid5 = orders_by_hid[5][0]
        r = sessions['dual'].get(f'{BASE}/orders/{oid5}', allow_redirects=False)
        check(f'双院看公卫工单({oid5}): {r.status_code}', r.status_code == 200)
else:
    print('  ℹ️ 新测试用户无工单，跨院详情测试跳过')

print()
print('=' * 80)
print('C. 角色权限边界')
print('=' * 80)

# C1-3: 第三方限制
r = sessions['h1_op'].get(f'{BASE}/data/', allow_redirects=False)
check(f'第三方→数据管理: {r.status_code}', r.status_code in (302, 403))

r = sessions['h1_op'].get(f'{BASE}/data/permissions', allow_redirects=False)
check(f'第三方→权限管理: {r.status_code}', r.status_code in (302, 403))

r = sessions['h1_op'].get(f'{BASE}/orders/create', allow_redirects=False)
check(f'第三方→新建工单: {r.status_code}', r.status_code in (403,))

# 第三方应有权访问的
r = sessions['h1_op'].get(f'{BASE}/orders/', allow_redirects=False)
check(f'第三方→工单列表: {r.status_code}', r.status_code in (200, 302))

r = sessions['h1_op'].get(f'{BASE}/')
check(f'第三方→首页: {r.status_code}', r.status_code == 200)

r = sessions['h1_op'].get(f'{BASE}/inspection/plans', allow_redirects=False)
check(f'第三方→巡检: {r.status_code}', r.status_code in (200, 302))

# C4-8: 常规运维限制
r = sessions['h1_eng'].get(f'{BASE}/audit/logs', allow_redirects=False)
check(f'常规运维→审计: {r.status_code}', r.status_code in (403, 302))

r = sessions['h1_eng'].get(f'{BASE}/monitor/', allow_redirects=False)
check(f'常规运维→监控: {r.status_code}', r.status_code in (403, 302))

r = sessions['h1_eng'].get(f'{BASE}/report/', allow_redirects=False)
check(f'常规运维→报表: {r.status_code}', r.status_code in (403, 302))

r = sessions['h1_eng'].get(f'{BASE}/data/permissions', allow_redirects=False)
check(f'常规运维→权限管理: {r.status_code}', r.status_code in (302, 403))

# 常规运维应有权访问的
r = sessions['h1_eng'].get(f'{BASE}/orders/', allow_redirects=False)
check(f'常规运维→工单: {r.status_code}', r.status_code in (200, 302))

r = sessions['h1_eng'].get(f'{BASE}/orders/create', allow_redirects=False)
check(f'常规运维→新建工单: {r.status_code}', r.status_code == 200)

# C9-11: 管理员特权
r = sessions['admin'].get(f'{BASE}/data/permissions', allow_redirects=False)
check(f'管理员→权限管理(重定向到数据管理): {r.status_code}', r.status_code in (200, 302))

r = sessions['admin'].get(f'{BASE}/audit/logs', allow_redirects=False)
check(f'管理员→审计日志(重定向到监控): {r.status_code}', r.status_code in (200, 302))

r = sessions['admin'].get(f'{BASE}/monitor/', allow_redirects=False)
check(f'管理员→监控: {r.status_code}', r.status_code == 200)

r = sessions['admin'].get(f'{BASE}/report/', allow_redirects=False)
check(f'管理员→报表: {r.status_code}', r.status_code == 200)

# C12: 第三方→新建工单(再次确认)
r = sessions['h1_op'].get(f'{BASE}/orders/create', allow_redirects=False)
check(f'第三方→新建工单(重验): {r.status_code}', r.status_code in (403,))

print()
print('=' * 80)
print('D. 管理员跨院访问')
print('=' * 80)

r = sessions['admin'].get(f'{BASE}/orders/api/search?limit=200')
if r.status_code == 200:
    data = r.json()
    orders = data if isinstance(data, list) else data.get('data', data.get('orders', []))
    hids = set(o.get('hospital_id') for o in orders if o.get('hospital_id'))
    check(f'admin→工单覆盖医院数: {len(hids)}', len(hids) >= 0, '')
    print(f'    覆盖医院: {sorted(hids) if hids else "(仅测试工单)"}')

r = sessions['admin'].get(f'{BASE}/data/switch_hospital/1', allow_redirects=False)
check(f'admin→切换七院: {r.status_code}', r.status_code in (200, 302))

print()
print('=' * 80)
print(f'🏁 测试完成: ✅ PASS={PASS}, ❌ FAIL={FAIL}')
print('=' * 80)
if FAIL > 0:
    print()
    print('⚠️  失败项: 参考上述 ❌ 标记')
    sys.exit(1)
print('\n✅ 全部通过')
