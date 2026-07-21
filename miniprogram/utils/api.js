const config = require('../config');

/**
 * 封装 wx.request，自动携带 token
 */
// 内存缓存token，避免每次请求读storage
let _tokenCache = null;

function _getToken() {
  if (!_tokenCache) {
    _tokenCache = wx.getStorageSync('token') || null;
  }
  return _tokenCache;
}

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    const token = _getToken();
    const header = { 'Content-Type': 'application/json' };
    if (token) {
      header['Authorization'] = 'Bearer ' + token;
    }

    var requestTask = wx.request({
      url: config.API_BASE_URL + path,
      method: method,
      data: data,
      header: header,
      timeout: 20000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // token 失效，跳转登录
          _tokenCache = null;
          wx.removeStorageSync('token');
          wx.removeStorageSync('user');
          wx.reLaunch({ url: '/pages/login/login' });
          reject(res.data);
        } else {
          reject(res.data);
        }
      },
      fail(err) {
        reject({ error: '网络请求失败，请检查网络连接', detail: err });
      },
    });
    // 兜底：吞掉 SDK 内部未捕获的 Promise rejection（如超时）
    if (requestTask && typeof requestTask.catch === 'function') {
      requestTask.catch(function(){});
    }
  });
}

module.exports = {
  // 登录
  login: (username, password) =>
    request('POST', '/login', { username, password }),

  // 获取个人信息
  getProfile: () => request('GET', '/profile'),

  // 获取工单列表（可筛选 status）
  getOrders: (status) => {
    let path = '/orders';
    if (status) path += '?status=' + status;
    return request('GET', path);
  },

  // 获取工单详情
  getOrderDetail: (orderId) =>
    request('GET', '/orders/' + orderId),

  // 接单
  acceptOrder: (orderId) =>
    request('POST', '/orders/' + orderId + '/accept'),

  // 提交解决方案
  solveOrder: (orderId, solution) =>
    request('POST', '/orders/' + orderId + '/solve', { solution }),

  // 退出登录
  logout: () => {
    _tokenCache = null;
    return request('POST', '/logout');
  },

  // 获取今日工作总结
  getTodaySummary: () =>
    request('GET', '/orders/today-summary'),

  // 获取流转记录
  getTransfers: (orderId) =>
    request('GET', '/orders/' + orderId + '/transfers'),

  // 退回到未接单
  returnOrder: (orderId) =>
    request('POST', '/orders/' + orderId + '/return'),

  // 转派工单
  transferOrder: (orderId, toPerson) =>
    request('POST', '/orders/' + orderId + '/transfer', { to_person: toPerson }),

  // 获取可选转派人选
  getPersonnel: (orderId) =>
    request('GET', '/orders/' + orderId + '/personnel'),

  // 获取匹配的方案模板
  getMatchingTemplate: (title) =>
    request('GET', '/templates/match?title=' + encodeURIComponent(title)),

  // 微信自动登录
  wxLogin: (code) => request('POST', '/wx_login', { code }),

  // 绑定微信到当前用户
  bindWx: (code) => request('POST', '/bind_wx', { code }),

  // 订阅新工单通知
  subscribe: (template_id) => request('POST', '/subscribe', { template_id }),

  // 查询订阅状态
  getSubscribeStatus: () => request('GET', '/subscribe/status'),

  // 取消订阅
  unsubscribe: () => {
    _tokenCache = null;
    return request('DELETE', '/subscribe');
  },

  // 发布工单
  createOrder: (data) =>
    request('POST', '/orders/create', data),

  // 工单图片
  getPhotos: (orderId) =>
    request('GET', '/orders/' + orderId + '/photos'),

  uploadPhotos: (orderId, filePaths) => {
    return new Promise((resolve, reject) => {
      var token = _getToken();
      var url = config.API_BASE_URL + '/orders/' + orderId + '/photos';
      var tasks = filePaths.map(function(fp) {
        return new Promise(function(res, rej) {
          wx.uploadFile({
            url: url,
            filePath: fp,
            name: 'photos',
            header: token ? { 'Authorization': 'Bearer ' + token } : {},
            success(r) {
              try {
                var data = JSON.parse(r.data);
                if (r.statusCode >= 200 && r.statusCode < 300) {
                  res(data);
                } else if (r.statusCode === 401) {
                  _tokenCache = null;
                  wx.removeStorageSync('token');
                  wx.removeStorageSync('user');
                  wx.reLaunch({ url: '/pages/login/login' });
                  rej(data);
                } else {
                  rej(data);
                }
              } catch(e) {
                rej({ error: '上传解析失败' });
              }
            },
            fail(err) {
              rej({ error: '上传失败' });
            },
          });
        });
      });
      Promise.all(tasks).then(function(results) {
        var all = { message: '', uploaded: [], errors: [] };
        results.forEach(function(r) {
          if (r.uploaded) all.uploaded = all.uploaded.concat(r.uploaded);
          if (r.errors) all.errors = all.errors.concat(r.errors);
        });
        all.message = '上传完成: ' + all.uploaded.length + '张';
        resolve(all);
      }).catch(function(err) {
        reject(err);
      });
    });
  },

  deletePhoto: (orderId, photoId) =>
    request('DELETE', '/orders/' + orderId + '/photos/' + photoId),

  // 获取匹配的方案模板
  getMatchingTemplate: (title) =>
    request('GET', '/templates/match?title=' + encodeURIComponent(title)),

  // 提交巡检结果
  submitInspection: (orderId, items, signature) =>
    request('POST', '/orders/' + orderId + '/inspection_submit', { items, signature }),

  // ========== 电子表单 ==========

  // 获取表单详情（含模板字段定义）
  getFormDetail: (formId) =>
    request('GET', '/forms/' + formId),

  // 保存表单字段值
  saveFormData: (formId, formData) =>
    request('POST', '/forms/' + formId + '/save', { form_data: formData }),

  // 提交表单待审批
  submitForm: (formId) =>
    request('POST', '/forms/' + formId + '/submit'),

  // 获取数据源（科室、人员、位置等）
  getDataSources: () =>
    request('GET', '/forms/api/data-sources'),

  // 获取全部地址
  getAddresses: () =>
    request('GET', '/addresses'),

  // 自动识别工单标题
  guess: (title) =>
    request('GET', '/guess?title=' + encodeURIComponent(title)),

  // ========== 通用请求（盘点用） ==========
  get: (path) => request('GET', path),
  post: (path, data) => request('POST', path, data),
};
