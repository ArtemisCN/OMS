const api = require('../../utils/api');

Page({
  data: { exams: [], history: [], loading: true, showHistory: false },

  onLoad() { this.loadExams(); },
  onShow() { this.loadExams(); },

  loadExams() {
    this.setData({ loading: true });
    api.get('/exam/list')
      .then((res) => {
        const exams = (res.exams || []).filter((e) => e.can_start);
        const history = (res.exams || []).filter((e) => !e.can_start && e.last_score !== null);
        this.setData({ exams: exams, history: history, loading: false });
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  goExam(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/exam/take?exam_id=' + id });
  },

  toggleHistory() {
    this.setData({ showHistory: !this.data.showHistory });
  },

  onPullDownRefresh() {
    this.loadExams();
    wx.stopPullDownRefresh();
  }
});
