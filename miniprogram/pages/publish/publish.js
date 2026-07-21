const api = require('../../utils/api');

Page({
  data: {
    // 一句话输入
    query: '',
    // 解析结果
    parsedFault: '',
    parsedBuilding: '',
    parsedFloor: '',
    parsedLocation: '',
    parsedDept: '',
    hasParsed: false,
    // 地址数据
    _all: [],
    buildings: [],
    floors: [],
    locations: [],
    // 已选
    selBuilding: '',
    selFloor: '',
    selLocation: '',
    selDept: '',
    // 状态
    submitting: false,
    ready: false,
    // 弹窗
    showAddrPicker: false,
    addrItems: [],
    addrTitle: '',
  },

  onLoad() { this._load(); },

  _load() {
    api.getAddresses().then(data => {
      const locs = (data && data.locations) || [];
      if (locs.length < 1) { this.setData({ ready: true }); return; }
      this.data._all = locs;
      const bs = {};
      locs.forEach(a => { if (a.building) bs[a.building] = true; });
      this.setData({
        buildings: Object.keys(bs).sort(),
        ready: true,
        // 默认快速选择第一个楼区
        selBuilding: Object.keys(bs).sort()[0] || '',
      });
      // 自动加载第一个楼区的楼层
      if (this.data.selBuilding) {
        this.setData({ floors: this._getFloors(this.data.selBuilding) });
      }
    }).catch(() => this.setData({ ready: true }));
  },

  _getFloors(building) {
    const seen = {}, r = [];
    this.data._all.forEach(a => {
      if (a.building === building && a.floor && !seen[a.floor]) {
        seen[a.floor] = true; r.push(a.floor);
      }
    });
    return r.sort();
  },

  _getLocations(building, floor) {
    const seen = {}, r = [];
    this.data._all.forEach(a => {
      if (a.building === building && a.floor === floor && a.location && !seen[a.location]) {
        seen[a.location] = true; r.push(a);
      }
    });
    return r;
  },

  // ===== 一句话输入 =====
  onQueryInput(e) {
    const q = e.detail.value;
    this.setData({ query: q, hasParsed: false });
    if (!q.trim()) { this.setData({ parsedFault: '' }); return; }
    // 实时解析
    api.guess(q).then(d => {
      if (!d || !d.fault) return;
      this.setData({
        parsedFault: d.fault,
        parsedBuilding: d.building || '',
        parsedFloor: d.floor || '',
        parsedLocation: d.location || '',
        parsedDept: d.department || '',
        hasParsed: true,
      });
      // 自动填充位置
      if (d.building && this.data.buildings.indexOf(d.building) >= 0) {
        this.setData({ selBuilding: d.building });
        const floors = this._getFloors(d.building);
        this.setData({ floors });
        if (d.floor && floors.indexOf(d.floor) >= 0) {
          this.setData({ selFloor: d.floor });
        }
        if (d.location) this.setData({ selLocation: d.location });
        if (d.department) this.setData({ selDept: d.department });
      }
    }).catch(() => {});
  },

  // ===== 地址选择（横向滚动 chips → 弹窗选具体） =====
  onBuildingSelect(e) {
    const b = e.currentTarget.dataset.value;
    if (!b) return;
    this.setData({
      selBuilding: b, selFloor: '', selLocation: '', selDept: '',
      floors: this._getFloors(b),
      locations: [],
    });
  },

  onFloorSelect(e) {
    const f = e.currentTarget.dataset.value;
    if (!f) return;
    this.setData({
      selFloor: f, selLocation: '', selDept: '',
      locations: this._getLocations(this.data.selBuilding, f),
    });
  },

  onLocationSelect(e) {
    const item = e.currentTarget.dataset.item;
    this.setData({
      selLocation: item.location,
      selDept: item.department || '',
      showAddrPicker: false,
    });
  },

  // 弹窗选择（处理无楼层直接选科室等边界情况）
  onOpenAddrPicker() {
    if (!this.data.selBuilding) {
      wx.showToast({ title: '请先选择楼区', icon: 'none' });
      return;
    }
    // 没有楼层时直接显示科室
    if (this.data.floors.length === 0) {
      // 该楼区没有分层数据，直接搜全楼区地址
      const seen = {}, r = [];
      this.data._all.forEach(a => {
        if (a.building === this.data.selBuilding && a.location && !seen[a.location]) {
          seen[a.location] = true; r.push(a);
        }
      });
      this.setData({
        showAddrPicker: true,
        addrTitle: this.data.selBuilding + ' · 选择位置',
        addrItems: r,
      });
      return;
    }
    if (!this.data.selFloor) {
      wx.showToast({ title: '请先选择楼层', icon: 'none' });
      return;
    }
    const locs = this._getLocations(this.data.selBuilding, this.data.selFloor);
    if (locs.length === 0) {
      wx.showToast({ title: '该楼层暂无科室数据', icon: 'none' });
      return;
    }
    this.setData({
      showAddrPicker: true,
      addrTitle: this.data.selBuilding + ' ' + this.data.selFloor + ' · 选择位置',
      addrItems: locs,
    });
  },

  onCloseAddrPicker() {
    this.setData({ showAddrPicker: false });
  },

  onClearAddr() {
    this.setData({
      selBuilding: '', selFloor: '', selLocation: '', selDept: '',
      floors: [], locations: [],
    });
  },

  // ===== 发布 =====
  onSubmit() {
    const title = (this.data.query || '').trim();
    if (!title) {
      wx.showToast({ title: '请输入故障描述', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    api.createOrder({
      title,
      building: this.data.selBuilding,
      floor: this.data.selFloor,
      department: this.data.selDept,
      location: this.data.selLocation,
    }).then(() => {
      wx.showToast({ title: '✅ 已发布', icon: 'success' });
      setTimeout(() => wx.navigateBack(), 800);
    }).catch(err => {
      this.setData({ submitting: false });
      wx.showToast({ title: (err && err.error) || '发布失败', icon: 'none' });
    });
  },
});
