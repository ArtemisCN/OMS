const api = require('./utils/api');

/** 全局兜底：静默吞掉 SDK 级的网络超时错误，不污染控制台 */
if (typeof wx.onUnhandledRejection === 'function') {
  wx.onUnhandledRejection((res) => {
    if (res && res.reason && typeof res.reason === 'object') {
      var msg = res.reason.message || res.reason.errMsg || '';
      if (msg.indexOf('timeout') > -1) {
        console.warn('[timeout]', res.reason);
        return;
      }
    }
  });
}

App({
  globalData: {
    ordersCache: {},
    user: {},
  },

  onLaunch() {
    const token = wx.getStorageSync('token');
    if (!token) {
      wx.redirectTo({ url: '/pages/login/login' });
      return;
    }
    const stored = wx.getStorageSync('ordersCache');
    if (stored) {
      this.globalData.ordersCache = stored;
    }
    const user = wx.getStorageSync('user');
    if (user) {
      this.globalData.user = user;
    }
    this._prefetchOrders();
  },

  _prefetchOrders() {
    api.getOrders('pending').then((res) => {
      const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
      this.globalData.ordersCache.pending = {
        orders: res.orders || [],
        stats: stats,
        time: Date.now(),
      };
    }).catch(() => {});
    api.getOrders('in_progress').then((res) => {
      const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
      this.globalData.ordersCache.in_progress = {
        orders: res.orders || [],
        stats: stats,
        time: Date.now(),
      };
    }).catch(() => {});
    api.getOrders('completed_today').then((res) => {
      const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
      this.globalData.ordersCache.completed = {
        orders: res.orders || [],
        stats: stats,
        time: Date.now(),
      };
    }).catch(() => {});
  },
});
