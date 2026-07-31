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
    unreadCount: 0,
    page: 1,
    hasMore: true,
    loadingMore: false,
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
    // 刷新用户信息（头像等可能已变更）
    var app = getApp();
    var user = wx.getStorageSync('user') || app.globalData.user || {};
    app.globalData.user = user;
    this.setData({ user: user });
    // 从后台切回时，只静默刷新，不弹 loading
    this.fetchOrders(true);
    this.startPendingPoll();
    this.startUnreadPoll();
    // 立即刷新未读（聊完回来立刻更新红点）
    var self = this;
    api.getUnreadCount().then(function(res) {
      self.setData({ unreadCount: res.total_unread || 0 });
    }).catch(function() {});
  },

  onHide() {
    this.stopPendingPoll();
    this.stopUnreadPoll();
  },

  onUnload() {
    this.stopPendingPoll();
    this.stopUnreadPoll();
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
    // 未登录不轮询
    if (!wx.getStorageSync('token')) return;
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

  fetchOrders(silent, page) {
    const tab = this.data.activeTab;
    const apiStatus = tab === 'completed' ? 'completed_today' : tab;
    page = page || 1;
    return api.getOrders(apiStatus, page)
      .then((res) => {
        const stats = res.stats || { pending: 0, in_progress: 0, completed: 0, completed_today: 0 };
        const app = getApp();
        const newOrders = res.orders || [];
        const isFirstPage = page <= 1;
        const orders = isFirstPage ? newOrders : (this.data.orders || []).concat(newOrders);
        const pagination = res.pagination || { page: page, has_more: false };
        if (isFirstPage) {
          app.globalData.ordersCache[tab] = {
            orders: newOrders,
            stats: stats,
            time: Date.now(),
          };
        }
        this.setData({
          orders: orders,
          stats: stats,
          loading: false,
          splash: false,
          page: page,
          hasMore: !!pagination.has_more,
          loadingMore: false,
        });

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
        this.setData({ loading: false, splash: false, loadingMore: false });
      });
  },

  // 触底加载更多
  onReachBottom() {
    if (this.data.loading || this.data.loadingMore || !this.data.hasMore) return;
    this.setData({ loadingMore: true });
    this.fetchOrders(true, this.data.page + 1);
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
      this.setData({ activeTab: tab, orders: cache?.orders || [], loading: false, page: 1, hasMore: true });
      this.fetchOrders(false);
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
    const items = [subscribed ? '🔔 已订阅' : '🔕 订阅通知', '🚪 退出登录'];
    wx.showActionSheet({
      itemList: items,
      success: (res) => {
        if (res.tapIndex === 0) {
          this.onSubscribe();
        } else if (res.tapIndex === 1) {
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

  onWorkbench() {
    wx.navigateTo({ url: '/pages/workbench/workbench' });
  },

  onDuty() {
    wx.navigateTo({ url: '/pages/duty/duty' });
  },

  onShift() {
    wx.navigateTo({ url: '/pages/shift/shift' });
  },

  // ===== 聊天 =====

  onChat() {
    wx.navigateTo({ url: '/pages/chat/chat' });
  },

  startUnreadPoll() {
    // 未登录不轮询
    if (!wx.getStorageSync('token')) return;
    var self = this;
    this._unreadTimer = setInterval(function() {
      api.getUnreadCount().then(function(res) {
        var count = res.total_unread || 0;
        self.setData({ unreadCount: count });
      }).catch(function() {});
    }, 10000);
  },

  stopUnreadPoll() {
    if (this._unreadTimer) {
      clearInterval(this._unreadTimer);
      this._unreadTimer = null;
    }
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
