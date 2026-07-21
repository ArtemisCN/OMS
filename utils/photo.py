"""工单图片处理工具：压缩保存，单张720p，不生成缩略图"""
import os
import uuid
from datetime import datetime
from PIL import Image

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'photos')
DEFAULT_QUALITY = 50
DEFAULT_MAX_SIZE_MB = 20

# 720p 最大边长
MAX_DIM = 1280

# 允许的图片类型
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}


def ensure_dirs():
    """确保存储目录存在"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)


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
        max_mb = int(ms.value) if ms and ms.value else DEFAULT_MAX_SIZE_MB
        max_mb = max(1, min(100, max_mb))
        # 最大边长
        ds = SystemSetting.query.filter_by(key='photo_max_dim').first()
        max_dim = int(ds.value) if ds and ds.value else MAX_DIM
        max_dim = max(0, max_dim)
    except Exception:
        quality = DEFAULT_QUALITY
        max_mb = DEFAULT_MAX_SIZE_MB
        max_dim = MAX_DIM
    return quality, max_mb * 1024 * 1024, max_dim


def save_photo(file_data, original_filename=None):
    """保存并压缩图片，返回 (filepath, width, height, filesize)

    单张 720p 级别压缩，不生成缩略图。
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

    # 生成唯一文件名
    ext = '.jpg'
    if original_filename:
        orig_ext = os.path.splitext(original_filename.lower())[1]
        if orig_ext in ALLOWED_EXTENSIONS:
            ext = orig_ext

    stem = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    filename = stem + ext

    # 用 Pillow 打开并处理
    from io import BytesIO
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

    # 保存（使用系统配置的质量）
    filepath = os.path.join(UPLOAD_DIR, filename)
    img.save(filepath, 'JPEG', quality=jpeg_quality, optimize=True)
    final_size = os.path.getsize(filepath)
    final_w, final_h = img.size

    relative_path = f'photos/{filename}'

    return relative_path, final_w, final_h, final_size
