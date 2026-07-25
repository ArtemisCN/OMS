const api = require('../../utils/api');

// 12 套精美渐变色盘 —— 按名字哈希分配，每个人独享专属色
const AVATAR_GRADIENTS = [
  ['#4f46e5', '#7c3aed'], // 深邃紫
  ['#ec4899', '#f472b6'], // 樱花粉
  ['#f59e0b', '#fbbf24'], // 琥珀金
  ['#10b981', '#34d399'], // 翡翠绿
  ['#3b82f6', '#60a5fa'], // 天空蓝
  ['#8b5cf6', '#a78bfa'], // 薰衣草
  ['#ef4444', '#f87171'], // 珊瑚红
  ['#14b8a6', '#2dd4bf'], // 薄荷青
  ['#f97316', '#fb923c'], // 晚霞橙
  ['#06b6d4', '#22d3ee'], // 极光蓝
  ['#a855f7', '#c084fc'], // 梦幻紫
  ['#84cc16', '#a3e635'], // 青柠绿
];

function _avatarColor(name) {
  var hash = 0;
  for (var i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return AVATAR_GRADIENTS[Math.abs(hash) % AVATAR_GRADIENTS.length];
}

Page({
  data: {
    conversations: [],
    loading: true,
  },

  _pollTimer: null,

  onLoad() {
    this.fetchConversations();
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

  onPullDownRefresh() {
    this.fetchConversations().then(() => {
      wx.stopPullDownRefresh();
    });
  },

  fetchConversations() {
    return api.getConversations()
      .then((res) => {
        var list = res.conversations || [];
        var userInfo = wx.getStorageSync('user') || {};
        var myId = userInfo.id;
        list.forEach(function(conv) {
          conv.last_time = conv.last_time ? _formatTime(conv.last_time) : '';
          conv.is_group = conv.type === 'group';

          // 取对方头像作为会话头像
          conv.conv_avatar = '';
          if (conv.participants && conv.participants.length) {
            for (var i = 0; i < conv.participants.length; i++) {
              var p = conv.participants[i];
              if (p.id !== myId && p.avatar) {
                conv.conv_avatar = p.avatar;
                break;
              }
            }
            if (!conv.conv_avatar) {
              for (var j = 0; j < conv.participants.length; j++) {
                if (conv.participants[j].id !== myId) {
                  conv.conv_avatar = conv.participants[j].avatar || '';
                  break;
                }
              }
            }
          }

          // 分配专属渐变色
          conv.avatarColor = _avatarColor(conv.title);
          // 取展示用名字首字符
          conv.avatarLetter = conv.title.slice(0, 1);
        });
        this.setData({ conversations: list, loading: false });
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  onConvTap(e) {
    var id = e.currentTarget.dataset.id;
    var title = e.currentTarget.dataset.title;
    wx.navigateTo({
      url: '/pages/chat-detail/chat-detail?conversation_id=' + id + '&title=' + encodeURIComponent(title)
    });
  },

  onConvLongPress(e) {
    var id = e.currentTarget.dataset.id;
    var self = this;
    wx.showActionSheet({
      itemList: ['🗑️ 删除聊天', '🚪 离开群聊'],
      success: function(res) {
        if (res.tapIndex === 0) {
          api.deleteConversation(id).then(function() {
            wx.showToast({ title: '已删除', icon: 'success' });
            self.fetchConversations();
          }).catch(function(err) {
            wx.showToast({ title: err?.error || '删除失败', icon: 'none' });
          });
        } else if (res.tapIndex === 1) {
          wx.showModal({
            title: '离开群聊',
            content: '确定离开该群聊？',
            success: function(modal) {
              if (modal.confirm) {
                api.post('/chat/leave', { conversation_id: id }).then(function() {
                  wx.showToast({ title: '已离开', icon: 'success' });
                  self.fetchConversations();
                }).catch(function(err) {
                  wx.showToast({ title: err?.error || '操作失败', icon: 'none' });
                });
              }
            }
          });
        }
      }
    });
  },

  onNewChat() {
    wx.navigateTo({ url: '/pages/new-chat/new-chat' });
  },

  startPoll() {
    this.stopPoll();
    this._pollTimer = setInterval(() => {
      this.fetchConversations();
    }, 10000);
  },

  stopPoll() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },
});

function _formatTime(isoStr) {
  if (!isoStr) return '';
  try {
    var d = new Date(isoStr);
    var now = new Date();
    var diff = now - d;
    var oneDay = 86400000;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < oneDay && d.getDate() === now.getDate()) {
      var h = d.getHours().toString().padStart(2, '0');
      var m = d.getMinutes().toString().padStart(2, '0');
      return h + ':' + m;
    }
    if (diff < oneDay * 2) return '昨天';
    var month = (d.getMonth() + 1).toString().padStart(2, '0');
    var day = d.getDate().toString().padStart(2, '0');
    return month + '/' + day;
  } catch(e) {
    return isoStr.slice(5, 10);
  }
}
