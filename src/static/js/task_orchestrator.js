// Unified Task Orchestrator for EDxo
// - Starts tasks, opens a generic tracking modal, streams progress (SSE) with polling fallback
// - Enriches notifications with a link to open tracking UI

(function () {
  // Helper: get CSRF token from meta or fallback cookie
  function getCsrfToken() {
    try {
      const meta = document.querySelector('meta[name="csrf-token"]');
      const val = meta && meta.getAttribute('content');
      if (val) return val;
    } catch {}
    try {
      const name = 'csrf_token=';
      const arr = document.cookie ? document.cookie.split(';') : [];
      for (let i = 0; i < arr.length; i++) {
        let c = arr[i];
        while (c.charAt(0) === ' ') c = c.substring(1);
        if (c.indexOf(name) === 0) return c.substring(name.length);
      }
    } catch {}
    return '';
  }
  // --- Task UI cache persisted in sessionStorage ---
  const TaskCache = {};
  const CacheSaveTimers = {};
  const STORAGE_PREFIX = 'edxo_task_cache_';
  const STORE_STREAM_LIMIT = 160000; // ~160KB tail
  const STORE_REASON_LIMIT = 120000; // ~120KB tail
  function clampTail(str, maxLen) {
    try {
      const s = String(str || '');
      if (s.length <= maxLen) return s;
      return '…\n' + s.slice(s.length - maxLen);
    } catch { return str; }
  }
  function loadCacheFromSession(taskId) {
    try {
      const raw = sessionStorage.getItem(STORAGE_PREFIX + taskId);
      if (!raw) return null;
      const j = JSON.parse(raw);
      return {
        stream: typeof j.stream === 'string' ? j.stream : '',
        reasoning: typeof j.reasoning === 'string' ? j.reasoning : '',
        meta: (j.meta && typeof j.meta === 'object') ? j.meta : null,
        state: typeof j.state === 'string' ? j.state : 'PENDING'
      };
    } catch { return null; }
  }
  function saveCacheToSession(taskId) {
    try {
      const c = TaskCache[taskId];
      if (!c) return;
      const payload = {
        stream: clampTail(c.stream || '', STORE_STREAM_LIMIT),
        reasoning: clampTail(c.reasoning || '', STORE_REASON_LIMIT),
        meta: c.meta || null,
        state: c.state || 'PENDING'
      };
      sessionStorage.setItem(STORAGE_PREFIX + taskId, JSON.stringify(payload));
    } catch {}
  }
  function scheduleCacheSave(taskId) {
    try {
      if (CacheSaveTimers[taskId]) return;
      CacheSaveTimers[taskId] = setTimeout(() => {
        CacheSaveTimers[taskId] = null;
        saveCacheToSession(taskId);
      }, 300);
    } catch {}
  }
  function getCache(taskId) {
    if (!taskId) return null;
    if (!TaskCache[taskId]) {
      TaskCache[taskId] = loadCacheFromSession(taskId) || { stream: '', reasoning: '', meta: null, state: 'PENDING' };
    }
    return TaskCache[taskId];
  }
  function sanitizeMetaForCache(meta) {
    try {
      if (!meta || typeof meta !== 'object') return meta;
      const clone = { ...meta };
      delete clone.stream_buffer;
      delete clone.stream_chunk;
      return clone;
    } catch { return meta; }
  }
  // ---------- Quick Modal: only "Informations complémentaires" ----------
  function ensureQuickModal() {
    let modal = document.getElementById('taskQuickModal');
    if (modal) return modal;
    const html = `
    <div class="modal fade" id="taskQuickModal" tabindex="-1" aria-labelledby="taskQuickLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="taskQuickLabel">Démarrer</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" id="task-quick-body"></div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
            <button type="button" class="btn btn-primary" id="task-quick-submit">Lancer</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    // Ensure spinner CSS is available (independent of Bootstrap)
    try {
      if (!document.getElementById('edxo-task-spinner-style')) {
        const style = document.createElement('style');
        style.id = 'edxo-task-spinner-style';
        style.textContent = `@keyframes edxo-spin{to{transform:rotate(360deg)}} .edxo-spinner{width:28px;height:28px;border:3px solid rgba(13,110,253,.2);border-top-color:#0d6efd;border-radius:50%;animation:edxo-spin .9s linear infinite}`;
        document.head.appendChild(style);
      }
    } catch {}
    modal = document.getElementById('taskQuickModal');
    return modal;
  }

  function openQuickTask(opts = {}) {
    const modalEl = ensureQuickModal();
    const label = modalEl.querySelector('#taskQuickLabel');
    const body = modalEl.querySelector('#task-quick-body');
    label.textContent = opts.title || 'Démarrer';

    const fields = Object.assign({}, opts.basePayload || {});
    const fixedPayload = Object.assign({}, opts.fixedPayload || {});
    if (!('additional_info' in fields)) fields.additional_info = '';

    const fieldLabels = Object.assign({
      nb_sessions: 'Nombre de sessions',
      total_hours: "Total d'heures",
      total_units: "Total d'unités",
      additional_info: 'Informations complémentaires'
    }, opts.fieldLabels || {});

    body.innerHTML = '';
    Object.entries(fields).forEach(([key, val]) => {
      const div = document.createElement('div');
      div.className = 'mb-3';
      const lbl = document.createElement('label');
      lbl.className = 'form-label';
      lbl.setAttribute('for', `task-quick-${key}`);
      lbl.textContent = fieldLabels[key] || key;
      div.appendChild(lbl);
      let input;
      if (key === 'additional_info') {
        input = document.createElement('textarea');
        input.className = 'form-control';
        input.rows = 3;
        input.value = val || '';
      } else {
        input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-control';
        input.value = val ?? '';
      }
      input.id = `task-quick-${key}`;
      div.appendChild(input);
      body.appendChild(div);
    });

    const btn = modalEl.querySelector('#task-quick-submit');
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', async () => {
      const payload = { ...fixedPayload };
      Object.keys(fields).forEach(key => {
        const el = body.querySelector(`#task-quick-${key}`);
        if (!el) return;
        if (el.tagName === 'TEXTAREA') {
          payload[key] = el.value || '';
        } else {
          const v = el.value;
          payload[key] = v === '' ? 0 : Number(v);
        }
      });
      const fullPayload = Object.assign({}, fixedPayload, payload);
      const fetchOpts = { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fullPayload) };
      try {
        const csrf = getCsrfToken();
        if (csrf) { fetchOpts.headers['X-CSRFToken'] = csrf; fetchOpts.headers['X-CSRF-Token'] = csrf; }
      } catch {}
      try {
        const taskId = await startCeleryTask(opts.url, fetchOpts, { title: opts.title, startMessage: opts.startMessage || 'En cours…', userPrompt: payload.additional_info || '', openModal: true, summaryEl: opts.summaryEl, streamEl: opts.streamEl, onDone: opts.onDone });
        try { if (document.activeElement) document.activeElement.blur(); } catch {}
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        return taskId;
      } catch (e) {
        alert('Erreur lors du démarrage: ' + (e && e.message ? e.message : e));
      }
    });
    // Autofocus the complementary info textarea once the modal is visible
    const infoEl = body.querySelector('#task-quick-additional_info');
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    try {
      modalEl.addEventListener('shown.bs.modal', () => {
        try {
          if (infoEl) {
            infoEl.focus();
            // Place caret at end for immediate typing continuation
            if (typeof infoEl.selectionStart === 'number') {
              const len = infoEl.value ? infoEl.value.length : 0;
              infoEl.selectionStart = len;
              infoEl.selectionEnd = len;
            }
          }
        } catch {}
      }, { once: true });
    } catch {}
    inst.show();
  }

  // ---------- Quick File Modal: only file field ----------
  function ensureFileModal() {
    let modal = document.getElementById('taskFileModal');
    if (modal) return modal;
    const html = `
    <div class="modal fade" id="taskFileModal" tabindex="-1" aria-labelledby="taskFileLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="taskFileLabel">Importer un fichier</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <label class="form-label">Fichier</label>
            <input type="file" class="form-control" id="task-file-input">
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
            <button type="button" class="btn btn-primary" id="task-file-submit">Importer</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('taskFileModal');
    return modal;
  }

  function openFileTask(opts = {}) {
    const modalEl = ensureFileModal();
    const label = modalEl.querySelector('#taskFileLabel');
    const input = modalEl.querySelector('#task-file-input');
    label.textContent = opts.title || 'Importer un fichier';
    input.value = '';
    // Reset submit handler
    const btn = modalEl.querySelector('#task-file-submit');
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', async () => {
      const file = input && input.files && input.files[0];
      if (!file) { alert('Veuillez choisir un fichier.'); return; }
      const fd = new FormData();
      fd.append('file', file);
      try {
        const extras = opts.extraFormData || {};
        Object.entries(extras).forEach(([k, v]) => fd.append(k, v));
      } catch {}
      const fetchOpts = { method: 'POST', credentials: 'same-origin', body: fd, headers: { 'Accept': 'application/json' } };
      try {
        const csrf = getCsrfToken();
        if (csrf) { fetchOpts.headers['X-CSRFToken'] = csrf; fetchOpts.headers['X-CSRF-Token'] = csrf; }
      } catch {}
      try {
        const taskId = await startCeleryTask(opts.url, fetchOpts, { title: opts.title, startMessage: opts.startMessage || 'Import en cours…', openModal: true });
        try { if (document.activeElement) document.activeElement.blur(); } catch {}
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        return taskId;
      } catch (e) {
        alert('Erreur lors du démarrage: ' + (e && e.message ? e.message : e));
      }
    });
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    try {
      modalEl.addEventListener('hide.bs.modal', () => { try { if (document.activeElement) document.activeElement.blur(); } catch {} });
      modalEl.addEventListener('hidden.bs.modal', () => { try { if (document.activeElement) document.activeElement.blur(); } catch {} });
    } catch {}
    inst.show();
  }

  // ---------- Unified Start Modal (generic task launcher) ----------
  function ensureStartModal() {
    let modal = document.getElementById('taskStartModal');
    if (modal) return modal;
    const html = `
    <div class="modal fade" id="taskStartModal" tabindex="-1" aria-labelledby="taskStartLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="taskStartLabel">Démarrer une tâche</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3">
              <label class="form-label">Endpoint</label>
              <input type="text" class="form-control" id="task-start-endpoint" placeholder="/api/.../start" />
            </div>
            <div class="row g-2 mb-3">
              <div class="col-sm-4">
                <label class="form-label">Méthode</label>
                <select class="form-select" id="task-start-method">
                  <option value="POST" selected>POST</option>
                  <option value="PUT">PUT</option>
                </select>
              </div>
              <div class="col-sm-8">
                <label class="form-label">Titre (UI)</label>
                <input type="text" class="form-control" id="task-start-title" placeholder="Titre de la tâche" />
              </div>
            </div>
            <div class="mb-3">
              <label class="form-label">Message de départ (notification)</label>
              <input type="text" class="form-control" id="task-start-message" placeholder="En cours…" />
            </div>
            <div class="mb-3">
              <label class="form-label" for="task-start-user-prompt">Afficher le prompt utilisateur (optionnel)</label>
              <textarea class="form-control" id="task-start-user-prompt" rows="2" placeholder="Sera affiché dans le suivi" aria-label="Prompt utilisateur"></textarea>
            </div>
            <div class="mb-2">
              <div class="btn-group btn-group-sm" role="group" aria-label="Payload mode">
                <input type="radio" class="btn-check" name="task-start-mode" id="task-start-mode-json" autocomplete="off" checked>
                <label class="btn btn-outline-secondary" for="task-start-mode-json">JSON</label>
                <input type="radio" class="btn-check" name="task-start-mode" id="task-start-mode-form" autocomplete="off">
                <label class="btn btn-outline-secondary" for="task-start-mode-form">Fichier</label>
              </div>
            </div>
            <div id="task-start-json-wrap" class="mb-2">
              <label class="form-label" for="task-start-json">Payload JSON</label>
              <textarea class="form-control" id="task-start-json" rows="8" placeholder='{"key":"value"}' aria-label="Payload JSON"></textarea>
              <div class="form-text">Assurez-vous que le JSON est valide.</div>
            </div>
            <div id="task-start-form-wrap" class="mb-2" style="display:none;">
              <label class="form-label">Fichier</label>
              <input type="file" class="form-control" id="task-start-file">
              <label class="form-label mt-2" for="task-start-form-extras">Champs additionnels (facultatifs)</label>
              <textarea class="form-control" id="task-start-form-extras" rows="3" placeholder="ai_model=gpt-5\nfoo=bar" aria-label="Champs additionnels"></textarea>
              <div class="form-text">1 champ par ligne au format clé=valeur.</div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
            <button type="button" class="btn btn-primary" id="task-start-submit">Démarrer</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('taskStartModal');

    const modeJson = document.getElementById('task-start-mode-json');
    const modeForm = document.getElementById('task-start-mode-form');
    const jsonWrap = document.getElementById('task-start-json-wrap');
    const formWrap = document.getElementById('task-start-form-wrap');
    const updateMode = () => {
      const useJson = modeJson.checked;
      jsonWrap.style.display = useJson ? '' : 'none';
      formWrap.style.display = useJson ? 'none' : '';
    };
    modeJson.addEventListener('change', updateMode);
    modeForm.addEventListener('change', updateMode);
    updateMode();

    // Submit handler
    document.getElementById('task-start-submit').addEventListener('click', async () => {
      const endpoint = document.getElementById('task-start-endpoint').value.trim();
      const method = document.getElementById('task-start-method').value || 'POST';
      const title = document.getElementById('task-start-title').value.trim() || 'Tâche';
      const startMessage = document.getElementById('task-start-message').value.trim() || 'Tâche en cours...';
      const userPrompt = document.getElementById('task-start-user-prompt').value || '';
      if (!endpoint) {
        alert('Veuillez fournir un endpoint.');
        return;
      }

      const fetchOpts = { method, credentials: 'same-origin', headers: {} };
      // CSRF if available
      try {
        const csrf = getCsrfToken();
        if (csrf) fetchOpts.headers['X-CSRFToken'] = csrf;
      } catch {}

      // Build body
      const useJson = document.getElementById('task-start-mode-json').checked;
      if (useJson) {
        const txt = document.getElementById('task-start-json').value || '{}';
        let obj;
        try { obj = JSON.parse(txt); } catch (e) { alert('JSON invalide.'); return; }
        // Auto-inject complementary text if provided
        if (userPrompt && (obj.additional_info === undefined || obj.additional_info === null)) {
          obj.additional_info = userPrompt;
        }
        fetchOpts.headers['Content-Type'] = 'application/json';
        fetchOpts.body = JSON.stringify(obj);
      } else {
        const fd = new FormData();
        const fileInput = document.getElementById('task-start-file');
        if (fileInput && fileInput.files && fileInput.files[0]) {
          fd.append('file', fileInput.files[0]);
        }
        const extra = document.getElementById('task-start-form-extras').value || '';
        extra.split('\n').forEach(line => {
          const idx = line.indexOf('=');
          if (idx > 0) {
            const k = line.slice(0, idx).trim();
            const v = line.slice(idx + 1).trim();
            if (k) fd.append(k, v);
          }
        });
        if (userPrompt) fd.append('additional_info', userPrompt);
        fetchOpts.body = fd; // Do NOT set Content-Type; browser sets multipart boundary
      }

      try {
        const extra = modal._extraOpts || {};
        // Start and immediately open unified tracking
        const taskId = await startCeleryTask(endpoint, fetchOpts, { title, startMessage, userPrompt, summaryEl: extra.summaryEl, streamEl: extra.streamEl, onDone: extra.onDone });
        // Hide modal after launching
        bootstrap.Modal.getOrCreateInstance(modal).hide();
        return taskId;
      } catch (e) {
        alert('Erreur lors du démarrage: ' + (e && e.message ? e.message : e));
      }
    });

    return modal;
  }

  function openTaskStartModal(opts = {}) {
    const modalEl = ensureStartModal();
    // Prefill
    const ep = document.getElementById('task-start-endpoint');
    const mm = document.getElementById('task-start-method');
    const tt = document.getElementById('task-start-title');
    const sm = document.getElementById('task-start-message');
    const up = document.getElementById('task-start-user-prompt');
    const jsonTA = document.getElementById('task-start-json');
    const modeJson = document.getElementById('task-start-mode-json');
    const modeForm = document.getElementById('task-start-mode-form');
    ep.value = opts.url || '';
    mm.value = (opts.method || 'POST').toUpperCase();
    tt.value = opts.title || '';
    sm.value = opts.startMessage || 'En cours…';
    up.value = opts.userPrompt || '';
    jsonTA.value = (opts.defaultJson ? JSON.stringify(opts.defaultJson, null, 2) : (opts.defaultJsonText || '')) || '';
    if (opts.mode === 'form') { modeForm.checked = true; } else { modeJson.checked = true; }
    // Update radio-dependent UI
    const ev = new Event('change');
    modeJson.dispatchEvent(ev);
    modeForm.dispatchEvent(ev);
    modalEl._extraOpts = { summaryEl: opts.summaryEl || null, streamEl: opts.streamEl || null, onDone: opts.onDone };
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    // Autofocus the user prompt ("Informations complémentaires") to allow immediate typing
    try {
      modalEl.addEventListener('shown.bs.modal', () => {
        try {
          const up = document.getElementById('task-start-user-prompt');
          if (up) {
            up.focus();
            if (typeof up.selectionStart === 'number') {
              const len = up.value ? up.value.length : 0;
              up.selectionStart = len;
              up.selectionEnd = len;
            }
          }
        } catch {}
      }, { once: true });
    } catch {}
    inst.show();
  }

  function ensureModal() {
    let modal = document.getElementById('taskOrchestratorModal');
    if (modal) return modal;
    const html = `
    <div class="modal fade" id="taskOrchestratorModal" tabindex="-1" aria-labelledby="taskOrchestratorLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="taskOrchestratorLabel">Suivi de la tâche</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2 small text-muted">ID: <span id="task-orch-id"></span> · État: <span id="task-orch-state">PENDING</span></div>
            <h6 class="mt-2 mb-1">Résumé du raisonnement</h6>
            <div id="task-orch-reasoning-wrap" class="position-relative mb-2">
              <div id="task-orch-reasoning-overlay" style="position:absolute;inset:0;pointer-events:none;z-index:10;display:flex;align-items:center;justify-content:center;">
                <div class="edxo-spinner" aria-label="Chargement"></div>
              </div>
              <div id="task-orch-reasoning" class="small" style="min-height:100px;max-height:25vh;overflow:auto;background:#f8f9fa;padding:8px;border-radius:6px;"></div>
            </div>

            <h6 class="mt-3 mb-1">Contenu généré</h6>
            <div class="d-flex gap-2 mb-2">
              <button class="btn btn-sm btn-outline-secondary active" id="task-orch-view-text" type="button">Texte</button>
              <button class="btn btn-sm btn-outline-secondary" id="task-orch-view-json" type="button" disabled>JSON</button>
            </div>
            <div id="task-orch-stream-wrap" class="position-relative">
              <div id="task-orch-stream-overlay" style="position:absolute;inset:0;pointer-events:none;z-index:10;display:flex;align-items:center;justify-content:center;">
                <div class="edxo-spinner" aria-label="Chargement"></div>
              </div>
              <div id="task-orch-stream-text" class="form-control" style="background:#0f172a;color:#e2e8f0;font-family:ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Cantarell, Noto Sans, Ubuntu, Helvetica Neue, Arial, 'Apple Color Emoji', 'Segoe UI Emoji';font-size:0.95rem;line-height:1.3;min-height:140px;max-height:280px;overflow:auto;white-space:pre-wrap;position:relative;z-index:1;"></div>
              <pre id="task-orch-stream-json" class="form-control" style="display:none;background:#0f172a;color:#e2e8f0;font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;font-size:0.9rem;min-height:140px;max-height:280px;white-space:pre-wrap;overflow:auto;"></pre>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline-danger me-auto" id="task-orch-cancel">Arrêter</button>
            <a id="task-orch-validate" class="btn btn-primary d-none" href="#">Aller à la validation</a>
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Fermer</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('taskOrchestratorModal');
    // Wire view toggle buttons for content
    try {
      const btnText = document.getElementById('task-orch-view-text');
      const btnJson = document.getElementById('task-orch-view-json');
      const areaText = document.getElementById('task-orch-stream-text');
      const areaJson = document.getElementById('task-orch-stream-json');
      if (btnText && btnJson && areaText && areaJson) {
        btnText.addEventListener('click', () => {
          btnText.classList.add('active');
          btnJson.classList.remove('active');
          areaText.style.display = '';
          areaJson.style.display = 'none';
        });
        btnJson.addEventListener('click', () => {
          btnJson.classList.add('active');
          btnText.classList.remove('active');
          areaText.style.display = 'none';
          areaJson.style.display = '';
          try { if (typeof tryUpdateJsonView === 'function') tryUpdateJsonView(); } catch {}
        });
      }
    } catch {}
    return modal;
  }

  function appendLog(text) {
    const log = document.getElementById('task-orch-log');
    if (!log) return;
    const now = new Date();
    const ts = now.toLocaleTimeString();
    const safe = ('' + text).replace(/[\u0000-\u001F\u007F<>]/g, ch => ({'<':'&lt;','>':'&gt;'}[ch]||''));
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.insertAdjacentHTML('beforeend', `<div>[${ts}] ${safe}</div>`);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  // Lightweight background watcher (notifications only) when modal is closed
  let BG = { timer: null, taskId: null };
  function stopBackgroundWatch() {
    try { if (BG.timer) clearTimeout(BG.timer); } catch {}
    BG.timer = null; BG.taskId = null;
  }
  async function backgroundPoll(statusUrl, title) {
    try {
      const r = await fetch(statusUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
      const data = await r.json();
      try {
        if (BG.taskId && data) {
          const tc = getCache(BG.taskId);
          if (data.state) tc.state = data.state;
          const meta = data.meta || {};
          if (typeof meta.stream_buffer === 'string') tc.stream = String(meta.stream_buffer);
          if (typeof meta.reasoning_summary === 'string') tc.reasoning = String(meta.reasoning_summary);
          if (meta && typeof meta === 'object') tc.meta = sanitizeMetaForCache(meta);
          scheduleCacheSave(BG.taskId);
        }
      } catch {}
      if (data && (data.state === 'SUCCESS' || data.state === 'FAILURE' || data.state === 'REVOKED')) {
        // Final notification
        try {
          // Suppress duplicate final notifications if already marked
          const key = `edxo_done_notified_${BG.taskId || ''}`;
          const already = (typeof sessionStorage !== 'undefined') && sessionStorage.getItem(key) === '1';
          if (!already && typeof window.addNotification === 'function') {
            const payload = data.result || data.meta || {};
            const vurl = payload.validation_url || payload.reviewUrl || payload.plan_de_cours_url || `/tasks/track/${data.task_id || ''}`;
            const msg = data.state === 'SUCCESS' ? 'Tâche terminée.' : 'Tâche arrêtée.';
            window.addNotification(`${title ? title + ' — ' : ''}${msg}`, data.state === 'SUCCESS' ? 'success' : 'warning', vurl, (BG.taskId || null));
            try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, '1'); } catch {}
          }
        } catch {}
        stopBackgroundWatch();
        return;
      }
      // Keep user informed periodically
      try {
        if (typeof window.addNotification === 'function') {
          const link = `/tasks/track/${BG.taskId || ''}`;
          const msg = (data && data.message) ? data.message : (title ? `${title} en cours…` : 'Tâche en cours…');
          // PENDING should still show spinner as in-progress
          window.addNotification(`${title ? title + ' — ' : ''}${msg}`, 'in-progress', link, (BG.taskId || null));
        }
      } catch {}
    } catch {}
    BG.timer = setTimeout(() => backgroundPoll(statusUrl, title), 1000);
  }

  function startBackgroundWatch(taskId, opts = {}) {
    stopBackgroundWatch();
    BG.taskId = taskId;
    const prefix = (typeof window !== 'undefined' && window.APP_PREFIX) ? window.APP_PREFIX : '';
    const statusUrl = opts.statusUrl || `${prefix}/tasks/status/${taskId}`;
    const title = opts.title || 'Suivi de la tâche';
    BG.timer = setTimeout(() => backgroundPoll(statusUrl, title), 1500);
  }

  function openTaskModal(taskId, opts = {}) {
    // Respect preference to use dedicated page instead of modal
    try {
      const preferPage = !!(window.EDxoTasks && window.EDxoTasks.settings && window.EDxoTasks.settings.preferPage);
      if (preferPage) {
        const prefix = (typeof window !== 'undefined' && window.APP_PREFIX) ? window.APP_PREFIX : '';
        window.location.href = `${prefix}/tasks/track/${taskId}`;
        return null;
      }
    } catch {}
    // Stop any background watcher to avoid duplicate polls while modal is open
    try { stopBackgroundWatch(); } catch {}
    const modalEl = ensureModal();
    document.getElementById('task-orch-id').textContent = taskId;
    document.getElementById('task-orch-state').textContent = 'PENDING';
    // Log UI removed (status and progress are reflected elsewhere)
    try { const logEl = document.getElementById('task-orch-log'); if (logEl) logEl.remove(); } catch {}
    const streamEl = opts.streamEl || document.getElementById('task-orch-stream-text');
    const usingExternalStream = !!opts.streamEl;
    try { if (streamEl) streamEl.style.background = '#0f172a'; } catch {}
    const streamJsonPre = document.getElementById('task-orch-stream-json');
    const streamOverlay = document.getElementById('task-orch-stream-overlay');
    const viewTextBtn = document.getElementById('task-orch-view-text');
    const viewJsonBtn = document.getElementById('task-orch-view-json');
    
    const reasoningEl = opts.summaryEl || document.getElementById('task-orch-reasoning');
    const usingExternalReason = !!opts.summaryEl;
    const reasoningOverlay = document.getElementById('task-orch-reasoning-overlay');

    // Helpers: text access + overlay visibility (scoped to this modal instance)
    function setStreamText(el, text) {
      try { if (!el) return; if ('value' in el) { el.value = text || ''; } else { el.textContent = text || ''; } } catch {}
    }
    function getStreamText(el) {
      try { if (!el) return ''; return ('value' in el) ? (el.value || '') : (el.textContent || ''); } catch { return ''; }
    }
    function scrollStreamToBottom(el) { try { if (el) el.scrollTop = el.scrollHeight; } catch {} }
    function getElText(el) { try { return el ? (('innerText' in el) ? (el.innerText || '') : (('value' in el) ? (el.value || '') : (el.textContent || ''))) : ''; } catch { return ''; } }
    function updateOverlaysVisibility() {
      try {
        // Consider current DOM content plus in-flight buffers (to avoid throttle delay)
        const streamTextNow = String(getElText(streamEl)).trim();
        const hasJsonPre = (!usingExternalStream) && !!String((streamJsonPre && streamJsonPre.textContent) || '').trim();
        const bufHasStream = (() => { try { return !!(typeof streamBuf === 'string' && streamBuf.trim().length); } catch { return false; } })();
        const hasStream = !!(streamTextNow || hasJsonPre || bufHasStream);
        const domHasReason = !!String(getElText(reasoningEl)).trim();
        const bufHasReason = (() => { try { return !!(typeof lastReasoning === 'string' && lastReasoning.trim().length); } catch { return false; } })();
        const hasReason = domHasReason || bufHasReason;
        if (streamOverlay) streamOverlay.style.display = hasStream ? 'none' : 'flex';
        if (reasoningOverlay) reasoningOverlay.style.display = (hasReason || hasStream) ? 'none' : 'flex';
      } catch {}
    }

    // Local helper: make reasoning easier to read by turning bold titles into headings
    function formatReasoningMarkdown(text) {
      if (!text) return '';
      let t = String(text).replace(/\r\n/g, '\n');
      // Normalize broken bold across lines: **Title\n** -> **Title**
      t = t.replace(/\*\*([\s\S]*?)\n+\*\*/g, '**$1**');
      // Convert a bold title at start-of-line followed by text into a heading + paragraph
      t = t.replace(/(^|\n)\s*\*\*([^*\n][^*]*?)\*\*\s+([^\n]+)/g, '$1\n\n### $2\n\n$3');
      // If a bold "title" appears right after text (no newline), force blank line before
      t = t.replace(/([^\n])\s*\*\*([A-Za-zÀ-ÿ0-9][^*]{0,118}?)\*\*(?=\s*(\n|$))/g, '$1\n\n**$2**');
      // Normalize existing ATX headings to level-3 with spacing
      t = t.replace(/(^|\n+)\s*#{1,6}\s+([^\n]+?)\s*(?=\n|$)/g, '$1\n\n### $2\n\n');
      // Convert standalone bold lines to level-3 headings
      t = t.replace(/(^|\n+)\s*\*\*([^*\n][^*]*?)\*\*\s*(?=\n|$)/g, '$1\n\n### $2\n\n');
      // Collapse excessive blank lines
      t = t.replace(/\n{3,}/g, '\n\n');
      if (!t.startsWith('\n')) t = '\n' + t;
      return t;
    }
    // Preload from cache if available
    try {
      const cache = getCache(taskId);
      // Reset view toggles to Text by default on every open
      try {
        const btnText = document.getElementById('task-orch-view-text');
        const btnJson = document.getElementById('task-orch-view-json');
        if (btnText && btnJson) {
          btnText.classList.add('active');
          btnJson.classList.remove('active');
        }
      } catch {}
      // Reset stream areas on open to avoid stale JSON/text from previous tasks
      if (streamJsonPre) { try { streamJsonPre.textContent = ''; } catch {} }
      if (viewJsonBtn) { try { viewJsonBtn.disabled = true; } catch {} }
      if (streamEl) {
        setStreamText(streamEl, cache.stream || '');
        scrollStreamToBottom(streamEl);
        // If cached stream looks like JSON, prefill JSON pane and enable toggle
        try {
          if (cache.stream) {
            try {
              const obj = JSON.parse(cache.stream);
              if (streamJsonPre) streamJsonPre.textContent = JSON.stringify(obj, null, 2);
              if (viewJsonBtn) viewJsonBtn.disabled = false;
            } catch {}
          }
        } catch {}
      }
      try { if (typeof tryUpdateJsonView === 'function') tryUpdateJsonView(); } catch {}
      if (reasoningEl) {
        const txt = cache.reasoning || '';
        try {
          if (window.marked && txt) {
            const mdText = formatReasoningMarkdown(txt);
            reasoningEl.innerHTML = window.marked.parse(mdText, { breaks: true });
          } else {
            reasoningEl.textContent = txt;
          }
        } catch (_) {
          reasoningEl.textContent = txt;
        }
        // Overlay visibility handled globally
      }
      updateOverlaysVisibility();
      // JSON pane removed
      if (cache.state) {
        document.getElementById('task-orch-state').textContent = cache.state;
      }
    } catch {}
    const validateBtn = document.getElementById('task-orch-validate');
    validateBtn.classList.add('d-none');
    // Popout button removed
    if (opts.title) {
      document.getElementById('taskOrchestratorLabel').textContent = opts.title;
    }
    // Prompt UI removed
    // Show modal in non-blocking mode (no backdrop, no focus trap) and keep page interactive
    const bsModal = new bootstrap.Modal(modalEl, { backdrop: false, keyboard: true, focus: false });
    bsModal.show();
    // Re-enable body scroll explicitly (Bootstrap toggles modal-open which blocks scroll)
    function unblockPage() {
      try {
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
        // Remove any stray backdrops and disable their pointer events
        document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
      } catch {}
      // Try to deactivate any focus trap (internal Bootstrap API)
      try { if (bsModal._focustrap && typeof bsModal._focustrap.deactivate === 'function') bsModal._focustrap.deactivate(); } catch {}
    }
    unblockPage();
    setTimeout(unblockPage, 50);
    // Ensure cleanup also happens on hide/hidden (covers all paths) — attach once per open
    modalEl.addEventListener('hide.bs.modal', unblockPage, { once: true });
    modalEl.addEventListener('hidden.bs.modal', unblockPage, { once: true });

    // SSE stream (can be disabled via settings.disableSSE to avoid dev-server blocking)
    const prefix = (typeof window !== 'undefined' && window.APP_PREFIX) ? window.APP_PREFIX : '';
    const eventsUrl = opts.eventsUrl || `${prefix}/tasks/events/${taskId}`;
    let es;
    let sawAnyMeaningfulProgress = false;
    let completed = false;
    let doneFired = false;
    let streamBuf = (getCache(taskId) || {}).stream || '';
    const MAX_STREAM_LEN = 120000; // ~120KB tail to avoid UI freezes
    let streamTimer = null;
    let streamDirty = false;
    let streamViewMode = 'text';
    function renderReadableFromJson(obj, level = 0) {
      try {
        if (obj === null || obj === undefined) return '';
        if (typeof obj !== 'object') return String(obj);

        // Helper to prettify a single item with name/content
        const renderNamed = (item) => {
          try {
            if (!item || typeof item !== 'object') return '';
            const name = item.field_name || item.name || item.title || '';
            const content = item.content || item.value || item.text || '';
            if (name || content) {
              const title = String(name || '').trim();
              const body = String(content || '').trim();
              const titleHtml = title ? `<div><strong>${title}</strong></div>` : '';
              const bodyHtml = body ? `<div style="margin-left:10px">${body}</div>` : '';
              return `<div style="margin:6px 0">${titleHtml}${bodyHtml}</div>`;
            }
            return '';
          } catch { return ''; }
        };

        if (Array.isArray(obj)) {
          if (obj.length === 0) return '<div class="text-muted">(vide)</div>';
          // If array contains named items, render them as titled sections
          const allNamed = obj.every(it => it && typeof it === 'object' && (('field_name' in it) || ('name' in it) || ('title' in it)));
          if (allNamed) {
            return obj.map(it => renderNamed(it)).join('');
          }
          // Fallback: bullet list
          return obj.map(it => {
            if (typeof it === 'object' && it !== null) {
              const inner = renderReadableFromJson(it, level + 1);
              return `<div style="margin:4px 0">• ${inner}</div>`;
            }
            return `<div>• ${String(it)}</div>`;
          }).join('');
        }

        // Object case
        const parts = [];
        // If object itself looks like named item, render it succinctly
        if ((('field_name' in obj) || ('name' in obj) || ('title' in obj)) && (('content' in obj) || ('value' in obj) || ('text' in obj))) {
          parts.push(renderNamed(obj));
        } else {
          for (const [k, v] of Object.entries(obj)) {
            const title = String(k).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            if (typeof v === 'object' && v !== null) {
              parts.push(`<div style="margin-top:${level?4:0}px"><strong>${title}</strong></div>`);
              parts.push(`<div style="margin-left:10px">${renderReadableFromJson(v, level + 1)}</div>`);
            } else {
              parts.push(`<div><strong>${title}:</strong> ${String(v)}</div>`);
            }
          }
        }
        return parts.join('');
      } catch { return ''; }
    }
    function tryUpdateJsonView() {
      try {
        const raw = streamBuf || (streamEl ? getStreamText(streamEl) : '');
        let parsed;
        try { parsed = JSON.parse(raw); } catch { parsed = null; }
        if (parsed) {
          if (viewJsonBtn) viewJsonBtn.disabled = false;
          try { if (streamJsonPre) streamJsonPre.textContent = JSON.stringify(parsed, null, 2); } catch {}
          // Render readable titles in text pane when in text mode
          if (streamEl && (streamViewMode === 'text')) {
            try { streamEl.innerHTML = renderReadableFromJson(parsed); } catch {}
          }
        } else {
          if (viewJsonBtn) viewJsonBtn.disabled = true;
          if (streamJsonPre && (streamViewMode === 'json')) {
            // Fallback to text view if JSON becomes invalid during stream
            if (viewTextBtn) viewTextBtn.click();
          }
          // Keep raw text in text view
          if (streamEl && (streamViewMode === 'text')) {
            try { setStreamText(streamEl, raw); } catch {}
          }
        }
      } catch {}
    }
    // Remember view mode from clicks
    try {
      if (viewTextBtn) viewTextBtn.addEventListener('click', () => { streamViewMode = 'text'; });
      if (viewJsonBtn) viewJsonBtn.addEventListener('click', () => { if (!viewJsonBtn.disabled) streamViewMode = 'json'; });
    } catch {}

    function clampAndMarkStreamDirty() {
      try {
        if (!streamBuf) return;
        if (streamBuf.length > MAX_STREAM_LEN) {
          streamBuf = '…\n' + streamBuf.slice(streamBuf.length - MAX_STREAM_LEN);
        }
        streamDirty = true;
        if (!streamTimer) {
          streamTimer = setTimeout(() => {
            try {
              streamTimer = null;
              if (!streamDirty) return;
              streamDirty = false;
              if (streamEl) {
                setStreamText(streamEl, streamBuf);
                // Keep viewport near bottom
                scrollStreamToBottom(streamEl);
              }
              // When generated content starts, hide both spinners; otherwise, only update content spinner
              updateOverlaysVisibility();
              tryUpdateJsonView();
              try { scheduleCacheSave(taskId); } catch {}
            } catch {}
          }, 250);
        }
      } catch {}
    }
    let lastReasoning = (getCache(taskId) || {}).reasoning || '';
    let reasoningTimer = null;
    let reasoningDirty = false;
    const reasoningThrottleMs = 120;
    function scheduleReasoningUpdate() {
      try {
        reasoningDirty = true;
        if (!reasoningTimer) {
          reasoningTimer = setTimeout(() => {
            reasoningTimer = null;
            if (!reasoningDirty) return;
            reasoningDirty = false;
            if (reasoningEl) {
              try {
                if (window.marked) {
                  const mdText = formatReasoningMarkdown(lastReasoning);
                  reasoningEl.innerHTML = window.marked.parse(mdText, { breaks: true });
                } else {
                  reasoningEl.textContent = lastReasoning;
                }
              } catch (_) {
                reasoningEl.textContent = lastReasoning;
              }
              updateOverlaysVisibility();
            }
          }, reasoningThrottleMs);
        }
      } catch {}
    }
    const allowSSE = !((window.EDxoTasks && window.EDxoTasks.settings && window.EDxoTasks.settings.disableSSE) === true);
    // Helper: sanitize meta for JSON pane (skip large streaming buffers)
    function sanitizeMeta(meta) {
      try {
        if (!meta || typeof meta !== 'object') return meta;
        const clone = { ...meta };
        if ('stream_buffer' in clone) delete clone.stream_buffer;
        if ('stream_chunk' in clone) delete clone.stream_chunk;
        return clone;
      } catch { return meta; }
    }

    // JSON pane removed: keep sanitized meta in cache without rendering
    let latestSanitized = null;
    let jsonTimer = null;
    const jsonThrottleMs = 700;
    function requestJsonUpdate(meta) {
      latestSanitized = sanitizeMeta(meta);
      try { getCache(taskId).meta = latestSanitized; scheduleCacheSave(taskId); } catch {}
      if (!jsonTimer) {
        jsonTimer = setTimeout(() => { jsonTimer = null; /* no UI render */ }, jsonThrottleMs);
      }
    }

    try {
      if (allowSSE) {
        es = new EventSource(eventsUrl);
      }
      if (es) es.addEventListener('open', () => appendLog('Flux connecté.'));
      if (es) es.addEventListener('progress', (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}');
            if (data && data.meta) {
              const { state, meta } = data;
              if (state) { document.getElementById('task-orch-state').textContent = state; try { getCache(taskId).state = state; scheduleCacheSave(taskId); } catch {} }
              if (meta && (meta.message || meta.step || typeof meta.progress === 'number')) {
                sawAnyMeaningfulProgress = true;
                const bits = [];
                if (meta.step) bits.push(`Étape: ${meta.step}`);
                if (meta.message) bits.push(meta.message);
                if (typeof meta.progress === 'number') bits.push(`Progression: ${meta.progress}%`);
                appendLog(bits.join(' | '));
              }
              // Live JSON stream buffer/chunks
              try {
                if (meta.stream_chunk) {
                  streamBuf += String(meta.stream_chunk);
                  clampAndMarkStreamDirty();
                  try { getCache(taskId).stream = streamBuf; scheduleCacheSave(taskId); } catch {}
                  // As soon as generated content starts, hide both spinners
                  try {
                    if (streamOverlay) streamOverlay.style.display = 'none';
                    if (reasoningOverlay) reasoningOverlay.style.display = 'none';
                  } catch {}
                } else if (meta.stream_buffer) {
                  streamBuf = String(meta.stream_buffer);
                  clampAndMarkStreamDirty();
                  try { getCache(taskId).stream = streamBuf; scheduleCacheSave(taskId); } catch {}
                  // Buffer present implies content; hide both spinners immediately
                  try {
                    if (streamOverlay) streamOverlay.style.display = 'none';
                    if (reasoningOverlay) reasoningOverlay.style.display = 'none';
                  } catch {}
                }
                updateOverlaysVisibility();
                if (meta.reasoning_chunk && reasoningEl) {
                  lastReasoning += String(meta.reasoning_chunk);
                  try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
                  scheduleReasoningUpdate();
                  try { if (reasoningOverlay && String(lastReasoning).trim()) reasoningOverlay.style.display = 'none'; } catch {}
                } else if (meta.reasoning_summary && reasoningEl) {
                  if (String(meta.reasoning_summary) !== lastReasoning) {
                    lastReasoning = String(meta.reasoning_summary);
                    try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
                    scheduleReasoningUpdate();
                    try { if (reasoningOverlay && String(lastReasoning).trim()) reasoningOverlay.style.display = 'none'; } catch {}
                  }
                }
              } catch {}
              // Update JSON snapshot (sanitized, throttled, and only when visible)
              try { requestJsonUpdate(meta || {}); } catch {}
            }
        } catch {}
      });
      if (es) es.addEventListener('done', (ev) => {
        try { const data = JSON.parse(ev.data || '{}'); handleDone(data); } catch { handleDone({}); }
        es.close();
      });
      if (es) es.addEventListener('error', () => {
        // If SSE errors, fallback to polling
        try { es.close(); } catch {}
        es = null;
        if (!stopped && !pollTimer) {
          poll();
        }
      });
    } catch (e) { /* SSE not available */ }

    // Polling fallback (and completion handling)
    const prefix = (typeof window !== 'undefined' && window.APP_PREFIX) ? window.APP_PREFIX : '';
    const statusUrl = opts.statusUrl || `${prefix}/tasks/status/${taskId}`;
    let stopped = false;
    let pollTimer = null;
    let pendingStreak = 0;
    // Immediate snapshot fetch to populate current state/JSON when reopening
    (async function initialSnap() {
      try {
        const r0 = await fetch(statusUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
        const d0 = await r0.json();
        if (d0 && d0.state) {
          try { document.getElementById('task-orch-state').textContent = d0.state; } catch {}
          try { getCache(taskId).state = d0.state; scheduleCacheSave(taskId); } catch {}
        }
        if (d0 && d0.meta) {
          try { requestJsonUpdate(d0.meta || {}); } catch {}
          try {
            const sb = d0.meta.stream_buffer;
            if (sb && streamEl) {
              streamBuf = String(sb);
              clampAndMarkStreamDirty();
              try { getCache(taskId).stream = streamBuf; scheduleCacheSave(taskId); } catch {}
            }
            const rs0 = d0.meta.reasoning_summary;
            if (rs0 && reasoningEl) {
              lastReasoning = String(rs0);
              try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
              scheduleReasoningUpdate();
            }
          } catch {}
        }
        updateOverlaysVisibility();
      } catch {}
    })();
    async function poll() {
      if (stopped) return;
      try {
        const r = await fetch(statusUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
        const data = await r.json();
        if (data && data.meta) {
          if (data.message) appendLog(data.message);
          try {
            const meta = data.meta || {};
            if (meta.stream_buffer) {
              const sb = String(meta.stream_buffer);
              if (streamEl) { streamBuf = sb; clampAndMarkStreamDirty(); }
              try { getCache(taskId).stream = sb; scheduleCacheSave(taskId); } catch {}
              // Hide both overlays as soon as content exists
              try {
                if (streamOverlay) streamOverlay.style.display = 'none';
                if (reasoningOverlay) reasoningOverlay.style.display = 'none';
              } catch {}
            }
            if (meta.reasoning_chunk) {
              lastReasoning += String(meta.reasoning_chunk);
              try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
              if (reasoningEl) scheduleReasoningUpdate();
              try { if (reasoningOverlay && String(lastReasoning).trim()) reasoningOverlay.style.display = 'none'; } catch {}
            } else if (meta.reasoning_summary) {
              lastReasoning = String(meta.reasoning_summary);
              try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
              if (reasoningEl) scheduleReasoningUpdate();
              try { if (reasoningOverlay && String(lastReasoning).trim()) reasoningOverlay.style.display = 'none'; } catch {}
            }
          } catch {}
          try { requestJsonUpdate(data.meta || {}); } catch {}
          try { updateOverlaysVisibility(); } catch {}
        }
        try { if (data && data.state) { getCache(taskId).state = data.state; scheduleCacheSave(taskId); } } catch {}
        // Detect long-standing PENDING with no meaningful progress
        if (data && data.state === 'PENDING') {
          const hasMeta = data && data.meta && Object.keys(data.meta || {}).length > 0;
          if (!hasMeta && !sawAnyMeaningfulProgress) {
            pendingStreak++;
          } else {
            pendingStreak = 0;
          }
          if (pendingStreak >= 10) { // ~15s (10 * 1.5s)
            appendLog("Aucune progression détectée. Nettoyage du suivi local (tâche probablement inexistante). ");
            try { sessionStorage.removeItem('currentTaskId'); } catch {}
            stopped = true;
            try { if (es) es.close(); } catch {}
            try { if (pollTimer) clearTimeout(pollTimer); } catch {}
            return;
          }
        } else {
          pendingStreak = 0;
        }
        if (data.state === 'SUCCESS' || data.state === 'FAILURE' || data.state === 'REVOKED') {
          handleDone(data);
          stopped = true;
          return;
        }
      } catch {}
      pollTimer = setTimeout(poll, 1500);
    }
    // If SSE is connected, skip continuous polling to reduce load
    if (!es) {
      poll();
    }

    function handleDone(data) {
      if (doneFired) return; // idempotent guard
      doneFired = true;
      const payload = data.result || data.meta || {};
      const state = data.state || payload.state || 'DONE';
      document.getElementById('task-orch-state').textContent = state;
      try { getCache(taskId).state = state; scheduleCacheSave(taskId); } catch {}
      appendLog(`Terminé avec état ${state}.`);
      completed = true;
      // Stop streams/polls immediately to avoid double notifications
      try { stopped = true; } catch {}
      try { if (es) es.close(); } catch {}
      try { if (pollTimer) clearTimeout(pollTimer); } catch {}
      try {
        if (!streamBuf && payload && payload.stream_buffer && streamEl) {
          streamBuf = String(payload.stream_buffer);
          // Try to pretty format JSON if applicable
          try {
            const obj = JSON.parse(streamBuf);
            setStreamText(streamEl, JSON.stringify(obj, null, 2));
          } catch { setStreamText(streamEl, streamBuf); }
          scrollStreamToBottom(streamEl);
          try { getCache(taskId).stream = streamBuf; scheduleCacheSave(taskId); } catch {}
        }
      } catch {}
      try { updateOverlaysVisibility(); } catch {}
      try { if (typeof tryUpdateJsonView === 'function') tryUpdateJsonView(); } catch {}
      // Pretty-print JSON if the final content looks like JSON; then apply light green background + border
      try {
        if (streamEl) {
          const current = getStreamText(streamEl) || '';
          if (current) {
            try { const obj = JSON.parse(current); setStreamText(streamEl, JSON.stringify(obj, null, 2)); if (streamJsonPre) streamJsonPre.textContent = JSON.stringify(obj, null, 2); if (viewJsonBtn) viewJsonBtn.disabled = false; } catch {}
          }
          // Light green background and emphasized green border to indicate completion
          try { streamEl.style.background = '#dcfce7'; } catch {}
          try { streamEl.style.border = '2px solid #16a34a'; } catch {}
          try { streamEl.style.color = '#064e3b'; } catch {}
          if (streamJsonPre) {
            try { streamJsonPre.style.background = '#dcfce7'; } catch {}
            try { streamJsonPre.style.border = '2px solid #16a34a'; } catch {}
            try { streamJsonPre.style.color = '#064e3b'; } catch {}
          }
          try { if (streamOverlay) streamOverlay.style.display = 'none'; } catch {}
        }
        if (reasoningOverlay) reasoningOverlay.style.display = 'none';
      } catch {}
      try {
        if (payload && payload.reasoning_summary && reasoningEl) {
          lastReasoning = String(payload.reasoning_summary);
          try { getCache(taskId).reasoning = lastReasoning; scheduleCacheSave(taskId); } catch {}
          scheduleReasoningUpdate();
        }
      } catch {}
      // Links for UI: separate validation link (button) from notification link
      // - validateUrl: only for explicit validation/review flows
      // - notifUrl: for notification click; accepts broader set including logigramme_url
      let validateUrl = payload.validation_url || payload.reviewUrl || null;
      let vurl = validateUrl || payload.plan_de_cours_url || payload.plan_cadre_url || payload.logigramme_url || null;
      const isLogigramme = !!validateUrl && /\/competences\/logigramme(?:$|[\/?#])/i.test(validateUrl);
      try {
        const planId = payload.plan_id || payload.planId;
        const coursId = payload.cours_id || payload.coursId;
        const taskIdFromStore = (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('currentTaskId')) || '';
        if (!vurl && payload.preview && planId) {
          vurl = `/plan_cadre/${planId}/review?task_id=${encodeURIComponent(taskIdFromStore)}`;
        }
        if (!vurl && planId && coursId) {
          vurl = `/cours/${coursId}/plan_cadre/${planId}`;
        }
      } catch {}
      if (validateUrl) {
        validateBtn.href = validateUrl;
        try { validateBtn.textContent = isLogigramme ? 'Voir le logigramme' : 'Aller à la validation'; } catch {}
        validateBtn.classList.remove('d-none');
      }
      // Final notification with contextual title and brief detail
      try {
        // Mark task as notified to suppress duplicates from background watcher
        try { if (sessionStorage) sessionStorage.setItem(`edxo_done_notified_${taskId}`, '1'); } catch {}
        if (typeof window.addNotification === 'function') {
          const baseTitle = (opts && opts.title) ? String(opts.title) : 'Tâche';
          const statusLabel = (state === 'SUCCESS') ? 'terminée' : (state === 'FAILURE' ? 'échouée' : 'arrêtée');
          let detail = '';
          try {
            const dmsg = (payload && (payload.message || payload.summary || payload.reasoning_summary)) || '';
            detail = dmsg ? ` — ${String(dmsg)}` : '';
          } catch {}
          const finalMsg = `${baseTitle} — ${statusLabel}${detail}`;
          const type = (state === 'SUCCESS') ? 'success' : (state === 'FAILURE' ? 'error' : 'warning');
          if (vurl) {
            const isReview = !!validateUrl && !isLogigramme;
            const noteSuffix = isReview ? '. Cliquez pour valider.' : '. Cliquez pour ouvrir.';
            window.addNotification(finalMsg + noteSuffix, type, vurl, taskId);
          } else {
            const link = `/tasks/track/${sessionStorage.getItem('currentTaskId') || ''}`;
            window.addNotification(finalMsg + '.', type, link, taskId);
          }
        }
      } catch {}
      if (typeof opts.onDone === 'function') {
        try { opts.onDone(payload, state); } catch {}
      }
    }

    // Cancel support
    const cancelBtn = document.getElementById('task-orch-cancel');
    if (cancelBtn) {
      cancelBtn.disabled = false;
      cancelBtn.onclick = async () => {
        cancelBtn.disabled = true;
        appendLog("Demande d'arrêt de la tâche…");
        try {
          const headers = {};
          try {
            const csrf = getCsrfToken();
            if (csrf) headers['X-CSRFToken'] = csrf;
          } catch {}
          const r = await fetch(`/tasks/cancel/${encodeURIComponent(taskId)}`, { method: 'POST', credentials: 'same-origin', headers });
          const j = await r.json().catch(() => ({}));
          if (j && j.ok) {
            appendLog('Arrêt demandé. En attente de l\'annulation…');
          } else {
            appendLog("Échec de la demande d'arrêt.");
            cancelBtn.disabled = false;
          }
        } catch (e) {
          appendLog("Erreur lors de la demande d'arrêt.");
          cancelBtn.disabled = false;
        }
      };
    }

    // Minimize button removed

    // Cleanup and focus handling to avoid aria-hidden focus issues
    modalEl.addEventListener('hide.bs.modal', () => {
      try { if (document.activeElement) document.activeElement.blur(); } catch {}
    });
    modalEl.addEventListener('hidden.bs.modal', () => {
      try { stopped = true; } catch {}
      try { if (es) es.close(); } catch {}
      try { if (pollTimer) clearTimeout(pollTimer); } catch {}
      try { if (streamTimer) clearTimeout(streamTimer); } catch {}
      streamTimer = null; streamDirty = false;
      try { if (jsonTimer) clearTimeout(jsonTimer); } catch {}
      jsonTimer = null; latestSanitized = null;
      try { if (reasoningTimer) clearTimeout(reasoningTimer); } catch {}
      reasoningTimer = null; reasoningDirty = false;
      // If not completed, keep watching in background and keep notifications alive
      if (!completed) {
        startBackgroundWatch(taskId, { statusUrl, title: opts.title });
      }
    }, { once: true });

    return bsModal;
  }

  async function startCeleryTask(startUrl, fetchOpts = {}, uiOpts = {}) {
    const res = await fetch(startUrl, Object.assign({ method: 'POST', credentials: 'same-origin', headers: { 'Accept': 'application/json' } }, fetchOpts));
    let data;
    try {
      data = await res.json();
    } catch (_) {
      try {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      } catch (e) {
        throw new Error(`HTTP ${res.status}`);
      }
    }
    if (!data || !data.task_id) throw new Error((data && (data.error || data.message)) || 'Aucun task_id retourné.');
    const taskId = data.task_id;
    // Persist task id for auto-resume
    try {
      sessionStorage.setItem('currentTaskId', taskId);
      sessionStorage.removeItem(`edxo_done_notified_${taskId}`);
      // Persist human-friendly title for notifications
      const t = (uiOpts && uiOpts.title) ? String(uiOpts.title) : 'Tâche';
      try { localStorage.setItem(`edxo_task_title_${taskId}`, t); } catch {}
    } catch {}
    // Enrich notifications with tracking link
    if (typeof window.addNotification === 'function') {
      const link = `/tasks/track/${taskId}`;
      const msg = uiOpts.title ? `${uiOpts.title} en cours…` : (uiOpts.startMessage || 'Tâche en cours…');
      // Show spinner immediately for PENDING (treat as in-progress)
      window.addNotification(msg, 'in-progress', link, taskId);
    }
    // Optionnellement ouvrir le modal et mettre à jour les éléments fournis
    if (uiOpts.openModal === true || uiOpts.summaryEl || uiOpts.streamEl) {
      try { stopBackgroundWatch(); } catch {}
      openTaskModal(taskId, uiOpts);
    }
    return taskId;
  }

  // Expose globally
  window.EDxoTasks = {
    // Default settings: prefer modal over dedicated page; no auto-open on start
    settings: { preferPage: false, autoOpenModal: false },
    openTaskModal,
    startCeleryTask,
    openTaskStartModal,
    openQuickTask,
    openFileTask,
    startBackgroundWatch,
    stopBackgroundWatch,
    cancelTask: async (taskId) => {
      const headers = {};
      try {
        const csrf = getCsrfToken();
        if (csrf) headers['X-CSRFToken'] = csrf;
      } catch {}
      const r = await fetch(`/tasks/cancel/${encodeURIComponent(taskId)}`, { method: 'POST', credentials: 'same-origin', headers });
      return r.json();
    }
  };

  // Auto-bind elements with [data-task-start] to open the start modal
  document.addEventListener('click', function (e) {
    const el = e.target && e.target.closest ? e.target.closest('[data-task-start]') : null;
    if (!el) return;
    e.preventDefault();
    const url = el.getAttribute('data-url') || el.getAttribute('href') || '';
    const title = el.getAttribute('data-title') || el.textContent || 'Tâche';
    const method = el.getAttribute('data-method') || 'POST';
    const mode = el.getAttribute('data-mode') || 'json';
    let defaultJsonText = el.getAttribute('data-json') || '';
    // If attribute is JSON-encoded text, keep as-is; otherwise use raw string
    try { JSON.parse(defaultJsonText); } catch { /* leave as text */ }
    openTaskStartModal({ url, title, method, mode, defaultJsonText });
  });
})();
