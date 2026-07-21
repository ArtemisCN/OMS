"""
系统健康监控脚本 - 每天运行一次，检测各类潜在故障
"""
import sys, os, json, smtplib, subprocess
sys.path.insert(0, '/var/www/hospital-workorder')
os.chdir('/var/www/hospital-workorder')

from datetime import datetime, timedelta

LOG_FILE = '/var/log/hospital-health.log'
WARNINGS = []

def log(msg):
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{t}] {msg}'
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def check_disk():
    """磁盘空间<10%报警"""
    st = os.statvfs('/')
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bfree
    pct = free / total * 100
    if pct < 10:
        msg = f'⚠️ 磁盘空间不足: 仅剩 {pct:.1f}%'
        WARNINGS.append(msg)
        log(f'[WARN] {msg}')
    else:
        log(f'[OK] 磁盘剩余 {pct:.1f}%')

def check_cert():
    """SSL证书到期检测"""
    try:
        result = subprocess.run(
            ['sudo', 'openssl', 'x509', '-enddate', '-noout',
             '-in', '/etc/letsencrypt/live/demolin.cn/fullchain.pem'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and 'notAfter=' in result.stdout:
            date_str = result.stdout.split('notAfter=')[1].strip()
            exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
            days_left = (exp_date - datetime.now()).days
            if days_left < 30:
                msg = f'⚠️ SSL证书将在 {days_left} 天后到期 ({date_str})'
                WARNINGS.append(msg)
                log(f'[WARN] {msg}')
            else:
                log(f'[OK] SSL证书有效，剩余 {days_left} 天')
        else:
            log(f'[WARN] 无法解析证书信息: {result.stdout}')
    except Exception as e:
        log(f'[WARN] 证书检测失败: {e}')

def check_mysql():
    """检测MySQL是否可达"""
    try:
        from wsgi import app
        from models import db
        with app.app_context():
            db.session.execute(db.text('SELECT 1'))
            log('[OK] MySQL 连接正常')
    except Exception as e:
        msg = f'⚠️ MySQL 连接异常: {e}'
        WARNINGS.append(msg)
        log(f'[WARN] {msg}')

def check_gunicorn():
    """检测Gunicorn是否在运行"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'gunicorn'],
            capture_output=True, text=True, timeout=5
        )
        count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
        if count >= 3:
            log(f'[OK] Gunicorn 运行中 ({count} 进程)')
        else:
            msg = f'⚠️ Gunicorn 进程数异常 ({count})'
            WARNINGS.append(msg)
            log(f'[WARN] {msg}')
    except Exception as e:
        log(f'[WARN] Gunicorn 检测失败: {e}')

def check_nginx():
    """检测Nginx是否在运行"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'nginx: master'],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            log('[OK] Nginx 运行中')
        else:
            msg = '⚠️ Nginx 未运行'
            WARNINGS.append(msg)
            log(f'[WARN] {msg}')
    except Exception as e:
        log(f'[WARN] Nginx 检测失败: {e}')

if __name__ == '__main__':
    log('=== 系统健康检查开始 ===')
    check_disk()
    check_cert()
    check_mysql()
    check_gunicorn()
    check_nginx()
    log('=== 系统健康检查结束 ===')

    if WARNINGS:
        # 写入警告文件供cron或其他通知机制读取
        with open('/var/log/hospital-health.warnings', 'w') as f:
            f.write('\n'.join(WARNINGS))
        print(f'\n⚠️ 发现 {len(WARNINGS)} 个问题需要关注!')
    else:
        # 清除警告文件（sudo忽略不存在）
        subprocess.run(['sudo', 'rm', '-f', '/var/log/hospital-health.warnings'], capture_output=True)
        print('\n✅ 全部正常')
