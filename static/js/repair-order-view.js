/**
 * Repair Order View - Edit & Signature functionality
 * External JS file to avoid CSP inline-script blocking
 */

(function() {
  'use strict';

  let currentEditId = null;

  window.editField = function(fieldId) {
    if (currentEditId) finishEdit();
    currentEditId = fieldId;
    const el = document.getElementById('val-' + fieldId);
    if (!el) return;
    el.dataset.origValue = el.textContent.trim();
    el.contentEditable = true;
    el.classList.add('edit-mode');
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  };

  function finishEdit() {
    if (!currentEditId) return;
    const el = document.getElementById('val-' + currentEditId);
    if (el) {
      el.contentEditable = false;
      el.classList.remove('edit-mode');
    }
    saveFields();
    currentEditId = null;
  }

  document.addEventListener('click', function(e) {
    if (currentEditId && !e.target.closest('.editable-value')) {
      finishEdit();
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && currentEditId) {
      e.preventDefault();
      finishEdit();
    }
    if (e.key === 'Escape' && currentEditId) {
      const el = document.getElementById('val-' + currentEditId);
      if (el) {
        el.textContent = el.dataset.origValue || '';
      }
      finishEdit();
    }
  });

  function getUrls() {
    const bar = document.querySelector('.status-bar');
    if (!bar) return {save:'', sign:'', submit:'', approve:'', reject:''};
    return {
      save: bar.dataset.saveFieldsUrl || '',
      sign: bar.dataset.signUrl || '',
      submit: bar.dataset.submitUrl || '',
      approve: bar.dataset.approveUrl || '',
      reject: bar.dataset.rejectUrl || '',
    };
  }

  window.saveFields = function() {
    const vals = {};
    document.querySelectorAll('.editable-value').forEach(function(el) {
      vals[el.dataset.fieldId] = el.textContent.trim();
    });
    var url = getUrls().save;
    if (!url) return;
    fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({field_values: vals}),
    });
  };

  window.signField = function(fieldId) {
    const sigDiv = document.getElementById('sig-' + fieldId);
    if (!sigDiv) return;
    if (sigDiv.querySelector('img')) {
      if (!confirm('重新签名？')) return;
    }

    // Modal backdrop
    var modal = document.createElement('div');
    modal.className = 'sig-modal-overlay';
    modal.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,.4);' +
      'display:flex;align-items:center;justify-content:center;z-index:9999;';

    // Modal content
    var content = document.createElement('div');
    content.style.cssText =
      'background:#fff;border-radius:12px;padding:20px;width:500px;' +
      'max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,.2);';

    // Title
    var title = document.createElement('h6');
    title.style.cssText = 'margin-bottom:12px';
    var placeholder = sigDiv.querySelector('.placeholder');
    title.textContent = '✍ ' + (placeholder ? placeholder.textContent : '签名');
    content.appendChild(title);

    // Canvas
    var canvas = document.createElement('canvas');
    canvas.id = 'sig-canvas';
    canvas.width = 460;
    canvas.height = 160;
    canvas.style.cssText =
      'border:1px solid #d0d5dd;border-radius:6px;width:100%;touch-action:none;cursor:crosshair;';
    content.appendChild(canvas);

    // Buttons
    var btnRow = document.createElement('div');
    btnRow.style.cssText =
      'display:flex;gap:8px;margin-top:12px;justify-content:flex-end;';

    var clearBtn = document.createElement('button');
    clearBtn.className = 'btn btn-sm btn-outline-secondary';
    clearBtn.textContent = '清除';
    clearBtn.onclick = function() { clearSigCanvas(); };

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-sm btn-outline-secondary';
    cancelBtn.textContent = '取消';
    cancelBtn.onclick = function() { modal.remove(); };

    var confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-sm btn-primary';
    confirmBtn.textContent = '确认签名';
    confirmBtn.onclick = function() { confirmSig(fieldId); };

    btnRow.appendChild(clearBtn);
    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(confirmBtn);
    content.appendChild(btnRow);
    modal.appendChild(content);
    document.body.appendChild(modal);

    // Setup canvas drawing
    requestAnimationFrame(function initCanvas() {
      var c = document.getElementById('sig-canvas');
      if (!c) return;
      var ctx = c.getContext('2d');
      ctx.strokeStyle = '#1d2939';
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      var drawing = false;

      function pos(e) {
        var r = c.getBoundingClientRect();
        return {
          x: (e.clientX - r.left) / r.width * c.width,
          y: (e.clientY - r.top) / r.height * c.height,
        };
      }
      function startDraw(e) {
        drawing = true;
        var p = pos(e);
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
      }
      function moveDraw(e) {
        if (!drawing) return;
        var p = pos(e);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
      }
      function stopDraw() { drawing = false; }

      c.addEventListener('mousedown', startDraw);
      c.addEventListener('mousemove', moveDraw);
      c.addEventListener('mouseup', stopDraw);
      c.addEventListener('mouseleave', stopDraw);
      c.addEventListener('touchstart', function(e) {
        e.preventDefault();
        var t = e.touches[0];
        startDraw({clientX: t.clientX, clientY: t.clientY});
      });
      c.addEventListener('touchmove', function(e) {
        e.preventDefault();
        var t = e.touches[0];
        moveDraw({clientX: t.clientX, clientY: t.clientY});
      });
      c.addEventListener('touchend', stopDraw);
    });
  };

  function clearSigCanvas() {
    var c = document.getElementById('sig-canvas');
    if (!c) return;
    var ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
  }

  function confirmSig(fieldId) {
    var c = document.getElementById('sig-canvas');
    if (!c) return;
    var dataUrl = c.toDataURL('image/png');
    var url = getUrls().sign;
    if (!url) return;
    fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({field_id: fieldId, signature: dataUrl}),
    }).then(function(r) { return r.json(); }).then(function() {
      var sigDiv = document.getElementById('sig-' + fieldId);
      if (sigDiv) {
        sigDiv.innerHTML = '<img src="' + dataUrl + '" alt="签名">';
      }
      var overlay = c.closest('.sig-modal-overlay');
      if (overlay) overlay.remove();
    });
  }

  // Expose needed functions globally for onclick in template
  window.clearSigCanvas = clearSigCanvas;
  window.confirmSig = confirmSig;
  window.submitOrder = function() {
    var url = getUrls().submit;
    if (!url) return;
    fetch(url, {method: 'POST'})
      .then(function(r) { return r.json(); })
      .then(function() { location.reload(); });
  };
  window.approveOrder = function() {
    var url = getUrls().approve;
    if (!url) return;
    fetch(url, {method: 'POST'})
      .then(function(r) { return r.json(); })
      .then(function() { location.reload(); });
  };
  window.rejectOrder = function() {
    var url = getUrls().reject;
    if (!url) return;
    fetch(url, {method: 'POST'})
      .then(function(r) { return r.json(); })
      .then(function() { location.reload(); });
  };

})();
