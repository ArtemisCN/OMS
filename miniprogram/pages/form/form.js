const api = require('../../utils/api');

Page({
  data: {
    form: null,
    fields: [],
    formData: {},
    _selIndices: {},
    _selLabels: {},
    loading: true,
    saving: false,
    submitting: false,
    showSignaturePad: false,
    signatureFieldId: '',
    signatureData: '',
    dataSources: {}, // loaded data sources
  },

  _sigCtx: null,
  _isDrawing: false,

  onLoad(options) {
    const formId = options.fid;
    if (!formId) {
      wx.showToast({ title: '参数错误', icon: 'none' });
      return;
    }
    this._formId = formId;
    this.loadForm(formId);
  },

  loadForm(formId) {
    this.setData({ loading: true });
    var self = this;
    api.getFormDetail(formId).then((res) => {
      const form = res;
      var fields = form.fields_json || [];
      const formData = form.form_data || {};
      // 初始化 checkbox 字段
      fields.forEach(f => {
        if (f.type === 'checkbox' && !formData[f.id]) {
          formData[f.id] = '';
        }
      });
      // 预计算 select 下标
      var selIdx = {}, selLabel = {};
      fields.forEach(function(f) {
        if (f.type === 'select' && f.options && f.options.length) {
          var idx = f.options.indexOf(formData[f.id] || '');
          selIdx[f.id] = idx > -1 ? idx : 0;
          selLabel[f.id] = idx > -1 ? formData[f.id] : (f.placeholder || f.options[0]);
        }
      });
      self.setData({
        form,
        fields: fields,
        formData,
        _selIndices: selIdx,
        _selLabels: selLabel,
        loading: false,
      });
      wx.setNavigationBarTitle({ title: form.template_name || '电子表单' });
      // 加载数据源并应用到字段
      self._loadDataSources();
    }).catch((err) => {
      wx.showToast({ title: '加载失败', icon: 'none' });
      this.setData({ loading: false });
    });
  },

  // ========== 数据源加载 ==========

  _loadDataSources() {
    var self = this;
    api.getDataSources().then(function(data) {
      self._applyDataSources(data);
    }).catch(function() {
      console.warn('数据源加载失败');
    });
  },

  _applyDataSources(dataSources) {
    var self = this;
    var fields = this.data.fields || [];
    var changed = false;
    fields.forEach(function(f) {
      var srcKey = f.data_source || self._matchFieldToDataSource(f.id);
      if (srcKey && dataSources[srcKey] && dataSources[srcKey].length) {
        var options = dataSources[srcKey].map(function(opt) {
          if (typeof opt === 'string') return opt;
          return opt.label != null ? opt.label : (Array.isArray(opt) ? opt[1] : opt);
        });
        if (JSON.stringify(f.options) !== JSON.stringify(options)) {
          f.type = 'select';
          f.options = options;
          changed = true;
        }
      }
    });
    if (changed) {
      this.setData({ fields: fields, dataSources: dataSources });
    } else {
      this.setData({ dataSources: dataSources });
    }
  },

  _matchFieldToDataSource(fieldId) {
    var map = {
      engineer_sign: 'personnel',
      auditor_sign: 'personnel',
      director_sign: 'personnel',
      asset_manager_sign: 'personnel',
      old_location: 'location',
      new_location: 'location',
      current_location: 'location',
      department: 'department',
      applicant_sign: 'personnel',
      repairer_sign: 'personnel',
      asset_admin_sign: 'personnel',
    };
    return map[fieldId] || null;
  },

  // ========== 字段输入处理 ==========

  onFieldInput(e) {
    const fid = e.currentTarget.dataset.fieldId;
    const val = e.detail.value;
    const key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._scheduleSave(fid, val);
  },

  onSelectChange(e) {
    const fid = e.currentTarget.dataset.fieldId;
    const idx = parseInt(e.detail.value, 10);
    var fields = this.data.fields || [];
    var f = null;
    for (var i = 0; i < fields.length; i++) {
      if (fields[i].id === fid) { f = fields[i]; break; }
    }
    var val = (f && f.options && f.options[idx]) ? f.options[idx] : '';
    var key = 'formData.' + fid;
    this.setData({
      [key]: val,
      ['_selIndices.' + fid]: idx,
      ['_selLabels.' + fid]: val || (f ? (f.placeholder || f.options[0]) : ''),
    });
    this._scheduleSave(fid, val);
  },

  onCheckboxChange(e) {
    const fid = e.currentTarget.dataset.fieldId;
    const val = e.detail.value;
    const checked = e.detail.checked;
    const key = 'formData.' + fid;
    this.setData({ [key]: checked ? val : '' });
    this._scheduleSave(fid, checked ? val : '');
  },

  onRadioChange(e) {
    const fid = e.currentTarget.dataset.fieldId;
    const val = e.detail.value;
    const key = 'formData.' + fid;
    this.setData({ [key]: val });
    this._scheduleSave(fid, val);
  },


  _saveTimer: null,

  _scheduleSave(fid, val) {
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this._saveField(fid, val);
    }, 800);
  },

  _saveField(fid, val) {
    const fd = {};
    fd[fid] = val;
    api.saveFormData(this._formId, fd).catch(() => {});
  },

  // ========== 提交审批 ==========

  onSubmit() {
    if (this.data.submitting) return;
    wx.showModal({
      title: '确认提交审批',
      content: '提交后将等待管理员审核，确认提交？',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({ submitting: true });
        api.submitForm(this._formId)
          .then((res) => {
            wx.showToast({ title: '已提交审批 ✅', icon: 'success' });
            setTimeout(() => wx.navigateBack(), 1500);
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

  // ========== 签名 ==========

  onSignatureTap(e) {
    const fid = e.currentTarget.dataset.fieldId;
    this.setData({
      showSignaturePad: true,
      signatureFieldId: fid,
      signatureData: '',
    }, () => {
      this._initCanvas();
    });
  },

  onSignatureClear() {
    this.setData({ signatureData: '' });
  },

  onSignatureCancel() {
    this.setData({ showSignaturePad: false, signatureFieldId: '' });
    this._sigCtx = null;
    this._isDrawing = false;
  },

  onSigTouchStart(e) {
    const touch = e.touches[0];
    var self = this;
    const q = wx.createSelectorQuery();
    q.select('#sigCanvas').boundingClientRect().exec(function(res) {
      if (!res || !res[0]) return;
      self._sigRect = res[0];
      var ctx = self._sigCtx;
      if (!ctx) return;
      ctx.beginPath();
      ctx.moveTo(touch.clientX - res[0].left, touch.clientY - res[0].top);
      self._isDrawing = true;
    });
  },

  onSigTouchMove(e) {
    if (!this._isDrawing || !this._sigCtx || !this._sigRect) return;
    const touch = e.touches[0];
    this._sigCtx.lineTo(touch.clientX - this._sigRect.left, touch.clientY - this._sigRect.top);
    this._sigCtx.stroke();
  },

  onSigTouchEnd() {
    this._isDrawing = false;
  },

  onClearCanvas() {
    if (!this._sigCtx) return;
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
        this._sigCtx = ctx;
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
            const sigData = 'data:image/png;base64,' + base64;
            const fid = this.data.signatureFieldId;
            const key = 'formData.' + fid;
            this.setData({
              [key]: sigData,
              showSignaturePad: false,
              signatureFieldId: '',
            });
            this._saveField(fid, sigData);
            this._sigCtx = null;
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
          this._sigCtx = ctx;
          this._isDrawing = false;
          this._sigRect = null;

          // 虚线引导（CSS 像素坐标，由 ctx.scale 处理 DPR）
          ctx.strokeStyle = '#d1d5db';
          ctx.lineWidth = 2;
          ctx.setLineDash([6, 6]);
          ctx.beginPath();
          ctx.moveTo(20, height / 2);
          ctx.lineTo(width - 20, height / 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.strokeStyle = '#1e293b';
          ctx.lineWidth = 3;
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';
        });
    }, 300);
  },

  onBack() {
    wx.navigateBack();
  },

  onResize() {
    if (this.data.showSignaturePad) {
      this._initCanvas();
    }
  },

  noop() {},
});
