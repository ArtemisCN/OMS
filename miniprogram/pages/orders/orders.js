const api = require('../../utils/api');
const { formatStatus, formatStatusBadge } = require('../../utils/util');
const CACHE_TTL = 15000;
const PENDING_POLL_INTERVAL = 10000;

const SUBSCRIBE_TEMPLATE_ID = '8e6hx9PlAdNQ12KsDuwrisPlbJV6g2O8pbjpTcfgbqU';

Page({
  data: {
    util: { formatStatus, formatStatusBadge },
    activeTab: 'pending',
    orders: [],
    loading: true,
    splash: false,
    stats: { pending: 0, in_progress: 0, completed: 0, completed_today: 0 },
    user: {},
    subscribed: false,
  },

  _prevPending: 0,
  _lastPersistTime: 0,

  onLoad() {
    const app = getApp();
    // ⚡ 从 app 同步恢复缓存（app.onLaunch 已提前从 storage 恢复）
    const tab = this.data.activeTab;
    const cache = app.globalData.ordersCache[tab];
    if (cache) {
      this._prevPending = cache.stats?.pending || 0;
      this.setData({
        orders: cache.orders || [],
        stats: cache.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 },
        user: app.globalData.user,
        loading: false,
        splash: false,
      });
      // 后台静默刷新
      this.fetchOrders(true);
    } else {
      // 首次安装，完全无缓存 → 显示 splash
      this.setData({ splash: true, user: app.globalData.user });
      this.fetchOrders(false);
    }
  },

  onShow() {
    // 从后台切回时，只静默刷新，不弹 loading
    this.fetchOrders(true);
    this.startPendingPoll();
  },

  onHide() {
    this.stopPendingPoll();
  },

  onUnload() {
    this.stopPendingPoll();
  },

  checkSubscribeStatus() {
    api.getSubscribeStatus().then((res) => {
      this.setData({ subscribed: !!res.subscribed });
    }).catch(() => {});
  },

  onSubscribe() {
    if (!SUBSCRIBE_TEMPLATE_ID) {
      wx.showToast({ title: '未配置模板ID', icon: 'none' });
      return;
    }
    wx.requestSubscribeMessage({
      tmplIds: [SUBSCRIBE_TEMPLATE_ID],
      success: (res) => {
        if (res[SUBSCRIBE_TEMPLATE_ID] === 'accept') {
          api.subscribe(SUBSCRIBE_TEMPLATE_ID).then(() => {
            this.setData({ subscribed: true });
            wx.showToast({ title: '订阅成功 🔔', icon: 'success' });
          }).catch((err) => {
            wx.showToast({ title: err?.error || '订阅失败', icon: 'none' });
          });
        } else {
          this.setData({ subscribed: false });
          api.unsubscribe().catch(() => {});
          wx.showToast({ title: '已关闭通知', icon: 'none' });
        }
      },
      fail: () => {
        wx.showToast({ title: '订阅请求失败', icon: 'none' });
      },
    });
  },

  startPendingPoll() {
    this.stopPendingPoll();
    if (this.data.activeTab === 'pending') {
      this._pendingTimer = setInterval(() => {
        this.fetchOrders(true);
      }, PENDING_POLL_INTERVAL);
    }
  },

  stopPendingPoll() {
    if (this._pendingTimer) {
      clearInterval(this._pendingTimer);
      this._pendingTimer = null;
    }
  },

  fetchOrders(silent) {
    const tab = this.data.activeTab;
    const apiStatus = tab === 'completed' ? 'completed_today' : tab;
    return api.getOrders(apiStatus)
      .then((res) => {
        const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
        const app = getApp();
        app.globalData.ordersCache[tab] = {
          orders: res.orders || [],
          stats: stats,
          time: Date.now(),
        };
        this.setData({ orders: res.orders || [], stats: stats, loading: false, splash: false });

        // 节流持久化（每30秒一次）
        const now = Date.now();
        if (now - this._lastPersistTime > 30000) {
          this._lastPersistTime = now;
          wx.setStorage({ key: 'ordersCache', data: app.globalData.ordersCache });
        }

        if (silent && app.globalData.ordersCache.pending?.stats) {
          const oldCount = this._prevPending;
          const newCount = app.globalData.ordersCache.pending.stats.pending || 0;
          this._prevPending = newCount;
          if (newCount > oldCount && oldCount > 0) {
            wx.showToast({ title: '📋 有新工单！', icon: 'none', duration: 2000 });
            wx.vibrateShort({ type: 'medium' });
          }
        }
      })
      .catch((err) => {
        if (!silent) {
          var msg = '加载失败';
          if (err && err.code === 401) {
            this.setData({ loading: false, splash: false });
            return;
          }
          if (err && err.errMsg && err.errMsg.indexOf('timeout') > -1) msg = '加载超时，请检查网络';
          else if (err && err.error) msg = err.error;
          wx.showToast({ title: msg, icon: 'none' });
        }
        this.setData({ loading: false, splash: false });
      });
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    const app = getApp();
    const cache = app.globalData.ordersCache[tab];

    // ⚡ 立即显示缓存，不设 loading
    if (cache && (Date.now() - cache.time) < CACHE_TTL) {
      this.setData({
        activeTab: tab,
        orders: cache.orders || [],
        stats: cache.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 },
        loading: false,
      });
      this.fetchOrders(true);
    } else {
      this.setData({ activeTab: tab, orders: cache?.orders || [], loading: false });
      const apiStatus = tab === 'completed' ? 'completed_today' : tab;
      api.getOrders(apiStatus).then((res) => {
        const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
        app.globalData.ordersCache[tab] = {
          orders: res.orders || [],
          stats: stats,
          time: Date.now(),
        };
        this.setData({ orders: res.orders || [], stats: stats, loading: false });
        const _now = Date.now();
        if (_now - this._lastPersistTime > 30000) {
          this._lastPersistTime = _now;
          wx.setStorage({ key: 'ordersCache', data: app.globalData.ordersCache });
        }
      });
    }
    if (tab === 'pending') {
      this.startPendingPoll();
    } else {
      this.stopPendingPoll();
    }
  },

  onOrderTap(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/order/order?id=' + id });
  },

  onQuickSolve(e) {
    const id = e.currentTarget.dataset.id;
    const order = this.data.orders.find(o => o.id === id);
    if (!order) return;

    wx.showLoading({ title: '结单中...' });
    api.getMatchingTemplate(order.title)
      .then((res) => {
        const template = res.template;
        const solution = template ? template.content : '经现场处理，' + order.title + '，问题已解决。';
        return api.solveOrder(id, solution);
      })
      .then(() => {
        wx.hideLoading();
        wx.showToast({ title: '✅ 已结单', icon: 'success' });
        this.fetchOrders(false);
      })
      .catch((err) => {
        wx.hideLoading();
        wx.showToast({ title: err?.error || '结单失败', icon: 'none' });
      });
  },

  onTodaySummary() {
    const count = this.data.stats.completed_today;
    if (count === 0) {
      wx.showToast({ title: '今日暂无已完成工单', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '生成中...' });
    api.getTodaySummary()
      .then((res) => {
        wx.hideLoading();
        if (res.summary) {
          wx.setClipboardData({
            data: res.summary,
            success: () => {
              wx.showToast({ title: '✅ 已复制到剪贴板', icon: 'success' });
            },
            fail: () => {
              wx.showToast({ title: '复制失败', icon: 'none' });
            }
          });
        }
      })
      .catch((err) => {
        wx.hideLoading();
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  onLogout() {
    wx.showModal({
      title: '确认退出',
      content: '确定要退出登录吗？',
      success: (res) => {
        if (res.confirm) {
          api.logout().catch(() => {});
          wx.removeStorageSync('token');
          wx.removeStorageSync('user');
          wx.removeStorageSync('ordersCache');
          wx.reLaunch({ url: '/pages/login/login' });
        }
      },
    });
  },

  // ⋮ 更多菜单：订阅通知 + 退出
  onMore() {
    const subscribed = this.data.subscribed;
    const items = [subscribed ? '🔔 已订阅' : '🔕 订阅通知', '🎓 在线考试', '🚪 退出登录'];
    wx.showActionSheet({
      itemList: items,
      success: (res) => {
        if (res.tapIndex === 0) {
          this.onSubscribe();
        } else if (res.tapIndex === 1) {
          this.onExam();
        } else if (res.tapIndex === 2) {
          this.onLogout();
        }
      },
    });
  },

  // 浮动发布按钮 / 顶栏加号
  onFabPublish() {
    wx.navigateTo({ url: '/pages/publish/publish' });
  },

  // 盘点入口
  onInventory() {
    wx.navigateTo({ url: '/pages/inventory/inventory' });
  },

  // 考试入口
  onExam() {
    wx.navigateTo({ url: '/pages/exam/exam' });
  },

  onBindWx() {
    wx.login({
      success: (res) => {
        if (!res.code) return;
        wx.showLoading({ title: '绑定中...' });
        api.bindWx(res.code)
          .then(() => {
            wx.hideLoading();
            wx.showToast({ title: '微信绑定成功 ✅', icon: 'success' });
            const user = wx.getStorageSync('user') || {};
            user.wx_bound = true;
            wx.setStorageSync('user', user);
            this.setData({ 'user.wx_bound': true });
          })
          .catch((err) => {
            wx.hideLoading();
            wx.showToast({ title: err && err.error ? err.error : '绑定失败', icon: 'none' });
          });
      },
      fail: () => {
        wx.showToast({ title: '获取微信信息失败', icon: 'none' });
      },
    });
  },
});
