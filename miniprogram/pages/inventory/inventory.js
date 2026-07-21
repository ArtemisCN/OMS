const api = require('../../utils/api');

Page({
  data: {
    tasks: [],
    loading: true,
    showCreate: false,
    taskName: '',
    totalScanned: 0,  // 预计算总数
    totalCount: 0,    // 预计算应盘点数
  },

  onLoad() {
    this.loadTasks();
  },

  onShow() {
    this.loadTasks();
  },

  loadTasks() {
    this.setData({ loading: true });
    api.get('/inventory/tasks')
      .then((res) => {
        const tasks = res.tasks || [];
        let totalScanned = 0;
        let totalCount = 0;
        tasks.forEach(function(t) {
          totalScanned += t.scanned_count || 0;
          totalCount += t.total_count || 0;
        });
        this.setData({ tasks: tasks, totalScanned: totalScanned, totalCount: totalCount, loading: false });
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: err?.error || '加载失败', icon: 'none' });
      });
  },

  onNewTask() {
    this.setData({ showCreate: true, taskName: '' });
  },

  onCancelCreate() {
    this.setData({ showCreate: false });
  },

  onTaskNameInput(e) {
    this.setData({ taskName: e.detail.value });
  },

  onCreateSubmit() {
    const name = this.data.taskName.trim();
    if (!name) {
      wx.showToast({ title: '请输入盘点名称', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '创建中...' });
    api.post('/inventory/create', { name: name })
      .then((res) => {
        wx.hideLoading();
        if (res.ok) {
          wx.showToast({ title: '创建成功', icon: 'success' });
          this.setData({ showCreate: false });
          this.loadTasks();
        } else {
          wx.showToast({ title: res.error || '创建失败', icon: 'none' });
        }
      })
      .catch((err) => {
        wx.hideLoading();
        wx.showToast({ title: err?.error || '创建失败', icon: 'none' });
      });
  },

  onTaskTap(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/inventory/scan?task_id=' + id });
  },
});
