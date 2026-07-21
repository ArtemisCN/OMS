const api = require('../../utils/api');

Page({
  data: {
    username: '',
    password: '',
    loading: false,
    bindWxAfterLogin: false,  // 是否显示绑定微信按钮
    wxCode: '',
  },

  onLoad() {
    // 如果已有 token，直接跳首页
    const token = wx.getStorageSync('token');
    if (token) {
      wx.reLaunch({ url: '/pages/orders/orders' });
    }
  },

  onInputUsername(e) {
    this.setData({ username: e.detail.value });
  },

  onInputPassword(e) {
    this.setData({ password: e.detail.value });
  },

  onLogin() {
    const { username, password } = this.data;
    if (!username || !password) {
      wx.showToast({ title: '请输入用户名和密码', icon: 'none' });
      return;
    }

    this.setData({ loading: true });
    api.login(username, password)
      .then((res) => {
        wx.setStorageSync('token', res.token);
        wx.setStorageSync('user', res.user);

        if (res.user.wx_bound) {
          // 已绑定微信，直接进
          wx.reLaunch({ url: '/pages/orders/orders' });
        } else {
          // 未绑定微信，尝试绑定
          this.tryBindWx(res.token);
        }
      })
      .catch((err) => {
        wx.showToast({
          title: err && err.error ? err.error : '登录失败',
          icon: 'none',
        });
        this.setData({ loading: false });
      });
  },

  tryBindWx(token) {
    // 获取 wx.login code 用于绑定
    wx.login({
      success: (res) => {
        if (res.code) {
          api.bindWx(res.code)
            .then(() => {
              wx.showToast({ title: '微信已自动绑定 ✅', icon: 'success' });
              const user = wx.getStorageSync('user') || {};
              user.wx_bound = true;
              wx.setStorageSync('user', user);
            })
            .catch(() => {
              // 绑定失败（可能没配 appid/secret），不影响正常使用
            })
            .finally(() => {
              wx.reLaunch({ url: '/pages/orders/orders' });
            });
        } else {
          this.setData({ loading: false });
          wx.reLaunch({ url: '/pages/orders/orders' });
        }
      },
      fail: () => {
        this.setData({ loading: false });
        wx.reLaunch({ url: '/pages/orders/orders' });
      },
    });
  },
});
