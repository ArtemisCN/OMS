#!/usr/bin/env python3
"""Take screenshots of all key pages using Chromium snap + CDP"""
import subprocess, time, os, sys, json, base64, signal

SNAPSHOT_DIR = '/home/ubuntu/hospital-workorder/static/demo/screenshots'
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
BASE = 'http://127.0.0.1:5000'

def screenshot(url, name, wait=2):
    """Open URL in chromium snap, wait, take screenshot"""
    path = os.path.join(SNAPSHOT_DIR, name)
    subprocess.run([
        '/snap/bin/chromium',
        '--headless',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        f'--screenshot={path}',
        f'--window-size=1440,900',
        url
    ], capture_output=True, timeout=30)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    print(f'  [{size:>6}B] {name}  <- {url}')
    time.sleep(0.5)

def screenshot_auth(url, name, cookie_file, wait=3):
    """Load page with cookies for authenticated screenshots"""
    path = os.path.join(SNAPSHOT_DIR, name)
    # chromium snap doesn't accept --user-data-dir with --headless easily
    # Use cookie injection via URL and CDP approach through file
    # Fallback: use the approach of GET with cookies from temp file
    cmd = [
        '/snap/bin/chromium',
        '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
        f'--screenshot={path}',
        f'--window-size=1440,900',
        url
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    print(f'  [{size:>6}B] {name}  <- {url}')
    time.sleep(0.5)

# ── Login first via curl to get cookies ──
print("[1/3] Logging in...")
r = subprocess.run([
    'curl', '-s', '-L', '-c', '/tmp/snap_cookies.txt',
    '-X', 'POST', f'{BASE}/login',
    '-d', 'username=admin&password=admin123'
], capture_output=True, text=True, timeout=10)
print(f'  Login: {r.return_code}')

# ── Take screenshots ──
print("[2/3] Taking screenshots...\n")

# Login page
screenshot(f'{BASE}/login', '01-login.png')

# Dashboard (authenticated via cookie)
screenshot_auth(f'{BASE}/', '02-dashboard.png', '/tmp/snap_cookies.txt')

# Order list
screenshot_auth(f'{BASE}/orders', '03-order-list.png', '/tmp/snap_cookies.txt')

# Publish order form
screenshot_auth(f'{BASE}/orders/publish', '04-publish-form.png', '/tmp/snap_cookies.txt')

# Order detail (find an existing order)
screenshot_auth(f'{BASE}/orders/1', '05-order-detail.png', '/tmp/snap_cookies.txt')

# Mobile web
screenshot_auth(f'{BASE}/mobile/', '06-mobile-list.png', '/tmp/snap_cookies.txt')

# Mobile order detail
screenshot_auth(f'{BASE}/mobile/order/1', '07-mobile-detail.png', '/tmp/snap_cookies.txt')

# Data management
screenshot_auth(f'{BASE}/data', '08-data-manage.png', '/tmp/snap_cookies.txt')

# Persons
screenshot_auth(f'{BASE}/data/persons', '09-persons.png', '/tmp/snap_cookies.txt')

# Solution templates
screenshot_auth(f'{BASE}/data/solutions', '10-solutions.png', '/tmp/snap_cookies.txt')

# Asset calendar
screenshot_auth(f'{BASE}/asset', '11-asset-calendar.png', '/tmp/snap_cookies.txt')

# Asset list
screenshot_auth(f'{BASE}/asset/list', '12-asset-list.png', '/tmp/snap_cookies.txt')

# Stock
screenshot_auth(f'{BASE}/stock', '13-stock.png', '/tmp/snap_cookies.txt')

# Inspection templates
screenshot_auth(f'{BASE}/inspection/templates', '14-inspection.png', '/tmp/snap_cookies.txt')

# Inspection plans
screenshot_auth(f'{BASE}/inspection/plans', '15-inspection-plans.png', '/tmp/snap_cookies.txt')

# Knowledge base
screenshot_auth(f'{BASE}/data/knowledge', '16-knowledge.png', '/tmp/snap_cookies.txt')

# Duty schedules
screenshot_auth(f'{BASE}/data/duty-schedules', '17-duty.png', '/tmp/snap_cookies.txt')

# Report
screenshot_auth(f'{BASE}/report', '18-report.png', '/tmp/snap_cookies.txt')

# Audit logs
screenshot_auth(f'{BASE}/audit/logs', '19-audit.png', '/tmp/snap_cookies.txt')

# Permissions
screenshot_auth(f'{BASE}/data/permissions', '20-permissions.png', '/tmp/snap_cookies.txt')

# Electronic forms
screenshot_auth(f'{BASE}/forms', '21-forms.png', '/tmp/snap_cookies.txt')

# Form templates
screenshot_auth(f'{BASE}/forms/templates', '22-form-templates.png', '/tmp/snap_cookies.txt')

print("\n[3/3] Done! Listing all screenshots:")
for f in sorted(os.listdir(SNAPSHOT_DIR)):
    sz = os.path.getsize(os.path.join(SNAPSHOT_DIR, f))
    print(f'  {f:30s} {sz/1024:>6.0f}KB')
