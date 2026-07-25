/**
 * 设备/平台检测工具
 * 支持 HarmonyOS / iOS / Android / devtools
 */
let _platform = null;
let _systemInfo = null;

function init(callback) {
  // 优先用 wx.getDeviceInfo（基础库 3.7.0+，支持 HarmonyOS 检测）
  if (typeof wx.getDeviceInfo === 'function') {
    const deviceInfo = wx.getDeviceInfo();
    _platform = deviceInfo.platform || 'unknown';
  }

  // 兜底：用 wx.getSystemInfoSync
  if (!_platform || _platform === 'unknown') {
    try {
      const sys = wx.getSystemInfoSync();
      _systemInfo = sys;
      if (!_platform || _platform === 'unknown') {
        if (sys.platform) _platform = sys.platform;
      }
    } catch (e) {
      _platform = 'unknown';
    }
  }

  if (callback) callback(getInfo());
}

function getInfo() {
  return {
    platform: _platform,
    isHarmonyOS: _platform === 'harmonyos',
    isIOS: _platform === 'ios',
    isAndroid: _platform === 'android',
    isDevtools: _platform === 'devtools',
    systemInfo: _systemInfo,
  };
}

module.exports = { init, getInfo };
