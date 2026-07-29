/**
 * base.js — 工单系统全局 JS（从 base.html 内联 script 提取）
 * 依赖：CONFIG / USER 全局变量（在 base.html 中定义）
 */

// 未登录页面兼容：USER 可能未定义
var USER = typeof USER !== 'undefined' ? USER : { avatar: '', displayName: '' };

// ===== 侧边栏收起/展开 =====
function toggleSidebar() {
    var body = document.body;
    var btn = document.getElementById('sidebarToggle');
    body.classList.toggle('sidebar-collapsed');
    var collapsed = body.classList.contains('sidebar-collapsed');
    btn.title = collapsed ? '展开侧边栏' : '收起侧边栏';
    try { localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0'); } catch(e) {}
}
try {
    if (localStorage.getItem('sidebarCollapsed') === '1') {
        var tb = document.getElementById('sidebarToggle');
        if (tb) {
            document.body.classList.add('sidebar-collapsed');
            tb.title = '展开侧边栏';
        }
    }
} catch(e) {}

// ===== 侧边栏自动隐藏 =====
(function() {
    var seconds = parseInt(CONFIG.sidebarAutoHideSeconds) || 0;
    if (seconds <= 0) return;
    var timer = null;
    var body = document.body;
    var sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    function resetTimer() {
        if (timer) clearTimeout(timer);
        if (body.classList.contains('sidebar-collapsed')) return;
        timer = setTimeout(function() {
            body.classList.add('sidebar-collapsed');
            var btn = document.getElementById('sidebarToggle');
            if (btn) btn.title = '展开侧边栏';
        }, seconds * 1000);
    }
    document.addEventListener('mousemove', resetTimer);
    document.addEventListener('click', resetTimer);
    document.addEventListener('keydown', resetTimer);
    resetTimer();
})();

// ===== 返回顶部（基于内容区滚动容器） =====
function getScrollContainer() {
    return document.querySelector('.col[style*="overflow-y:auto"]') || window;
}
function scrollToTop() {
    var container = getScrollContainer();
    if (container === window) {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
        container.scrollTo({ top: 0, behavior: 'smooth' });
    }
}
var scrollContainer = getScrollContainer();
scrollContainer.addEventListener('scroll', function() {
    var btn = document.getElementById('back-to-top');
    if (btn) {
        var scrollY = scrollContainer === window ? window.scrollY : scrollContainer.scrollTop;
        btn.classList.toggle('visible', scrollY > 300);
    }
});

// ===== 页面加载进度条 =====
(function() {
    var bar = document.getElementById('loading-bar');
    if (!bar) return;
    bar.classList.add('active');
    var inner = bar.querySelector('.bar');
    inner.style.width = '30%';

    function finishLoad() {
        inner.style.width = '100%';
        setTimeout(function() {
            bar.classList.remove('active');
            inner.style.width = '0';
        }, 400);
    }

    if (document.readyState === 'complete') {
        finishLoad();
    } else {
        window.addEventListener('load', finishLoad);
        setTimeout(function() { if (inner.style.width !== '100%') inner.style.width = '60%'; }, 500);
        setTimeout(function() { if (inner.style.width !== '100%') inner.style.width = '80%'; }, 1500);
    }

    document.addEventListener('click', function(e) {
        var a = e.target.closest('a');
        if (!a) return;
        var href = a.getAttribute('href');
        if (!href || href === '#' || href.startsWith('javascript:') || href.startsWith('#') || a.getAttribute('data-bs-toggle')) return;
        bar.classList.add('active');
        inner.style.width = '10%';
        setTimeout(function() { inner.style.width = '50%'; }, 100);
    });
})();

// ===== Toast 通知系统 =====
window.showToast = function(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    if (!container) return;

    var icons = {
        success: '<i class="fas fa-check-circle"></i>',
        error: '<i class="fas fa-exclamation-circle"></i>',
        warning: '<i class="fas fa-exclamation-triangle"></i>',
        info: '<i class="fas fa-info-circle"></i>'
    };

    var toast = document.createElement('div');
    toast.className = 'toast-notification toast-' + type;
    toast.innerHTML = '<div class="toast-icon">' + (icons[type] || icons.info) + '</div>'
        + '<div class="toast-body">' + message + '</div>'
        + '<button class="toast-close" onclick="dismissToast(this.parentElement)">&times;</button>';
    container.appendChild(toast);

    setTimeout(function() {
        dismissToast(toast);
    }, 5000);
};

window.dismissToast = function(toast) {
    if (toast.classList.contains('removing')) return;
    toast.classList.add('removing');
    setTimeout(function() {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
    }, 300);
};

// ===== 将 flash 消息转为 Toast =====
(function() {
    var alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        var msg = alert.textContent.trim();
        if (!msg) return;
        var cls = 'info';
        if (alert.classList.contains('alert-success')) cls = 'success';
        else if (alert.classList.contains('alert-danger')) cls = 'error';
        else if (alert.classList.contains('alert-warning')) cls = 'warning';
        showToast(msg, cls);
        alert.style.display = 'none';
    });
})();

// ===== Live Clock =====
document.addEventListener('DOMContentLoaded', function() {
    if (document.querySelector('.live-clock-text')) return;
    var clockTarget = document.querySelector('h5.mb-0.fw-bold');
    if (clockTarget && !document.querySelector('.live-clock')) {
        var clock = document.createElement('span');
        clock.className = 'live-clock ms-2';
        clock.innerHTML = '<span class="clock-dot"></span><span class="clock-text"></span>';
        clockTarget.parentElement.appendChild(clock);
        updateClock();
        setInterval(updateClock, 1000);
    }
});

function updateClock() {
    var el = document.querySelector('.live-clock .clock-text');
    if (!el) return;
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    el.textContent = h + ':' + m + ':' + s;
}

// ===== 主题切换 =====
(function() {
    var theme = localStorage.getItem('theme');
    if (!theme) {
        theme = CONFIG.defaultDarkMode || 'light';
    }
    if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
    function toggleTheme() {
        var html = document.documentElement;
        if (html.getAttribute('data-theme') === 'dark') {
            html.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
        } else {
            html.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        }
    }
    window.toggleTheme = toggleTheme;
    window.toggleHospitalDropdown = function() {
        var dd = document.getElementById('hospitalDropdown');
        if (dd) dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
    }
    document.addEventListener('click', function(e) {
        var dd = document.getElementById('hospitalDropdown');
        if (dd && !e.target.closest('.hospital-switcher')) {
            dd.style.display = 'none';
        }
    });
})();

// ===== 头像选择 =====
var AVATAR_LIST = [];
var AVATAR_LOADED = false;

function openAvatarPicker() {
  var modal = document.getElementById('avatarModal');
  if (!modal) return;
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  if (!AVATAR_LOADED) {
    modal.querySelector('#avatarGrid').innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#999;">加载中...</div>';
    fetch('/user/avatars').then(function(r){return r.json()}).then(function(data){
      AVATAR_LIST = data.avatars || [];
      AVATAR_LOADED = true;
      renderAvatarGrid();
    }).catch(function(){
      modal.querySelector('#avatarGrid').innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#999;">加载失败，请刷新页面重试</div>';
    });
  } else {
    renderAvatarGrid();
  }
}

function renderAvatarGrid() {
  var current = USER.avatar || '';
  var html = '';

  function renderGroup(label, start, end) {
    html += '<div style="grid-column:1/-1;font-size:13px;font-weight:600;color:var(--text-muted,#999);margin-bottom:4px;' + (start > 0 ? 'margin-top:8px;' : '') + '">' + label + '</div>';
    for (var i = start; i < end && i < AVATAR_LIST.length; i++) {
      var url = AVATAR_LIST[i];
      var sel = url === current ? ' selected' : '';
      html += '<div class="avatar-picker-item' + sel + '" data-src="' + url + '" onclick="selectAvatar(this)" style="position:relative;border-radius:12px;overflow:hidden;cursor:pointer;border:3px solid transparent;transition:all .2s;' + (sel ? 'border-color:var(--primary-color,#4f46e5);' : '') + '">';
      html += '<img src="' + url + '" onerror="this.parentElement.style.display=\'none\'" style="width:100%;aspect-ratio:1;display:block;object-fit:cover;background:#f0f0f0;">';
      if (sel) html += '<div style="position:absolute;top:4px;right:4px;width:20px;height:20px;background:var(--primary-color,#4f46e5);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;">✓</div>';
      html += '</div>';
    }
  }

  renderGroup('🎨 卡通冒险', 0, 8);
  renderGroup('✨ 可爱动漫', 8, 16);
  renderGroup('🐾 动物表情', 16, 24);
  renderGroup('👾 像素角色', 24, 32);
  renderGroup('🎭 卡通角色', 32, 40);
  renderGroup('🎪 趣味插画', 40, 48);

  var grid = document.getElementById('avatarGrid');
  grid.innerHTML = html;
  updateAvatarPreview(current);
}

function selectAvatar(el) {
  var src = el.getAttribute('data-src');
  if (!src) return;
  document.querySelectorAll('#avatarGrid .avatar-picker-item').forEach(function(item){
    item.style.borderColor = 'transparent';
    var checkDivs = item.querySelectorAll('div:not(:first-child)');
    checkDivs.forEach(function(d){
      if (d.style.position === 'absolute') d.remove();
    });
    item.classList.remove('selected');
  });
  el.style.borderColor = 'var(--primary-color,#4f46e5)';
  el.classList.add('selected');
  var check = document.createElement('div');
  check.style.cssText = 'position:absolute;top:4px;right:4px;width:20px;height:20px;background:var(--primary-color,#4f46e5);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;';
  check.textContent = '✓';
  el.appendChild(check);
  updateAvatarPreview(src);
  wxShowLoading('设置中...');
  fetch('/user/avatar/select', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({avatar: src})
  }).then(function(r){return r.json()}).then(function(data){
    wxHideLoading();
    if (data.ok) {
      var sidebarAvatar = document.getElementById('sidebarAvatar');
      if (sidebarAvatar) sidebarAvatar.innerHTML = '<img src="' + src + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
      showToast('✅ 头像已更换', 'success');
    } else {
      showToast(data.error || '设置失败', 'error');
    }
  }).catch(function(){
    wxHideLoading();
    showToast('网络错误', 'error');
  });
}

function updateAvatarPreview(src) {
  var preview = document.getElementById('avatarPreview');
  if (!preview) return;
  if (src) {
    preview.innerHTML = '<img src="' + src + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
  } else {
    preview.textContent = USER.displayName || '';
  }
}

function closeAvatarPicker() {
  var modal = document.getElementById('avatarModal');
  if (modal) modal.style.display = 'none';
  document.body.style.overflow = '';
}

function wxShowLoading(t) {
  var el = document.getElementById('avatarModal');
  if (!el) return;
  var existing = el.querySelector('.picker-loading');
  if (!existing) {
    var d = document.createElement('div');
    d.className = 'picker-loading';
    d.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,0.7);color:#fff;padding:12px 20px;border-radius:8px;font-size:14px;z-index:10;';
    d.textContent = t || '处理中...';
    el.appendChild(d);
  }
}

function wxHideLoading() {
  var el = document.getElementById('avatarModal');
  if (el) {
    var d = el.querySelector('.picker-loading');
    if (d) d.remove();
  }
}
