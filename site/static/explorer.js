// Self-contained canvas force-directed graph. No external libraries.
(function () {
  const canvas = document.getElementById("graph");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const stat = document.getElementById("graphstat");

  const COLORS = {
    county: "#a3132a", department: "#d9a441", agency: "#d9a441",
    office: "#3556a3", person: "#2f7d4f", statute: "#888",
    municipality: "#b9a", government: "#555",
  };

  let RAW = { nodes: [], edges: [] };
  let nodes = [], links = [];
  let view = { x: 0, y: 0, k: 1 };
  let dragNode = null, panning = false, last = null;
  let focusId = null;

  const W = () => canvas.clientWidth, H = () => canvas.clientHeight;

  function activeTypes() {
    return new Set(Array.from(document.querySelectorAll(".etype:checked"))
      .map(c => c.value));
  }

  function rebuild() {
    const types = activeTypes();
    let edges = RAW.edges.filter(e => types.has(e.type));

    if (focusId) {
      const keep = new Set([focusId]);
      edges.forEach(e => {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      });
      edges = edges.filter(e => keep.has(e.source) && keep.has(e.target));
    }

    const used = new Set();
    edges.forEach(e => { used.add(e.source); used.add(e.target); });

    const prev = new Map(nodes.map(n => [n.id, n]));
    nodes = RAW.nodes.filter(n => used.has(n.id)).map(n => {
      const p = prev.get(n.id);
      return Object.assign({}, n, {
        x: p ? p.x : (Math.random() - 0.5) * 400,
        y: p ? p.y : (Math.random() - 0.5) * 400,
        vx: 0, vy: 0,
        r: Math.max(4, Math.min(16, 3 + Math.sqrt(n.degree || 1) * 1.6)),
      });
    });
    const nmap = new Map(nodes.map(n => [n.id, n]));
    links = edges.map(e => ({ s: nmap.get(e.source), t: nmap.get(e.target), type: e.type }))
      .filter(l => l.s && l.t);

    if (stat) stat.textContent = `${nodes.length} nodes · ${links.length} edges shown`;
    alpha = 1;
  }

  let alpha = 1;
  function tick() {
    if (alpha > 0.02) {
      // Repulsion (O(n^2), fine for a few hundred nodes).
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy || 1;
          const f = 1400 / d2;
          const d = Math.sqrt(d2);
          const fx = (dx / d) * f, fy = (dy / d) * f;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
      }
      // Springs.
      links.forEach(l => {
        let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 70) * 0.02;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        l.s.vx += fx; l.s.vy += fy; l.t.vx -= fx; l.t.vy -= fy;
      });
      // Centering + integrate.
      nodes.forEach(n => {
        n.vx += -n.x * 0.002; n.vy += -n.y * 0.002;
        if (n === dragNode) { n.vx = 0; n.vy = 0; return; }
        n.x += n.vx * alpha; n.y += n.vy * alpha;
        n.vx *= 0.85; n.vy *= 0.85;
      });
      alpha *= 0.985;
    }
    draw();
    requestAnimationFrame(tick);
  }

  function toScreen(n) {
    return { x: (n.x + view.x) * view.k + W() / 2, y: (n.y + view.y) * view.k + H() / 2 };
  }
  function toWorld(px, py) {
    return { x: (px - W() / 2) / view.k - view.x, y: (py - H() / 2) / view.k - view.y };
  }

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== W() * dpr) { canvas.width = W() * dpr; canvas.height = H() * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W(), H());

    ctx.lineWidth = 1;
    links.forEach(l => {
      const a = toScreen(l.s), b = toScreen(l.t);
      ctx.strokeStyle = focusId ? "rgba(140,140,140,.55)" : "rgba(140,140,140,.3)";
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });

    ctx.font = "11px -apple-system, sans-serif";
    nodes.forEach(n => {
      const s = toScreen(n);
      ctx.beginPath();
      ctx.arc(s.x, s.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = COLORS[n.type] || "#999";
      ctx.globalAlpha = (focusId && n.id !== focusId) ? 0.9 : 1;
      ctx.fill();
      if (n.id === focusId) { ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; ctx.stroke(); }
      ctx.globalAlpha = 1;
      if (n.r >= 7 || n.id === focusId || view.k > 1.3) {
        ctx.fillStyle = getComputedStyle(document.body).color;
        ctx.fillText(n.name.slice(0, 24), s.x + n.r + 3, s.y + 3);
      }
    });
  }

  function nodeAt(px, py) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const s = toScreen(nodes[i]);
      if ((s.x - px) ** 2 + (s.y - py) ** 2 <= (nodes[i].r + 3) ** 2) return nodes[i];
    }
    return null;
  }

  // Interaction.
  canvas.addEventListener("mousedown", e => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    const n = nodeAt(px, py);
    if (n) { dragNode = n; } else { panning = true; }
    last = { x: px, y: py }; last.moved = false;
  });
  window.addEventListener("mousemove", e => {
    if (!dragNode && !panning) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    last.moved = true;
    if (dragNode) { const w = toWorld(px, py); dragNode.x = w.x; dragNode.y = w.y; alpha = Math.max(alpha, 0.3); }
    else if (panning) { view.x += (px - last.x) / view.k; view.y += (py - last.y) / view.k; }
    last = { x: px, y: py, moved: true };
  });
  window.addEventListener("mouseup", e => {
    if (dragNode && last && !last.moved) { location.href = window.ROOT + dragNode.href; }
    dragNode = null; panning = false;
  });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    view.k = Math.max(0.2, Math.min(4, view.k * factor));
  }, { passive: false });

  document.querySelectorAll(".etype").forEach(c => c.addEventListener("change", rebuild));
  const reset = document.getElementById("reset");
  if (reset) reset.addEventListener("click", () => {
    focusId = null; document.getElementById("focus").value = ""; rebuild();
  });

  const focus = document.getElementById("focus");
  if (focus) focus.addEventListener("input", () => {
    const q = focus.value.trim().toLowerCase();
    if (q.length < 2) return;
    const hit = RAW.nodes.find(n => n.name.toLowerCase().startsWith(q))
      || RAW.nodes.find(n => n.name.toLowerCase().includes(q));
    if (hit) { focusId = hit.id; view = { x: 0, y: 0, k: 1 }; rebuild(); }
  });

  fetch(window.GRAPH_URL).then(r => r.json()).then(d => {
    RAW = d; rebuild(); tick();
  });
})();
