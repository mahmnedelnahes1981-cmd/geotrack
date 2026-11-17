/* GeoTrack — Field Log offline-first queue.
 * Every log is stored locally first (localStorage), then pushed to the server
 * when the network is available. Sync is idempotent via client-side UUIDs.
 */
(function () {
  'use strict';

  var screen = document.querySelector('.field-screen');
  if (!screen) return;
  var PROJECT_ID = screen.getAttribute('data-project-id');
  var QUEUE_KEY = 'geotrack_field_queue_' + PROJECT_ID;
  var NAME_KEY = 'geotrack_field_operator';

  var form = document.getElementById('fieldlog-form');
  var pendingList = document.getElementById('pending-list');
  var pendingCount = document.getElementById('pending-count');
  var syncBadge = document.getElementById('sync-badge');
  var syncBtn = document.getElementById('sync-btn');
  var netStatus = document.getElementById('net-status');
  var netText = document.getElementById('net-text');
  var toast = document.getElementById('toast');
  var recordedBy = document.getElementById('recorded-by');

  // --- helpers ---------------------------------------------------------------
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function readQueue() {
    try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); }
    catch (e) { return []; }
  }
  function writeQueue(entries) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(entries));
    renderQueue();
  }
  function num(value) {
    var n = parseFloat(value);
    return isNaN(n) ? 0 : n;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(function () { toast.classList.remove('show'); }, 2600);
  }

  // --- pending list rendering ---------------------------------------------------
  function renderQueue() {
    var entries = readQueue();
    pendingCount.textContent = entries.length;
    syncBadge.textContent = entries.length;
    syncBadge.style.display = entries.length ? 'flex' : 'none';

    pendingList.innerHTML = entries.map(function (entry) {
      var bits = [];
      if (entry.pile_id) bits.push('الخازوق ' + esc(entry.pile_id));
      if (num(entry.depth_m) > 0) bits.push('عمق ' + num(entry.depth_m).toFixed(1) + 'م');
      if (num(entry.concrete_m3) > 0) bits.push('خرسانة ' + num(entry.concrete_m3).toFixed(1) + 'م³');
      if (num(entry.sheet_pile_m2) > 0) bits.push('ستائر ' + num(entry.sheet_pile_m2).toFixed(1) + 'م²');
      bits.push('ساعات ' + num(entry.operating_hours).toFixed(1));
      return (
        '<li class="pending-item" data-uuid="' + esc(entry.client_uuid) + '">' +
          '<span aria-hidden="true">⏳</span>' +
          '<div class="p-meta">' +
            '<div class="p-line1">' + esc(entry.log_date) + ' — ' + (bits.join(' · ') || 'سجل') + '</div>' +
            '<div class="p-line2">' + esc(entry.recorded_by || 'بدون اسم') + '</div>' +
          '</div>' +
          '<button type="button" class="p-del" data-del="' + esc(entry.client_uuid) + '" title="حذف من الطابور">✕</button>' +
        '</li>'
      );
    }).join('');
  }

  pendingList.addEventListener('click', function (event) {
    var uuidToDelete = event.target.getAttribute && event.target.getAttribute('data-del');
    if (!uuidToDelete) return;
    writeQueue(readQueue().filter(function (entry) { return entry.client_uuid !== uuidToDelete; }));
    showToast('اتمسح من الطابور');
  });

  // --- connectivity indicator ---------------------------------------------------
  function updateNet() {
    var online = navigator.onLine;
    netStatus.classList.toggle('online', online);
    netStatus.classList.toggle('offline', !online);
    netText.textContent = online ? 'متصل' : 'بدون إنترنت';
  }
  window.addEventListener('online', function () { updateNet(); syncNow(); });
  window.addEventListener('offline', updateNet);
  updateNet();

  // --- form submit: always save locally first -----------------------------------
  if (recordedBy) recordedBy.value = localStorage.getItem(NAME_KEY) || '';

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var data = new FormData(form);
    var entry = {
      client_uuid: uuid(),
      log_date: String(data.get('log_date') || ''),
      rig_id: data.get('rig_id') ? parseInt(data.get('rig_id'), 10) : null,
      pile_id: String(data.get('pile_id') || '').trim() || null,
      depth_m: num(data.get('depth_m')),
      concrete_m3: num(data.get('concrete_m3')),
      sheet_pile_m2: num(data.get('sheet_pile_m2')),
      operating_hours: num(data.get('operating_hours')),
      soil_notes: String(data.get('soil_notes') || '').trim() || null,
      breakdown_notes: String(data.get('breakdown_notes') || '').trim() || null,
      remarks: String(data.get('remarks') || '').trim() || null,
      recorded_by: String(data.get('recorded_by') || '').trim() || null,
      created_offline: !navigator.onLine,
    };
    if (!entry.log_date) { showToast('التاريخ مطلوب'); return; }
    if (entry.recorded_by) localStorage.setItem(NAME_KEY, entry.recorded_by);

    var queue = readQueue();
    queue.push(entry);
    writeQueue(queue);

    form.querySelectorAll('input[type="number"], textarea, input[name="pile_id"]').forEach(function (input) { input.value = ''; });
    showToast(navigator.onLine ? 'اتسجل — بيتم الرفع…' : 'اتسجل على الجهاز ✔ — هيترفع أول ما النت يرجع');
    syncNow();
  });

  // --- sync --------------------------------------------------------------------
  var syncing = false;
  async function syncNow() {
    updateNet();
    if (syncing) return;
    var queue = readQueue();
    if (!queue.length) { renderQueue(); return; }
    if (!navigator.onLine) { showToast('لسه مفيش نت — الطابور مستني'); return; }

    syncing = true;
    syncBtn.classList.add('syncing');
    try {
      var response = await fetch('/api/projects/' + PROJECT_ID + '/logs/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ logs: queue }),
      });
      if (!response.ok) throw new Error('sync failed: ' + response.status);
      var data = await response.json();
      var done = {};
      (data.results || []).forEach(function (result) {
        if (result.status === 'synced' || result.status === 'duplicate') {
          done[result.client_uuid] = true;
        }
      });
      var remaining = queue.filter(function (entry) { return !done[entry.client_uuid]; });
      writeQueue(remaining);
      showToast('تمت مزامنة ' + (data.synced || 0) + ' سجل' + ((data.duplicates || 0) ? ' (و' + data.duplicates + ' مكرر مرمي)' : ''));
      if ((data.synced || 0) > 0 && !remaining.length) {
        setTimeout(function () { window.location.reload(); }, 700);
      }
    } catch (error) {
      showToast('تعذر الرفع — الطابور محفوظ على الجهاز');
    } finally {
      syncing = false;
      syncBtn.classList.remove('syncing');
    }
  }

  syncBtn.addEventListener('click', syncNow);
  renderQueue();
  syncNow();                 // flush anything left from a previous session
  window.setInterval(syncNow, 45000);
})();
