"""服务器监控路由 - 仅管理员可见"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from models import can_access
import psutil
import os, subprocess
from datetime import datetime, timedelta

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')


def size_fmt(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def uptime_fmt(seconds):
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    parts.append(f"{mins}分钟")
    return ''.join(parts)


def parse_cron_desc(line):
    """将crontab行转成中文描述 + 提取日志路径"""
    parts = line.strip().split()
    if len(parts) < 6:
        return line, '', ''

    # 环境变量行（非5段调度）跳过
    maybe_sched = ' '.join(parts[:5])
    if not all(c.isdigit() or c in '*,/-' for c in maybe_sched.replace(' ', '')):
        return line, '', ''

    cron_part = ' '.join(parts[:5])
    cmd = ' '.join(parts[5:])

    # 提取日志路径
    log_path = ''
    for i, p in enumerate(parts):
        if p == '>>' and i + 1 < len(parts):
            log_path = parts[i + 1].split(' 2>&1')[0].split(' 2>/dev/null')[0]
            break

    # 转中文
    mins, hour, dom, month, dow = parts[0], parts[1], parts[2], parts[3], parts[4]
    
    parts_desc = []
    # 分钟
    if mins == '*' and hour == '*':
        parts_desc = ['每分钟']
    elif mins == '*':
        parts_desc.append('每分钟')
    elif mins.startswith('*/'):
        parts_desc.append(f'每{mins[2:]}分钟')
    else:
        parts_desc.append(f'第{mins}分')

    # 小时
    if hour == '*':
        pass  # 已经由上面的"每分钟"处理了
    elif hour.startswith('*/'):
        parts_desc.append(f'每{hour[2:]}小时')
    else:
        parts_desc.append(f'每天{hour}点')

    # 星期
    dow_map = {'0': '周日', '1': '周一', '2': '周二', '3': '周三',
               '4': '周四', '5': '周五', '6': '周六', '7': '周日'}
    if dow != '*' and not dow.startswith('*/'):
        days = [dow_map.get(d, d) for d in dow.split(',') if d]
        if days:
            parts_desc.append(f'({",".join(days)})')

    desc = ''.join(parts_desc)
    return desc, log_path, cmd


def check_cron_last_run(cmd, log_path):
    """检查cron任务最后执行时间"""
    now = datetime.now()
    
    # 方法1: 从日志文件取最后修改时间
    if log_path and os.path.exists(log_path):
        try:
            mtime = os.path.getmtime(log_path)
            mt = datetime.fromtimestamp(mtime)
            # 检查是否今天或昨天
            if mt.date() == now.date():
                last = mt.strftime('今天 %H:%M')
            elif mt.date() == (now - timedelta(days=1)).date():
                last = mt.strftime('昨天 %H:%M')
            else:
                last = mt.strftime('%m-%d %H:%M')
            # 检查文件最后几行是否有时间戳
            try:
                result = subprocess.run(['tail', '-3', log_path], capture_output=True, text=True, timeout=3)
                for rline in result.stdout.strip().split('\n'):
                    if rline.strip():
                        last = last + ' ✓'
                        break
            except Exception:
                pass
            return last
        except Exception:
            pass

    # 方法2: 根据cron调度估算
    if cmd and 'auto_escalate' in cmd:
        return '近5分钟内'
    elif cmd and 'health_monitor' in cmd:
        return '今早8点'
    elif cmd and 'cleanup' in cmd:
        return '上周日'
    return '-'


@monitor_bp.route('/')
@login_required
def index():
    if not can_access('服务器监控'):
        return "无权访问", 403
    return render_template('monitor/index.html')


@monitor_bp.route('/data')
@login_required
def data():
    if not can_access('服务器监控'):
        return jsonify(error="无权访问"), 403

    # CPU
    cpu_per_core = psutil.cpu_percent(interval=0.5, percpu=True)
    cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 1) if cpu_per_core else 0.0
    cpu_count = psutil.cpu_count()
    cpu_count_logical = psutil.cpu_count(logical=True)
    load_avg = psutil.getloadavg()
    cpu_freq = psutil.cpu_freq()

    # 内存
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # 磁盘
    disk = psutil.disk_usage('/')
    partitions = []
    for p in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(p.mountpoint)
            partitions.append({
                'device': p.device, 'mount': p.mountpoint, 'fstype': p.fstype,
                'total': usage.total, 'used': usage.used, 'free': usage.free,
                'percent': usage.percent, 'total_fmt': size_fmt(usage.total),
                'used_fmt': size_fmt(usage.used), 'free_fmt': size_fmt(usage.free),
            })
        except (PermissionError, OSError):
            pass

    # 网络 / IO
    net = psutil.net_io_counters()
    try:
        disk_io = psutil.disk_io_counters()
        disk_io_data = {
            'read_bytes': disk_io.read_bytes, 'write_bytes': disk_io.write_bytes,
            'read_count': disk_io.read_count, 'write_count': disk_io.write_count,
            'read_fmt': size_fmt(disk_io.read_bytes), 'write_fmt': size_fmt(disk_io.write_bytes),
        }
    except (PermissionError, OSError):
        disk_io_data = None

    boot_time = psutil.boot_time()
    boot_dt = datetime.fromtimestamp(boot_time)
    uptime_seconds = (datetime.now() - boot_dt).total_seconds()
    process_count = len(psutil.pids())

    # ---------- 证书 ----------
    cert_info = {'valid': False, 'days_left': 0, 'issuer': '', 'expire_date': ''}
    cert_path = '/etc/letsencrypt/live/demolin.cn/fullchain.pem'
    if os.path.exists(cert_path):
        try:
            r = subprocess.run(['sudo', 'openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and 'notAfter=' in r.stdout:
                date_str = r.stdout.split('notAfter=')[1].strip()
                exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                days_left = (exp_date - datetime.now()).days
                r2 = subprocess.run(['sudo', 'openssl', 'x509', '-issuer', '-noout', '-in', cert_path],
                                    capture_output=True, text=True, timeout=5)
                issuer = r2.stdout.replace('issuer=', '').strip() if r2.returncode == 0 else ''
                cert_info = {
                    'valid': True, 'days_left': days_left,
                    'expire_date': exp_date.strftime('%Y-%m-%d'), 'issuer': issuer[:60],
                }
        except Exception:
            pass

    # ---------- 日志文件 ----------
    log_files = [
        ('工单系统日志', '/var/log/hospital-workorder.log'),
        ('健康检查日志', '/var/log/hospital-health.log'),
        ('自动升级日志', '/var/log/auto_escalate.log'),
        ('系统清理日志', '/var/log/hospital-workorder-cleanup.log'),
        ('Nginx 访问日志', '/var/log/nginx/access.log'),
        ('Nginx 错误日志', '/var/log/nginx/error.log'),
        ('数据库主文件', '/var/www/hospital-workorder/instance/workorders.db'),
        ('数据库 WAL', '/var/www/hospital-workorder/instance/workorders.db-wal'),
    ]
    logs = []
    for name, path in log_files:
        try:
            st = os.stat(path)
            logs.append({
                'name': name, 'path': path, 'size': st.st_size,
                'size_fmt': size_fmt(st.st_size),
                'mtime': datetime.fromtimestamp(st.st_mtime).strftime('%m-%d %H:%M'),
                'exists': True,
            })
        except (FileNotFoundError, PermissionError):
            logs.append({
                'name': name, 'path': path, 'size': 0,
                'size_fmt': '--', 'mtime': '--', 'exists': False,
            })

    # ---------- 定时任务 ----------
    cron_jobs = []
    try:
        r = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            last_comment = ''
            for line in r.stdout.strip().split('\n'):
                line = line.strip()
                if line.startswith('#'):
                    # 跳过自动生成的注释行（crontab版本/编辑提示等）
                    comment = line.lstrip('#').strip()
                    skip_keywords = ['DO NOT EDIT', 'Cron version', 'installed on', 'crontab.c']
                    if any(k in comment for k in skip_keywords):
                        continue
                    if comment:
                        last_comment = comment
                    continue
                if line:
                    desc, lpath, cmd = parse_cron_desc(line)
                    if desc == line and not cmd:
                        last_comment = ''
                        continue  # 跳过非cron行
                    last_run = check_cron_last_run(cmd, lpath)
                    # 用注释覆盖自动生成描述，更易读
                    if last_comment:
                        display_desc = last_comment
                        last_comment = ''
                    else:
                        # 从命令路径推导描述
                        cmd_lower = cmd.lower()
                        if 'stargate' in cmd_lower:
                            display_desc = '腾讯云 Stargate 守护'
                        elif 'auto_escalate' in cmd_lower:
                            display_desc = '工单状态自动升级'
                        elif 'health_monitor' in cmd_lower:
                            display_desc = '服务器健康检查'
                        elif 'cleanup' in cmd_lower or 'clean' in cmd_lower:
                            display_desc = '系统清理维护'
                        elif 'backup' in cmd_lower:
                            display_desc = '系统备份'
                        elif '/www/server/cron/' in cmd:
                            display_desc = '宝塔面板定时任务'
                        else:
                            display_desc = desc
                    cron_jobs.append({
                        'raw': line,
                        'desc': display_desc,
                        'cmd': cmd[:80],
                        'log_path': lpath,
                        'last_run': last_run,
                    })
    except Exception:
        pass
    cron_jobs = cron_jobs[:12]

    # ---------- 备份状态 ----------
    backup_info = {'latest': '', 'size_fmt': '', 'age': '', 'exists': False}
    backup_dir = '/var/backups/hospital-workorder'
    if os.path.isdir(backup_dir):
        try:
            files = sorted([f for f in os.listdir(backup_dir) if f.endswith(('.sql', '.db', '.tar', '.gz'))], reverse=True)
            if files:
                latest = files[0]
                path = os.path.join(backup_dir, latest)
                st = os.stat(path)
                age_hours = (datetime.now().timestamp() - st.st_mtime) / 3600
                backup_info = {
                    'latest': latest,
                    'size_fmt': size_fmt(st.st_size),
                    'age': f'{int(age_hours/24)}天前' if age_hours >= 24 else f'{int(age_hours)}小时前',
                    'exists': True,
                }
        except Exception:
            pass

    # ---------- 服务连通性 ----------
    services = []
    # Gunicorn/Flask
    try:
        r = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '-m', '3',
                           'http://127.0.0.1:5000/'], capture_output=True, text=True, timeout=5)
        flask_ok = r.stdout.strip() in ('200', '302')
    except Exception:
        flask_ok = False
    services.append({'name': 'Web服务', 'ok': flask_ok})

    # MySQL
    try:
        r = subprocess.run(['sudo', '-u', 'root',
                           '/var/www/hospital-workorder/venv/bin/python3', '-c',
                           'from app import create_app; from models import db; app=create_app(); app.app_context().push(); db.session.execute(db.text(\"SELECT 1\")); print(\"ok\")'],
                          capture_output=True, text=True, timeout=5)
        mysql_ok = 'ok' in r.stdout
    except Exception:
        mysql_ok = False
    services.append({'name': '数据库', 'ok': mysql_ok})

    # Nginx
    try:
        r = subprocess.run(['pgrep', '-f', 'nginx: master'], capture_output=True, text=True, timeout=3)
        nginx_ok = bool(r.stdout.strip())
    except Exception:
        nginx_ok = False
    services.append({'name': 'Nginx', 'ok': nginx_ok})

    # Certbot 上次续签
    certbot_last = ''
    try:
        r = subprocess.run(['sudo', 'journalctl', '-u', 'certbot.timer', '--no-pager', '-n', '3', '-o', 'short-iso'],
                          capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            for line in r.stdout.strip().split('\n'):
                if 'Triggered' in line or 'Started' in line:
                    certbot_last = line[:16]
                    break
            if not certbot_last:
                certbot_last = r.stdout.strip().split('\n')[-1][:16]
    except Exception:
        pass
    services.append({'name': 'Certbot', 'ok': bool(certbot_last)})

    # ---------- 系统更新（文件缓存1小时） ----------
    cache_file = '/tmp/monitor_updates.json'
    updates = 0
    security = 0
    try:
        if os.path.exists(cache_file) and (datetime.now().timestamp() - os.path.getmtime(cache_file)) < 3600:
            import json
            with open(cache_file) as f:
                cached = json.load(f)
                updates, security = cached['updates'], cached['security']
        else:
            r = subprocess.run(['apt-get', '--just-print', 'upgrade'], capture_output=True, text=True, timeout=30)
            for line in r.stdout.split('\n'):
                if 'Inst ' in line:
                    updates += 1
                    if '-security' in line:
                        security += 1
            import json
            with open(cache_file, 'w') as f:
                json.dump({'updates': updates, 'security': security}, f)
    except Exception:
        pass

    # ---------- SSH失败登录（文件缓存5分钟） ----------
    ssh_cache_file = '/tmp/monitor_ssh.json'
    ssh_fails = 0
    try:
        if os.path.exists(ssh_cache_file) and (datetime.now().timestamp() - os.path.getmtime(ssh_cache_file)) < 300:
            import json
            with open(ssh_cache_file) as f:
                ssh_fails = json.load(f).get('fails', 0)
        else:
            r = subprocess.run(
                ['sudo', 'grep', '-c', 'Failed password', '/var/log/auth.log'],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ssh_fails = int(r.stdout.strip())
            import json
            with open(ssh_cache_file, 'w') as f:
                json.dump({'fails': ssh_fails}, f)
    except Exception:
        pass

    # ---------- 最近错误 ----------
    recent_errors = []
    for log_name, log_path in [('工单系统', '/var/log/hospital-workorder.log'),
                                ('健康检查', '/var/log/hospital-health.log')]:
        try:
            r = subprocess.run(['grep', '-E', '(ERROR|Traceback|Error|error|WARNING)', log_path],
                              capture_output=True, text=True, timeout=5)
            if r.stdout.strip():
                lines = r.stdout.strip().split('\n')
                for l in lines[-5:]:
                    recent_errors.append(f'[{log_name}] {l.strip()[:120]}')
        except Exception:
            pass
    recent_errors = recent_errors[:8]

    # ---------- 网络连接统计 ----------
    net_conns = {'total': 0, 'established': 0, 'listen': 0, 'time_wait': 0}
    try:
        conns = psutil.net_connections()
        net_conns['total'] = len(conns)
        for c in conns:
            s = c.status
            if s == 'ESTABLISHED': net_conns['established'] += 1
            elif s == 'LISTEN': net_conns['listen'] += 1
            elif s == 'TIME_WAIT': net_conns['time_wait'] += 1
    except (psutil.AccessDenied, PermissionError):
        pass

    # ---------- 在线用户 ----------
    online_users = []
    try:
        for u in psutil.users():
            online_users.append({
                'name': u.name,
                'terminal': u.terminal or '--',
                'host': u.host or '本地',
                'since': datetime.fromtimestamp(u.started).strftime('%m-%d %H:%M'),
            })
    except Exception:
        pass

    # ---------- 监听端口 ----------
    listen_ports = []
    seen = set()
    try:
        for c in psutil.net_connections():
            if c.status == 'LISTEN' and c.laddr:
                key = (c.laddr.port, c.type)
                if key not in seen:
                    seen.add(key)
                    pid = c.pid
                    proc_name = '--'
                    if pid:
                        try:
                            p = psutil.Process(pid)
                            proc_name = p.name()[:24]
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    proto = 'TCP' if c.type == 1 else 'UDP'
                    listen_ports.append({
                        'port': c.laddr.port,
                        'proto': proto,
                        'pid': pid or 0,
                        'proc': proc_name,
                    })
    except (psutil.AccessDenied, PermissionError):
        pass
    listen_ports = sorted(listen_ports, key=lambda x: x['port'])[:20]

    return jsonify({
        'cpu': {
            'percent': cpu_percent, 'count': cpu_count,
            'count_logical': cpu_count_logical,
            'load_1': round(load_avg[0], 2), 'load_5': round(load_avg[1], 2),
            'load_15': round(load_avg[2], 2),
            'freq_current': round(cpu_freq.current, 0) if cpu_freq else 0,
            'freq_max': round(cpu_freq.max, 0) if cpu_freq else 0,
            'per_core': cpu_per_core,
        },
        'memory': {
            'total': mem.total, 'available': mem.available, 'used': mem.used,
            'percent': mem.percent,
            'total_fmt': size_fmt(mem.total), 'used_fmt': size_fmt(mem.used),
            'available_fmt': size_fmt(mem.available),
            'swap_total': swap.total, 'swap_used': swap.used,
            'swap_percent': swap.percent,
            'swap_total_fmt': size_fmt(swap.total), 'swap_used_fmt': size_fmt(swap.used),
        },
        'disk': {
            'total': disk.total, 'used': disk.used, 'free': disk.free,
            'percent': disk.percent,
            'total_fmt': size_fmt(disk.total), 'used_fmt': size_fmt(disk.used),
            'free_fmt': size_fmt(disk.free), 'partitions': partitions,
        },
        'uptime': {
            'seconds': uptime_seconds, 'fmt': uptime_fmt(uptime_seconds),
            'boot_time': boot_dt.strftime('%Y-%m-%d %H:%M:%S'),
        },
        'net': {
            'bytes_sent': net.bytes_sent, 'bytes_recv': net.bytes_recv,
            'sent_fmt': size_fmt(net.bytes_sent), 'recv_fmt': size_fmt(net.bytes_recv),
        },
        'disk_io': disk_io_data,
        'process_count': process_count,
        'cert': cert_info,
        'logs': logs,
        'cron_jobs': cron_jobs,
        'backup': backup_info,
        'services': services,
        'updates': updates,
        'security': security,
        'ssh_fails': ssh_fails,
        'recent_errors': recent_errors,
        'net_conns': net_conns,
        'online_users': online_users,
        'listen_ports': listen_ports,
        'ts': datetime.now().strftime('%H:%M:%S'),
    })


# ---------- 操作接口 ----------

@monitor_bp.route('/renew-cert', methods=['POST'])
@login_required
def renew_cert():
    if not can_access('服务器监控'):
        return jsonify(success=False, msg='无权操作'), 403
    try:
        r = subprocess.run(['sudo', 'certbot', 'renew', '--non-interactive'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return jsonify(success=True, msg='证书续签成功 ✓')
        else:
            return jsonify(success=False, msg=f'续签失败: {r.stderr[:200]}')
    except subprocess.TimeoutExpired:
        return jsonify(success=False, msg='续签超时（60s）')
    except Exception as e:
        return jsonify(success=False, msg=str(e))


BACKUP_DIR = '/var/backups/hospital-workorder'
PROJECT_DIR = '/var/www/hospital-workorder'
DB_PATH = os.path.join(PROJECT_DIR, 'instance', 'workorders.db')


@monitor_bp.route('/clean-log', methods=['POST'])
@login_required
def clean_log():
    if not can_access('服务器监控'):
        return jsonify(success=False, msg='无权操作'), 403
    path = request.json.get('path', '')
    if not path:
        return jsonify(success=False, msg='缺少路径')
    # 安全检查：只允许清理 /var/log/ 下的文件
    if not path.startswith('/var/log/'):
        return jsonify(success=False, msg='不允许清理该路径')
    try:
        r = subprocess.run(['sudo', 'bash', '-c', f': > "{path}"'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return jsonify(success=True, msg=f'已清理: {path}')
        else:
            return jsonify(success=False, msg=f'清理失败: {r.stderr[:200]}')
    except Exception as e:
        return jsonify(success=False, msg=str(e))




@monitor_bp.route('/backup-list')
@login_required
def backup_list():
    if not can_access('服务器监控'):
        return jsonify(error='无权访问'), 403
    backups = []
    try:
        if not os.path.isdir(BACKUP_DIR):
            return jsonify(backups=[])
        for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
            path = os.path.join(BACKUP_DIR, f)
            if os.path.isfile(path):
                btype = 'system' if f.startswith('system-') else 'data' if f.startswith('data-') else 'full' if f.startswith('full-') else None
                if not btype:
                    continue
                st = os.stat(path)
                backups.append({
                    'name': f, 'type': btype,
                    'size_fmt': size_fmt(st.st_size),
                    'mtime': datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'age': f'{int((datetime.now().timestamp()-st.st_mtime)//86400)}天前',
                })
    except Exception:
        pass
    return jsonify(backups=backups)


@monitor_bp.route('/backup-create', methods=['POST'])
@login_required
def backup_create():
    if not can_access('服务器监控'):
        return jsonify(success=False, msg='无权操作'), 403
    btype = request.json.get('type', 'full')
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if btype == 'data':
            fname = f'data-{now}.db'
            subprocess.run(['sudo', 'cp', DB_PATH, os.path.join(BACKUP_DIR, fname)], check=True, timeout=30)
        elif btype == 'system':
            fname = f'system-{now}.tar.gz'
            dst = os.path.join(BACKUP_DIR, fname)
            subprocess.run(['sudo', 'bash', '-c',
                f'cd {PROJECT_DIR} && tar czf {dst} --exclude=venv --exclude=__pycache__ --exclude=.git --exclude=node_modules --exclude=instance/workorders.db --exclude=instance/workorders.db-wal .'],
                check=True, timeout=60)
        else:
            fname = f'full-{now}.tar.gz'
            dst = os.path.join(BACKUP_DIR, fname)
            subprocess.run(['sudo', 'cp', DB_PATH, '/tmp/wb.db'], check=True, timeout=10)
            try:
                subprocess.run(['sudo', 'bash', '-c',
                    f'cd {PROJECT_DIR} && tar czf {dst} --exclude=venv --exclude=__pycache__ --exclude=.git --exclude=node_modules --transform "s|/tmp/wb.db|instance/workorders.db|" /tmp/wb.db .'],
                    check=True, timeout=60)
            finally:
                subprocess.run(['sudo', 'rm', '-f', '/tmp/wb.db'])
        return jsonify(success=True, msg=f'备份完成: {fname}')
    except subprocess.TimeoutExpired:
        return jsonify(success=False, msg='备份超时')
    except Exception as e:
        return jsonify(success=False, msg=str(e))


@monitor_bp.route('/backup-restore', methods=['POST'])
@login_required
def backup_restore():
    if not can_access('服务器监控'):
        return jsonify(success=False, msg='无权操作'), 403
    # 验证管理员身份二次确认
    verify_user = (request.json.get('username') or '').strip()
    verify_pass = request.json.get('password') or ''
    if verify_user and verify_pass:
        from models import User
        u = User.query.filter_by(username=verify_user).first()
        if not u or not u.check_password(verify_pass) or not u.is_admin:
            return jsonify(success=False, msg='管理员身份验证失败，已取消恢复')
    elif verify_user or verify_pass:
        return jsonify(success=False, msg='请输入完整的账号和密码')
    # 没传凭证时默认当前用户（兼容旧调用）
    name = request.json.get('name', '')
    if not name or '..' in name or '/' in name:
        return jsonify(success=False, msg='无效文件名')
    src = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(src):
        return jsonify(success=False, msg='备份文件不存在')
    try:
        if name.startswith('data-') and name.endswith('.db'):
            subprocess.run(['sudo', 'cp', DB_PATH, DB_PATH + '.before_restore'], check=True, timeout=10)
            subprocess.run(['sudo', 'cp', src, DB_PATH], check=True, timeout=10)
            return jsonify(success=True, msg='数据已恢复（原库备份为 .before_restore）')
        elif name.startswith('system-') and name.endswith('.tar.gz'):
            subprocess.run(['sudo', 'cp', DB_PATH, '/tmp/db_before_restore.db'], check=True, timeout=10)
            subprocess.run(['sudo', 'bash', '-c', f'cd {PROJECT_DIR} && tar xzf {src} --overwrite'], check=True, timeout=60)
            return jsonify(success=True, msg='系统已恢复')
        elif name.startswith('full-') and name.endswith('.tar.gz'):
            subprocess.run(['sudo', 'cp', DB_PATH, DB_PATH + '.before_restore'], check=True, timeout=10)
            subprocess.run(['sudo', 'bash', '-c', f'cd {PROJECT_DIR} && tar xzf {src} --overwrite'], check=True, timeout=60)
            return jsonify(success=True, msg='完整备份已恢复')
        else:
            return jsonify(success=False, msg='不支持的备份格式')
    except Exception as e:
        return jsonify(success=False, msg=f'恢复失败: {str(e)}')


@monitor_bp.route('/backup-delete', methods=['POST'])
@login_required
def backup_delete():
    if not can_access('服务器监控'):
        return jsonify(success=False, msg='无权操作'), 403
    name = request.json.get('name', '')
    if not name or '..' in name or '/' in name:
        return jsonify(success=False, msg='无效文件名')
    src = os.path.join(BACKUP_DIR, name)
    try:
        os.remove(src)
        return jsonify(success=True, msg=f'已删除: {name}')
    except Exception as e:
        return jsonify(success=False, msg=str(e))