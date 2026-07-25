const api = require('../../utils/api');

Page({
  data: {
    loading: true,
    records: {},
    todayDuty: [],
    year: 0,
    month: 0,
    days: [],
    staff: [],
    today: '',
    scrollToHd: '',
  },

  onLoad() {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;
    this.setData({ year: y, month: m, today: now.toISOString().slice(0, 10) });
    this.loadData(y, m);
  },

  loadData(year, month) {
    this.setData({ loading: true });
    const days = this._getDays(year, month);
    var self = this;
    api.get('/duty-schedules?year=' + year + '&month=' + month).then((res) => {
      const records = res.records || {};
      // 只显示自己所属组员
      const app = getApp();
      const user = app.globalData.user || {};
      const myTeam = user.team || '';
      const staffSet = new Set();
      for (const key in records) {
        const name = key.split('_')[0];
        if (name) staffSet.add(name);
      }
      // 按用户所属组筛选值班人员（后端已过滤，前端只展示）
      var staff = Array.from(staffSet);
      // 保存当前滚动位置
      var targetHd = 'hd-today';
      if (this.data.scrollToHd && this.data.scrollToHd.indexOf('hd-day-') === 0) {
        targetHd = this.data.scrollToHd;
      }
      this.setData({
        records: records,
        todayDuty: res.today || [],
        days: days,
        staff: staff,
        loading: false,
        scrollToHd: targetHd,
      });
    }).catch(() => {
      this.setData({
        records: {},
        todayDuty: [],
        days: days,
        staff: [],
        loading: false,
      });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  _getDays(year, month) {
    const days = [];
    const total = new Date(year, month, 0).getDate();
    for (let d = 1; d <= total; d++) {
      const dateStr = year + '-' + String(month).padStart(2, '0') + '-' + String(d).padStart(2, '0');
      const dow = new Date(year, month - 1, d).getDay();
      const dowLabels = ['日','一','二','三','四','五','六'];
      days.push({ day: d, date: dateStr, dow: dow, dowLabel: dowLabels[dow], md: String(month) + '/' + String(d), isWeekend: dow === 0 || dow === 6, isToday: dateStr === this.data.today });
    }
    return days;
  },

  onPrevMonth() {
    let { year, month } = this.data;
    month--;
    if (month < 1) { month = 12; year--; }
    this.setData({ year, month });
    this.loadData(year, month);
  },

  onNextMonth() {
    let { year, month } = this.data;
    month++;
    if (month > 12) { month = 1; year++; }
    this.setData({ year, month });
    this.loadData(year, month);
  },

  onGoToday() {
    const now = new Date();
    this.setData({ year: now.getFullYear(), month: now.getMonth() + 1 });
    this.loadData(now.getFullYear(), now.getMonth() + 1);
  },

  onGoBack() {
    wx.navigateBack();
  },
});
