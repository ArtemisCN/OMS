const api = require('../../utils/api');
const { formatStatus } = require('../../utils/util');

Page({
  data: { dsCache: {},
    util: { formatStatus },
    order: null,
    form: null,
    formData: {},       // inline form field values
    formSubmitting: false,
    solution: '',
    matchedTemplate: null,
    canSubmit: false,
    loading: true,
    submitting: false,
    showSignaturePad: false,
    signatureData: '',
    // form signature inline
    showFormSigPad: false,
    formSigFieldId: '',
    formSigData: '',
    // 转派人选选择器
    showPersonnelPicker: false,
    personnelList: [],
    personnelLoading: false,
    showTransfersModal: false,
    transferLogs: [],
    // 工单图片
    photos: [],
    uploading: false,
  },

  _ctx: null,
  _isDrawing: false,
  _sigRect: null,
  _formSigCtx: null,
  _formSigIsDrawing: false,
  _formSigRect: null,
  _saveTimer: null,

  onLoad(options) {
    const orderId = options.id;
    if (!orderId) {
      wx.showToast({ title: '参数错误', icon: 'none' });
      return;
    }
    this.loadOrder(orderId);
  },

  onShareAppMessage() {
    var order = this.data.order;
    if (!order) return { title: '工单详情' };
    return {
      title: order.title || '工单详情',
      path: '/pages/order/order?id=' + order.id,
    };
  },

  onShareTimeline() {
    var order = this.data.order;
    if (!order) return { title: '工单详情' };
    return {
      title: order.title || '工单详情',
      query: 'id=' + order.id,
    };
  },

  loadOrder(orderId) {
    this.setData({ loading: true });
    api.getOrderDetail(orderId)
      .then((res) => {
        const order = res.order;
        const form = res.form || null;
        // Initialize formData from form
        var formData = {};
        if (form && form.form_data) {
          formData = JSON.parse(JSON.stringify(form.form_data));
        }
        this.setData({ order: order, form: form, formData: formData, loading: false });
        this._updateFormDisplayVals();
        wx.setNavigationBarTitle({ title: order.title });
        this.loadPhotos();
        if (order.title) {
          api.getMatchingTemplate(order.title).then((tmplRes) => {
            if (tmplRes.template) {
              this.setData({ matchedTemplate: tmplRes.template });
            }
          }).catch(() => {});
        }
      })
      .catch((err) => {
        var msg = '加载失败';
        if (err && err.code === 401) {
          // 401 静默，request 函数已处理跳转登录
          this.setData({ loading: false });
          return;
        }
        if (err && err.errMsg && err.errMsg.indexOf('timeout') > -1) msg = '加载超时，请检查网络';
        else if (err && err.error) msg = err.error;
        wx.showToast({ title: msg, icon: 'none' });
        this.setData({ loading: false });
      });
  },

  onInputSolution(e) {
    const val = e.detail.value;
    this.setData({
      solution: val,
      canSubmit: val.trim().length > 0,
    });
  },

  onFillTemplate() {
    const tmpl = this.data.matchedTemplate;
    if (!tmpl) return;
    this.setData({
      solution: tmpl.content,
      canSubmit: true,
    });
  },

  onAccept() {
    const order = this.data.order;
    if (!order) return;

    wx.showModal({
      title: '确认接单',
      content: '确定要接取此工单吗？',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({ submitting: true });
        api.acceptOrder(order.id)
          .then((res) => {
            wx.showToast({ title: '接单成功 ✅', icon: 'success' });
            this.loadOrder(order.id);
          })
          .catch((err) => {
            wx.showToast({
              title: err && err.error ? err.error : '接单失败',
              icon: 'none',
            });
          })
          .finally(() => {
            this.setData({ submitting: false });
          });
      },
    });
  },

  onSolve() {
    const order = this.data.order;
    if (!order) return;
    const solution = this.data.solution.trim();

    if (!solution) {
      wx.showToast({ title: '请填写解决方案', icon: 'none' });
      return;
    }

    wx.showModal({
      title: '确认完成',
      content: '提交后将标记为已完成，确认吗？',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({ submitting: true });
        api.solveOrder(order.id, solution)
          .then((res) => {
            wx.showToast({ title: '完成提交 ✅', icon: 'success' });
            this.loadOrder(order.id);
          })
          .catch((err) => {
            wx.showToast({
              title: err && err.error ? err.error : '提交失败',
              icon: 'none',
            });
          })
          .finally(() => {
            this.setData({ submitting: false });
          });
      },
    });
  },

  onToggleInspectionItem(e) {
    const idx = e.currentTarget.dataset.index;
    const order = this.data.order;
    if (!order || !order.inspection_data || !order.inspection_data.items) return;
    const items = order.inspection_data.items;
    const item = items[idx];
    const newResult = item.result === true ? false : item.result === false ? null : true;
    const newItems = items.map((it, i) => i === idx ? { ...it, result: newResult } : it);
    this.setData({ 'order.inspection_data.items': newItems });
  },

  // ========== 电子表单内联操作 ==========

  onFormInput(e) {
    const fid = e.currentTarget.dataset.fid;
    const val = e.detail.value;
    var key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._updateFormDisplayVals();
    this._scheduleFormSave(fid, val);
  },

  onFormPickerChange(e) {
    const fid = e.currentTarget.dataset.fid;
    const idx = e.detail.value;
    var fields = this.data.form.fields_json || [];
    var field = fields.find(function(f) { return f.id === fid; });
    if (!field || !field.options) return;
    var val = field.options[idx] || '';
    var key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._updateFormDisplayVals();
    this._scheduleFormSave(fid, val);
  },

  onFormRadioChange(e) {
    const fid = e.currentTarget.dataset.fid;
    const val = e.detail.value;
    var key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._updateFormDisplayVals();
    this._scheduleFormSave(fid, val);
  },

  // ========== 工单图片 ==========

  loadPhotos() {
    var order = this.data.order;
    if (!order) return;
    api.getPhotos(order.id).then((res) => {
      this.setData({ photos: res.photos || [] });
    }).catch(() => {});
  },

  onAddPhotos() {
    var self = this;
    wx.chooseMedia({
      count: 9,
      mediaType: ['image'],
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        var files = res.tempFiles || [];
        if (files.length === 0) return;
        var filePaths = files.map(function(f) { return f.tempFilePath; });
        self.setData({ uploading: true });
        wx.showLoading({ title: '上传中 0/' + filePaths.length, mask: true });
        var order = self.data.order;
        api.uploadPhotos(order.id, filePaths).then((result) => {
          wx.hideLoading();
          self.setData({ uploading: false });
          wx.showToast({ title: result.message || '上传完成', icon: 'success' });
          self.loadPhotos();
        }).catch((err) => {
          wx.hideLoading();
          self.setData({ uploading: false });
          wx.showToast({ title: '上传失败', icon: 'none' });
        });
      },
    });
  },

  onPreviewPhoto(e) {
    var idx = e.currentTarget.dataset.idx;
    var photos = this.data.photos;
    if (!photos || photos.length === 0) return;
    var urls = photos.map(function(p) { return 'https://demolin.cn' + p.url; });
    wx.previewImage({
      current: urls[idx] || urls[0],
      urls: urls,
    });
  },

  onDeletePhoto(e) {
    var id = e.currentTarget.dataset.id;
    var order = this.data.order;
    if (!id || !order) return;
    var self = this;
    wx.showModal({
      title: '删除图片',
      content: '确定要删除这张图片吗？',
      success: (res) => {
        if (!res.confirm) return;
        api.deletePhoto(order.id, id).then(() => {
          wx.showToast({ title: '已删除', icon: 'success' });
          self.loadPhotos();
        }).catch((err) => {
          wx.showToast({ title: '删除失败', icon: 'none' });
        });
      },
    });
  },

  _updateFormDisplayVals() {
    var formData = this.data.formData || {};
    var fields = (this.data.form && this.data.form.fields_json) || [];
    var dv = {};
    fields.forEach(function(f) {
      if (f.type === 'select' && f.options && f.options.length) {
        var idx = f.options.indexOf(formData[f.id] || '');
        dv[f.id + '_selectedIndex'] = idx > -1 ? idx : 0;
        dv[f.id + '_selectedLabel'] = idx > -1 ? formData[f.id] : (f.placeholder || f.options[0]);
      }
      if (f.type === 'signature') {
        var val = formData[f.id] || '';
        dv[f.id + '_hasImage'] = val.substring(0, 11) === 'data:image';
      }
    });
    this.setData({ _displayVals: dv });
  },

  onFormDateChange(e) {
    const fid = e.currentTarget.dataset.fid;
    const val = e.detail.value;
    var key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._scheduleFormSave(fid, val);
  },

  onFormCheckboxChange(e) {
    const fid = e.currentTarget.dataset.fid;
    const checked = e.detail.checked;
    var val = checked ? (e.currentTarget.dataset.val || 'on') : '';
    var key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._scheduleFormSave(fid, val);
  },

  _scheduleFormSave(fid, val) {
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this._doFormSave();
    }, 800);
  },

  _doFormSave() {
    var form = this.data.form;
    if (!form) return;
    var fd = {};
    Object.assign(fd, this.data.formData);
    api.saveFormData(form.id, fd).catch(function() {});
  },

  // 提交表单审批
  onSubmitForm() {
    if (this.data.formSubmitting) return;
    wx.showModal({
      title: '确认提交审批',
      content: '提交后将等待管理员审核，确认提交？',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({ formSubmitting: true });
        // Save first, then submit
        var form = this.data.form;
        if (!form) { this.setData({ formSubmitting: false }); return; }
        var fd = {};
        Object.assign(fd, this.data.formData);
        api.saveFormData(form.id, fd).then(function() {
          return api.submitForm(form.id);
        }).then(function() {
          wx.showToast({ title: '已提交审批 ✅', icon: 'success' });
          // Reload order detail
          if (this.loadOrder) this.loadOrder(form.work_order_id || this.data.order.id);
        }.bind(this)).catch(function(err) {
          wx.showToast({ title: (err && err.error) || '提交失败', icon: 'none' });
        }).finally(function() {
          this.setData({ formSubmitting: false });
        }.bind(this));
      },
    });
  },

  // ========== 表单签名（内联） ==========

  onFormSignatureTap(e) {
    const fid = e.currentTarget.dataset.fid;
    this.setData({
      showFormSigPad: true,
      formSigFieldId: fid,
      formSigData: '',
    }, () => {
      this._initFormSigCanvas();
    });
  },

  onFormSigClear() {
    this.setData({ formSigData: '' });
    if (this._formSigCtx) {
      this._formSigCtx.clearRect(0, 0, 300, 80);
    }
  },

  onFormSigCancel() {
    this.setData({ showFormSigPad: false, formSigFieldId: '' });
    this._formSigCtx = null;
    this._formSigIsDrawing = false;
  },

  onFormSigTouchStart(e) {
    const touch = e.touches[0];
    var self = this;
    const q = wx.createSelectorQuery();
    q.select('#formSigCanvas').boundingClientRect().exec(function(res) {
      if (!res || !res[0]) return;
      self._formSigRect = res[0];
      var ctx = self._formSigCtx;
      if (!ctx) return;
      ctx.beginPath();
      ctx.moveTo(touch.clientX - res[0].left, touch.clientY - res[0].top);
      self._formSigIsDrawing = true;
    });
  },

  onFormSigTouchMove(e) {
    if (!this._formSigIsDrawing || !this._formSigCtx || !this._formSigRect) return;
    const touch = e.touches[0];
    this._formSigCtx.lineTo(touch.clientX - this._formSigRect.left, touch.clientY - this._formSigRect.top);
    this._formSigCtx.stroke();
  },

  onFormSigTouchEnd() {
    this._formSigIsDrawing = false;
  },

  _initFormSigCanvas() {
    setTimeout(() => {
      const query = wx.createSelectorQuery();
      query.select('#formSigCanvas')
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res || !res[0]) {
            console.error('Form signature canvas not found');
            return;
          }
          const canvas = res[0].node;
          const ctx = canvas.getContext('2d');
          const dpr = wx.getWindowInfo().pixelRatio;
          const width = res[0].width;
          const height = res[0].height;
          canvas.width = width * dpr;
          canvas.height = height * dpr;
          ctx.scale(dpr, dpr);
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, width, height);
          ctx.strokeStyle = '#1e293b';
          ctx.lineWidth = 3;
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';
          this._formSigCtx = ctx;
          this._formSigIsDrawing = false;
          this._formSigRect = null;
          ctx.setLineDash([6, 6]);
          ctx.strokeStyle = '#d1d5db';
          ctx.beginPath();
          ctx.moveTo(20, height / 2);
          ctx.lineTo(width - 20, height / 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.strokeStyle = '#1e293b';
        });
    }, 300);
  },

  onFormSigConfirm() {
    const query = wx.createSelectorQuery();
    query.select('#formSigCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0]) return;
        const canvas = res[0].node;
        wx.canvasToTempFilePath({
          canvas: canvas,
          success: (tmpRes) => {
            const fs = wx.getFileSystemManager();
            const base64 = fs.readFileSync(tmpRes.tempFilePath, 'base64');
            const sigData = 'data:image/png;base64,' + base64;
            const fid = this.data.formSigFieldId;
            var key = 'formData.' + fid;
            this.setData({
              [key]: sigData,
              showFormSigPad: false,
              formSigFieldId: '',
            });
            this._updateFormDisplayVals();
            this._scheduleFormSave(fid, sigData);
            this._formSigCtx = null;
            this._formSigIsDrawing = false;
          },
          fail: () => {
            wx.showToast({ title: '签名获取失败', icon: 'none' });
          },
        });
      });
  },

  // ========== 巡检签名 ==========

  onSignatureTap() {
    this.setData({ showSignaturePad: true }, () => {
      this._initCanvas();
    });
  },

  onSignatureClear() {
    this.setData({ signatureData: '' });
  },

  onSignatureCancel() {
    this.setData({ showSignaturePad: false });
    this._ctx = null;
    this._isDrawing = false;
  },

  onSigTouchStart(e) {
    const touch = e.touches[0];
    var self = this;
    const q = wx.createSelectorQuery();
    q.select('#sigCanvas').boundingClientRect().exec(function(res) {
      if (!res || !res[0]) return;
      self._sigRect = res[0];
      var ctx = self._ctx;
      if (!ctx) return;
      ctx.beginPath();
      ctx.moveTo(touch.clientX - res[0].left, touch.clientY - res[0].top);
      self._isDrawing = true;
    });
  },

  onSigTouchMove(e) {
    if (!this._isDrawing || !this._ctx || !this._sigRect) return;
    const touch = e.touches[0];
    this._ctx.lineTo(touch.clientX - this._sigRect.left, touch.clientY - this._sigRect.top);
    this._ctx.stroke();
  },

  onSigTouchEnd() {
    this._isDrawing = false;
  },

  onClearCanvas() {
    if (!this._ctx) return;
    const query = wx.createSelectorQuery();
    query.select('#sigCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0]) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        this._isDrawing = false;
      });
  },

  onSignatureConfirm() {
    const query = wx.createSelectorQuery();
    query.select('#sigCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0]) return;
        const canvas = res[0].node;
        wx.canvasToTempFilePath({
          canvas: canvas,
          success: (tmpRes) => {
            const fs = wx.getFileSystemManager();
            const base64 = fs.readFileSync(tmpRes.tempFilePath, 'base64');
            this.setData({
              signatureData: 'data:image/png;base64,' + base64,
              showSignaturePad: false,
            });
            this._ctx = null;
            this._isDrawing = false;
          },
          fail: () => {
            wx.showToast({ title: '签名获取失败', icon: 'none' });
          },
        });
      });
  },

  _initCanvas() {
    setTimeout(() => {
      const query = wx.createSelectorQuery();
      query.select('#sigCanvas')
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res || !res[0]) {
            console.error('Canvas not found');
            return;
          }
          const canvas = res[0].node;
          const ctx = canvas.getContext('2d');

          const dpr = wx.getWindowInfo().pixelRatio;
          const width = res[0].width;
          const height = res[0].height;

          canvas.width = width * dpr;
          canvas.height = height * dpr;

          ctx.scale(dpr, dpr);
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, width, height);

          ctx.strokeStyle = '#1e293b';
          ctx.lineWidth = 3;
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';

          this._ctx = ctx;
          this._isDrawing = false;
          this._sigRect = null;

          // 画虚线提示
          ctx.setLineDash([6, 6]);
          ctx.strokeStyle = '#d1d5db';
          ctx.beginPath();
          ctx.moveTo(20, height / 2);
          ctx.lineTo(width - 20, height / 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.strokeStyle = '#1e293b';
        });
    }, 300);
  },

  onSubmitInspection() {
    const order = this.data.order;
    if (!order) return;
    const items = order.inspection_data && order.inspection_data.items || [];
    const done = items.filter(i => i.result !== null);
    if (done.length === 0) {
      wx.showToast({ title: '请至少完成一项', icon: 'none' });
      return;
    }
    if (!this.data.signatureData) {
      wx.showToast({ title: '请先签字确认', icon: 'none' });
      return;
    }
    wx.showModal({
      title: '确认提交',
      content: '已完成 ' + done.length + '/' + items.length + ' 项，确认提交？',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({ submitting: true });
        api.submitInspection(order.id, done, this.data.signatureData)
          .then(() => {
            wx.showToast({ title: '巡检完成 ✅', icon: 'success' });
            this.loadOrder(order.id);
          })
          .catch((err) => {
            wx.showToast({ title: (err && err.error) || '提交失败', icon: 'none' });
          })
          .finally(() => {
            this.setData({ submitting: false });
          });
      },
    });
  },

  onBack() {
    wx.navigateBack();
  },

  // ========== 退回/转派/流转记录 ==========

  onMoreActions() {
    var order = this.data.order;
    if (!order || order.status !== 'in_progress') return;
    wx.showActionSheet({
      itemList: ['🔄 退回待接单', '📤 转派给他人', '📋 流转记录'],
      success: (res) => {
        var self = this;
        if (res.tapIndex === 0) {
          setTimeout(function() { self.onReturnOrder(); }, 400);
        } else if (res.tapIndex === 1) {
          setTimeout(function() { self.onTransferOrder(); }, 400);
        } else if (res.tapIndex === 2) {
          setTimeout(function() { self.onShowTransfers(); }, 400);
        }
      },
    });
  },

  onReturnOrder() {
    var order = this.data.order;
    wx.showModal({
      title: '退回确认',
      content: '确定要将此工单退回到待接单池吗？',
      success: (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '退回中...' });
        api.returnOrder(order.id)
          .then((res) => {
            wx.hideLoading();
            wx.showToast({ title: res.message || '已退回', icon: 'success' });
            this.loadOrder(order.id);
          })
          .catch((err) => {
            wx.hideLoading();
            wx.showToast({ title: err && err.error ? err.error : '退回失败', icon: 'none' });
          });
      },
    });
  },

  onTransferOrder() {
    var order = this.data.order;
    var self = this;
    this.setData({ personnelLoading: true, showPersonnelPicker: true });
    api.getPersonnel(order.id)
      .then((res) => {
        var list = res.personnel || [];
        if (list.length === 0) {
          this.setData({ showPersonnelPicker: false, personnelLoading: false });
          wx.showToast({ title: '当前医院无可转派人选', icon: 'none' });
          return;
        }
        this.setData({ personnelList: list, personnelLoading: false });
      })
      .catch((err) => {
        this.setData({ showPersonnelPicker: false, personnelLoading: false });
        wx.showToast({ title: '加载人选失败', icon: 'none' });
      });
  },

  onPickPerson(e) {
    var idx = e.currentTarget.dataset.index;
    var target = this.data.personnelList[idx];
    if (!target) return;
    this.setData({ showPersonnelPicker: false });
    var order = this.data.order;
    var self = this;
    wx.showModal({
      title: '转派确认',
      content: '确定将工单转派给「' + target + '」吗？',
      success: (m) => {
        if (!m.confirm) return;
        wx.showLoading({ title: '转派中...' });
        api.transferOrder(order.id, target)
          .then((res2) => {
            wx.hideLoading();
            wx.showToast({ title: res2.message || '已转派', icon: 'success' });
            self.loadOrder(order.id);
          })
          .catch((err2) => {
            wx.hideLoading();
            wx.showToast({ title: err2 && err2.error ? err2.error : '转派失败', icon: 'none' });
          });
      },
    });
  },

  onCancelPersonPicker() {
    this.setData({ showPersonnelPicker: false, personnelList: [], personnelLoading: false });
  },

  onShowTransfers() {
    var order = this.data.order;
    this.setData({ showTransfersModal: true });
    api.getTransfers(order.id)
      .then((res) => {
        var logs = res.transfers || [];
        this.setData({ transferLogs: logs });
      })
      .catch((err) => {
        this.setData({ showTransfersModal: false });
        wx.showToast({ title: '加载失败', icon: 'none' });
      });
  },

  onCloseTransfers() {
    this.setData({ showTransfersModal: false, transferLogs: [] });
  },

  onResize() {
    if (this.data.showSignaturePad) {
      this._initCanvas();
    }
    if (this.data.showFormSigPad) {
      this._initFormSigCanvas();
    }
  },

  noop() {},
});
