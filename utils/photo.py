"""工单图片处理工具：支持本地存储 + 腾讯云COS"""
import os
import uuid
from datetime import datetime
from PIL import Image
from io import BytesIO

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'photos')
MAX_DIM = 1280
DEFAULT_QUALITY = 50
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}


def _get_cos_config():
    """从SystemSetting读取COS配置"""
    from models import SystemSetting
    cfg = {}
    for key in ['cos_enabled', 'cos_bucket', 'cos_region', 'cos_secret_id', 'cos_secret_key', 'cos_cdn_domain']:
        s = SystemSetting.query.filter_by(key=key).first()
        cfg[key] = s.value if s else ''
    return cfg


def _get_cos_client(cfg):
    """初始化COS客户端"""
    from qcloud_cos import CosConfig, CosS3Client
    config = CosConfig(
        Region=cfg['cos_region'],
        SecretId=cfg['cos_secret_id'],
        SecretKey=cfg['cos_secret_key'],
        Token=None,
        Scheme='https'
    )
    return CosS3Client(config)


def ensure_dirs():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_local(file_data, filename):
    """存本地"""
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(file_data)
    return f'photos/{filename}'


def _upload_cos(file_data, filename, cfg):
    """上传到COS"""
    client = _get_cos_client(cfg)
    key = f'photos/{datetime.now().strftime("%Y/%m/%d")}/{filename}'
    client.put_object(
        Bucket=cfg['cos_bucket'],
        Body=file_data,
        Key=key,
        StorageClass='STANDARD',
        EnableMD5=False
    )
    return key


def get_photo_url(filepath):
    """获取图片可访问URL"""
    cfg = _get_cos_config()
    if cfg.get('cos_enabled') == '1' and cfg.get('cos_bucket'):
        domain = cfg.get('cos_cdn_domain') or f"https://{cfg['cos_bucket']}.cos.{cfg['cos_region']}.myqcloud.com"
        return f"{domain}/{filepath}"
    return f"/uploads/{filepath}"


def delete_photo_file(filepath):
    """删除图片（本地+COS都试）"""
    if not filepath:
        return
    cfg = _get_cos_config()
    # 删除本地
    local_path = os.path.join(UPLOAD_DIR, os.path.basename(filepath))
    if os.path.exists(local_path):
        os.remove(local_path)
    # 删除COS
    if cfg.get('cos_enabled') == '1' and cfg.get('cos_bucket'):
        try:
            client = _get_cos_client(cfg)
            client.delete_object(Bucket=cfg['cos_bucket'], Key=filepath)
        except Exception:
            pass


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_EXTENSIONS


def get_photo_settings():
    """从系统参数读取照片相关设置，带缓存"""
    try:
        from models import db, SystemSetting
        # 质量
        qs = SystemSetting.query.filter_by(key='photo_quality').first()
        quality = int(qs.value) if qs and qs.value else DEFAULT_QUALITY
        quality = max(1, min(100, quality))
        # 大小限制
        ms = SystemSetting.query.filter_by(key='upload_max_mb').first()
        max_mb = int(ms.value) if ms and ms.value else 20
        max_mb = max(1, min(100, max_mb))
        # 最大边长
        ds = SystemSetting.query.filter_by(key='photo_max_dim').first()
        max_dim = int(ds.value) if ds and ds.value else MAX_DIM
        max_dim = max(0, max_dim)
    except Exception:
        quality = DEFAULT_QUALITY
        max_mb = 20
        max_dim = MAX_DIM
    return quality, max_mb * 1024 * 1024, max_dim


def save_photo(file_data, original_filename=None):
    """保存并压缩图片，返回 (filepath, width, height, filesize)
    
    支持本地存储和腾讯云COS两种模式（根据系统参数自动判断）。
    Args:
        file_data: 文件二进制数据 (bytes)
        original_filename: 原始文件名（仅用于扩展名检测）
    Returns:
        (relative_path, width, height, file_size)
    """
    ensure_dirs()

    # 从系统参数读取配置
    jpeg_quality, max_file_size, max_dim = get_photo_settings()

    # 检查文件大小
    if len(file_data) > max_file_size:
        max_mb = max_file_size // (1024 * 1024)
        raise ValueError(f'图片大小超过限制（{max_mb}MB）')

    # 用 Pillow 打开并处理
    img = Image.open(BytesIO(file_data))

    # 转为 RGB（RGBA → 白色背景合成）
    if img.mode in ('RGBA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'RGBA':
            bg.paste(img, mask=img.split()[3])
        else:
            bg.paste(img)
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    orig_w, orig_h = img.size

    # 缩放（使用系统配置的最大边长，0=不压缩）
    if max_dim > 0 and max(orig_w, orig_h) > max_dim:
        ratio = max_dim / max(orig_w, orig_h)
        new_w = int(orig_w * ratio)
        new_h = int(orig_h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # 生成文件名
    stem = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    filename = stem + '.jpg'

    # 压缩到 JPEG bytes
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=jpeg_quality, optimize=True)
    jpeg_data = buf.getvalue()
    final_w, final_h = img.size

    # 判断用本地还是COS
    cfg = _get_cos_config()
    if cfg.get('cos_enabled') == '1' and cfg.get('cos_bucket') and cfg.get('cos_secret_id'):
        try:
            relative_path = _upload_cos(jpeg_data, filename, cfg)
        except Exception as e:
            # COS失败，回退到本地
            relative_path = _save_local(jpeg_data, filename)
    else:
        relative_path = _save_local(jpeg_data, filename)

    return relative_path, final_w, final_h, len(jpeg_data)
