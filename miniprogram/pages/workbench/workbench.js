const api = require('../../utils/api');

Page({
  data: {
    loading: true,
    stats: null,
  },

  onLoad() {
    this.loadData();
  },

  onShow() {
    // 后台切回时静默刷新
    if (this.data.stats) this.loadData(true);
  },

  loadData(silent) {
    if (silent) {
      api.get('/workbench').then((res) => {
        this.setData({ stats: res });
      }).catch(() => {});
      return;
    }
    this.setData({ loading: true });
    api.get('/workbench').then((res) => {
      this.setData({ stats: res, loading: false });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  onGoOrders() {
    wx.navigateBack();
  },

  onChangeAvatar() {
    wx.navigateTo({ url: '/pages/avatar/avatar' });
  },
});
