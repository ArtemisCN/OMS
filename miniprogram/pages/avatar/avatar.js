const api = require('../../utils/api');

Page({
  data: {
    groups: [
      { label: '🎨 卡通冒险', key: 'adv', avatars: [
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Kitty&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Max&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Luna&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Charlie&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Molly&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Cooper&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Daisy&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/adventurer/svg?seed=Buddy&backgroundColor=fde68a',
      ]},
      { label: '✨ 可爱动漫', key: 'anime', avatars: [
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Alice&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Bob&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Coral&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Dean&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Eve&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Finn&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Gina&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/lorelei/svg?seed=Hank&backgroundColor=fde68a',
      ]},
      { label: '🐾 动物表情', key: 'animal', avatars: [
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Cat&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Dog&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Fox&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Bear&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Panda&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Rabbit&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Lion&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/fun-emoji/svg?seed=Koala&backgroundColor=fde68a',
      ]},
      { label: '👾 像素角色', key: 'pixel', avatars: [
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Hero&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Ninja&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Wizard&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Knight&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Elf&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Dwarf&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Dragon&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/pixel-art/svg?seed=Robot&backgroundColor=fde68a',
      ]},
      { label: '🎭 卡通角色', key: 'char', avatars: [
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Sunny&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Rain&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Star&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Cloud&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Moon&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Wave&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Flame&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/avataaars/svg?seed=Storm&backgroundColor=fde68a',
      ]},
      { label: '🎪 趣味插画', key: 'peeps', avatars: [
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Happy&backgroundColor=b6e3f4',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Smile&backgroundColor=ffd5dc',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Chill&backgroundColor=c0aede',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Wink&backgroundColor=d1d4f9',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Cozy&backgroundColor=ffdfbf',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Bliss&backgroundColor=fecaca',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Dream&backgroundColor=bbf7d0',
        'https://api.dicebear.com/9.x/open-peeps/svg?seed=Zen&backgroundColor=fde68a',
      ]},
    ],
    userAvatar: '',
  },

  onLoad() {
    var app = getApp();
    var user = app.globalData.user || {};
    this.setData({ userAvatar: user.avatar || '' });
  },

  onSelect(e) {
    var src = e.currentTarget.dataset.src;
    var self = this;
    wx.showLoading({ title: '设置中...' });
    api.post('/avatar/select', { avatar: src }).then(function() {
      wx.hideLoading();
      self.setData({ userAvatar: src });
      var app = getApp();
      app.globalData.user.avatar = src;
      wx.setStorageSync('user', app.globalData.user);
      wx.showToast({ title: '✅ 头像已更换', icon: 'success' });
    }).catch(function(err) {
      wx.hideLoading();
      wx.showToast({ title: err?.error || '设置失败', icon: 'none' });
    });
  },
});
