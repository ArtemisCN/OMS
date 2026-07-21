// ===== 在线聊天系统 =====
(function() {
    'use strict';

    var chat = {
        ws: null,
        token: null,
        wsUrl: null,
        user: null,
        conversations: [],
        currentConvId: null,
        onlineUsers: new Set(),
        connected: false,
        reconnectTimer: null,
        pingTimer: null,

        // 录音状态
        mediaRecorder: null,
        audioChunks: [],
        recordingTimer: null,
        recordingSeconds: 0,
        isRecording: false,

        // DOM 引用
        bubble: null,
        window: null,
        header: null,
        title: null,
        backBtn: null,
        convList: null,
        msgArea: null,
        inputArea: null,
        input: null,
        sendBtn: null,
        userList: null,
        newChat: null,
        imageBtn: null,
        imageInput: null,
        voiceBtn: null,
        voiceStatus: null,
        voiceTimer: null,
        voiceStop: null,
        voiceCancel: null,
        preview: null,
        previewImg: null,

        // 当前播放中的语音
        currentAudio: null,
        currentVoiceEl: null
    };

    // 初始化
    chat.init = function() {
        chat.bubble = document.getElementById('chat-bubble');
        chat.bubbleWasDocked = false;
        chat.window = document.getElementById('chat-window');
        chat.header = document.getElementById('chat-header');
        chat.title = document.getElementById('chat-title');
        chat.backBtn = document.getElementById('chat-back');
        chat.convList = document.getElementById('chat-conv-list');
        chat.msgArea = document.getElementById('chat-messages');
        chat.inputArea = document.getElementById('chat-input-area');
        chat.input = document.getElementById('chat-input');
        chat.sendBtn = document.getElementById('chat-send');
        chat.userList = document.getElementById('chat-user-list');
        chat.newChat = document.getElementById('chat-new-chat');
        chat.emojiBtn = document.getElementById('chat-emoji-btn');
        chat.emojiPicker = document.getElementById('chat-emoji-picker');
        chat.imageBtn = document.getElementById('chat-image-btn');
        chat.imageInput = document.getElementById('chat-image-input');
        chat.voiceBtn = document.getElementById('chat-voice-btn');
        chat.voiceStatus = document.getElementById('chat-voice-status');
        chat.voiceTimer = document.getElementById('chat-voice-timer');
        chat.voiceStop = document.getElementById('chat-voice-stop');
        chat.voiceCancel = document.getElementById('chat-voice-cancel');

        if (!chat.bubble || !chat.window) return;

        // 事件
        chat.bubble.addEventListener('click', chat.toggleWindow);
        document.getElementById('chat-close').addEventListener('click', chat.closeWindow);
        chat.backBtn.addEventListener('click', chat.showConvList);
        chat.newChat.addEventListener('click', chat.showUserList);
        // 群聊
        var groupBtn = document.getElementById('chat-new-group');
        if (groupBtn) {
            groupBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                chat.showGroupUserList();
            });
        }
        chat.sendBtn.addEventListener('click', chat.sendMessage);
        chat.input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') chat.sendMessage();
        });
        chat.input.addEventListener('input', chat.onTyping);

        // Emoji 选择器
        if (chat.emojiBtn && chat.emojiPicker) {
            chat.renderEmojiPicker();
            chat.emojiBtn.addEventListener('click', chat.toggleEmojiPicker);
            document.addEventListener('click', chat.onDocClickForEmoji);
        }

        // 图片上传
        if (chat.imageInput) {
            chat.imageInput.addEventListener('change', chat.onImageSelected);
        }

        // 语音录制
        if (chat.voiceBtn) {
            chat.voiceBtn.addEventListener('click', chat.toggleRecording);
        }
        if (chat.voiceStop) {
            chat.voiceStop.addEventListener('click', chat.stopRecording);
        }
        if (chat.voiceCancel) {
            chat.voiceCancel.addEventListener('click', chat.cancelRecording);
        }

        // 创建图片预览遮罩
        chat.createPreviewOverlay();

        // 获取配置并连接
        chat.fetchConfig();

        // 启动在线状态轮询
        chat.onlinePollTimer = setInterval(chat.checkOnlineStatus, 5000);
        // 启动未读轮询
        chat.unreadPollTimer = setInterval(chat.checkUnreadCount, 10000);
        // 页面可见性变化时处理
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) {
                // 回到页面时立即刷新
                chat.checkOnlineStatus();
                chat.checkUnreadCount();
            }
        });
    };

    // 创建图片预览遮罩
    chat.createPreviewOverlay = function() {
        var overlay = document.createElement('div');
        overlay.id = 'chat-image-preview';
        var img = document.createElement('img');
        overlay.appendChild(img);
        overlay.addEventListener('click', function() {
            overlay.classList.remove('show');
        });
        document.body.appendChild(overlay);
        chat.preview = overlay;
        chat.previewImg = img;
    };

    // 获取 WebSocket 配置
    chat.fetchConfig = function() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/ws-config', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.token = data.token;
                    chat.wsUrl = data.ws_url;
                    chat.user = data.user;
                    chat.connect();
                } catch(e) { console.error('Chat config error:', e); }
            }
        };
        xhr.send();
    };

    // WebSocket 连接
    chat.connect = function() {
        if (chat.ws && chat.ws.readyState === WebSocket.OPEN) return;
        if (!chat.wsUrl || !chat.token) return;

        try {
            chat.ws = new WebSocket(chat.wsUrl);
        } catch(e) {
            console.error('WebSocket 连接失败:', e);
            chat.scheduleReconnect();
            return;
        }

        chat.ws.onopen = function() {
            // 鉴权
            chat.ws.send(JSON.stringify({
                type: 'auth',
                token: chat.token
            }));
            chat.connected = true;
            clearTimeout(chat.reconnectTimer);
            chat.startPing();
        };

        chat.ws.onmessage = function(e) {
            try {
                var data = JSON.parse(e.data);
                chat.handleMessage(data);
            } catch(err) { /* ignore parse errors */ }
        };

        chat.ws.onclose = function() {
            chat.connected = false;
            chat.stopPing();
            chat.scheduleReconnect();
        };

        chat.ws.onerror = function() {
            // onclose 会触发重连
        };
    };

    chat.scheduleReconnect = function() {
        clearTimeout(chat.reconnectTimer);
        chat.reconnectTimer = setTimeout(function() {
            chat.fetchConfig();
        }, 5000);
    };

    chat.startPing = function() {
        chat.stopPing();
        chat.pingTimer = setInterval(function() {
            if (chat.ws && chat.ws.readyState === WebSocket.OPEN) {
                chat.ws.send(JSON.stringify({type: 'ping'}));
            }
        }, 30000);
    };

    chat.stopPing = function() {
        clearInterval(chat.pingTimer);
    };

    // 消息处理
    chat.handleMessage = function(data) {
        switch (data.type) {
            case 'auth_ok':
                console.log('Chat 鉴权成功');
                break;

            case 'conversations':
                chat.conversations = data.list || [];
                chat.renderConvList();
                break;

            case 'new_message':
                chat.onNewMessage(data);
                break;

            case 'typing':
                break;

            case 'recalled':
                var recMsgId = data.message_id;
                if (recMsgId && chat.msgArea) {
                    var recEls = chat.msgArea.querySelectorAll('.chat-msg');
                    recEls.forEach(function(el) {
                        var recallBtn = el.querySelector('.recall-btn[data-msgid="' + recMsgId + '"]');
                        if (recallBtn) {
                            el.querySelector('.msg-content-wrapper').innerHTML = '<span style="color:var(--text-muted);font-style:italic;font-size:12px;">消息已撤回</span>';
                            recallBtn.remove();
                            var rs = el.querySelector('.read-status');
                            if (rs) rs.remove();
                        }
                    });
                }
                break;

            case 'user_offline':
                chat.onlineUsers.delete(data.user_id);
                chat.renderUserList();
                break;
        }
    };

    // 显示发送消息确认（新消息到达）
    chat.onNewMessage = function(msg) {
        var isCurrentConv = msg.conversation_id === chat.currentConvId;
        var isFromOther = !msg.is_self;
        // 更新会话列表
        var found = false;
        for (var i = 0; i < chat.conversations.length; i++) {
            if (chat.conversations[i].id === msg.conversation_id) {
                var conv = chat.conversations[i];
                conv.last_message = msg.content;
                conv.last_sender = msg.sender_name;
                conv.last_time = msg.created_at;
                if (!isCurrentConv) conv.unread = (conv.unread || 0) + 1;
                found = true;
                break;
            }
        }
        if (!found) {
            chat.refreshConversations();
        }
        chat.renderConvList();
        chat.updateBubble();

        // 如果正在当前会话，追加消息
        if (isCurrentConv) {
            chat.appendMessage(msg, msg.is_self);
            chat.scrollToBottom();
        }

        // 收到他人消息 → 震动弹窗！
        if (isFromOther && chat.window && !chat.window.classList.contains('open')) {
            chat.bubble.classList.add('pulse');
            setTimeout(function() { chat.bubble.classList.remove('pulse'); }, 800);
            setTimeout(function() {
                chat.openWindow();
                // 震动效果
                chat.window.classList.add('shake');
                setTimeout(function() { chat.window.classList.remove('shake'); }, 500);
                if (msg.conversation_id && chat.conversations) {
                    chat.openConversation(msg.conversation_id, msg.sender_name || '消息');
                }
            }, 400);
        }
    };

    // 刷新会话列表
    chat.refreshConversations = function() {
        if (chat.ws && chat.ws.readyState === WebSocket.OPEN) {
            chat.ws.send(JSON.stringify({type: 'conversations'}));
        }
    };

    // 切换窗口
    chat.toggleWindow = function() {
        if (chat.window.classList.contains('open')) {
            chat.closeWindow();
        } else {
            chat.openWindow();
        }
    };

    chat.openWindow = function() {
        chat.window.classList.add('open');
        document.body.classList.add('chat-open');
        if (chat.bubble) {
            chat.bubbleWasDocked = chat.bubble.classList.contains('docked-left') || chat.bubble.classList.contains('docked-right');
            if (chat.bubbleWasDocked) {
                chat.bubble.classList.add('chat-open-state');
            }
        }
        chat.showConvList();
        chat.refreshConversations();
    };

    chat.closeWindow = function() {
        chat.window.classList.remove('open');
        document.body.classList.remove('chat-open');
        if (chat.bubble && chat.bubbleWasDocked) {
            chat.bubble.classList.remove('chat-open-state');
            chat.bubbleWasDocked = false;
        }
        chat.showConvList();
        chat.stopAllAudio();
    };

    // 停止所有正在播放的语音
    chat.stopAllAudio = function() {
        if (chat.currentAudio) {
            chat.currentAudio.pause();
            chat.currentAudio = null;
        }
        if (chat.currentVoiceEl) {
            chat.currentVoiceEl.classList.remove('playing');
            chat.currentVoiceEl = null;
        }
    };

    // 显示会话列表
    chat.showConvList = function() {
        chat.title.textContent = '消息';
        chat.backBtn.classList.remove('show');
        chat.convList.classList.remove('hide');
        chat.msgArea.classList.remove('show');
        chat.inputArea.classList.remove('show');
        chat.userList.classList.remove('show');
        chat.voiceStatus.style.display = 'none';
        chat.newChat.style.display = 'flex';
        chat.renderConvList();
    };

    // 显示用户列表
    chat.showUserList = function() {
        chat.title.textContent = '发起聊天';
        chat.backBtn.classList.add('show');
        chat.convList.classList.add('hide');
        chat.msgArea.classList.remove('show');
        chat.inputArea.classList.remove('show');
        chat.voiceStatus.style.display = 'none';
        chat.userList.classList.add('show');
        chat.newChat.style.display = 'none';
        chat.loadUsers();
    };

    // 加载用户列表
    chat.loadUsers = function() {
        if (!chat.userList) return;
        chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:var(--text-muted);font-size:13px;">加载中...</div>';
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/users', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.renderUserList(data.teams || []);
                } catch(e) {
                    chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">数据解析失败</div>';
                }
            } else {
                chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">加载失败 (HTTP ' + xhr.status + ')</div>';
            }
        };
        xhr.onerror = function() {
            chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">网络错误，请检查连接</div>';
        };
        xhr.send();
    };

    // 渲染用户列表
    chat.renderUserList = function(teams) {
        if (!chat.userList) return;
        if (!teams || !Array.isArray(teams)) { teams = []; }
        chat.userList.innerHTML = '';
        if (teams.length === 0) {
            chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:var(--text-muted);font-size:13px;">暂无其他用户<br><span style="font-size:11px;">系统中只有你一个人</span></div>';
            return;
        }
        teams.forEach(function(t) {
            var header = document.createElement('div');
            header.className = 'chat-team-header';
            header.innerHTML = '<i class="fas fa-users"></i> ' + escapeHtml(t.team) + ' <span class="team-count">' + (t.users || []).length + '人</span>';
            chat.userList.appendChild(header);

            var card = document.createElement('div');
            card.className = 'chat-team-card';

            (t.users || []).forEach(function(u) {
                var item = document.createElement('div');
                item.className = 'chat-user-item';
                var online = chat.onlineUsers.has(u.id);
                item.innerHTML = '<span class="dot ' + (online ? '' : 'offline') + '"></span>' +
                    '<div><div class="u-name">' + escapeHtml(u.name) + '</div>' +
                    '<div class="u-hospital">' + escapeHtml(u.hospital || '') + '</div></div>' +
                    '<button class="start-btn" data-uid="' + u.id + '">发消息</button>';
                item.querySelector('.start-btn').addEventListener('click', function(e) {
                    e.stopPropagation();
                    chat.startConversation(u.id);
                });
                card.appendChild(item);
            });
            chat.userList.appendChild(card);
        });
    };

    // 发起会话
    chat.startConversation = function(targetId) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/start', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.openConversation(data.conversation_id, data.title);
                } catch(e) {
                    console.error('Chat start parse error:', e);
                }
            } else {
                console.error('Chat start failed:', xhr.status, xhr.responseText);
            }
        };
        xhr.onerror = function() {
            console.error('Chat start network error');
        };
        xhr.send(JSON.stringify({user_id: targetId}));
    };

    // 显示群聊选人列表
    chat.showGroupUserList = function() {
        chat.title.textContent = '选择群成员';
        chat.backBtn.classList.add('show');
        chat.convList.classList.add('hide');
        chat.msgArea.classList.remove('show');
        chat.inputArea.classList.remove('show');
        chat.voiceStatus.style.display = 'none';
        chat.userList.classList.add('show');
        chat.newChat.style.display = 'none';
        chat.loadGroupUsers();
    };

    // 加载群聊选人（带多选框）
    chat.loadGroupUsers = function() {
        if (!chat.userList) return;
        chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:var(--text-muted);font-size:13px;">加载中...</div>';
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/users', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.renderGroupUserList(data.teams || []);
                } catch(e) {
                    chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">数据解析失败</div>';
                }
            } else {
                chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">加载失败</div>';
            }
        };
        xhr.onerror = function() {
            chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:#ef4444;font-size:13px;">网络错误</div>';
        };
        xhr.send();
    };

    // 渲染群聊选人列表（带多选框 + 确定按钮）
    chat.renderGroupUserList = function(teams) {
        if (!chat.userList) return;
        if (!teams || !Array.isArray(teams)) { teams = []; }
        chat.userList.innerHTML = '';
        chat.selectedGroupUserIds = {};

        if (teams.length === 0) {
            chat.userList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:var(--text-muted);font-size:13px;">暂无其他用户</div>';
            return;
        }
        teams.forEach(function(t) {
            var header = document.createElement('div');
            header.className = 'chat-team-header';
            header.innerHTML = '<i class="fas fa-users"></i> ' + escapeHtml(t.team) + ' <span class="team-count">' + (t.users || []).length + '人</span>';
            chat.userList.appendChild(header);

            var card = document.createElement('div');
            card.className = 'chat-team-card';

            (t.users || []).forEach(function(u) {
                var item = document.createElement('div');
                item.className = 'chat-user-item';
                var online = chat.onlineUsers.has(u.id);
                var checked = chat.selectedGroupUserIds && chat.selectedGroupUserIds[u.id] ? 'checked' : '';
                item.innerHTML = '<input type="checkbox" class="group-checkbox" data-uid="' + u.id + '" ' + checked + '>' +
                    '<span class="dot ' + (online ? '' : 'offline') + '"></span>' +
                    '<div><div class="u-name">' + escapeHtml(u.name) + '</div>' +
                    '<div class="u-hospital">' + escapeHtml(u.hospital || '') + '</div></div>';
                item.querySelector('.group-checkbox').addEventListener('change', function(e) {
                    var uid = parseInt(this.getAttribute('data-uid'));
                    if (this.checked) {
                        chat.selectedGroupUserIds[uid] = true;
                    } else {
                        delete chat.selectedGroupUserIds[uid];
                    }
                });
                card.appendChild(item);
            });
            chat.userList.appendChild(card);
        });
        // 创建群聊确认按钮
        var confirmBtn = document.createElement('button');
        confirmBtn.textContent = '✓ 确定创建群聊';
        confirmBtn.className = 'btn btn-sm btn-primary';
        confirmBtn.style.cssText = 'display:block;width:calc(100% - 16px);margin:8px;padding:8px;border:none;border-radius:8px;background:var(--primary,#6366f1);color:#fff;font-size:13px;cursor:pointer;';
        confirmBtn.onclick = function() {
            var ids = Object.keys(chat.selectedGroupUserIds || {}).map(Number);
            chat.createGroupChat(ids);
        };
        chat.userList.appendChild(confirmBtn);
    };
    // 创建群聊
    chat.createGroupChat = function(userIds) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/create-group', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.openConversation(data.conversation_id, data.title);
                    chat.refreshConversations();
                } catch(e) { console.error('Group create parse error:', e); }
            } else {
                try {
                    var err = JSON.parse(xhr.responseText);
                    alert(err.error || '创建失败');
                } catch(e) { alert('创建失败'); }
            }
        };
        xhr.onerror = function() { alert('网络错误'); };
        xhr.send(JSON.stringify({user_ids: userIds}));
    };

    // 渲染会话列表
    chat.renderConvList = function() {
        if (!chat.convList) return;
        chat.convList.innerHTML = '';
        var convs = chat.conversations || [];
        if (convs.length === 0) {
            chat.convList.innerHTML = '<div style="text-align:center;padding:40px 16px;color:var(--text-muted);font-size:13px;">暂无消息<br><span style="font-size:11px;">点击上方「发起聊天」开始对话</span></div>';
            return;
        }
        convs.forEach(function(c) {
            var item = document.createElement('div');
            item.className = 'chat-conv-item';
            var name = c.title || (c.participants || []).filter(function(p) { return p.id !== (chat.user && chat.user.id); }).map(function(p) { return p.name; }).join(', ') || '未知';
            var preview = (c.last_sender ? c.last_sender + ': ' : '') + (c.last_message || '');
            var time = c.last_time ? chat.formatTime(c.last_time) : '';
            var otherIds = (c.participants || []).filter(function(p) { return p.id !== (chat.user && chat.user.id); }).map(function(p) { return p.id; });
            var anyOnline = false;
            for (var oi = 0; oi < otherIds.length; oi++) {
                if (chat.onlineUsers.has(otherIds[oi])) { anyOnline = true; break; }
            }
            item.innerHTML = '<div class="avatar">' + name.charAt(0) +
                (anyOnline ? '<span class="online-dot"></span>' : '') + '</div>' +
                '<div class="info"><div class="name">' + escapeHtml(name) +
                (anyOnline ? '<span class="online-tag">在线</span>' : '') +
                '</div>' +
                '<div class="preview">' + escapeHtml(preview) + '</div></div>' +
                '<div class="time">' + time + '</div>' +
                (c.unread > 0 ? '<div class="unread-badge">' + (c.unread > 99 ? '99+' : c.unread) + '</div>' : '');
            item.addEventListener('click', function() {
                chat.openConversation(c.id, name);
            });
            chat.convList.appendChild(item);
        });
        chat.updateBubble();
    };

    // 打开会话
    chat.openConversation = function(convId, title) {
        chat.currentConvId = convId;
        chat.title.textContent = title;
        chat.backBtn.classList.add('show');
        chat.convList.classList.add('hide');
        chat.msgArea.classList.add('show');
        chat.inputArea.classList.add('show');
        chat.userList.classList.remove('show');
        chat.voiceStatus.style.display = 'none';
        chat.newChat.style.display = 'none';
        // 清空未读
        for (var i = 0; i < chat.conversations.length; i++) {
            if (chat.conversations[i].id === convId) {
                chat.conversations[i].unread = 0;
                break;
            }
        }
        chat.updateBubble();
        chat.renderConvList();
        // 加载消息
        chat.loadMessages(convId);
        chat.input.focus();
        // 延迟加载已读状态（等消息渲染完成）
        setTimeout(function() { chat.loadReadStatus(convId); }, 500);
    };

    // 加载消息历史
    chat.loadMessages = function(convId) {
        chat.msgArea.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:12px;">加载中...</div>';
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/messages?conversation_id=' + convId, true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.msgArea.innerHTML = '';
                    (data.messages || []).forEach(function(m) {
                        chat.appendMessage(m, m.is_self);
                    });
                    chat.scrollToBottom();
                } catch(e) {
                    chat.msgArea.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">消息加载失败</div>';
                }
            } else {
                chat.msgArea.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">消息加载失败</div>';
            }
        };
        xhr.onerror = function() {
            chat.msgArea.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">网络错误</div>';
        };
        xhr.send();
    };

    // 追加消息（支持 text / image / voice）
    chat.appendMessage = function(msg, isSelf) {
        var div = document.createElement('div');
        div.className = 'chat-msg ' + (isSelf ? 'self' : 'other');
        var senderHtml = '';
        if (!isSelf) {
            senderHtml = '<div class="sender">' + escapeHtml(msg.sender_name) +
                (msg.sender_hospital ? '<span class="hospital-tag">' + escapeHtml(msg.sender_hospital) + '</span>' : '') +
                '</div>';
        }
        var time = chat.formatTime(msg.created_at);
        var contentHtml = '';

        if (msg.msg_type === 'image') {
            // 图片消息
            contentHtml = senderHtml +
                '<img class="msg-image" src="' + escapeHtml(msg.content) + '" alt="图片" loading="lazy">' +
                '<div class="time-tag">' + time + '</div>';
        } else if (msg.msg_type === 'voice') {
            // 语音消息 — 显示波形+时长
            var duration = msg.content.split('|')[1] || '0:00';
            var audioUrl = msg.content.split('|')[0] || msg.content;
            var dataId = 'voice-' + msg.id;
            contentHtml = senderHtml +
                '<div class="msg-voice" data-audio="' + escapeHtml(audioUrl) + '" data-id="' + dataId + '">' +
                    '<div class="voice-play-icon"><i class="fas fa-play"></i></div>' +
                    '<div class="voice-wave">' +
                        '<span></span><span></span><span></span><span></span><span></span>' +
                    '</div>' +
                    '<span class="voice-duration">' + escapeHtml(duration) + '</span>' +
                '</div>' +
                '<div class="time-tag">' + time + '</div>';
        } else {
            // 纯文本消息
            var canRecall = isSelf && msg.recalled === false && (new Date().getTime() - new Date(msg.created_at).getTime()) < 120000;
            contentHtml = senderHtml +
                '<div class="msg-content-wrapper">' +
                (msg.recalled ? '<span style="color:var(--text-muted);font-style:italic;font-size:12px;">消息已撤回</span>' : escapeHtml(msg.content)) +
                '</div>' +
                '<div class="msg-footer">' +
                '<span class="time-tag">' + time + '</span>' +
                (canRecall ? '<span class="recall-btn" data-msgid="' + msg.id + '" style="cursor:pointer;font-size:11px;color:var(--link-color,#3b82f6);margin-left:6px;">撤回</span>' : '') +
                (isSelf && msg.recalled === false ? '<span class="read-status" data-msgid="' + msg.id + '" style="font-size:11px;color:var(--text-muted);margin-left:4px;"></span>' : '') +
                '</div>';
        }

        div.innerHTML = contentHtml;
        chat.msgArea.appendChild(div);

        // 绑定图片点击预览
        if (msg.msg_type === 'image') {
            var imgEl = div.querySelector('.msg-image');
            if (imgEl) {
                imgEl.addEventListener('click', function(e) {
                    e.stopPropagation();
                    chat.showImagePreview(this.src);
                });
            }
        }

        // 绑定语音播放
        if (msg.msg_type === 'voice') {
            var voiceEl = div.querySelector('.msg-voice');
            if (voiceEl) {
                voiceEl.addEventListener('click', function() {
                    chat.playVoice(this);
                });
            }
        }

        // 绑定撤回按钮
        var recallBtn = div.querySelector('.recall-btn');
        if (recallBtn) {
            recallBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                var msgId = parseInt(this.getAttribute('data-msgid'));
                if (confirm('确定撤回这条消息？')) {
                    chat.recallMessage(msgId);
                }
            });
        }
    };

    // 撤回消息
    chat.recallMessage = function(msgId) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/recall', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                // 找到消息元素并更新
                var msgs = chat.msgArea.querySelectorAll('.chat-msg');
                msgs.forEach(function(el) {
                    var recall = el.querySelector('.recall-btn[data-msgid="' + msgId + '"]');
                    if (recall) {
                        el.querySelector('.msg-content-wrapper').innerHTML = '<span style="color:var(--text-muted);font-style:italic;font-size:12px;">消息已撤回</span>';
                        recall.remove();
                        var readStatus = el.querySelector('.read-status');
                        if (readStatus) readStatus.remove();
                    }
                });
                chat.refreshConversations();
            } else {
                try {
                    var err = JSON.parse(xhr.responseText);
                    alert(err.error || '撤回失败');
                } catch(e) { alert('撤回失败'); }
            }
        };
        xhr.onerror = function() { alert('网络错误'); };
        xhr.send(JSON.stringify({message_id: msgId}));
        // 同时通过 WS 广播撤回，让其他人实时看到
        if (chat.ws && chat.ws.readyState === WebSocket.OPEN && chat.currentConvId) {
            chat.ws.send(JSON.stringify({
                type: 'recall',
                message_id: msgId,
                conversation_id: chat.currentConvId
            }));
        }
    };

    // 加载已读状态
    chat.loadReadStatus = function(convId) {
        if (!convId) return;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/read-status?conversation_id=' + convId, true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var readUsers = data.read_users || [];
                    // 找到每个消息的 read-status 元素
                    var statusEls = chat.msgArea.querySelectorAll('.read-status');
                    statusEls.forEach(function(el) {
                        var msgId = parseInt(el.getAttribute('data-msgid'));
                        var readNames = [];
                        readUsers.forEach(function(ru) {
                            if (ru.read_to_id >= msgId) {
                                readNames.push(ru.name);
                            }
                        });
                        if (readNames.length > 0) {
                            if (readNames.length <= 2) {
                                el.textContent = '已读 ' + readNames.join('、');
                            } else {
                                el.textContent = '已读 ' + readNames.length + '人';
                            }
                            el.style.color = 'var(--link-color,#3b82f6)';
                        }
                    });
                } catch(e) {}
            }
        };
        xhr.send();
    };



    // 图片预览
    chat.showImagePreview = function(src) {
        if (chat.preview && chat.previewImg) {
            chat.previewImg.src = src;
            chat.preview.classList.add('show');
        }
    };

    // 语音播放
    chat.playVoice = function(el) {
        var audioUrl = el.getAttribute('data-audio');
        if (!audioUrl) return;

        // 如果点击的是正在播放的，暂停
        if (chat.currentVoiceEl === el && chat.currentAudio && !chat.currentAudio.paused) {
            chat.currentAudio.pause();
            el.classList.remove('playing');
            el.querySelector('.voice-play-icon i').className = 'fas fa-play';
            return;
        }

        // 停止上一个
        chat.stopAllAudio();

        var audio = new Audio(audioUrl);
        chat.currentAudio = audio;
        chat.currentVoiceEl = el;
        el.classList.add('playing');
        el.querySelector('.voice-play-icon i').className = 'fas fa-pause';

        audio.addEventListener('ended', function() {
            el.classList.remove('playing');
            el.querySelector('.voice-play-icon i').className = 'fas fa-play';
            chat.currentAudio = null;
            chat.currentVoiceEl = null;
        });

        audio.addEventListener('error', function() {
            el.classList.remove('playing');
            el.querySelector('.voice-play-icon i').className = 'fas fa-play';
            chat.currentAudio = null;
            chat.currentVoiceEl = null;
        });

        audio.play().catch(function() {
            el.classList.remove('playing');
            el.querySelector('.voice-play-icon i').className = 'fas fa-play';
        });
    };

    // ===== 图片上传 =====
    chat.onImageSelected = function(e) {
        var file = e.target.files[0];
        if (!file) return;
        // 重置 input 以便重复选同一文件
        chat.imageInput.value = '';
        chat.uploadAndSendImage(file);
    };

    chat.uploadAndSendImage = function(file) {
        if (!chat.currentConvId) return;
        var formData = new FormData();
        formData.append('file', file);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/upload', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.sendImageMessage(data.url);
                } catch(e) {
                    console.error('Image upload parse error:', e);
                }
            } else {
                console.error('Image upload failed:', xhr.status);
            }
        };
        xhr.onerror = function() {
            console.error('Image upload network error');
        };
        xhr.send(formData);
    };

    chat.sendImageMessage = function(imageUrl) {
        if (!chat.currentConvId) return;

        // 通过 HTTP 发送
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/send', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.appendMessage(data, true);
                    chat.scrollToBottom();
                    chat.refreshConversations();
                } catch(e) { }
            }
        };
        xhr.send(JSON.stringify({
            conversation_id: chat.currentConvId,
            content: imageUrl,
            msg_type: 'image'
        }));

        // 也通过 WS 发送
        if (chat.ws && chat.ws.readyState === WebSocket.OPEN) {
            chat.ws.send(JSON.stringify({
                type: 'send',
                conversation_id: chat.currentConvId,
                content: imageUrl,
                msg_type: 'image'
            }));
        }
    };

    // ===== 语音录制 =====
    chat.toggleRecording = function() {
        if (chat.isRecording) {
            // 如果已经在录制，停止
            chat.stopRecording();
        } else {
            chat.startRecording();
        }
    };

    chat.startRecording = function() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            console.error('浏览器不支持录音');
            return;
        }

        chat.isRecording = true;
        chat.voiceBtn.classList.add('is-recording');
        chat.voiceBtn.innerHTML = '<i class="fas fa-stop"></i>';
        chat.voiceStatus.style.display = 'flex';

        chat.audioChunks = [];
        chat.recordingSeconds = 0;
        chat.voiceTimer.textContent = '00:00';

        // 计时器
        chat.recordingTimer = setInterval(function() {
            chat.recordingSeconds++;
            var m = String(Math.floor(chat.recordingSeconds / 60)).padStart(2, '0');
            var s = String(chat.recordingSeconds % 60).padStart(2, '0');
            if (chat.voiceTimer) chat.voiceTimer.textContent = m + ':' + s;
            // 限制 60 秒
            if (chat.recordingSeconds >= 60) {
                chat.stopRecording();
            }
        }, 1000);

        // 开始录制
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(function(stream) {
                // 使用 webm/opus 格式 (所有现代浏览器支持)
                var mimeType = 'audio/webm;codecs=opus';
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    mimeType = 'audio/ogg;codecs=opus';
                }
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    mimeType = '';
                }

                chat.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType: mimeType } : {});

                chat.mediaRecorder.ondataavailable = function(e) {
                    if (e.data.size > 0) {
                        chat.audioChunks.push(e.data);
                    }
                };

                chat.mediaRecorder.onstop = function() {
                    // 停止所有音轨
                    stream.getTracks().forEach(function(track) { track.stop(); });
                };

                chat.mediaRecorder.start(100); // 每100ms收集数据
            })
            .catch(function(err) {
                console.error('录音启动失败:', err);
                chat.cancelRecording();
            });
    };

    chat.stopRecording = function() {
        if (!chat.isRecording || !chat.mediaRecorder) return;
        chat.isRecording = false;

        clearInterval(chat.recordingTimer);
        chat.voiceBtn.classList.remove('is-recording');
        chat.voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
        chat.voiceStatus.style.display = 'none';

        var duration = chat.recordingSeconds;
        chat.recordingSeconds = 0;

        // 如果录音太短 (< 0.5秒)
        if (duration < 0.5) {
            if (chat.mediaRecorder.state !== 'inactive') {
                chat.mediaRecorder.stop();
            }
            chat.mediaRecorder = null;
            chat.audioChunks = [];
            return;
        }

        chat.mediaRecorder.addEventListener('stop', function() {
            var blob = new Blob(chat.audioChunks, { type: chat.mediaRecorder.mimeType || 'audio/webm' });
            chat.audioChunks = [];
            chat.mediaRecorder = null;
            if (blob.size < 100) return; // 太短忽略
            chat.uploadAndSendVoice(blob, duration);
        });

        if (chat.mediaRecorder.state === 'recording') {
            chat.mediaRecorder.stop();
        }
    };

    chat.cancelRecording = function() {
        if (chat.mediaRecorder && chat.mediaRecorder.state === 'recording') {
            chat.mediaRecorder.stop();
        }
        chat.isRecording = false;
        clearInterval(chat.recordingTimer);
        chat.voiceBtn.classList.remove('is-recording');
        chat.voiceBtn.innerHTML = '<i class="fas fa-microphone"></i>';
        chat.voiceStatus.style.display = 'none';
        chat.audioChunks = [];
        chat.recordingSeconds = 0;
        chat.mediaRecorder = null;
    };

    chat.uploadAndSendVoice = function(blob, duration) {
        if (!chat.currentConvId) return;
        var formData = new FormData();
        formData.append('file', blob, 'voice.webm');

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/upload', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var dStr = String(Math.floor(duration / 60)).padStart(2, '0') + ':' + String(Math.floor(duration % 60)).padStart(2, '0');
                    var content = data.url + '|' + dStr;
                    chat.sendVoiceMessage(content);
                } catch(e) { console.error('Voice upload parse error:', e); }
            } else {
                console.error('Voice upload failed:', xhr.status);
            }
        };
        xhr.onerror = function() {
            console.error('Voice upload network error');
        };
        xhr.send(formData);
    };

    chat.sendVoiceMessage = function(content) {
        if (!chat.currentConvId) return;

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/send', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.appendMessage(data, true);
                    chat.scrollToBottom();
                    chat.refreshConversations();
                } catch(e) { }
            }
        };
        xhr.send(JSON.stringify({
            conversation_id: chat.currentConvId,
            content: content,
            msg_type: 'voice'
        }));

        if (chat.ws && chat.ws.readyState === WebSocket.OPEN) {
            chat.ws.send(JSON.stringify({
                type: 'send',
                conversation_id: chat.currentConvId,
                content: content,
                msg_type: 'voice'
            }));
        }
    };

    // ===== 发送文本消息 =====
    chat.sendMessage = function() {
        var content = chat.input.value.trim();
        if (!content || !chat.currentConvId) return;
        chat.input.value = '';

        // 通过 HTTP 发送
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/chat/send', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.appendMessage(data, true);
                    chat.scrollToBottom();
                    chat.refreshConversations();
                } catch(e) {
                    console.error('Chat send parse error:', e);
                }
            } else {
                console.error('Chat send failed:', xhr.status, xhr.responseText);
            }
        };
        xhr.onerror = function() {
            console.error('Chat send network error');
        };
        xhr.send(JSON.stringify({
            conversation_id: chat.currentConvId,
            content: content
        }));

        // 也通过 WebSocket 发送
        if (chat.ws && chat.ws.readyState === WebSocket.OPEN) {
            chat.ws.send(JSON.stringify({
                type: 'send',
                conversation_id: chat.currentConvId,
                content: content
            }));
        }
    };

    // 输入中
    chat._typingTimer = null;
    chat.onTyping = function() {
        if (chat._typingTimer) clearTimeout(chat._typingTimer);
        chat._typingTimer = setTimeout(function() {
            if (chat.ws && chat.ws.readyState === WebSocket.OPEN && chat.currentConvId) {
                chat.ws.send(JSON.stringify({
                    type: 'typing',
                    conversation_id: chat.currentConvId
                }));
            }
        }, 300);
    };

    // 更新气泡未读
    chat.updateBubble = function() {
        if (!chat.bubble) return;
        var total = 0;
        (chat.conversations || []).forEach(function(c) {
            total += (c.unread || 0);
        });
        if (total > 0) {
            chat.bubble.classList.add('has-unread');
            chat.bubble.setAttribute('data-unread', total > 99 ? '99+' : total);
        } else {
            chat.bubble.classList.remove('has-unread');
            chat.bubble.removeAttribute('data-unread');
        }
    };

    // 轮询在线状态
    chat.checkOnlineStatus = function() {
        if (document.hidden) return; // 页面不可见时不轮询
        if (!chat.window || !chat.window.classList.contains('open')) return;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/online-users', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    chat.onlineUsers = new Set(data.online_ids || []);
                    if (chat.userList && chat.userList.classList.contains('show')) {
                        chat.loadUsers();
                    }
                    chat.renderConvList();
                } catch(e) {}
            }
        };
        xhr.send();
    };

    // 轮询未读
    chat.checkUnreadCount = function() {
        if (document.hidden) return;
        if (chat.window && chat.window.classList.contains('open')) return;
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/chat/unread-counts', true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var total = data.total_unread || 0;
                    if (total > 0) {
                        chat.bubble.classList.add('has-unread');
                        chat.bubble.setAttribute('data-unread', total > 99 ? '99+' : total);
                    } else {
                        chat.bubble.classList.remove('has-unread');
                        chat.bubble.removeAttribute('data-unread');
                    }
                } catch(e) {}
            }
        };
        xhr.send();
    };

    // ===== Emoji =====
    chat.EMOJIS = '😀😃😄😁😆😅🤣😂🙂🙃😉😊😇🥰😍🤩😘😗😚😋😛😜🤪😝🤑🤗🤭🫣🤫🤔🫡🤐😑😶🫥😏😒🙄😬🤨😌😪🤤😴😷🤒🤕🤢🤮🥴😵🤯🥳🥺😢😭😤😠😡🤬💀☠️💩🤡👹👺👻👽👾🤖😺😸😹😻😼😽🙀😿😾🙌👏👍👎👊✊🤛🤜🤞✌️🤟🤘👌🤌🤏🖐️✋🤚👋🤙💪🦵🦶👂🦻👃🧠🦷🦴👀👅👄❤️🧡💛💚💙💜🖤🤍🤎💕💞💓💗💖💘💝💟♥️💑💋👫👬👭💃🕺👶👧🧒👦👩🧑👨👩‍🦱👨‍🦱👩‍🦰👨‍🦰👱‍♀️👱👱‍♂️👩‍🦳👨‍🦳👩‍🦲👨‍🦲🧔‍♀️🧔🧔‍♂️👵🧓👴👲👳‍♀️👳👳‍♂️👸👰‍♀️👰👰‍♂️🤴🤵‍♀️🤵🤵‍♂️🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🐔🐧🐦🐤🐣🐥🦆🦅🦉🦇🐺🐗🐴🦄🐝🐛🦋🐌🐞🐜🦟🦗🦂🐢🐍🦎🦖🦕🐙🦑🦐🦀🐡🐠🐟🐬🐳🐋🦈🪸🐊🐅🐆🦓🦍🦧🐘🦛🦏🐪🐫🦒🦘🦬🐃🐂🐄🐎🐖🐏🐑🦙🐐🦌🐕🐩🕊️🐇🦝🦨🦡🦫🦦🦥🐁🐀🐿️🦔🌺🌸🌷🌹🌻🌼🌿🍀🍁🍂🍃🌵🌴🌲🌳🌾🌊☀️🌈⭐🌙🌞🌸💐🍎🍊🍋🍌🍉🍇🍓🫐🍈🍒🍑🥭🍍🥝🍅🫒🥥🥑🍆🥔🥕🌽🌶️🫑🥒🥬🥦🧄🧅🍄🥜🫘🌰🍞🥐🥖🥨🧀🥚🍳🧈🥞🧇🥓🥩🍗🍖🦴🌭🍔🍟🍕🫓🥪🥙🧆🌮🌯🫔🥗🥘🫕🥫🍝🍜🍲🍛🍣🍱🥟🦪🍤🍙🍚🍘🍥🥠🥮🍢🍡🍧🍨🍦🥧🧁🍰🎂🍮🍭🍬🍫🍿🍩🍪🌰🥜🥛🍼🫖☕🍵🧃🥤🧋🍶🍺🍻🥂🍷🥃🍸🍹🧉🍾🧊🥄🍴🍽️🥣🥡🥢🧂⚽🏀🏈⚾🎾🏐🏉🎱🏓🏸🏒🏑🏏⛳🥅🥊🥋🎯🎳🎿⛷️🏂🪂🏋️🤸🤼🤽🤾🤺⛹️🏌️🏄🏊🤿🏇🏃🚶🧎🏽‍🤝‍🏽🏋️‍♂️🏋️‍♀️🏌️‍♂️🏌️‍♀️🤸‍♂️🤸‍♀️⛹️‍♂️⛹️‍♀️🏋️‍♀️🏋️‍♂️🚗🚕🚙🚌🚎🏎️🚓🚑🚒🚐🛻🚚🚛🚜🛵🏍️🛺🚲🛴🚏🛤️🛣️🚦🚥🚧⚓⛵🛶🚤🛳️⛴️🛥️🚢✈️🛩️🛫🛬🚁🚟🚠🚡🛰️🚀🛸🏠🏡🏢🏣🏥🏦🏨🏩🏪🏫🏬🏭🏯🏰💒🗼🗽⛲⛪🕌🕍🕋⛩️🛕🛤️🛣️🗾🎄🎃🎊🎉🎈🎁🎀🎎🎏🎐🎑🎫🎟️🎪🎤🎧🎼🎹🥁🪘🎷🎺🎸🪕🎻🎬🎨🖼️📸📷🎥📽️🎞️📺📻📡🕹️💻📱📞📟🖥️🖨️⌨️🖱️🖲️💾💿📀🎮👾💡🔦🔋🔌🔧🔨🪛🔩⚙️🪜🧰🧲🪮🔪🗡️⚔️🛡️🚬⚰️🪦⚱️🏺🔮📿💎🎲♟️🧩🎯🎳🎮🎰🧸🪆🃏🀄🎴🔮🎭🖼️🎨👑👒🎩🎓🧢⛑️👑💄💍💼🕶️👜👝👛👓🥽🌂🧳☂️💣🔫🧨💉💊🩸🩹🩺🩻🦯🩼🛌🔪🚿🛁🪥🪒🧴🧷🧹🧺🧻🪣🧼🪠🪟🛋️🪑🚪🛏️🛌🧸🪆🎠🎡🎢🚂🚃🚄🚅🚆🚇🚈🚉🚊🚝🚞🚋🚌🚍🚎🚐🚑🚒🚓🚔🚕🚖🚗🚘🚙🚚🚛🚜🚲🛴🛵🏍️🛺🚨🚔🚍🚘🚖⌚📱💻⌨️🖥️🖨️🖱️🖲️🕹️🗜️💽💾💿📀📼📷📸📹🎥📽️🎞️📞☎️📟📠📺📻🎙️🎚️🎛️🧭⏱️⏲️⏰🕰️⌛⏳📡🔋🔌💡🔦🕯️🪔🧯🗑️🛢️💸💵💴💶💷🪙💰💳💎⚖️🪜🔧🔨⚒️🛠️⛏️🪚🔩⚙️🪤🧰🧲🪮🔗⛓️🧿🪝🪟🛞🧴🧷🧹🧺🧻🪣🧼🪠🪥🪒🧽🪩🪄🔮🎭🩰🧵🪡🧶🪢🎶🎵🎼🎤🎧🎺🎻🪕🥁🪘📯🎷🎸🎹🎺🎻🪕🪇🎙️🎚️🎛️📻📣📢🔔🕯️🪔🧨🎆🎇🎈🎉🎊🎎🎏🎐🎑🧧🎁🎀🪅🪆🎃🎄🎋🎍🎊🎉🎈'.match(/.{1,2}/g) || [],
    chat.renderEmojiPicker = function() {
        if (!chat.emojiPicker) return;
        chat.emojiPicker.innerHTML = '';
        chat.EMOJIS.forEach(function(e) {
            var span = document.createElement('span');
            span.textContent = e;
            span.title = e;
            span.addEventListener('click', function(ev) {
                ev.stopPropagation();
                chat.insertEmoji(e);
            });
            chat.emojiPicker.appendChild(span);
        });
    };

    chat.toggleEmojiPicker = function(e) {
        e.stopPropagation();
        if (!chat.emojiPicker) return;
        chat.emojiPicker.classList.toggle('show');
    };

    chat.onDocClickForEmoji = function(e) {
        if (chat.emojiPicker && chat.emojiPicker.classList.contains('show')) {
            if (!chat.emojiPicker.contains(e.target) && e.target !== chat.emojiBtn) {
                chat.emojiPicker.classList.remove('show');
            }
        }
    };

    chat.insertEmoji = function(emoji) {
        if (!chat.input) return;
        var start = chat.input.selectionStart;
        var end = chat.input.selectionEnd;
        var val = chat.input.value;
        chat.input.value = val.substring(0, start) + emoji + val.substring(end);
        chat.input.selectionStart = chat.input.selectionEnd = start + emoji.length;
        chat.input.focus();
        var ev = new Event('input', { bubbles: true });
        chat.input.dispatchEvent(ev);
    };

    // 滚到底部
    chat.scrollToBottom = function() {
        setTimeout(function() {
            chat.msgArea.scrollTop = chat.msgArea.scrollHeight;
        }, 50);
    };

    // 格式化时间
    chat.formatTime = function(isoStr) {
        if (!isoStr) return '';
        try {
            var d = new Date(isoStr);
            var now = new Date();
            var pad = function(n) { return String(n).padStart(2, '0'); };
            if (d.toDateString() === now.toDateString()) {
                return pad(d.getHours()) + ':' + pad(d.getMinutes());
            }
            var yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            if (d.toDateString() === yesterday.toDateString()) {
                return '昨天 ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
            }
            return pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
        } catch(e) { return ''; }
    };

    // HTML 转义
    function escapeHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // DOM 加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { chat.init(); });
    } else {
        chat.init();
    }
})();