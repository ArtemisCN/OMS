const api = require('../../utils/api');

Page({
  data: {
    teams: [],
    loading: true,
    mode: 'single', // 'single' | 'group'
    selectedIds: [], // 群聊选中的用户ID列表
    selectedNames: [],
  },

  onLoad() {
    this.loadUsers();
  },

  loadUsers() {
    var self = this;
    api.getChatUsers()
      .then(function(res) {
        self.setData({ teams: res.teams || [], loading: false });
      })
      .catch(function(err) {
        self.setData({ loading: false });
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  switchMode() {
    var newMode = this.data.mode === 'single' ? 'group' : 'single';
    this.setData({ mode: newMode, selectedIds: [], selectedNames: [] });
  },

  onUserTap(e) {
    if (this.data.mode === 'group') {
      this.toggleUser(e);
      return;
    }
    // 单人模式：直接发起聊天
    var uid = e.currentTarget.dataset.uid;
    var self = this;
    wx.showLoading({ title: '发起聊天...' });
    api.startConversation(uid)
      .then(function(res) {
        wx.hideLoading();
        wx.redirectTo({
          url: '/pages/chat-detail/chat-detail?conversation_id=' + res.conversation_id + '&title=' + encodeURIComponent(res.title)
        });
      })
      .catch(function(err) {
        wx.hideLoading();
        wx.showToast({ title: err?.error || '发起失败', icon: 'none' });
      });
  },

  toggleUser(e) {
    var uid = e.currentTarget.dataset.uid;
    var name = e.currentTarget.dataset.name;
    var ids = this.data.selectedIds;
    var names = this.data.selectedNames;
    var idx = ids.indexOf(uid);
    if (idx >= 0) {
      ids.splice(idx, 1);
      names.splice(idx, 1);
    } else {
      ids.push(uid);
      names.push(name);
    }
    this.setData({ selectedIds: ids, selectedNames: names });
  },

  createGroup() {
    var ids = this.data.selectedIds;
    if (ids.length < 1) {
      wx.showToast({ title: '请至少选择一个人', icon: 'none' });
      return;
    }
    var self = this;
    wx.showLoading({ title: '创建群聊...' });
    api.post('/chat/start_group', { user_ids: ids })
      .then(function(res) {
        wx.hideLoading();
        wx.redirectTo({
          url: '/pages/chat-detail/chat-detail?conversation_id=' + res.conversation_id + '&title=' + encodeURIComponent(res.title)
        });
      })
      .catch(function(err) {
        wx.hideLoading();
        wx.showToast({ title: err?.error || '创建失败', icon: 'none' });
      });
  },
});
