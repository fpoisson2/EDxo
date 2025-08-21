/* Interactive compétences ↔ cours logigramme (vanilla SVG)
 * Data provided via window.COMPETENCE_MAP_DATA
 */
(function () {
  const data = (window.COMPETENCE_MAP_DATA || {});
  const svg = document.getElementById('competenceGraph');
  if (!svg || !data || !data.competences) return;

  let WIDTH = svg.clientWidth || svg.parentElement.clientWidth || 1200;
  const HEIGHT = svg.clientHeight || 700;
  const margin = { top: 40, right: 40, bottom: 40, left: 40 };
  const colGap = 220; // horizontal distance between columns
  const compColX = margin.left + 120; // x for competence column

  // Sessions columns (at least one)
  const sessions = (data.sessions && data.sessions.length ? data.sessions : [0]).sort((a,b)=>a-b);
  const sessionCols = sessions.map((s, idx) => ({ session: s, x: compColX + (idx+1) * colGap }));
  // Dynamic width to fit all columns
  const rightMost = sessionCols.length ? sessionCols[sessionCols.length - 1].x : compColX;
  WIDTH = Math.max(WIDTH, rightMost + margin.right + 200);

  // Compute positions
  const compSpacing = Math.max(40, (HEIGHT - margin.top - margin.bottom) / Math.max(1, data.competences.length));
  const comps = data.competences.map((c, i) => ({
    ...c,
    x: compColX,
    y: margin.top + (i + 0.5) * compSpacing,
    type: 'competence'
  }));
  const compsById = new Map(comps.map(c => [c.id, c]));

  // Group courses by session
  const coursesBySession = new Map();
  data.cours.forEach(c => {
    const s = Number(c.session || 0);
    if (!coursesBySession.has(s)) coursesBySession.set(s, []);
    coursesBySession.get(s).push(c);
  });
  // For each session, distribute vertically
  const courses = [];
  sessionCols.forEach(col => {
    const arr = (coursesBySession.get(col.session) || []).slice().sort((a,b)=> (a.code||'').localeCompare(b.code||''));
    const spacing = Math.max(40, (HEIGHT - margin.top - margin.bottom) / Math.max(1, arr.length));
    arr.forEach((c, i) => {
      courses.push({
        ...c,
        x: col.x,
        y: margin.top + (i + 0.5) * spacing,
        type: 'course'
      });
    });
  });
  const coursesById = new Map(courses.map(c => [c.id, c]));

  // Normalize links and index per node
  const links = (data.links || []).map(l => ({
    ...l,
    source: compsById.get(l.competence_id),
    target: coursesById.get(l.cours_id)
  })).filter(l => l.source && l.target);

  // SVG helpers
  function make(tag, attrs, parent) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  }
  function cubicPath(x1, y1, x2, y2) {
    const dx = (x2 - x1) * 0.5;
    const c1x = x1 + dx, c1y = y1;
    const c2x = x2 - dx, c2y = y2;
    return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
  }

  // Set viewBox and clear
  svg.setAttribute('viewBox', `0 0 ${WIDTH} ${HEIGHT}`);
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Defs: arrowheads
  const defs = make('defs', null, svg);
  const markers = [
    { id: 'arrow-dev', color: '#0d6efd' },
    { id: 'arrow-att', color: '#198754' },
    { id: 'arrow-rei', color: '#6c757d' }
  ];
  markers.forEach(m => {
    const mk = make('marker', { id: m.id, viewBox: '0 0 10 10', refX: '10', refY: '5', markerWidth: '8', markerHeight: '8', orient: 'auto-start-reverse' }, defs);
    make('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: m.color }, mk);
  });

  // Zoom/pan container
  const rootG = make('g', { id: 'root' }, svg);
  let viewScale = 1.0;
  let viewX = 0, viewY = 0;
  function applyView() {
    rootG.setAttribute('transform', `translate(${viewX},${viewY}) scale(${viewScale})`);
  }
  applyView();

  // Column guides and titles
  const guidesG = make('g', null, rootG);
  // Competence column title
  make('text', { x: compColX, y: 18, class: 'col-title', 'text-anchor': 'middle' }, guidesG).textContent = 'Compétences';
  sessionCols.forEach((col, idx) => {
    make('line', { x1: col.x, y1: 26, x2: col.x, y2: HEIGHT - 10, class: 'col-guide' }, guidesG);
    make('text', { x: col.x, y: 18, class: 'col-title', 'text-anchor': 'middle' }, guidesG).textContent = `Session ${col.session}`;
  });

  // Layers
  const linksG = make('g', { id: 'links' }, rootG);
  const nodesG = make('g', { id: 'nodes' }, rootG);

  // Draw links
  const maxWeight = links.reduce((m, l) => Math.max(m, l.weight || 1), 1);
  const typeColor = { developpe: '#0d6efd', atteint: '#198754', reinvesti: '#6c757d' };
  const linkEls = links.map(l => {
    const path = make('path', {
      d: cubicPath(l.source.x + 20, l.source.y, l.target.x - 40, l.target.y),
      class: `link ${l.type}`,
      'stroke-width': String(1.5 + 2.5 * ((l.weight || 1) / maxWeight)),
      stroke: typeColor[l.type] || '#999',
      fill: 'none',
      'data-source': `comp:${String(l.source.id)}`,
      'data-target': `course:${String(l.target.id)}`,
      'data-type': l.type
    }, linksG);
    // Arrowhead per type
    const markerId = l.type === 'developpe' ? 'arrow-dev' : (l.type === 'atteint' ? 'arrow-att' : 'arrow-rei');
    path.setAttribute('marker-end', `url(#${markerId})`);
    return { el: path, link: l };
  });

  // Draw nodes – competences
  const nodeEls = [];
  comps.forEach(c => {
    const g = make('g', { class: 'node comp', transform: `translate(${c.x},${c.y})` }, nodesG);
    const circle = make('circle', { r: 16 }, g);
    circle.classList.add('shadow');
    const label = make('text', { class: 'node-label', x: 22, y: 4 }, g);
    label.textContent = c.code || `C${c.id}`;
    const title = make('title', null, g);
    title.textContent = `${c.code} — ${c.nom}`;
    g.dataset.id = `comp:${String(c.id)}`;
    g.dataset.kind = 'competence';
    nodeEls.push({ el: g, node: c });
  });

  // Draw nodes – courses
  // Session palette
  const sessionPalette = ['#00bcd4','#ff9800','#8bc34a','#e91e63','#9c27b0','#3f51b5','#795548','#607d8b'];
  function colorForSession(s) { const idx = Math.max(0, sessions.indexOf(Number(s))); return sessionPalette[idx % sessionPalette.length]; }

  courses.forEach(c => {
    const g = make('g', { class: 'node course', transform: `translate(${c.x},${c.y})` }, nodesG);
    g.dataset.session = String(c.session || 0);
    const rect = make('rect', { x: -60, y: -16, width: 120, height: 32, rx: 6, ry: 6 }, g);
    rect.classList.add('shadow');
    // Fill by fil color if present, else by session color
    const sessCol = colorForSession(c.session || 0);
    if (c.fil_color) {
      rect.style.fill = c.fil_color;
      // Session ribbon at top
      make('rect', { x: -60, y: -16, width: 120, height: 4, rx: 4, ry: 4, fill: sessCol }, g);
    } else {
      rect.style.fill = sessCol;
    }
    const label = make('text', { class: 'node-label', 'text-anchor': 'middle', x: 0, y: 4 }, g);
    label.textContent = c.code || `CO${c.id}`;
    const title = make('title', null, g);
    title.textContent = `${c.code} — ${c.nom}`;
    g.dataset.id = `course:${String(c.id)}`;
    g.dataset.kind = 'course';
    nodeEls.push({ el: g, node: c });
  });

  // Interaction helpers
  function setDimState(activeIds) {
    // Only show links whose both ends are in the active set
    linkEls.forEach(({ el }) => {
      const src = el.getAttribute('data-source');
      const tgt = el.getAttribute('data-target');
      const isActive = activeIds.has(src) && activeIds.has(tgt);
      el.classList.toggle('dim', !isActive);
      el.style.display = isActive ? '' : 'none';
    });
    // Highlight nodes in the set, dim others
    nodeEls.forEach(({ el }) => {
      const id = el.dataset.id;
      const isOn = activeIds.has(id);
      el.classList.toggle('highlight', isOn);
      el.classList.toggle('dim', !isOn);
    });
  }
  function clearDim() {
    linkEls.forEach(({ el }) => { el.classList.remove('dim'); el.style.display = ''; });
    nodeEls.forEach(({ el }) => { el.classList.remove('highlight'); el.classList.remove('dim'); });
  }

  // Hover highlight and click to pin
  // Single-select pinning across nodes
  let pinnedId = null;
  function highlightNode(el) {
    const id = el.dataset.id;
    const connected = new Set([id]);
    if (el.dataset.kind === 'competence') {
      // Add only connected courses
      linkEls.forEach(({ el: pl }) => { if (pl.getAttribute('data-source') === id) connected.add(pl.getAttribute('data-target')); });
    } else {
      // Add only connected competences
      linkEls.forEach(({ el: pl }) => { if (pl.getAttribute('data-target') === id) connected.add(pl.getAttribute('data-source')); });
    }
    setDimState(connected);
  }
  nodeEls.forEach(({ el }) => {
    el.addEventListener('mouseenter', () => { if (pinnedId === null) highlightNode(el); });
    el.addEventListener('mouseleave', () => { if (pinnedId === null) clearDim(); });
    el.addEventListener('click', () => {
      const id = el.dataset.id;
      if (pinnedId === id) {
        pinnedId = null;
        clearDim();
      } else {
        pinnedId = id;
        highlightNode(el);
      }
    });
  });

  // Drag to adjust Y
  // Drag with SVG-space coordinates (stable with zoom/pan)
  function svgPoint(evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const inv = svg.getScreenCTM().inverse();
    return pt.matrixTransform(inv);
  }
  nodeEls.forEach(({ el, node }) => {
    let dragging = false;
    let startYw = 0; // start y in world coords
    let nodeStartY = 0;
    el.addEventListener('mousedown', (e) => {
      dragging = true;
      el.classList.add('dragging');
      const wp = svgPoint(e);
      startYw = wp.y;
      nodeStartY = node.y;
      e.preventDefault();
      e.stopPropagation(); // prevent panning start
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const wp = svgPoint(e);
      const dy = wp.y - startYw;
      node.y = Math.max(margin.top + 16, Math.min(HEIGHT - margin.bottom - 16, nodeStartY + dy));
      el.setAttribute('transform', `translate(${node.x},${node.y})`);
      // update links
      linkEls.forEach(({ el: pl, link }) => {
        if (link.source === node) {
          pl.setAttribute('d', cubicPath(link.source.x + 20, link.source.y, link.target.x - 40, link.target.y));
        } else if (link.target === node) {
          pl.setAttribute('d', cubicPath(link.source.x + 20, link.source.y, link.target.x - 40, link.target.y));
        }
      });
    });
    window.addEventListener('mouseup', () => { dragging = false; el.classList.remove('dragging'); });
  });

  // Filtering by type
  const toggleDeveloppee = document.getElementById('toggleDeveloppee');
  const toggleAtteinte = document.getElementById('toggleAtteinte');
  const toggleReinvesti = document.getElementById('toggleReinvesti');
  function applyTypeFilters() {
    const showDev = toggleDeveloppee ? toggleDeveloppee.checked : true;
    const showAtt = toggleAtteinte ? toggleAtteinte.checked : true;
    const showRei = toggleReinvesti ? toggleReinvesti.checked : true;
    linkEls.forEach(({ el, link }) => {
      const show = (link.type === 'developpe' && showDev) || (link.type === 'atteint' && showAtt) || (link.type === 'reinvesti' && showRei);
      el.style.display = show ? '' : 'none';
    });
  }
  if (toggleDeveloppee) toggleDeveloppee.addEventListener('change', applyTypeFilters);
  if (toggleAtteinte) toggleAtteinte.addEventListener('change', applyTypeFilters);
  if (toggleReinvesti) toggleReinvesti.addEventListener('change', applyTypeFilters);
  applyTypeFilters();

  // Search highlight
  const searchBox = document.getElementById('searchBox');
  function applySearch() {
    const raw = (searchBox.value || '').trim();
    const q = raw.toLocaleLowerCase();
    if (!q) { clearDim(); return; }
    const norm = (s) => (s || '').toString().normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
    const nq = norm(q);
    const matched = new Set();
    nodeEls.forEach(({ el, node }) => {
      const label = `${node.code || ''} ${node.nom || ''}`;
      if (norm(label).includes(nq)) matched.add(el.dataset.id);
    });
    if (matched.size) {
      const expanded = new Set(matched);
      // Expand to neighbors
      linkEls.forEach(({ el: pl }) => {
        const src = pl.getAttribute('data-source');
        const tgt = pl.getAttribute('data-target');
        if (matched.has(src)) expanded.add(tgt);
        if (matched.has(tgt)) expanded.add(src);
      });
      setDimState(expanded);
    } else { clearDim(); }
  }
  if (searchBox) {
    searchBox.addEventListener('input', applySearch);
  }

  // Zoom controls: wheel zoom + drag pan + buttons
  let panning = false; let panStart = { x: 0, y: 0 }; let viewStart = { x: 0, y: 0 };
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = -Math.sign(e.deltaY) * 0.1;
    const prev = viewScale;
    viewScale = Math.min(4, Math.max(0.25, viewScale * (1 + delta)));
    // Zoom relative to cursor position
    const ptX = e.offsetX; const ptY = e.offsetY;
    viewX = ptX - (ptX - viewX) * (viewScale / prev);
    viewY = ptY - (ptY - viewY) * (viewScale / prev);
    applyView();
  }, { passive: false });
  svg.addEventListener('mousedown', (e) => { panning = true; panStart = { x: e.clientX, y: e.clientY }; viewStart = { x: viewX, y: viewY }; });
  window.addEventListener('mousemove', (e) => { if (!panning) return; viewX = viewStart.x + (e.clientX - panStart.x); viewY = viewStart.y + (e.clientY - panStart.y); applyView(); });
  window.addEventListener('mouseup', () => { panning = false; });
  const zoomInBtn = document.getElementById('zoomInBtn');
  const zoomOutBtn = document.getElementById('zoomOutBtn');
  const resetViewBtn = document.getElementById('resetViewBtn');
  if (zoomInBtn) zoomInBtn.addEventListener('click', () => { viewScale = Math.min(4, viewScale * 1.2); applyView(); });
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => { viewScale = Math.max(0.25, viewScale / 1.2); applyView(); });
  if (resetViewBtn) resetViewBtn.addEventListener('click', () => { viewScale = 1; viewX = 0; viewY = 0; applyView(); });

  // Timeline disabled for now

  // Export SVG/PNG
  const exportSvgBtn = document.getElementById('exportSvgBtn');
  const exportPngBtn = document.getElementById('exportPngBtn');
  function download(filename, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  if (exportSvgBtn) exportSvgBtn.addEventListener('click', () => {
    const clone = svg.cloneNode(true);
    clone.removeAttribute('style');
    // Ensure stroke colors are set inline (already done) and include a minimal style
    const style = document.createElement('style');
    style.textContent = '.link{fill:none;opacity:.9}.node-label{font:12px Roboto,Arial,sans-serif;fill:#222}';
    clone.insertBefore(style, clone.firstChild);
    const ser = new XMLSerializer().serializeToString(clone);
    download('logigramme.svg', ser, 'image/svg+xml');
  });
  if (exportPngBtn) exportPngBtn.addEventListener('click', () => {
    const clone = svg.cloneNode(true);
    clone.removeAttribute('style');
    const ser = new XMLSerializer().serializeToString(clone);
    const img = new Image();
    const svgBlob = new Blob([ser], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    img.onload = function () {
      const canvas = document.createElement('canvas');
      canvas.width = WIDTH; canvas.height = HEIGHT;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0,0,WIDTH,HEIGHT);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'logigramme.png';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      }, 'image/png');
    };
    img.src = url;
  });

  // Build legend: only fils (sessions legend removed)
  const filLegend = document.getElementById('filLegend');
  if (filLegend && data.fils && data.fils.length) {
    filLegend.innerHTML = '';
    data.fils.forEach(f => {
      const dot = document.createElement('span');
      dot.className = 'legend-dot';
      dot.style.background = f.couleur || '#ccc';
      dot.title = f.description || 'Fil';
      filLegend.appendChild(dot);
      const txt = document.createElement('span');
      txt.textContent = ` ${(f.description||'Fil')} `;
      filLegend.appendChild(txt);
    });
  }

  // Info panel on click
  const infoPanel = document.getElementById('infoPanel');
  const infoTitle = document.getElementById('infoTitle');
  const infoBody = document.getElementById('infoBody');
  const infoClose = document.getElementById('infoClose');
  if (infoClose) infoClose.addEventListener('click', () => { infoPanel.style.display = 'none'; });
  function showInfoForNode(el, node, evt) {
    if (!infoPanel) return;
    if (el.dataset.kind === 'competence') {
      infoTitle.textContent = `Compétence ${node.code}`;
      const url = `/programme/competence/code/${encodeURIComponent(node.code)}`;
      infoBody.innerHTML = `
        <div><strong>Nom:</strong> ${node.nom || ''}</div>
        <div class="mt-1"><a class="btn btn-sm btn-outline-primary" href="${url}">Ouvrir la fiche compétence</a></div>
      `;
    } else {
      infoTitle.textContent = `Cours ${node.code}`;
      const url = `/cours/${node.id}/plan_cadre`;
      const ftxt = node.fil_desc ? ` — <span class="badge" style="background:${node.fil_color||'#ccc'}">${node.fil_desc}</span>` : '';
      infoBody.innerHTML = `
        <div><strong>Nom:</strong> ${node.nom || ''}</div>
        <div><strong>Session:</strong> ${node.session || ''}${ftxt}</div>
        <div class="mt-1 d-flex gap-2 flex-wrap">
          <a class="btn btn-sm btn-outline-secondary" href="/cours/${node.id}">Voir le cours</a>
          <a class="btn btn-sm btn-outline-primary" href="${url}">Ouvrir le plan-cadre</a>
        </div>
      `;
    }
    // Position near cursor, relative to viewport
    const vpW = window.innerWidth || document.documentElement.clientWidth;
    const vpH = window.innerHeight || document.documentElement.clientHeight;
    const mx = evt && typeof evt.clientX === 'number' ? evt.clientX : vpW / 2;
    const my = evt && typeof evt.clientY === 'number' ? evt.clientY : vpH / 2;
    const left = Math.max(8, Math.min(vpW - 280, mx + 12));
    const top = Math.max(8, Math.min(vpH - 160, my + 12));
    infoPanel.style.position = 'fixed';
    infoPanel.style.left = left + 'px';
    infoPanel.style.top = top + 'px';
    infoPanel.style.display = '';
  }
  // Integrate with selection: click = select, double-click = open popup
  nodeEls.forEach(({ el, node }) => {
    let clickTimer = null;
    el.addEventListener('click', (e) => {
      if (clickTimer) return;
      clickTimer = setTimeout(() => {
        clickTimer = null;
        const id = el.dataset.id;
        if (pinnedId === id) { pinnedId = null; clearDim(); }
        else { pinnedId = id; highlightNode(el); }
      }, 220);
    });
    el.addEventListener('dblclick', (e) => {
      if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
      showInfoForNode(el, node, e);
    });
  });
})();
/* Interactive compétences ↔ cours logigramme (vanilla SVG)
 * Data provided via window.COMPETENCE_MAP_DATA
 */
(function () {
  const data = (window.COMPETENCE_MAP_DATA || {});
  const svg = document.getElementById('competenceGraph');
  if (!svg || !data || !data.competences) return;

  let WIDTH = svg.clientWidth || svg.parentElement.clientWidth || 1200;
  const HEIGHT = svg.clientHeight || 700;
  const margin = { top: 40, right: 40, bottom: 40, left: 40 };
  const colGap = 220; // distance horizontale entre colonnes
  const compColX = margin.left + 120; // x pour la colonne compétences

  // Colonnes de sessions
  const sessions = (data.sessions && data.sessions.length ? data.sessions : [0]).sort((a,b)=>a-b);
  const sessionCols = sessions.map((s, idx) => ({ session: s, x: compColX + (idx+1) * colGap }));
  // Largeur dynamique
  const rightMost = sessionCols.length ? sessionCols[sessionCols.length - 1].x : compColX;
  WIDTH = Math.max(WIDTH, rightMost + margin.right + 200);

  // Positions des nœuds
  const compSpacing = Math.max(40, (HEIGHT - margin.top - margin.bottom) / Math.max(1, data.competences.length));
  const comps = data.competences.map((c, i) => ({
    ...c,
    x: compColX,
    y: margin.top + (i + 0.5) * compSpacing,
    type: 'competence'
  }));
  const compsById = new Map(comps.map(c => [c.id, c]));

  const coursesBySession = new Map();
  (data.cours || []).forEach(c => {
    const s = Number(c.session || 0);
    if (!coursesBySession.has(s)) coursesBySession.set(s, []);
    coursesBySession.get(s).push(c);
  });
  const courses = [];
  sessionCols.forEach(col => {
    const arr = (coursesBySession.get(col.session) || []).slice().sort((a,b)=> (a.code||'').localeCompare(b.code||''));
    const spacing = Math.max(40, (HEIGHT - margin.top - margin.bottom) / Math.max(1, arr.length));
    arr.forEach((c, i) => {
      courses.push({ ...c, x: col.x, y: margin.top + (i + 0.5) * spacing, type: 'course' });
    });
  });
  const coursesById = new Map(courses.map(c => [c.id, c]));

  // Liens normalisés
  const links = (data.links || []).map(l => ({
    ...l,
    source: compsById.get(l.competence_id),
    target: coursesById.get(l.cours_id)
  })).filter(l => l.source && l.target);

  // Helpers SVG
  function make(tag, attrs, parent) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  }
  function cubicPath(x1, y1, x2, y2) {
    const dx = (x2 - x1) * 0.5;
    const c1x = x1 + dx, c1y = y1;
    const c2x = x2 - dx, c2y = y2;
    return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
  }

  // ViewBox + clear
  svg.setAttribute('viewBox', `0 0 ${WIDTH} ${HEIGHT}`);
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Defs: flèches
  const defs = make('defs', null, svg);
  const markers = [
    { id: 'arrow-dev', color: '#0d6efd' },
    { id: 'arrow-att', color: '#198754' },
    { id: 'arrow-rei', color: '#6c757d' }
  ];
  markers.forEach(m => {
    const mk = make('marker', { id: m.id, viewBox: '0 0 10 10', refX: '10', refY: '5', markerWidth: '8', markerHeight: '8', orient: 'auto-start-reverse' }, defs);
    make('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: m.color }, mk);
  });

  // Conteneur zoom/pan
  const rootG = make('g', { id: 'root' }, svg);
  let viewScale = 1.0; let viewX = 0, viewY = 0;
  function applyView() { rootG.setAttribute('transform', `translate(${viewX},${viewY}) scale(${viewScale})`); }
  applyView();

  // Guides colonnes
  const guidesG = make('g', null, rootG);
  make('text', { x: compColX, y: 18, class: 'col-title', 'text-anchor': 'middle' }, guidesG).textContent = 'Compétences';
  sessionCols.forEach(col => {
    make('line', { x1: col.x, y1: 26, x2: col.x, y2: HEIGHT - 10, class: 'col-guide' }, guidesG);
    make('text', { x: col.x, y: 18, class: 'col-title', 'text-anchor': 'middle' }, guidesG).textContent = `Session ${col.session}`;
  });

  // Couches
  const linksG = make('g', { id: 'links' }, rootG);
  const nodesG = make('g', { id: 'nodes' }, rootG);

  // Dessin des liens
  const maxWeight = links.reduce((m, l) => Math.max(m, l.weight || 1), 1);
  const typeColor = { developpe: '#0d6efd', atteint: '#198754', reinvesti: '#6c757d' };
  const linkEls = links.map(l => {
    const path = make('path', {
      d: cubicPath(l.source.x + 20, l.source.y, l.target.x - 40, l.target.y),
      class: `link ${l.type}`,
      'stroke-width': String(1.5 + 2.5 * ((l.weight || 1) / maxWeight)),
      stroke: typeColor[l.type] || '#999',
      fill: 'none',
      'data-source': `comp:${String(l.source.id)}`,
      'data-target': `course:${String(l.target.id)}`,
      'data-type': l.type
    }, linksG);
    const markerId = l.type === 'developpe' ? 'arrow-dev' : (l.type === 'atteint' ? 'arrow-att' : 'arrow-rei');
    path.setAttribute('marker-end', `url(#${markerId})`);
    return { el: path, link: l };
  });

  // Dessin des nœuds: compétences
  const nodeEls = [];
  comps.forEach(c => {
    const g = make('g', { class: 'node comp', transform: `translate(${c.x},${c.y})` }, nodesG);
    make('circle', { r: 16 }, g).classList.add('shadow');
    const label = make('text', { class: 'node-label', x: 22, y: 4 }, g);
    label.textContent = c.code || `C${c.id}`;
    make('title', null, g).textContent = `${c.code} — ${c.nom}`;
    g.dataset.id = `comp:${String(c.id)}`;
    g.dataset.kind = 'competence';
    nodeEls.push({ el: g, node: c });
  });

  // Dessin des nœuds: cours
  const sessionPalette = ['#00bcd4','#ff9800','#8bc34a','#e91e63','#9c27b0','#3f51b5','#795548','#607d8b'];
  function colorForSession(s) { const idx = Math.max(0, sessions.indexOf(Number(s))); return sessionPalette[idx % sessionPalette.length]; }
  courses.forEach(c => {
    const g = make('g', { class: 'node course', transform: `translate(${c.x},${c.y})` }, nodesG);
    g.dataset.session = String(c.session || 0);
    const rect = make('rect', { x: -60, y: -16, width: 120, height: 32, rx: 6, ry: 6 }, g);
    rect.classList.add('shadow');
    const sessCol = colorForSession(c.session || 0);
    if (c.fil_color) {
      rect.style.fill = c.fil_color;
      make('rect', { x: -60, y: -16, width: 120, height: 4, rx: 4, ry: 4, fill: sessCol }, g);
    } else {
      rect.style.fill = sessCol;
    }
    const label = make('text', { class: 'node-label', 'text-anchor': 'middle', x: 0, y: 4 }, g);
    label.textContent = c.code || `CO${c.id}`;
    make('title', null, g).textContent = `${c.code} — ${c.nom}`;
    g.dataset.id = `course:${String(c.id)}`;
    g.dataset.kind = 'course';
    nodeEls.push({ el: g, node: c });
  });

  // Surbrillance / masquage
  function setDimState(activeIds, { hideOthers = false } = {}) {
    linkEls.forEach(({ el }) => {
      const src = el.getAttribute('data-source');
      const tgt = el.getAttribute('data-target');
      const isActive = activeIds.has(src) && activeIds.has(tgt);
      el.classList.toggle('dim', !isActive);
      el.style.display = isActive ? '' : 'none';
    });
    nodeEls.forEach(({ el }) => {
      const id = el.dataset.id;
      const isOn = activeIds.has(id);
      el.classList.toggle('highlight', isOn);
      if (hideOthers) {
        el.style.display = isOn ? '' : 'none';
        el.classList.remove('dim');
      } else {
        el.style.display = '';
        el.classList.toggle('dim', !isOn);
      }
    });
  }
  function clearDim() {
    linkEls.forEach(({ el }) => { el.classList.remove('dim'); el.style.display = ''; });
    nodeEls.forEach(({ el }) => { el.classList.remove('highlight'); el.classList.remove('dim'); el.style.display = ''; });
  }

  let pinnedId = null;
  function highlightNode(el, { hideOthers = false } = {}) {
    const id = el.dataset.id;
    const connected = new Set([id]);
    if (el.dataset.kind === 'competence') {
      linkEls.forEach(({ el: pl }) => { if (pl.getAttribute('data-source') === id) connected.add(pl.getAttribute('data-target')); });
    } else {
      linkEls.forEach(({ el: pl }) => { if (pl.getAttribute('data-target') === id) connected.add(pl.getAttribute('data-source')); });
    }
    setDimState(connected, { hideOthers });
  }

  // Survol = aperçu (dim), clic = pin + cacher le reste, double-clic = popup
  nodeEls.forEach(({ el, node }) => {
    el.addEventListener('mouseenter', () => { if (pinnedId === null) highlightNode(el, { hideOthers: false }); });
    el.addEventListener('mouseleave', () => { if (pinnedId === null) clearDim(); });
    let clickTimer = null;
    el.addEventListener('click', () => {
      if (clickTimer) return;
      clickTimer = setTimeout(() => {
        clickTimer = null;
        const id = el.dataset.id;
        if (pinnedId === id) { pinnedId = null; clearDim(); }
        else { pinnedId = id; highlightNode(el, { hideOthers: true }); }
      }, 220);
    });
    el.addEventListener('dblclick', (e) => {
      if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
      showInfoForNode(el, node, e);
    });
  });

  // Drag to adjust Y
  function svgPoint(evt) {
    const pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY;
    const inv = svg.getScreenCTM().inverse(); return pt.matrixTransform(inv);
  }
  nodeEls.forEach(({ el, node }) => {
    let dragging = false; let startYw = 0; let nodeStartY = 0;
    el.addEventListener('mousedown', (e) => {
      dragging = true; el.classList.add('dragging');
      const wp = svgPoint(e); startYw = wp.y; nodeStartY = node.y;
      e.preventDefault(); e.stopPropagation();
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const wp = svgPoint(e); const dy = wp.y - startYw;
      node.y = Math.max(margin.top + 16, Math.min(HEIGHT - margin.bottom - 16, nodeStartY + dy));
      el.setAttribute('transform', `translate(${node.x},${node.y})`);
      linkEls.forEach(({ el: pl, link }) => {
        if (link.source === node || link.target === node) {
          pl.setAttribute('d', cubicPath(link.source.x + 20, link.source.y, link.target.x - 40, link.target.y));
        }
      });
    });
    window.addEventListener('mouseup', () => { dragging = false; el.classList.remove('dragging'); });
  });

  // Filtrage par type
  const toggleDeveloppee = document.getElementById('toggleDeveloppee');
  const toggleAtteinte = document.getElementById('toggleAtteinte');
  const toggleReinvesti = document.getElementById('toggleReinvesti');
  function applyTypeFilters() {
    const showDev = toggleDeveloppee ? toggleDeveloppee.checked : true;
    const showAtt = toggleAtteinte ? toggleAtteinte.checked : true;
    const showRei = toggleReinvesti ? toggleReinvesti.checked : true;
    linkEls.forEach(({ el, link }) => {
      const show = (link.type === 'developpe' && showDev) || (link.type === 'atteint' && showAtt) || (link.type === 'reinvesti' && showRei);
      el.style.display = show ? '' : 'none';
    });
  }
  if (toggleDeveloppee) toggleDeveloppee.addEventListener('change', applyTypeFilters);
  if (toggleAtteinte) toggleAtteinte.addEventListener('change', applyTypeFilters);
  if (toggleReinvesti) toggleReinvesti.addEventListener('change', applyTypeFilters);
  applyTypeFilters();

  // Recherche
  const searchBox = document.getElementById('searchBox');
  function applySearch() {
    const raw = (searchBox.value || '').trim();
    const q = raw.toLocaleLowerCase();
    if (!q) { clearDim(); return; }
    const norm = (s) => (s || '').toString().normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
    const nq = norm(q);
    const matched = new Set();
    nodeEls.forEach(({ el, node }) => {
      const label = `${node.code || ''} ${node.nom || ''}`;
      if (norm(label).includes(nq)) matched.add(el.dataset.id);
    });
    if (matched.size) {
      const expanded = new Set(matched);
      linkEls.forEach(({ el: pl }) => {
        const src = pl.getAttribute('data-source');
        const tgt = pl.getAttribute('data-target');
        if (matched.has(src)) expanded.add(tgt);
        if (matched.has(tgt)) expanded.add(src);
      });
      setDimState(expanded);
    } else { clearDim(); }
  }
  if (searchBox) searchBox.addEventListener('input', applySearch);

  // Zoom & Pan
  let panning = false; let panStart = { x: 0, y: 0 }; let viewStart = { x: 0, y: 0 };
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = -Math.sign(e.deltaY) * 0.1; const prev = viewScale;
    viewScale = Math.min(4, Math.max(0.25, viewScale * (1 + delta)));
    const ptX = e.offsetX; const ptY = e.offsetY;
    viewX = ptX - (ptX - viewX) * (viewScale / prev);
    viewY = ptY - (ptY - viewY) * (viewScale / prev);
    applyView();
  }, { passive: false });
  svg.addEventListener('mousedown', (e) => { panning = true; panStart = { x: e.clientX, y: e.clientY }; viewStart = { x: viewX, y: viewY }; });
  window.addEventListener('mousemove', (e) => { if (!panning) return; viewX = viewStart.x + (e.clientX - panStart.x); viewY = viewStart.y + (e.clientY - panStart.y); applyView(); });
  window.addEventListener('mouseup', () => { panning = false; });
  const zoomInBtn = document.getElementById('zoomInBtn');
  const zoomOutBtn = document.getElementById('zoomOutBtn');
  const resetViewBtn = document.getElementById('resetViewBtn');
  if (zoomInBtn) zoomInBtn.addEventListener('click', () => { viewScale = Math.min(4, viewScale * 1.2); applyView(); });
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => { viewScale = Math.max(0.25, viewScale / 1.2); applyView(); });
  if (resetViewBtn) resetViewBtn.addEventListener('click', () => { viewScale = 1; viewX = 0; viewY = 0; applyView(); });

  // Export SVG/PNG
  const exportSvgBtn = document.getElementById('exportSvgBtn');
  const exportPngBtn = document.getElementById('exportPngBtn');
  function download(filename, text, type) {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  if (exportSvgBtn) exportSvgBtn.addEventListener('click', () => {
    const clone = svg.cloneNode(true); clone.removeAttribute('style');
    const style = document.createElement('style');
    style.textContent = '.link{fill:none;opacity:.9}.node-label{font:12px Roboto,Arial,sans-serif;fill:#222}.col-title{font:12px Roboto,Arial,sans-serif;fill:#222}';
    clone.insertBefore(style, clone.firstChild);
    const ser = new XMLSerializer().serializeToString(clone);
    download('logigramme.svg', ser, 'image/svg+xml');
  });
  if (exportPngBtn) exportPngBtn.addEventListener('click', () => {
    const clone = svg.cloneNode(true); clone.removeAttribute('style');
    const style = document.createElement('style');
    style.textContent = '.link{fill:none;opacity:.9}.node-label{font:12px Roboto,Arial,sans-serif;fill:#222}.col-title{font:12px Roboto,Arial,sans-serif;fill:#222}';
    clone.insertBefore(style, clone.firstChild);
    const ser = new XMLSerializer().serializeToString(clone);
    const img = new Image();
    const svgBlob = new Blob([ser], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    img.onload = function () {
      const canvas = document.createElement('canvas'); canvas.width = WIDTH; canvas.height = HEIGHT;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#ffffff'; ctx.fillRect(0,0,WIDTH,HEIGHT); ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'logigramme.png'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }, 'image/png');
    };
    img.src = url;
  });

  // Légendes
  // (HTML legend for sessions removed; only fil legend remains and is built above)

  // Légende intégrée au SVG (pour export)
  const legendG = make('g', { class: 'svg-legend' }, rootG);
  (function buildSvgLegend() {
    // Stack each legend item vertically to avoid overlap
    const startX = margin.left;
    let y = margin.top; // align with top margin, left of competence column
    const lh = 16; // line height
    // Compétence
    make('circle', { cx: startX, cy: y, r: 6, fill: '#6c63ff' }, legendG);
    make('text', { x: startX + 14, y: y + 4, class: 'col-title' }, legendG).textContent = 'Compétence';
    y += lh;
    // Liens
    function addLinkLegend(color, label) {
      make('line', { x1: startX, y1: y, x2: startX + 26, y2: y, stroke: color, 'stroke-width': 3 }, legendG);
      make('text', { x: startX + 32, y: y + 4, class: 'col-title' }, legendG).textContent = label;
      y += lh;
    }
    addLinkLegend('#0d6efd', 'Dév. signif.');
    addLinkLegend('#198754', 'Atteint');
    addLinkLegend('#6c757d', 'Réinvesti');
    // Fils
    make('text', { x: startX, y: y + 4, class: 'col-title' }, legendG).textContent = 'Fils:';
    y += lh;
    (data.fils || []).forEach(f => {
      const color = f.couleur || '#ccc'; const desc = (f.description || 'Fil');
      make('circle', { cx: startX, cy: y, r: 6, fill: color }, legendG);
      make('text', { x: startX + 14, y: y + 4, class: 'col-title' }, legendG).textContent = desc;
      y += lh;
    });
  })();

  // Popup d'info
  const infoPanel = document.getElementById('infoPanel');
  const infoTitle = document.getElementById('infoTitle');
  const infoBody = document.getElementById('infoBody');
  const infoClose = document.getElementById('infoClose');
  if (infoClose) infoClose.addEventListener('click', () => { infoPanel.style.display = 'none'; });
  function showInfoForNode(el, node, evt) {
    if (!infoPanel) return;
    if (el.dataset.kind === 'competence') {
      infoTitle.textContent = `Compétence ${node.code}`;
      const url = `/programme/competence/code/${encodeURIComponent(node.code)}`;
      infoBody.innerHTML = `<div><strong>Nom:</strong> ${node.nom || ''}</div><div class="mt-1"><a class="btn btn-sm btn-outline-primary" href="${url}">Ouvrir la fiche compétence</a></div>`;
    } else {
      infoTitle.textContent = `Cours ${node.code}`;
      const url = `/cours/${node.id}/plan_cadre`;
      const ftxt = node.fil_desc ? ` — <span class="badge" style="background:${node.fil_color||'#ccc'}">${node.fil_desc}</span>` : '';
      infoBody.innerHTML = `<div><strong>Nom:</strong> ${node.nom || ''}</div><div><strong>Session:</strong> ${node.session || ''}${ftxt}</div><div class="mt-1 d-flex gap-2 flex-wrap"><a class="btn btn-sm btn-outline-secondary" href="/cours/${node.id}">Voir le cours</a><a class="btn btn-sm btn-outline-primary" href="${url}">Ouvrir le plan-cadre</a></div>`;
    }
    const vpW = window.innerWidth || document.documentElement.clientWidth;
    const vpH = window.innerHeight || document.documentElement.clientHeight;
    const mx = evt && typeof evt.clientX === 'number' ? evt.clientX : vpW / 2;
    const my = evt && typeof evt.clientY === 'number' ? evt.clientY : vpH / 2;
    const left = Math.max(8, Math.min(vpW - 280, mx + 12));
    const top = Math.max(8, Math.min(vpH - 160, my + 12));
    infoPanel.style.position = 'fixed';
    infoPanel.style.left = left + 'px';
    infoPanel.style.top = top + 'px';
    infoPanel.style.right = '';
    infoPanel.style.bottom = '';
    infoPanel.style.display = '';
  }
})();
