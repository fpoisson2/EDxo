/* LinkEditor module: edit mode for competence graph
 * Works with SVG built by competence_logigramme.js
 * Exposes:
 *  - enableEditMode(), disableEditMode()
 *  - setAddLinkTool(enabled)
 *  - beginLinkCreation(), selectLinkSource(nodeEl), selectLinkTarget(nodeEl), createLink(opts)
 *  - openLinkEditor(edgeEl, evt), updateLink(edgeEl, {type, weight}), deleteLink(edgeEl)
 *  - saveLinks()
 */
(function () {
  const svg = document.getElementById('competenceGraph');
  if (!svg) return;

  const data = (window.COMPETENCE_MAP_DATA || { links: [], competences: [], cours: [] });

  // Elements
  const linksG = svg.querySelector('#links');
  const nodesG = svg.querySelector('#nodes');
  const container = document.getElementById('graphContainer');
  const editToggleBtn = document.getElementById('editModeToggle');
  const saveBtn = document.getElementById('saveLinksBtn');
  const badge = document.getElementById('editModeBadge');

  const typeColor = { developpe: '#0d6efd', atteint: '#198754', reinvesti: '#6c757d' };

  let editMode = false;
  let addLinkTool = false;
  let creating = { active: false, sourceEl: null, targetEl: null };
  let dragLine = null; // temporary path while dragging to create
  let selectedEdge = null; // SVGPathElement (visual)
  const selectedEdges = new Set(); // multiple selection (visual paths)
  let marquee = { active: false, startX: 0, startY: 0, boxEl: null };

  // Build node index by data id string ("comp:ID" or "course:ID")
  function buildNodeIndex() {
    const idx = new Map();
    nodesG.querySelectorAll('g.node').forEach(g => {
      const key = g.getAttribute('data-node-id') || g.dataset.id;
      const kind = g.getAttribute('data-node-kind') || g.dataset.kind;
      idx.set(key, { el: g, kind, key, id: parseInt((key||'').split(':')[1] || '0', 10) });
    });
    return idx;
  }

  function parseTranslate(el) {
    const tr = el.getAttribute('transform') || '';
    const m = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(tr);
    return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : { x: 0, y: 0 };
  }

  function cubicPath(x1, y1, x2, y2) {
    const dx = (x2 - x1) * 0.5;
    const c1x = x1 + dx, c1y = y1;
    const c2x = x2 - dx, c2y = y2;
    return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
  }

  function currentEdges() {
    return Array.from(linksG.querySelectorAll('path.link'));
  }

  function isEdgeHitTarget(t) { return !!(t && (t.classList && t.classList.contains('link-hit'))); }
  function isNodeTarget(t) { return !!(t && t.closest && t.closest('g.node')); }

  function ensureHitForPath(path) {
    if (path.__hit && path.__hit.parentNode === linksG) return path.__hit;
    const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    hit.setAttribute('class', 'link-hit');
    hit.setAttribute('d', path.getAttribute('d'));
    hit.setAttribute('stroke', 'rgba(0,0,0,0)');
    hit.setAttribute('stroke-width', '16');
    hit.setAttribute('fill', 'none');
    hit.setAttribute('pointer-events', 'stroke');
    hit.setAttribute('data-source', path.getAttribute('data-source'));
    hit.setAttribute('data-target', path.getAttribute('data-target'));
    hit.setAttribute('data-type', path.getAttribute('data-type'));
    if (path.nextSibling) linksG.insertBefore(hit, path.nextSibling); else linksG.appendChild(hit);
    path.__hit = hit; hit.__visual = path;
    return hit;
  }

  function recomputeStrokeWidths() { /* no-op: weight removed */ }

  function idsFromAttrs(srcAttr, tgtAttr) {
    const sid = (srcAttr||'').split(':');
    const tid = (tgtAttr||'').split(':');
    const sKind = sid[0]; const sId = parseInt(sid[1]||'0', 10);
    const tKind = tid[0]; const tId = parseInt(tid[1]||'0', 10);
    // Graph draws competence -> course (source=comp, target=course)
    // Data schema is { cours_id, competence_id }
    const competence_id = sKind === 'comp' ? sId : (tKind === 'comp' ? tId : 0);
    const cours_id = sKind === 'course' ? sId : (tKind === 'course' ? tId : 0);
    return { cours_id, competence_id };
  }

  function markerIdForType(type) {
    return type === 'developpe' ? 'arrow-dev' : (type === 'atteint' ? 'arrow-att' : 'arrow-rei');
  }

  function openLinkEditor(edgeEl, evt) {
    // Allow hit-path to be passed
    if (edgeEl && edgeEl.__visual) edgeEl = edgeEl.__visual;
    if (!editMode) return;
    closePanels();
    clearSelection();
    selectedEdge = edgeEl;
    markSelected(edgeEl);
    // bring to front
    try {
      linksG.appendChild(edgeEl);
      if (edgeEl.__hit) linksG.appendChild(edgeEl.__hit);
    } catch (_) {}
    const type = edgeEl.getAttribute('data-type');
    const { cours_id, competence_id } = idsFromAttrs(edgeEl.getAttribute('data-source'), edgeEl.getAttribute('data-target'));
    const link = data.links.find(l => l.cours_id === cours_id && l.competence_id === competence_id && l.type === type);
    // weight removed

    const panel = document.createElement('div');
    panel.className = 'card shadow-sm p-2';
    panel.style.position = 'absolute';
    panel.style.zIndex = '1000';
    panel.style.minWidth = '220px';
    panel.innerHTML = `
      <div class="mb-2"><strong>Éditer le lien</strong></div>
      <div class="mb-2">
        <label class="form-label form-label-sm">Type du lien</label>
        <select class="form-select form-select-sm" id="le-type">
          <option value="developpe">Développé significativement</option>
          <option value="atteint">Atteint</option>
          <option value="reinvesti">Réinvesti</option>
        </select>
      </div>
      
      <div class="d-flex gap-2 justify-content-end">
        <button class="btn btn-sm btn-outline-danger" id="le-delete">Supprimer</button>
        <button class="btn btn-sm btn-primary" id="le-save">Enregistrer</button>
      </div>
    `;
    container.appendChild(panel);
    // Position near event or center
    const rect = container.getBoundingClientRect();
    const x = evt ? (evt.clientX - rect.left) : rect.width / 2;
    const y = evt ? (evt.clientY - rect.top) : rect.height / 2;
    panel.style.left = Math.max(8, Math.min(rect.width - 240, x - 20)) + 'px';
    panel.style.top = Math.max(8, Math.min(rect.height - 160, y - 20)) + 'px';

    const typeSel = panel.querySelector('#le-type');
    typeSel.value = type;
    panel.querySelector('#le-save').addEventListener('click', () => {
      const newType = typeSel.value;
      updateLink(edgeEl, { type: newType });
      closePanels();
    });
    panel.querySelector('#le-delete').addEventListener('click', () => {
      deleteLink(edgeEl);
      closePanels();
    });
    // close on outside click
    setTimeout(() => {
      function outside(e) { if (!panel.contains(e.target)) { closePanels(); document.removeEventListener('mousedown', outside); } }
      document.addEventListener('mousedown', outside);
    }, 0);
    panels.push(panel);
  }

  function updateLink(edgeEl, { type }) {
    const oldType = edgeEl.getAttribute('data-type');
    const { cours_id, competence_id } = idsFromAttrs(edgeEl.getAttribute('data-source'), edgeEl.getAttribute('data-target'));
    // Update data: find old by ids + oldType
    const idx = data.links.findIndex(l => l.cours_id === cours_id && l.competence_id === competence_id && l.type === oldType);
    if (idx >= 0) {
      data.links[idx].type = type;
      delete data.links[idx].weight;
      data.links[idx].counts = makeCounts(type, 1);
    }
    // Update DOM class, marker, data-type
    edgeEl.classList.remove('developpe', 'atteint', 'reinvesti');
    edgeEl.classList.add(type);
    edgeEl.setAttribute('data-type', type);
    edgeEl.setAttribute('stroke', typeColor[type] || '#999');
    edgeEl.setAttribute('marker-end', `url(#${markerIdForType(type)})`);
    if (edgeEl.__hit) edgeEl.__hit.setAttribute('data-type', type);
    recomputeStrokeWidths();
    if (window.applyCompetenceTypeFilters) { window.applyCompetenceTypeFilters(); syncHitVisibility(); }
  }

  function deleteLink(edgeEl) {
    // If hit path provided, map to visual
    if (edgeEl && edgeEl.__visual) edgeEl = edgeEl.__visual;
    const { cours_id, competence_id } = idsFromAttrs(edgeEl.getAttribute('data-source'), edgeEl.getAttribute('data-target'));
    const type = edgeEl.getAttribute('data-type');
    const pos = data.links.findIndex(l => l.cours_id === cours_id && l.competence_id === competence_id && l.type === type);
    if (pos >= 0) data.links.splice(pos, 1);
    // Remove visual + hit
    if (edgeEl.__hit && edgeEl.__hit.parentNode) edgeEl.__hit.parentNode.removeChild(edgeEl.__hit);
    if (edgeEl.parentNode) edgeEl.parentNode.removeChild(edgeEl);
    selectedEdge = null;
    selectedEdges.delete(edgeEl);
    recomputeStrokeWidths();
    if (window.applyCompetenceTypeFilters) { window.applyCompetenceTypeFilters(); }
  }

  function makeCounts(type, w) {
    return {
      developpe: type === 'developpe' ? 1 : 0,
      atteint: type === 'atteint' ? 1 : 0,
      reinvesti: type === 'reinvesti' ? 1 : 0,
      total: 1
    };
  }

  function beginLinkCreation() {
    if (!editMode) return;
    creating = { active: true, sourceEl: null, targetEl: null };
    showBadgeText('Édition — sélectionnez un nœud source');
    // Highlight selectable nodes
    nodesG.classList.add('picking');
  }

  function selectLinkSource(nodeEl) {
    if (!creating.active) return;
    creating.sourceEl = nodeEl;
    showBadgeText('Édition — sélectionnez un nœud cible');
  }

  function selectLinkTarget(nodeEl) {
    if (!creating.active || !creating.sourceEl) return;
    creating.targetEl = nodeEl;
    openCreatePanel();
  }

  function svgToContainerXY(x, y) {
    const pt = svg.createSVGPoint();
    pt.x = x; pt.y = y;
    const screen = pt.matrixTransform(nodesG.getScreenCTM());
    const rect = container.getBoundingClientRect();
    return { x: screen.x - rect.left, y: screen.y - rect.top };
  }

  function isValidPair(aEl, bEl) {
    if (!aEl || !bEl) return false;
    const ak = (aEl.getAttribute('data-node-kind') || aEl.dataset.kind);
    const bk = (bEl.getAttribute('data-node-kind') || bEl.dataset.kind);
    return (ak === 'course' && bk === 'competence') || (ak === 'competence' && bk === 'course');
  }

  function openCreatePanel() {
    if (!isValidPair(creating.sourceEl, creating.targetEl)) {
      showBanner('Sélectionnez un cours et une compétence', 'warning');
      cancelCreation();
      return;
    }
    closePanels();
    const panel = document.createElement('div');
    panel.className = 'card shadow-sm p-2';
    panel.style.position = 'absolute';
    panel.style.zIndex = '1000';
    panel.style.minWidth = '240px';
    panel.innerHTML = `
      <div class="mb-2"><strong>Nouveau lien</strong></div>
      <div class="mb-2">
        <label class="form-label form-label-sm">Type du lien</label>
        <select class="form-select form-select-sm" id="nl-type">
          <option value="developpe">Développé significativement</option>
          <option value="atteint">Atteint</option>
          <option value="reinvesti">Réinvesti</option>
        </select>
      </div>
      
      
      <div class="d-flex gap-2 justify-content-end">
        <button class="btn btn-sm btn-outline-secondary" id="nl-cancel">Annuler</button>
        <button class="btn btn-sm btn-primary" id="nl-create">Créer</button>
      </div>
    `;
    container.appendChild(panel);
    // Place between nodes
    const a = parseTranslate(creating.sourceEl);
    const b = parseTranslate(creating.targetEl);
    const midx = (a.x + b.x) / 2; const midy = (a.y + b.y) / 2;
    const cxy = svgToContainerXY(midx, midy);
    panel.style.left = Math.max(8, cxy.x - 120) + 'px';
    panel.style.top = Math.max(8, cxy.y - 80) + 'px';
    panels.push(panel);

    panel.querySelector('#nl-cancel').addEventListener('click', () => { cancelCreation(); closePanels(); });
    panel.querySelector('#nl-create').addEventListener('click', () => {
      const type = panel.querySelector('#nl-type').value;
      createLink({ sourceNode: creating.sourceEl, targetNode: creating.targetEl, type });
      closePanels();
    });
  }

  function createLink({ sourceNode, targetNode, type }) {
    const sKey = sourceNode.getAttribute('data-node-id') || sourceNode.dataset.id;
    const tKey = targetNode.getAttribute('data-node-id') || targetNode.dataset.id;
    const sKind = (sourceNode.getAttribute('data-node-kind') || sourceNode.dataset.kind);
    const tKind = (targetNode.getAttribute('data-node-kind') || targetNode.dataset.kind);
    // Convert direction to cours_id -> competence_id
    let cours_id, competence_id;
    if (sKind === 'course' && tKind === 'competence') {
      cours_id = parseInt(sKey.split(':')[1], 10);
      competence_id = parseInt(tKey.split(':')[1], 10);
    } else if (sKind === 'competence' && tKind === 'course') {
      cours_id = parseInt(tKey.split(':')[1], 10);
      competence_id = parseInt(sKey.split(':')[1], 10);
    } else {
      // Invalid pair, ignore
      return;
    }
    // allow multiple links for same pair/types if needed; no dedup enforced
    const newLink = {
      cours_id,
      competence_id,
      type,
      counts: makeCounts(type, 1)
    };
    data.links.push(newLink);
    // Draw
    const sPos = parseTranslate(sourceNode);
    const tPos = parseTranslate(targetNode);
    // Render as competence -> course path regardless of click order
    const compEl = (sKind === 'competence') ? sourceNode : targetNode;
    const courseEl = (sKind === 'course') ? sourceNode : targetNode;
    const compPos = parseTranslate(compEl);
    const coursePos = parseTranslate(courseEl);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', cubicPath(compPos.x + 20, compPos.y, coursePos.x - 40, coursePos.y));
    path.setAttribute('class', `link ${type}`);
    path.setAttribute('stroke', typeColor[type] || '#999');
    path.setAttribute('fill', 'none');
    path.setAttribute('marker-end', `url(#${markerIdForType(type)})`);
    path.setAttribute('data-source', compEl.getAttribute('data-node-id'));
    path.setAttribute('data-target', courseEl.getAttribute('data-node-id'));
    path.setAttribute('data-type', type);
    linksG.appendChild(path);
    // Create large hit target and listeners
    const hit = ensureHitForPath(path);
    recomputeStrokeWidths();
    // Re-wire listener if in edit mode
    if (editMode && hit) attachEdgeEditListeners(hit);
    cancelCreation();
    if (window.applyCompetenceTypeFilters) { window.applyCompetenceTypeFilters(); syncHitVisibility(); }
  }

  function cancelCreation() {
    creating = { active: false, sourceEl: null, targetEl: null };
    showBadgeText('Édition activée');
    if (dragLine) { dragLine.remove(); dragLine = null; }
  }

  function showBadgeText(text) {
    if (badge) { badge.textContent = text; }
  }

  function saveLinks() {
    return JSON.parse(JSON.stringify(data.links));
  }

  // Panels handling
  const panels = [];
  function closePanels() {
    panels.splice(0).forEach(p => p.remove());
    // keep selection unless explicitly cleared elsewhere
  }

  function clearSelection() {
    if (selectedEdge) { selectedEdge.classList.remove('selected'); selectedEdge = null; }
    selectedEdges.forEach(p => p.classList.remove('selected'));
    selectedEdges.clear();
    removeMultiPanel();
  }

  function markSelected(path) {
    path.classList.add('selected');
    selectedEdges.add(path);
  }

  function showMultiPanel() {
    removeMultiPanel();
    if (!selectedEdges.size) return;
    const panel = document.createElement('div');
    panel.className = 'card shadow-sm p-2';
    panel.style.position = 'absolute';
    panel.style.zIndex = '1000';
    panel.style.minWidth = '240px';
    panel.style.right = '12px';
    panel.style.top = '12px';
    panel.innerHTML = `
      <div class="mb-2"><strong>Sélection: ${selectedEdges.size} lien(s)</strong></div>
      <div class="mb-2">
        <label class="form-label form-label-sm">Appliquer le type</label>
        <select class="form-select form-select-sm" id="ms-type">
          <option value="developpe">Développé significativement</option>
          <option value="atteint">Atteint</option>
          <option value="reinvesti">Réinvesti</option>
        </select>
      </div>
      <div class="d-flex gap-2 justify-content-end">
        <button class="btn btn-sm btn-outline-danger" id="ms-delete">Supprimer</button>
        <button class="btn btn-sm btn-primary" id="ms-apply">Appliquer</button>
      </div>`;
    container.appendChild(panel);
    panels.push(panel);
    panel.querySelector('#ms-delete').addEventListener('click', () => {
      // delete all selected
      Array.from(selectedEdges).forEach(p => deleteLink(p));
      clearSelection();
      showBanner('Liens supprimés de la sélection', 'success');
    });
    panel.querySelector('#ms-apply').addEventListener('click', () => {
      const type = panel.querySelector('#ms-type').value;
      Array.from(selectedEdges).forEach(p => updateLink(p, { type }));
      showBanner('Type appliqué à la sélection', 'success');
    });
  }

  function removeMultiPanel() {
    const idx = panels.findIndex(p => p && p.querySelector && p.querySelector('#ms-apply'));
    if (idx >= 0) { const p = panels.splice(idx,1)[0]; if (p) p.remove(); }
  }

  // Edit mode toggle
  function enableEditMode() {
    if (editMode) return;
    editMode = true;
    document.body.classList.add('edit-mode');
    if (badge) {
      badge.classList.remove('d-none');
      showBadgeText('Édition activée');
    }
    // show save button
    if (saveBtn) saveBtn.classList.remove('d-none');
    // Create hit overlays and attach listeners
    currentEdges().forEach(p => { const h = ensureHitForPath(p); attachEdgeEditListeners(h); });
    syncHitVisibility();
    // Marquee selection on container background
    container.addEventListener('pointerdown', onMarqueeDown, true);
    window.addEventListener('pointermove', onMarqueeMove, true);
    window.addEventListener('pointerup', onMarqueeUp, true);
    // Attach listeners to nodes for creation tool (click and drag)
    nodesG.addEventListener('click', onNodeClickForCreation, true);
    attachDragCreate();
    window.addEventListener('keydown', onKeydown);
  }

  function disableEditMode() {
    editMode = false;
    addLinkTool = false;
    document.body.classList.remove('edit-mode');
    if (badge) badge.classList.add('d-none');
    // hide save button
    if (saveBtn) saveBtn.classList.add('d-none');
    // Remove listeners and hit overlays
    currentEdges().forEach(p => { if (p.__hit) { detachEdgeEditListeners(p.__hit); p.__hit.remove(); delete p.__hit; } });
    container.removeEventListener('pointerdown', onMarqueeDown, true);
    window.removeEventListener('pointermove', onMarqueeMove, true);
    window.removeEventListener('pointerup', onMarqueeUp, true);
    clearSelection();
    nodesG.removeEventListener('click', onNodeClickForCreation, true);
    detachDragCreate();
    window.removeEventListener('keydown', onKeydown);
    closePanels();
    clearSelection();
  }

  function syncHitVisibility() {
    currentEdges().forEach(p => { if (p.__hit) { p.__hit.style.display = (p.style.display === 'none' ? 'none' : ''); } });
  }

  // Keep hits visibility in sync when filters change
  document.addEventListener('competenceTypeFiltersApplied', () => { if (editMode) syncHitVisibility(); });

  function setAddLinkTool(enabled) {
    // Optional legacy toggle; drag-to-create is always available in edit mode now
    if (!editMode) return;
    addLinkTool = !!enabled;
    if (addLinkTool) { beginLinkCreation(); }
    else { cancelCreation(); }
  }

  function attachEdgeEditListeners(path) {
    let down = null;
    function onDown(e) {
      down = { x: e.clientX, y: e.clientY, t: performance.now() };
    }
    function onUp(e) {
      if (!down) return;
      const dx = Math.abs(e.clientX - down.x);
      const dy = Math.abs(e.clientY - down.y);
      const dt = performance.now() - down.t;
      down = null;
      if (dx < 4 && dy < 4 && dt < 500) {
        e.stopPropagation(); e.preventDefault();
        openLinkEditor(path, e);
      }
    }
    path.__leDown = onDown;
    path.__leUp = onUp;
    path.addEventListener('pointerdown', onDown);
    path.addEventListener('pointerup', onUp);
  }
  function detachEdgeEditListeners(path) {
    if (path.__leDown) { path.removeEventListener('pointerdown', path.__leDown); delete path.__leDown; }
    if (path.__leUp) { path.removeEventListener('pointerup', path.__leUp); delete path.__leUp; }
  }

  function onNodeClickForCreation(e) {
    if (!editMode || dragLine) return;
    const g = e.target.closest('g.node');
    if (!g) return;
    if (!creating.sourceEl) selectLinkSource(g);
    else if (!creating.targetEl) selectLinkTarget(g);
    e.stopPropagation(); e.preventDefault();
  }

  // --- UI wiring: Edit toggle and Save ---
  function wireButtons() {
    // Edit toggle
    if (editToggleBtn && !editToggleBtn.__wired) {
      editToggleBtn.__wired = true;
      editToggleBtn.addEventListener('click', () => {
        const isActive = document.body.classList.contains('edit-mode');
        if (isActive) {
          disableEditMode();
          editToggleBtn.setAttribute('aria-pressed', 'false');
          editToggleBtn.classList.remove('btn-danger');
          editToggleBtn.classList.add('btn-outline-danger');
        } else {
          enableEditMode();
          editToggleBtn.setAttribute('aria-pressed', 'true');
          editToggleBtn.classList.add('btn-danger');
          editToggleBtn.classList.remove('btn-outline-danger');
        }
      });
    }
    // Save links to backend
    if (saveBtn && !saveBtn.__wired) {
      saveBtn.__wired = true;
      saveBtn.addEventListener('click', async () => {
        try {
          const payload = saveLinks();
          const programmeId = (data.programme && data.programme.id) ? String(data.programme.id) : '';
          if (!programmeId) throw new Error('Programme introuvable');
          const url = `/programme/${encodeURIComponent(programmeId)}/links`;
          const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
          saveBtn.disabled = true;
          const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(payload) });
          const out = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(out.error || ('HTTP '+resp.status));
          showBanner(out.message || 'Liens enregistrés', 'success');
          // Exit edit mode after save for clarity
          disableEditMode();
        } catch (e) {
          showBanner(e && e.message ? e.message : 'Erreur lors de la sauvegarde', 'danger');
        } finally {
          saveBtn.disabled = false;
        }
      });
    }
  }

  // Small banner helper
  function showBanner(text, kind) {
    try {
      const main = document.querySelector('main.container') || document.body;
      const alert = document.createElement('div');
      alert.className = `alert alert-${kind||'info'} alert-dismissible fade show`;
      alert.role = 'alert';
      alert.innerHTML = `${text}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>`;
      main.prepend(alert);
    } catch (_) {}
  }

  // Wire immediately (buttons exist in the same page)
  wireButtons();

  // Expose API for other scripts (generation overlay, etc.)
  window.LinkEditor = {
    enableEditMode,
    disableEditMode,
    setAddLinkTool,
    beginLinkCreation,
    selectLinkSource,
    selectLinkTarget,
    createLink,
    openLinkEditor,
    updateLink,
    deleteLink,
    saveLinks
  };

  function onKeydown(e) {
    if (!editMode) return;
    if (e.key === 'Escape') { cancelCreation(); closePanels(); clearSelection(); }
    if ((e.key === 'Delete' || e.key === 'Backspace')) {
      if (selectedEdges.size) { Array.from(selectedEdges).forEach(p => deleteLink(p)); clearSelection(); }
      else if (selectedEdge) { deleteLink(selectedEdge); closePanels(); }
    }
  }

  // Wire toolbar buttons
  if (editToggleBtn) {
    editToggleBtn.addEventListener('click', () => {
      const active = editToggleBtn.getAttribute('aria-pressed') === 'true';
      if (active) {
        editToggleBtn.setAttribute('aria-pressed', 'false');
        editToggleBtn.classList.remove('btn-danger');
        editToggleBtn.classList.add('btn-outline-danger');
        disableEditMode();
      } else {
        editToggleBtn.setAttribute('aria-pressed', 'true');
        editToggleBtn.classList.remove('btn-outline-danger');
        editToggleBtn.classList.add('btn-danger');
        enableEditMode();
      }
    });
  }
  // No add link button: creation works by click or drag in edit mode

  // Drag-to-create interactions
  function svgPointFromClient(e) {
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    // Use nodesG to account for current zoom/pan transform
    return pt.matrixTransform(nodesG.getScreenCTM().inverse());
  }
  function attachDragCreate() {
    nodesG.addEventListener('pointerdown', dragPointerDown, true);
    window.addEventListener('pointermove', dragPointerMove, true);
    window.addEventListener('pointerup', dragPointerUp, true);
  }
  function detachDragCreate() {
    nodesG.removeEventListener('pointerdown', dragPointerDown, true);
    window.removeEventListener('pointermove', dragPointerMove, true);
    window.removeEventListener('pointerup', dragPointerUp, true);
  }
  function dragPointerDown(e) {
    if (!editMode) return;
    const g = e.target.closest('g.node');
    if (!g) return;
    e.preventDefault(); e.stopPropagation();
    creating.sourceEl = g;
    creating.active = true;
    // Create temp path
    if (!dragLine) {
      dragLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      dragLine.setAttribute('class', 'link');
      dragLine.setAttribute('stroke', '#888');
      dragLine.setAttribute('fill', 'none');
      linksG.appendChild(dragLine);
    }
    const s = parseTranslate(g);
    const p = svgPointFromClient(e);
    dragLine.setAttribute('d', cubicPath(s.x + 20, s.y, p.x, p.y));
  }
  function dragPointerMove(e) {
    if (!creating.active || !dragLine) return;
    const s = parseTranslate(creating.sourceEl);
    const p = svgPointFromClient(e);
    dragLine.setAttribute('d', cubicPath(s.x + 20, s.y, p.x, p.y));
  }
  function dragPointerUp(e) {
    if (!creating.active) return;
    const target = e.target.closest && e.target.closest('g.node');
    if (target && target !== creating.sourceEl) {
      creating.targetEl = target;
      openCreatePanel();
    }
    if (dragLine) { dragLine.remove(); dragLine = null; }
    // Keep creating.sourceEl/targetEl for the panel; reset will happen on create/cancel
  }

  // Marquee selection helpers (screen space)
  function onMarqueeDown(e) {
    if (!editMode) return;
    // ignore if started on nodes or links
    if (isNodeTarget(e.target) || isEdgeHitTarget(e.target)) return;
    e.preventDefault(); e.stopPropagation();
    marquee.active = true; marquee.startX = e.clientX; marquee.startY = e.clientY;
    if (!marquee.boxEl) {
      marquee.boxEl = document.createElement('div');
      marquee.boxEl.style.position = 'absolute';
      marquee.boxEl.style.border = '1px dashed #0d6efd';
      marquee.boxEl.style.background = 'rgba(13,110,253,0.08)';
      marquee.boxEl.style.pointerEvents = 'none';
      marquee.boxEl.style.zIndex = '1000';
      container.appendChild(marquee.boxEl);
    }
    marquee.boxEl.style.display = 'block';
    marquee.boxEl.style.left = (e.clientX - container.getBoundingClientRect().left) + 'px';
    marquee.boxEl.style.top = (e.clientY - container.getBoundingClientRect().top) + 'px';
    marquee.boxEl.style.width = '0px';
    marquee.boxEl.style.height = '0px';
  }
  function onMarqueeMove(e) {
    if (!editMode || !marquee.active || !marquee.boxEl) return;
    const r = container.getBoundingClientRect();
    const x1 = marquee.startX, y1 = marquee.startY;
    const x2 = e.clientX, y2 = e.clientY;
    const left = Math.min(x1, x2) - r.left;
    const top = Math.min(y1, y2) - r.top;
    const w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
    marquee.boxEl.style.left = left + 'px';
    marquee.boxEl.style.top = top + 'px';
    marquee.boxEl.style.width = w + 'px';
    marquee.boxEl.style.height = h + 'px';
  }
  function onMarqueeUp(e) {
    if (!editMode || !marquee.active) return;
    marquee.active = false;
    if (marquee.boxEl) marquee.boxEl.style.display = 'none';
    // Compute selection in screen coords
    const x1 = Math.min(marquee.startX, e.clientX);
    const y1 = Math.min(marquee.startY, e.clientY);
    const x2 = Math.max(marquee.startX, e.clientX);
    const y2 = Math.max(marquee.startY, e.clientY);
    if (Math.abs(x2-x1) < 3 || Math.abs(y2-y1) < 3) return; // too small
    // Multi-select any edge whose bounding box intersects the rectangle
    clearSelection();
    currentEdges().forEach(p => {
      const bb = (p.__hit || p).getBoundingClientRect();
      const ix1 = Math.max(x1, bb.left), iy1 = Math.max(y1, bb.top);
      const ix2 = Math.min(x2, bb.right), iy2 = Math.min(y2, bb.bottom);
      if (ix2 > ix1 && iy2 > iy1) markSelected(p);
    });
    if (selectedEdges.size) showMultiPanel();
  }

  // Save to server
  async function persistLinks() {
    try {
      const url = `/programme/${data.programme.id}/links`;
      const payload = saveLinks();
      const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf || ''
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const out = await res.json().catch(() => ({}));
      showBanner(out.message || 'Liens enregistrés', 'success');
      return true;
    } catch (e) {
      console.error('Save failed', e);
      showBanner("Erreur lors de l'enregistrement", 'danger');
      return false;
    }
  }
  if (saveBtn) saveBtn.addEventListener('click', () => { if (editMode) persistLinks(); });
  if (editToggleBtn && !editToggleBtn.__leWired) {
    editToggleBtn.__leWired = true;
    editToggleBtn.addEventListener('click', () => {
      const isActive = document.body.classList.contains('edit-mode');
      if (isActive) {
        disableEditMode();
        editToggleBtn.setAttribute('aria-pressed', 'false');
        editToggleBtn.classList.remove('btn-danger');
        editToggleBtn.classList.add('btn-outline-danger');
      } else {
        enableEditMode();
        editToggleBtn.setAttribute('aria-pressed', 'true');
        editToggleBtn.classList.add('btn-danger');
        editToggleBtn.classList.remove('btn-outline-danger');
      }
    });
  }

  // Public API
  window.LinkEditor = {
    enableEditMode, disableEditMode, setAddLinkTool,
    beginLinkCreation, selectLinkSource, selectLinkTarget, createLink,
    openLinkEditor, updateLink, deleteLink,
    saveLinks, persistLinks
  };
  window.saveLinks = saveLinks;

  function showBanner(message, variant = 'success') {
    try {
      const main = document.querySelector('main.container') || document.body;
      const alert = document.createElement('div');
      alert.className = `alert alert-${variant} alert-dismissible fade show`;
      alert.role = 'alert';
      alert.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>`;
      main.prepend(alert);
      setTimeout(() => {
        alert.classList.remove('show');
        alert.addEventListener('transitionend', () => alert.remove());
      }, 2400);
    } catch (_) {
      showBadgeText(message);
    }
  }
})();
