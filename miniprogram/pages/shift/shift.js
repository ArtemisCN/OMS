const api = require('../../utils/api');

Page({
  data: {
    loading: true,
    tab: 'create',
    handovers: [],
    persons: [],
    unreadCount: 0,
    hasMore: false,
    page: 1,
    // form
    handoverPerson: '',
    receivePerson: '',
    content: '',
    notes: '',
    photos: [],
    submitting: false,
    // 工单选择
    showOrderPicker: false,
    myOrders: [],
    selectedOrderIds: [],
  },

  onLoad() {
    this.loadHistory();
    this.loadPersons();
    // 默认交班人为当前登录用户
    var app = getApp();
    var userInfo = app.globalData.user || wx.getStorageSync('user') || {};
    this.setData({ handoverPerson: userInfo.display_name || userInfo.username || '' });
  },

  onShow() {
    // 切回页面时刷新未读数
    this.loadHistory(true);
  },

  loadPersons() {
    api.get('/shift-handovers?page=1').then((res) => {
      this.setData({ persons: res.persons || [] });
    }).catch(() => {});
  },

  loadHistory(silent) {
    if (!silent) this.setData({ loading: true });
    api.get('/shift-handovers?page=1').then((res) => {
      this.setData({
        handovers: res.handovers || [],
        unreadCount: res.unread_count || 0,
        hasMore: res.has_more || false,
        page: 1,
        loading: false,
      });
    }).catch(() => {
      this.setData({ loading: false });
      if (!silent) wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  onSwitchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ tab: tab });
    if (tab === 'history') {
      // 切到历史tab → 标记已读
      this.markRead();
      if (this.data.handovers.length === 0) this.loadHistory();
    }
  },

  markRead() {
    api.post('/shift-handovers/mark-read', {}).then(() => {
      this.setData({ unreadCount: 0 });
    }).catch(() => {});
  },

  onLoadMore() {
    if (!this.data.hasMore) return;
    var nextPage = this.data.page + 1;
    api.get('/shift-handovers?page=' + nextPage).then((res) => {
      this.setData({
        handovers: this.data.handovers.concat(res.handovers || []),
        hasMore: res.has_more || false,
        page: nextPage,
      });
    }).catch(() => {});
  },

  onContentInput(e) { this.setData({ content: e.detail.value }); },
  onNotesInput(e) { this.setData({ notes: e.detail.value }); },

  onAddPhoto() {
    var self = this;
    wx.chooseImage({
      count: 9,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: function(res) {
        var files = res.tempFilePaths || [];
        if (files.length === 0) return;
        wx.showLoading({ title: '上传中...' });
        var uploaded = [];
        var tasks = files.map(function(fp) {
          return api.uploadChatFile(fp).then(function(r) {
            uploaded.push(r.url);
          });
        });
        Promise.all(tasks).then(function() {
          wx.hideLoading();
          var existing = self.data.photos || [];
          self.setData({ photos: existing.concat(uploaded) });
        }).catch(function() {
          wx.hideLoading();
          wx.showToast({ title: '上传失败', icon: 'none' });
        });
      }
    });
  },

  onDelPhoto(e) {
    var idx = e.currentTarget.dataset.index;
    var photos = this.data.photos;
    photos.splice(idx, 1);
    this.setData({ photos: photos });
  },

  onPreviewPhoto(e) {
    var src = e.currentTarget.dataset.src;
    var all = this.data.photos || [];
    if (all.length === 0) all = [src];
    if (all.indexOf(src) < 0) all = [src];
    wx.previewImage({ urls: all, current: src });
  },

  // ========== 工单选择 ==========

  onPickOrders() {
    var self = this;
    wx.showLoading({ title: '加载工单...' });
    api.get('/shift-handovers/my-orders').then((res) => {
      wx.hideLoading();
      self.setData({
        myOrders: res.orders || [],
        showOrderPicker: true,
      });
    }).catch(() => {
      wx.hideLoading();
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  onToggleOrder(e) {
    var oid = parseInt(e.currentTarget.dataset.id);
    var selected = this.data.selectedOrderIds.slice();
    var idx = selected.indexOf(oid);
    if (idx >= 0) {
      selected.splice(idx, 1);
    } else {
      selected.push(oid);
    }
    this.setData({ selectedOrderIds: selected });
  },

  onCloseOrderPicker() {
    this.setData({ showOrderPicker: false });
  },

  onConfirmOrders() {
    this.setData({ showOrderPicker: false });
  },

  onTapOrder(e) {
    var oid = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/order/order?id=' + oid
    });
  },

  // ========== 提交 ==========

  onSubmit() {
    const { handoverPerson, receivePerson, content, photos, selectedOrderIds } = this.data;
    if (!handoverPerson || !receivePerson) {
      wx.showToast({ title: '请选择交班人和接班人', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    api.post('/shift-handovers', {
      handover_person: handoverPerson,
      receive_person: receivePerson,
      content: content,
      notes: this.data.notes,
      photos: photos,
      work_order_ids: selectedOrderIds,
    }).then((res) => {
      wx.showToast({ title: '交接班记录已保存', icon: 'success' });
      this.setData({
        handoverPerson: '', receivePerson: '', content: '', notes: '', photos: [],
        selectedOrderIds: [], submitting: false, tab: 'history',
      });
      // 重新加载自己信息到交班人
      var app = getApp();
      var userInfo = app.globalData.user || wx.getStorageSync('user') || {};
      this.setData({ handoverPerson: userInfo.display_name || userInfo.username || '' });
      this.markRead();
      this.loadHistory();
    }).catch(() => {
      this.setData({ submitting: false });
      wx.showToast({ title: '保存失败', icon: 'none' });
    });
  },

  onPickerChange(e) {
    const field = e.currentTarget.dataset.field;
    const idx = e.detail.value;
    const persons = this.data.persons;
    this.setData({ [field]: persons[idx].name });
  },

  onGoBack() {
    wx.navigateBack();
  },

  noop() {},
});
