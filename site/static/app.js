// Shared: type-ahead search over data/search.json.
(function () {
  const input = document.getElementById("q");
  const results = document.getElementById("results");
  if (!input || !results) return;

  let index = [];
  let active = -1;
  fetch(window.SEARCH_URL).then(r => r.json()).then(d => { index = d; });

  function score(item, q) {
    const n = item.name.toLowerCase();
    if (n === q) return 100;
    if (n.startsWith(q)) return 50;
    const i = n.indexOf(q);
    return i >= 0 ? 20 - i * 0.1 : -1;
  }

  function render(matches) {
    results.innerHTML = "";
    if (!matches.length) { results.hidden = true; return; }
    matches.forEach((m, i) => {
      const li = document.createElement("li");
      li.className = i === active ? "active" : "";
      li.innerHTML = `<a href="${window.ROOT}${m.href}">${m.name}</a>` +
        `<span class="rtype">${m.type}</span>`;
      li.addEventListener("mousedown", () => { location.href = window.ROOT + m.href; });
      results.appendChild(li);
    });
    results.hidden = false;
  }

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    active = -1;
    if (q.length < 2) { results.hidden = true; return; }
    const matches = index
      .map(it => ({ it, s: score(it, q) }))
      .filter(x => x.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 12)
      .map(x => x.it);
    render(matches);
  });

  input.addEventListener("keydown", (e) => {
    const items = results.querySelectorAll("li");
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); e.preventDefault(); }
    else if (e.key === "Enter") {
      const a = results.querySelector(active >= 0 ? `li:nth-child(${active + 1}) a` : "li a");
      if (a) location.href = a.href;
      return;
    } else if (e.key === "Escape") { results.hidden = true; return; }
    items.forEach((li, i) => li.classList.toggle("active", i === active));
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search")) results.hidden = true;
  });
})();
