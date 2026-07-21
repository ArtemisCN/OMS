const api = require('../../utils/api');

Page({
  data: {
    taskId: 0,
    task: null,
    buildings: [],
    items: [],
    selectedBuilding: null,
    scanMode: false,
    scanFloor: '',
    showAssetDetail: false,
    scanResult: 'normal',
    scanNotes: '',
    scannedCode: '',
    isNewAsset: false,

    // 预计算的任务统计（避免 WXML 中 ?. 语法）
    taskTotal: 0,
    taskScanned: 0,
    taskNormal: 0,
    taskIssue: 0,
    taskNew: 0,

    // 当前楼层统计
    selectedFloorName: '',
    selectedFloorTotal: 0,
    selectedFloorScanned: 0,

    // 预计算的资产详情字段
    assetTitle: '',
    assetDeviceType: '--',
    assetBrand: '--',
    assetModelNo: '--',
    assetSn: '',
    assetDept: '--',
    assetLocation: '--',
    assetIp: '',
    assetCpu: '',
    assetMemory: '',
    assetDisk: '',
    hasSn: false,
    hasIp: false,
    hasCpu: false,
    hasMemory: false,
    hasDisk: false,

    editMode: false,
    editFieldList: [],  // [{key, label, value}]
  },

  onLoad(options) {
    const taskId = parseInt(options.task_id || 0);
    this.setData({ taskId });
    this.loadDetail(taskId);
  },

  onShow() {
    if (this.data.taskId) {
      this.loadDetail(this.data.taskId);
    }
  },

  loadDetail(taskId) {
    var that = this;
    wx.showLoading({ title: '加载中...' });
    api.get('/inventory/' + taskId)
      .then(function(res) {
        wx.hideLoading();
        var task = res.task || {};
        var buildings = res.buildings || [];
        // 为每个楼层预计算盘点统计
        for (var bi = 0; bi < buildings.length; bi++) {
          var b = buildings[bi];
          var floors = b.floors || [];
          var bStats = b.stats || {};
          for (var fi = 0; fi < floors.length; fi++) {
            var f = floors[fi];
            var fs = bStats[f] || {};
            floors[fi] = {
              name: f,
              scanned: fs.scanned || 0,
              normal: fs.normal || 0,
              total: fs.total || 0
            };
          }
        }
        that.setData({
          task: task,
          buildings: buildings,
          items: res.items || [],
          taskTotal: task.total_count || 0,
          taskScanned: task.scanned_count || 0,
          taskNormal: task.normal_count || 0,
          taskIssue: task.issue_count || 0,
          taskNew: task.new_asset_count || 0,
        });
      })
      .catch(function(err) {
        wx.hideLoading();
        wx.showToast({ title: (err && err.error) || '加载失败', icon: 'none' });
      });
  },

  onBuildingTap(e) {
    this.setData({ selectedBuilding: e.currentTarget.dataset.building });
  },

  onBackToBuildings() {
    this.setData({ selectedBuilding: null, selectedFloorName: '', scanFloor: null, scanMode: false });
  },

  onBackToFloors() {
    this.setData({ selectedFloorName: '', scanFloor: null, scanMode: false });
  },

  onBackToFloor() {
    this.setData({ scanMode: false });
  },

  onSelectFloor(e) {
    var floor = e.currentTarget.dataset.floor;
    var floorData = this._getFloorData(floor);
    // 如果已选中同一个楼层则取消选中
    if (this.data.selectedFloorName === floor) {
      this.setData({ selectedFloorName: '', selectedFloorTotal: 0, selectedFloorScanned: 0 });
      return;
    }
    this.setData({
      scanMode: false,
      selectedFloorName: floor,
      scanFloor: floor,
      showAssetDetail: false,
      scannedCode: '',
      selectedFloorTotal: floorData.total || 0,
      selectedFloorScanned: floorData.scanned || 0,
    });
  },

  _getFloorData(floorName) {
    var buildings = this.data.buildings;
    for (var bi = 0; bi < buildings.length; bi++) {
      var b = buildings[bi];
      if (b.building === this.data.selectedBuilding) {
        var floors = b.floors || [];
        for (var fi = 0; fi < floors.length; fi++) {
          if (floors[fi].name === floorName) {
            return floors[fi];
          }
        }
      }
    }
    return {};
  },

  onStartScan() {
    var that = this;
    var floor = that.data.selectedFloorName || that.data.scanFloor || '';
    that.setData({ scanMode: true, scanFloor: floor });
    setTimeout(function() { that.startScan(); }, 300);
  },

  startScan() {
    var that = this;
    if (typeof wx.scanCode !== 'function') {
      wx.showToast({ title: '当前版本不支持扫码', icon: 'none' });
      return;
    }

    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['barCode', 'qrCode'],
      success: function(res) {
        var code = res.result || '';
        if (!code) {
          wx.showToast({ title: '未识别到编码', icon: 'none' });
          return;
        }
        that.setData({ scannedCode: code, scanResult: 'normal', scanNotes: '' });
        that.lookupAsset(code);
      },
      fail: function(err) {
        if (err.errMsg && err.errMsg.indexOf('cancel') > -1) {
          that.setData({ scanMode: false });
          return;
        }
        wx.showToast({ title: '扫码失败', icon: 'none' });
      },
    });
  },

  lookupAsset(code) {
    var that = this;
    wx.showLoading({ title: '查询中...' });
    api.get('/inventory/assets/' + encodeURIComponent(code) + '?task_id=' + that.data.taskId)
      .then(function(res) {
        wx.hideLoading();
        if (res.found) {
          var a = res.asset;
          that._showAssetDetail(a, false);
        } else {
          that._showNewAsset(code);
        }
      })
      .catch(function(err) {
        wx.hideLoading();
        wx.showToast({ title: (err && err.error) || '查询失败', icon: 'none' });
      });
  },

  _showAssetDetail(asset, isNew) {
    var that = this;
    if (isNew) {
      this.setData({
        foundAsset: null,
        isNewAsset: true,
        editMode: true,
        showAssetDetail: true,
        scanResult: 'new',
        assetTitle: '未匹配到资产（将作为新盘资产）',
        assetDeviceType: '--',
        assetBrand: '--',
        assetModelNo: '--',
        assetSn: '',
        assetDept: '--',
        assetLocation: (that.data.selectedBuilding || '') + ' ' + (that.data.scanFloor || ''),
        assetIp: '',
        assetCpu: '',
        assetMemory: '',
        assetDisk: '',
        hasSn: false, hasIp: false, hasCpu: false, hasMemory: false, hasDisk: false,
        editFieldList: [
          { key: 'device_type', label: '设备类型', value: '' },
          { key: 'brand', label: '品牌', value: '' },
          { key: 'model_no', label: '型号', value: '' },
          { key: 'department', label: '科室', value: '' },
          { key: 'location', label: '位置', value: that.data.selectedBuilding + ' ' + that.data.scanFloor },
        ],
      });
      return;
    }

    this.setData({
      foundAsset: asset,
      isNewAsset: false,
      showAssetDetail: true,
      editMode: false,
      scanResult: 'normal',
      assetTitle: '已匹配资产',
      assetDeviceType: asset.device_type || '--',
      assetBrand: asset.brand || '--',
      assetModelNo: asset.model_no || '--',
      assetSn: asset.sn || '',
      assetDept: asset.department || '--',
      assetLocation: (asset.building || '') + (asset.floor ? ' ' + asset.floor : '') + (asset.location ? ' ' + asset.location : ''),
      assetIp: asset.ip_address || '',
      assetCpu: asset.cpu || '',
      assetMemory: asset.memory || '',
      assetDisk: asset.disk_size || '',
      hasSn: !!(asset.sn),
      hasIp: !!(asset.ip_address),
      hasCpu: !!(asset.cpu),
      hasMemory: !!(asset.memory),
      hasDisk: !!(asset.disk_size),
      editFieldList: [
        { key: 'device_type', label: '设备类型', value: asset.device_type || '' },
        { key: 'brand', label: '品牌', value: asset.brand || '' },
        { key: 'model_no', label: '型号', value: asset.model_no || '' },
        { key: 'department', label: '科室', value: asset.department || '' },
        { key: 'location', label: '位置', value: (asset.building || '') + ' ' + (asset.floor || '') },
        { key: 'sn', label: '序列号', value: asset.sn || '' },
      ],
    });
  },

  _showNewAsset(code) {
    this._showAssetDetail({
      asset_no: code,
      device_type: '',
      brand: '',
      model_no: '',
      sn: '',
      department: '',
      building: this.data.selectedBuilding || '',
      floor: this.data.scanFloor || '',
      location: '',
      ip_address: '',
      cpu: '',
      memory: '',
      disk_size: '',
    }, true);
  },

  onCloseDetail() {
    this.setData({ showAssetDetail: false, editMode: false });
  },

  onResultChange(e) {
    var result = e.currentTarget.dataset.result;
    var data = { scanResult: result };
    if (result === 'normal') {
      data.scanNotes = '';
      data.editMode = false;
    }
    if (result === 'issue') {
      data.editMode = true;
    }
    this.setData(data);
  },

  onNotesInput(e) {
    this.setData({ scanNotes: e.detail.value });
  },

  onEditMode() {
    this.setData({ editMode: true, scanResult: 'issue' });
  },

  onEditFieldInput(e) {
    var field = e.currentTarget.dataset.field;
    var value = e.detail.value;
    var list = this.data.editFieldList;
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === field) {
        list[i].value = value;
        break;
      }
    }
    this.setData({ editFieldList: list });
  },

  onConfirmResult() {
    var that = this;
    var data = {
      task_id: this.data.taskId,
      asset_no: this.data.scannedCode,
      result: this.data.scanResult,
      notes: this.data.scanNotes,
      building: this.data.selectedBuilding || '',
      floor: this.data.scanFloor || '',
    };

    if (this.data.editMode) {
      var edits = [];
      var list = this.data.editFieldList;
      for (var i = 0; i < list.length; i++) {
        if (list[i].value) {
          edits.push(list[i].label + ': ' + list[i].value);
        }
      }
      if (edits.length > 0) {
        data.notes = (data.notes ? data.notes + ' | ' : '') + '编辑: ' + edits.join(', ');
      }
    }

    wx.showLoading({ title: '提交中...' });
    api.post('/inventory/scan', data)
      .then(function(res) {
        wx.hideLoading();
        if (res.ok) {
          wx.showToast({ title: '盘点完成 ✅', icon: 'success', duration: 1000 });
          that.setData({ showAssetDetail: false, editMode: false });
          that.loadDetail(that.data.taskId);
          // 弹出继续扫确认
          setTimeout(function() {
            wx.showModal({
              title: '继续盘点',
              content: '已记录，继续扫下一台？',
              confirmText: '继续扫',
              cancelText: '取消',
              success: function(mres) {
                if (mres.confirm) {
                  that.setData({ scanMode: true, scannedCode: '', scanResult: 'normal', scanNotes: '' });
                  that.startScan();
                } else {
                  that.setData({ scanMode: false, showAssetDetail: false, scannedCode: '' });
                }
              }
            });
          }, 1200);
        } else {
          wx.showToast({ title: (res && res.error) || '提交失败', icon: 'none' });
        }
      })
      .catch(function(err) {
        wx.hideLoading();
        wx.showToast({ title: (err && err.error) || '提交失败', icon: 'none' });
      });
  },

  onSkipScan() {
    this.setData({ showAssetDetail: false });
    this.startScan();
  },

  onManualInput() {
    var that = this;
    wx.showModal({
      title: '手动输入',
      content: '',
      editable: true,
      placeholderText: '输入资产编码',
      success: function(res) {
        if (res.confirm && res.content) {
          that.setData({ scannedCode: res.content });
          that.lookupAsset(res.content);
        }
      },
    });
  },
});
