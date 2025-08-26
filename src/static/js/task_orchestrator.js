// Unified Task Orchestrator for EDxo
// - Starts tasks, opens a generic tracking modal, streams progress (SSE) with polling fallback
// - Enriches notifications with a link to open tracking UI

(function () {
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
              <label class="form-label">Afficher le prompt utilisateur (optionnel)</label>
              <textarea class="form-control" id="task-start-user-prompt" rows="2" placeholder="Sera affiché dans le suivi"></textarea>
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
              <label class="form-label">Payload JSON</label>
              <textarea class="form-control" id="task-start-json" rows="8" placeholder='{"key":"value"}'></textarea>
              <div class="form-text">Assurez-vous que le JSON est valide.</div>
            </div>
            <div id="task-start-form-wrap" class="mb-2" style="display:none;">
              <label class="form-label">Fichier</label>
              <input type="file" class="form-control" id="task-start-file">
              <label class="form-label mt-2">Champs additionnels (facultatifs)</label>
              <textarea class="form-control" id="task-start-form-extras" rows="3" placeholder="ai_model=gpt-5\nfoo=bar"></textarea>
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
        const csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
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
        // Start and immediately open unified tracking
        const taskId = await startCeleryTask(endpoint, fetchOpts, { title, startMessage, userPrompt });
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
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
            <div id="task-orch-user-prompt" class="mb-2 d-none">
              <button class="btn btn-sm btn-outline-secondary mb-2" type="button" id="task-orch-toggle-prompt">Afficher le prompt</button>
              <pre id="task-orch-prompt" class="small" style="display:none;max-height:25vh;overflow:auto;background:#f8f9fa;padding:8px;border-radius:6px;"></pre>
            </div>
            <div id="task-orch-stream" style="background:#0f172a;color:#e2e8f0;border-radius:6px;padding:10px;min-height:140px;max-height:280px;overflow:auto;font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;font-size:0.9rem;"></div>
            <div class="mt-3">
              <button class="btn btn-sm btn-outline-secondary" type="button" id="task-orch-toggle-json">Afficher JSON</button>
              <pre id="task-orch-json" class="mt-2" style="display:none;max-height:30vh;overflow:auto;background:#f8f9fa;padding:8px;border-radius:6px;"></pre>
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
    const toggleBtn = document.getElementById('task-orch-toggle-json');
    toggleBtn.addEventListener('click', () => {
      const pre = document.getElementById('task-orch-json');
      pre.style.display = pre.style.display === 'none' ? 'block' : 'none';
      toggleBtn.textContent = pre.style.display === 'none' ? 'Afficher JSON' : 'Masquer JSON';
    });
    const togglePromptBtn = document.getElementById('task-orch-toggle-prompt');
    if (togglePromptBtn) {
      togglePromptBtn.addEventListener('click', () => {
        const pre = document.getElementById('task-orch-prompt');
        pre.style.display = pre.style.display === 'none' ? 'block' : 'none';
        togglePromptBtn.textContent = pre.style.display === 'none' ? 'Afficher le prompt' : 'Masquer le prompt';
      });
    }
    return modal;
  }

  function appendLog(text) {
    const stream = document.getElementById('task-orch-stream');
    if (!stream) return;
    const now = new Date();
    const ts = now.toLocaleTimeString();
    const safe = ('' + text).replace(/[\u0000-\u001F\u007F<>]/g, ch => ({'<':'&lt;','>':'&gt;'}[ch]||''));
    const atBottom = stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 4;
    stream.insertAdjacentHTML('beforeend', `<div>[${ts}] ${safe}</div>`);
    if (atBottom) stream.scrollTop = stream.scrollHeight;
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
      if (data && (data.state === 'SUCCESS' || data.state === 'FAILURE' || data.state === 'REVOKED')) {
        // Final notification
        try {
          if (typeof window.addNotification === 'function') {
            const payload = data.result || data.meta || {};
            const vurl = payload.validation_url || payload.reviewUrl || payload.plan_de_cours_url || `/tasks/track/${data.task_id || ''}`;
            const msg = data.state === 'SUCCESS' ? 'Tâche terminée.' : 'Tâche arrêtée.';
            window.addNotification(`${title ? title + ' — ' : ''}${msg}`, data.state === 'SUCCESS' ? 'success' : 'warning', vurl);
          }
        } catch {}
        stopBackgroundWatch();
        return;
      }
      // Keep user informed periodically
      try {
        if (typeof window.addNotification === 'function') {
          const link = `/tasks/track/${BG.taskId || ''}`;
          const msg = (data && data.message) ? data.message : 'Tâche en cours...';
          window.addNotification(`${title ? title + ' — ' : ''}${msg}`, 'in-progress', link);
        }
      } catch {}
    } catch {}
    BG.timer = setTimeout(() => backgroundPoll(statusUrl, title), 3000);
  }

  function startBackgroundWatch(taskId, opts = {}) {
    stopBackgroundWatch();
    BG.taskId = taskId;
    const statusUrl = opts.statusUrl || `/tasks/status/${taskId}`;
    const title = opts.title || 'Suivi de la tâche';
    BG.timer = setTimeout(() => backgroundPoll(statusUrl, title), 1500);
  }

  function openTaskModal(taskId, opts = {}) {
    // Respect preference to use dedicated page instead of modal
    try {
      const preferPage = !!(window.EDxoTasks && window.EDxoTasks.settings && window.EDxoTasks.settings.preferPage);
      if (preferPage) {
        window.location.href = `/tasks/track/${taskId}`;
        return null;
      }
    } catch {}
    // Stop any background watcher to avoid duplicate polls while modal is open
    try { stopBackgroundWatch(); } catch {}
    const modalEl = ensureModal();
    document.getElementById('task-orch-id').textContent = taskId;
    document.getElementById('task-orch-state').textContent = 'PENDING';
    document.getElementById('task-orch-stream').innerHTML = '';
    document.getElementById('task-orch-json').textContent = '';
    const validateBtn = document.getElementById('task-orch-validate');
    validateBtn.classList.add('d-none');
    // Popout button removed
    if (opts.title) {
      document.getElementById('taskOrchestratorLabel').textContent = opts.title;
    }
    // Optional user prompt display
    try {
      const promptWrap = document.getElementById('task-orch-user-prompt');
      const promptPre = document.getElementById('task-orch-prompt');
      if (opts.userPrompt) {
        promptPre.textContent = String(opts.userPrompt || '');
        promptWrap.classList.remove('d-none');
      } else {
        promptPre.textContent = '';
        promptWrap.classList.add('d-none');
      }
    } catch {}
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
    // Ensure cleanup also happens on hide/hidden (covers all paths)
    modalEl.addEventListener('hide.bs.modal', unblockPage);
    modalEl.addEventListener('hidden.bs.modal', unblockPage);

    // SSE stream (can be disabled via settings.disableSSE to avoid dev-server blocking)
    const eventsUrl = opts.eventsUrl || `/tasks/events/${taskId}`;
    let es;
    let sawAnyMeaningfulProgress = false;
    let completed = false;
    let streamBuf = '';
    const allowSSE = !((window.EDxoTasks && window.EDxoTasks.settings && window.EDxoTasks.settings.disableSSE) === true);
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
            if (state) document.getElementById('task-orch-state').textContent = state;
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
              } else if (meta.stream_buffer) {
                streamBuf = String(meta.stream_buffer);
              }
              if (streamBuf) {
                const streamEl = document.getElementById('task-orch-stream');
                if (streamEl) {
                  streamEl.textContent = streamBuf;
                  streamEl.scrollTop = streamEl.scrollHeight;
                }
              }
              if (meta.reasoning_summary) {
                appendLog('Résumé du raisonnement mis à jour.');
              }
            } catch {}
            // Update JSON snapshot
            try { document.getElementById('task-orch-json').textContent = JSON.stringify(meta || {}, null, 2); } catch {}
          }
        } catch {}
      });
      if (es) es.addEventListener('done', (ev) => {
        try { const data = JSON.parse(ev.data || '{}'); handleDone(data); } catch { handleDone({}); }
        es.close();
      });
      if (es) es.addEventListener('error', () => { /* Silent; fallback will handle */ });
    } catch (e) { /* SSE not available */ }

    // Polling fallback (and completion handling)
    const statusUrl = opts.statusUrl || `/tasks/status/${taskId}`;
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
        }
        if (d0 && d0.meta) {
          try { document.getElementById('task-orch-json').textContent = JSON.stringify(d0.meta || {}, null, 2); } catch {}
          try {
            const sb = d0.meta.stream_buffer;
            if (sb) {
              const streamEl = document.getElementById('task-orch-stream');
              if (streamEl) {
                try { streamEl.textContent = JSON.stringify(JSON.parse(sb), null, 2); } catch { streamEl.textContent = String(sb); }
                streamEl.scrollTop = streamEl.scrollHeight;
              }
            }
          } catch {}
        }
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
              streamBuf = String(meta.stream_buffer);
              const streamEl = document.getElementById('task-orch-stream');
              if (streamEl) {
                streamEl.textContent = streamBuf;
                streamEl.scrollTop = streamEl.scrollHeight;
              }
            }
          } catch {}
          try { document.getElementById('task-orch-json').textContent = JSON.stringify(data.meta || {}, null, 2); } catch {}
        }
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
    poll();

    function handleDone(data) {
      const payload = data.result || data.meta || {};
      const state = data.state || payload.state || 'DONE';
      document.getElementById('task-orch-state').textContent = state;
      appendLog(`Terminé avec état ${state}.`);
      completed = true;
      try {
        if (!streamBuf && payload && payload.stream_buffer) {
          streamBuf = String(payload.stream_buffer);
          const streamEl = document.getElementById('task-orch-stream');
          if (streamEl) {
            // Try to pretty format JSON if applicable
            try {
              const obj = JSON.parse(streamBuf);
              streamEl.textContent = JSON.stringify(obj, null, 2);
            } catch { streamEl.textContent = streamBuf; }
            streamEl.scrollTop = streamEl.scrollHeight;
          }
        }
      } catch {}
      // Validation/redirect link inference
      let vurl = payload.validation_url || payload.reviewUrl || payload.plan_de_cours_url || payload.plan_cadre_url || null;
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
      if (vurl) {
        validateBtn.href = vurl;
        validateBtn.classList.remove('d-none');
      }
      // Success notification with tracking/validation link
      try {
        if (typeof window.addNotification === 'function') {
          if (vurl) {
            window.addNotification('Tâche terminée. Cliquez pour valider.', 'success', vurl);
          } else {
            const link = `/tasks/track/${sessionStorage.getItem('currentTaskId') || ''}`;
            window.addNotification('Tâche terminée.', 'success', link);
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
            const csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
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
      // If not completed, keep watching in background and keep notifications alive
      if (!completed) {
        startBackgroundWatch(taskId, { statusUrl, title: opts.title });
      }
    }, { once: true });

    return bsModal;
  }

  async function startCeleryTask(startUrl, fetchOpts = {}, uiOpts = {}) {
    const res = await fetch(startUrl, Object.assign({ method: 'POST', credentials: 'same-origin' }, fetchOpts));
    const data = await res.json();
    if (!data || !data.task_id) throw new Error('Aucun task_id retourné.');
    const taskId = data.task_id;
    // Persist task id for auto-resume
    try { sessionStorage.setItem('currentTaskId', taskId); } catch {}
    // Enrich notifications with tracking link
    if (typeof window.addNotification === 'function') {
      const link = `/tasks/track/${taskId}`;
      window.addNotification(uiOpts.startMessage || 'Tâche en cours...', 'in-progress', link);
    }
    // Optionally open the modal (default disabled to avoid blocking UX)
    if (uiOpts.openModal === true) {
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
    startBackgroundWatch,
    stopBackgroundWatch,
    cancelTask: async (taskId) => {
      const headers = {};
      try {
        const csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
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
