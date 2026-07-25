const api = require('../../utils/api');

Page({
  data: {
    conversationId: null,
    title: '聊天',
    messages: [],
    inputText: '',
    scrollTo: '',
    loadingMore: false,
    hasMore: true,
    beforeId: null,
    MAX_RECALL_SECONDS: 120,
  },

  _pollTimer: null,

  onLoad(options) {
    var convId = parseInt(options.conversation_id);
    var app = getApp();
    var user = app.globalData.user || wx.getStorageSync('user') || {};
    this.setData({
      conversationId: convId,
      title: decodeURIComponent(options.title || '聊天'),
      myAvatar: user.avatar || '',
    });
    wx.setNavigationBarTitle({ title: this.data.title });
    this.loadMessages();
    // 标记已读
    api.markAllRead().catch(function() {});
  },

  onShow() {
    this.startPoll();
  },

  onHide() {
    this.stopPoll();
  },

  onUnload() {
    this.stopPoll();
  },

  loadMessages() {
    var self = this;
    api.getMessages(this.data.conversationId)
      .then(function(res) {
        var msgs = self._fixImageUrls(res.messages || []);
        self.setData({
          messages: msgs,
          hasMore: msgs.length >= 50,
          beforeId: msgs.length > 0 ? msgs[0].id : null,
          loadingMore: false,
        });
        setTimeout(function() {
          if (msgs.length > 0) {
            self.setData({ scrollTo: 'msg-' + msgs[msgs.length - 1].id });
          }
        }, 100);
      })
      .catch(function(err) {
        self.setData({ loadingMore: false });
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  /** 修复图片URL：相对路径补全为绝对路径 */
  _fixImageUrls(msgs) {
    var BASE = 'https://demolin.cn';
    return msgs.map(function(m) {
      if (m.msg_type === 'image' && m.content && m.content.indexOf('://') < 0) {
        m.content = BASE + m.content;
      }
      return m;
    });
  },

  onScrollToTop() {
    if (this.data.loadingMore || !this.data.hasMore || !this.data.beforeId) return;
    var self = this;
    this.setData({ loadingMore: true });
    api.getMessages(this.data.conversationId, this.data.beforeId)
      .then(function(res) {
        var older = self._fixImageUrls(res.messages || []);
        if (older.length > 0) {
          var all = older.concat(self.data.messages);
          self.setData({
            messages: all,
            beforeId: older[0].id,
            loadingMore: false,
            hasMore: older.length >= 50,
          });
        } else {
          self.setData({ loadingMore: false, hasMore: false });
        }
      })
      .catch(function() {
        self.setData({ loadingMore: false });
      });
  },

  onInput(e) {
    this.setData({ inputText: e.detail.value });
  },

  onSend() {
    var text = this.data.inputText.trim();
    if (!text) return;
    var self = this;
    api.sendMessage(this.data.conversationId, text)
      .then(function(res) {
        self.setData({ inputText: '' });
        var msgs = self.data.messages.concat([res]);
        self.setData({ messages: msgs });
        setTimeout(function() {
          self.setData({ scrollTo: 'msg-' + res.id });
        }, 50);
      })
      .catch(function(err) {
        wx.showToast({ title: err?.error || '发送失败', icon: 'none' });
      });
  },

  onPickImage() {
    var self = this;
    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: function(res) {
        var filePath = res.tempFilePaths[0];
        wx.showLoading({ title: '上传中...' });
        api.uploadChatFile(filePath)
          .then(function(uploadRes) {
            wx.hideLoading();
            // uploadRes.url is already absolute from backend
            return api.sendMessage(self.data.conversationId, uploadRes.url, 'image');
          })
          .then(function(msgRes) {
            var msgs = self.data.messages.concat([msgRes]);
            self.setData({ messages: msgs });
            setTimeout(function() {
              self.setData({ scrollTo: 'msg-' + msgRes.id });
            }, 50);
          })
          .catch(function(err) {
            wx.hideLoading();
            wx.showToast({ title: err?.error || '发送失败', icon: 'none' });
          });
      }
    });
  },

  onImageTap(e) {
    var src = e.currentTarget.dataset.src;
    wx.previewImage({ urls: [src], current: src });
  },

  onLongPress(e) {
    var msgId = e.currentTarget.dataset.id;
    var msgs = this.data.messages;
    var msg = null;
    for (var i = 0; i < msgs.length; i++) {
      if (msgs[i].id === msgId) { msg = msgs[i]; break; }
    }
    if (!msg || msg.recalled) return;

    var self = this;
    var items = [];

    // 自己的消息 → 可撤回
    if (msg.is_self) {
      var elapsed = (Date.now() - new Date(msg.created_at).getTime()) / 1000;
      if (elapsed <= self.data.MAX_RECALL_SECONDS) {
        items.push('↩️ 撤回消息');
      }
    }

    items.push('🗑️ 删除该聊天');

    // 群聊可离开
    if (!msg.is_self === false) {
      // 仅当是群聊时显示离开选项
    }
    var convId = self.data.conversationId;

    if (items.length === 0) return;

    wx.showActionSheet({
      itemList: items,
      success: function(res) {
        var action = items[res.tapIndex];
        if (action.indexOf('撤回') >= 0) {
          api.recallMessage(msgId)
            .then(function() {
              msg.recalled = true;
              self.setData({ messages: msgs });
            })
            .catch(function(err) {
              wx.showToast({ title: err?.error || '撤回失败', icon: 'none' });
            });
        } else if (action.indexOf('删除') >= 0) {
          api.deleteConversation(self.data.conversationId)
            .then(function() {
              wx.showToast({ title: '已删除聊天', icon: 'success' });
              setTimeout(function() { wx.navigateBack(); }, 800);
            })
            .catch(function(err) {
              wx.showToast({ title: err?.error || '删除失败', icon: 'none' });
            });
        }
      }
    });
  },

  showTimeSeparator(index, messages) {
    if (index === 0) return true;
    var curr = new Date(messages[index].created_at);
    var prev = new Date(messages[index - 1].created_at);
    return (curr - prev) > 300000;
  },

  formatTime(isoStr) {
    if (!isoStr) return '';
    try {
      var d = new Date(isoStr);
      var now = new Date();
      var h = d.getHours().toString().padStart(2, '0');
      var m = d.getMinutes().toString().padStart(2, '0');
      if (d.toDateString() === now.toDateString()) return h + ':' + m;
      var month = (d.getMonth() + 1).toString().padStart(2, '0');
      var day = d.getDate().toString().padStart(2, '0');
      return month + '/' + day + ' ' + h + ':' + m;
    } catch(e) { return ''; }
  },

  startPoll() {
    this.stopPoll();
    var self = this;
    this._pollTimer = setInterval(function() {
      var convId = self.data.conversationId;
      api.getMessages(convId).then(function(res) {
        var newMsgs = self._fixImageUrls(res.messages || []);
        var oldMsgs = self.data.messages;
        // 按 ID 去重合并
        var merged = oldMsgs.slice();
        var existingIds = {};
        oldMsgs.forEach(function(m) { existingIds[m.id] = true; });
        var added = 0;
        newMsgs.forEach(function(m) {
          if (!existingIds[m.id]) {
            merged.push(m);
            existingIds[m.id] = true;
            added++;
          }
        });
        if (added > 0) {
          merged.sort(function(a, b) { return a.id - b.id; });
          var lastId = merged[merged.length - 1].id;
          self.setData({ messages: merged });
          setTimeout(function() {
            self.setData({ scrollTo: 'msg-' + lastId });
          }, 50);
        }
      }).catch(function() {});
    }, 5000);
  },

  stopPoll() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },
});
