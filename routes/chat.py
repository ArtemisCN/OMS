"""在线聊天 REST API — 使用 Flask-Login 鉴权"""
import os
import uuid
import json
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User, Hospital, ChatConversation, ChatParticipant, ChatMessage, ChatToken, get_group_name_by_id
from datetime import datetime

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'mp3', 'wav', 'ogg', 'webm', 'm4a',
                       'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar', '7z'}
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'uploads', 'chat')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')

def _get_user_hospital_name(user_id):
    user = User.query.get(user_id)
    if user:
        assigned = user.get_assigned_hospitals()
        if assigned:
            return assigned[0].name
    return ''

def _serialize_conversation(conv, current_user_id):
    participants = ChatParticipant.query.filter_by(conversation_id=conv.id, is_active=True).all()
    unread = 0
    for p in participants:
        if p.user_id == current_user_id:
            unread = ChatMessage.query.filter(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.created_at > (p.last_read_at or datetime(2000, 1, 1)),
                ChatMessage.sender_id != current_user_id
            ).count()
            break
    title = conv.title
    if conv.type == 'single':
        for p in participants:
            if p.user_id != current_user_id:
                title = p.user_name
                break
    return {
        'id': conv.id, 'title': title, 'type': conv.type,
        'last_message': conv.last_message or '', 'last_sender': conv.last_sender or '',
        'last_time': conv.last_time.isoformat() if conv.last_time else '',
        'unread': unread,
        'participants': [{'id': p.user_id, 'name': p.user_name, 'hospital_id': p.hospital_id} for p in participants]
    }

@chat_bp.route('/conversations')
@login_required
def list_conversations():
    participant_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == current_user.id, ChatParticipant.is_active == True
    ).subquery()
    conversations = ChatConversation.query.filter(
        ChatConversation.id.in_(participant_ids)
    ).order_by(ChatConversation.updated_at.desc()).all()
    return jsonify({'conversations': [_serialize_conversation(c, current_user.id) for c in conversations]})

@chat_bp.route('/messages')
@login_required
def get_messages():
    conv_id = request.args.get('conversation_id', type=int)
    before_id = request.args.get('before_id', type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)
    if not conv_id: return jsonify({'error': '缺少 conversation_id'}), 400
    participant = ChatParticipant.query.filter_by(conversation_id=conv_id, user_id=current_user.id, is_active=True).first()
    if not participant: return jsonify({'error': '无权访问'}), 403
    participant.last_read_at = datetime.now()
    db.session.commit()
    query = ChatMessage.query.filter_by(conversation_id=conv_id)
    if before_id: query = query.filter(ChatMessage.id < before_id)
    messages = query.order_by(ChatMessage.id.desc()).limit(limit).all()
    messages.reverse()
    return jsonify({'messages': [{
        'id': m.id, 'sender_id': m.sender_id, 'sender_name': m.sender_name,
        'sender_hospital': m.sender_hospital, 'content': m.content, 'msg_type': m.msg_type,
        'recalled': m.recalled, 'file_name': m.file_name, 'file_size': m.file_size,
        'created_at': m.created_at.isoformat(), 'is_self': m.sender_id == current_user.id
    } for m in messages]})

@chat_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    if not data: return jsonify({'error': '无效请求'}), 400
    conv_id = data.get('conversation_id')
    content = (data.get('content') or '').strip()
    if not conv_id or not content: return jsonify({'error': '缺少参数'}), 400
    participant = ChatParticipant.query.filter_by(conversation_id=conv_id, user_id=current_user.id, is_active=True).first()
    if not participant: return jsonify({'error': '无权访问'}), 403
    hospital_name = _get_user_hospital_name(current_user.id)
    msg_type = data.get('msg_type', 'text')
    msg = ChatMessage(
        conversation_id=conv_id, sender_id=current_user.id,
        sender_name=current_user.display_name or current_user.username,
        sender_hospital=hospital_name, content=content, msg_type=msg_type,
        file_name=data.get('file_name', ''), file_size=data.get('file_size')
    )
    db.session.add(msg)
    conv = ChatConversation.query.get(conv_id)
    if conv:
        conv.last_message = content
        conv.last_sender = current_user.display_name or current_user.username
        conv.last_time = datetime.now()
        conv.updated_at = datetime.now()
    db.session.commit()
    return jsonify({
        'id': msg.id, 'sender_id': msg.sender_id, 'sender_name': msg.sender_name,
        'sender_hospital': msg.sender_hospital, 'content': msg.content,
        'msg_type': msg.msg_type, 'created_at': msg.created_at.isoformat(), 'is_self': True
    })

@chat_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files: return jsonify({'error': '没有上传文件'}), 400
    file = request.files['file']
    if file.filename == '' or not file: return jsonify({'error': '文件为空'}), 400
    if not _allowed_file(file.filename): return jsonify({'error': '不支持的文件类型'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    is_image = ext in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
    return jsonify({'url': f'/static/uploads/chat/{filename}', 'filename': filename, 'file_name': file.filename, 'is_image': is_image})

@chat_bp.route('/users')
@login_required
def list_chat_users():
    my_team = current_user.person.team if current_user.person and current_user.person.team else None
    users = User.query.order_by(User.display_name).all()
    teams_map, teams_order = {}, []
    for u in users:
        if u.id == current_user.id: continue
        team_name = (u.person.team if u.person and u.person.team else '未分组')
        if my_team and team_name != my_team: continue
        hospital_name = _get_user_hospital_name(u.id)
        group_name = get_group_name_by_id(u.group_id) or u.group or ''
        if team_name not in teams_map:
            teams_map[team_name] = []
            teams_order.append(team_name)
        teams_map[team_name].append({'id': u.id, 'name': u.display_name or u.username, 'hospital': hospital_name, 'team': u.person.team if u.person else '', 'group': group_name, 'is_admin': u.is_admin})
    result = []
    for tname in teams_order:
        if tname == '未分组': continue
        result.append({'team': tname, 'users': teams_map[tname]})
    if '未分组' in teams_map: result.append({'team': '未分组', 'users': teams_map['未分组']})
    return jsonify({'teams': result})

@chat_bp.route('/start', methods=['POST'])
@login_required
def start_conversation():
    data = request.get_json()
    target_id = data.get('user_id')
    if not target_id: return jsonify({'error': '缺少 user_id'}), 400
    target_id = int(target_id)
    if target_id == current_user.id: return jsonify({'error': '不能和自己聊天'}), 400
    target = User.query.get(target_id)
    if not target: return jsonify({'error': '用户不存在'}), 404
    my_conv_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == current_user.id, ChatParticipant.is_active == True
    ).subquery()
    existing = ChatConversation.query.filter(ChatConversation.id.in_(my_conv_ids), ChatConversation.type == 'single').all()
    for conv in existing:
        parts = ChatParticipant.query.filter_by(conversation_id=conv.id).all()
        part_ids = [p.user_id for p in parts]
        if target_id in part_ids:
            return jsonify({'conversation_id': conv.id, 'title': target.display_name or target.username})
    target_name = target.display_name or target.username
    my_name = current_user.display_name or current_user.username
    conv = ChatConversation(title=target_name, type='single')
    db.session.add(conv)
    db.session.flush()
    for uid, uname in [(current_user.id, my_name), (target.id, target_name)]:
        p = ChatParticipant(conversation_id=conv.id, user_id=uid, user_name=uname)
        db.session.add(p)
    db.session.commit()
    return jsonify({'conversation_id': conv.id, 'title': conv.title})

@chat_bp.route('/token')
@login_required
def get_chat_token():
    token = ChatToken.generate(current_user)
    return jsonify({'token': token.token, 'ws_url': 'wss://demolin.cn/ws/'})

@chat_bp.route('/ws-config')
@login_required
def ws_config():
    token = ChatToken.generate(current_user)
    hospital_name = _get_user_hospital_name(current_user.id)
    return jsonify({'token': token.token, 'ws_url': 'wss://demolin.cn/ws/', 'user': {'id': current_user.id, 'name': current_user.display_name or current_user.username, 'hospital': hospital_name}})

@chat_bp.route('/online-users')
@login_required
def online_users_list():
    try:
        with open('/tmp/chat_online.json', 'r') as f:
            data = json.load(f)
            return jsonify({'online_ids': data.get('online_ids', [])})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return jsonify({'online_ids': []})

@chat_bp.route('/unread-counts')
@login_required
def unread_counts():
    participant_ids = db.session.query(ChatParticipant.conversation_id).filter(
        ChatParticipant.user_id == current_user.id, ChatParticipant.is_active == True
    ).subquery()
    conversations = ChatConversation.query.filter(ChatConversation.id.in_(participant_ids)).all()
    total = 0
    for c in conversations:
        for p in c.participants:
            if p.user_id == current_user.id:
                unread = ChatMessage.query.filter(
                    ChatMessage.conversation_id == c.id,
                    ChatMessage.created_at > (p.last_read_at or datetime(2000, 1, 1)),
                    ChatMessage.sender_id != current_user.id
                ).count()
                total += unread
                break
    return jsonify({'total_unread': total})

@chat_bp.route('/mark-read', methods=['POST'])
@login_required
def mark_read():
    participants = ChatParticipant.query.filter_by(user_id=current_user.id, is_active=True).all()
    now = datetime.now()
    for p in participants: p.last_read_at = now
    db.session.commit()
    return jsonify({'ok': True})

@chat_bp.route('/read-status', methods=['GET'])
@login_required
def read_status():
    conv_id = request.args.get('conversation_id', type=int)
    if not conv_id: return jsonify({'error': '缺少 conversation_id'}), 400
    participants = ChatParticipant.query.filter_by(conversation_id=conv_id, is_active=True).all()
    others = [p for p in participants if p.user_id != current_user.id]
    last_msg = ChatMessage.query.filter_by(conversation_id=conv_id).order_by(ChatMessage.id.desc()).first()
    read_users = []
    for p in others:
        user = User.query.get(p.user_id)
        if not user: continue
        name = user.display_name or user.username or '用户'
        if last_msg and p.last_read_at:
            if last_msg.created_at <= p.last_read_at:
                read_up_to = ChatMessage.query.filter(
                    ChatMessage.conversation_id == conv_id,
                    ChatMessage.created_at <= p.last_read_at
                ).order_by(ChatMessage.id.desc()).first()
                read_to_id = read_up_to.id if read_up_to else 0
            else:
                read_to_id = 0
        else:
            read_to_id = 0
        read_users.append({'user_id': p.user_id, 'name': name, 'read_to_id': read_to_id})
    return jsonify({'read_users': read_users})

@chat_bp.route('/recall', methods=['POST'])
@login_required
def recall_message():
    data = request.get_json(silent=True) or {}
    msg_id = data.get('message_id')
    if not msg_id:
        return jsonify({'error': '缺少 message_id'}), 400
    try:
        msg_id = int(msg_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'message_id 必须为整数'}), 400
    msg = ChatMessage.query.get(msg_id)
    if not msg: return jsonify({'error': '消息不存在'}), 404
    if msg.sender_id != current_user.id: return jsonify({'error': '只能撤回自己的消息'}), 403
    delta = (datetime.now() - msg.created_at).total_seconds()
    if delta > 120: return jsonify({'error': '超过2分钟，无法撤回'}), 400
    msg.recalled = True
    msg.content = '消息已撤回'
    db.session.commit()
    return jsonify({'ok': True, 'message_id': msg.id, 'conversation_id': msg.conversation_id})

@chat_bp.route('/search')
@login_required
def search_messages():
    q = request.args.get('q', '').strip()
    if not q: return jsonify([])
    limit = min(request.args.get('limit', 30, type=int), 100)
    conv_ids = [p.conversation_id for p in ChatParticipant.query.filter_by(user_id=current_user.id, is_active=True).all()]
    if not conv_ids: return jsonify([])
    msgs = ChatMessage.query.filter(ChatMessage.conversation_id.in_(conv_ids), ~ChatMessage.recalled, ChatMessage.content.ilike(f'%{q}%')).order_by(ChatMessage.id.desc()).limit(limit).all()
    convs = {c.id: c for c in ChatConversation.query.filter(ChatConversation.id.in_(conv_ids)).all()}
    results = []
    for m in msgs:
        conv = convs.get(m.conversation_id)
        title = ''
        if conv and conv.type == 'single':
            for p in conv.participants:
                if p.user_id != current_user.id: title = p.user_name; break
        else: title = conv.title if conv else ''
        results.append({'id': m.id, 'conversation_id': m.conversation_id, 'sender_name': m.sender_name, 'content': m.content[:200], 'created_at': m.created_at.isoformat() if m.created_at else '', 'conv_title': title})
    return jsonify(results)

@chat_bp.route('/create-group', methods=['POST'])
@login_required
def create_group_chat():
    data = request.get_json()
    if not data: return jsonify({'error': '无效请求'}), 400
    user_ids = data.get('user_ids', [])
    if not isinstance(user_ids, list) or len(user_ids) < 2: return jsonify({'error': '至少需要2人'}), 400
    user_ids = list(set(user_ids))
    if current_user.id not in user_ids: user_ids.append(current_user.id)
    users = User.query.filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u.display_name or u.username for u in users}
    if len(user_ids) == 2:
        ids_set = set(user_ids)
        my_conv_ids = [p.conversation_id for p in ChatParticipant.query.filter_by(user_id=current_user.id, is_active=True).all()]
        existing = ChatConversation.query.filter(ChatConversation.id.in_(my_conv_ids), ChatConversation.type == 'single').all()
        for conv in existing:
            parts = ChatParticipant.query.filter_by(conversation_id=conv.id).all()
            if ids_set == {p.user_id for p in parts}:
                target_id = [uid for uid in user_ids if uid != current_user.id][0]
                return jsonify({'conversation_id': conv.id, 'title': user_map.get(target_id, '')})
    names = [user_map.get(uid, '用户') for uid in user_ids if uid != current_user.id]
    title = '、'.join(names[:3])
    if len(names) > 3: title += f' 等{len(names)}人'
    conv = ChatConversation(title=title, type='group')
    db.session.add(conv); db.session.flush()
    for uid in user_ids:
        p = ChatParticipant(conversation_id=conv.id, user_id=uid, user_name=user_map.get(uid, ''))
        db.session.add(p)
    db.session.commit()
    return jsonify({'conversation_id': conv.id, 'title': title})
