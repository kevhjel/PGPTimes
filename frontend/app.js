async function jget(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(path + " => " + res.status);
  return res.json();
}

function secondsToClock(s) {
  if (s == null || isNaN(s)) return "";
  return `${parseFloat(s).toFixed(3)} s`;
}

async function loadSummary() {
  try {
    return await jget("../data/summary.json");
  } catch {
    return await jget("./data/summary.json");
  }
}

async function loadHeat(heatNo) {
  try {
    return await jget(`../data/heats/${heatNo}.json`);
  } catch {
    return await jget(`./data/heats/${heatNo}.json`);
  }
}

async function loadDriverIndex() {
  try {
    return await jget("../data/driver_index.json");
  } catch {
    return await jget("./data/driver_index.json");
  }
}

async function loadWatchlist() {
  try {
    return await jget("../data/drivers_watchlist.json");
  } catch {
    return await jget("./data/drivers_watchlist.json");
  }
}

window.renderHeat = async function(heatNo) {
  const el = document.getElementById("heatContainer");
  el.innerHTML = "";
  let doc;
  try {
    doc = await loadHeat(heatNo);
  } catch {
    el.innerHTML = `<div class="small">No data for heat ${heatNo}</div>`;
    return;
  }
  const head = document.createElement("div");
  head.className = "row";
  head.innerHTML = `<div class="badge">Heat ${doc.heat_no}</div>
    <div class="small">${doc.heat_type || ""}</div>
    <div class="small">${doc.start_time_iso || ""}</div>
    <div class="small"><a href="${doc.source_url}" target="_blank">Open on site</a></div>`;
  el.appendChild(head);

  const table = document.createElement("table");
  table.innerHTML = `<thead><tr>
    <th>Pos</th><th>Driver</th><th>Kart</th><th>Best</th><th>Laps</th>
  </tr></thead><tbody></tbody>`;
  const tb = table.querySelector("tbody");
  (doc.drivers || []).forEach(d => {
    const tr = document.createElement("tr");
    const laps = Array.isArray(d.laps) ? d.laps.map(secondsToClock).join(", ") : "";
    tr.innerHTML = `
      <td>${d.position ?? ""}</td>
      <td>${d.name ? `<a href="./driver_charts.html#${encodeURIComponent(d.name)}">${d.name}</a>` : ""}</td>
      <td>${d.kart ?? ""}</td>
      <td>${secondsToClock(d.best_lap_seconds)}</td>
      <td style="font-family: ui-monospace, monospace;">${laps}</td>
    `;
    tb.appendChild(tr);
  });
  el.appendChild(table);
};

window.renderWatchlist = async function() {
  const container = document.getElementById("drivers");
  container.innerHTML = "";
  const watch = await loadWatchlist();
  const idx = await loadDriverIndex();
  const drivers = idx.drivers || {};
  if (!watch.length) {
    container.innerHTML = `<div class="card small">No drivers in watchlist yet.</div>`;
    return;
  }
  watch.forEach(name => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<div class="row" style="justify-content: space-between;">
      <div><strong><a href="./driver_charts.html#${encodeURIComponent(name)}">${name}</a></strong></div>
    </div>`;
    const list = drivers[name] || [];
    if (!list.length) {
      card.innerHTML += `<div class="small">No entries scraped yet.</div>`;
      container.appendChild(card);
      return;
    }
    const t = document.createElement("table");
    t.innerHTML = `<thead><tr>
      <th>Heat</th><th>Type</th><th>Pos</th><th>Kart</th><th>Best Lap</th><th># Laps</th><th>Start</th>
    </tr></thead><tbody></tbody>`;
    const tb = t.querySelector("tbody");
    list.forEach(e => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><a href="./index.html#${e.heat_no}" onclick="window.renderHeat(${e.heat_no});">${e.heat_no}</a></td>
        <td>${e.heat_type ?? ""}</td>
        <td>${e.position ?? ""}</td>
        <td>${e.kart ?? ""}</td>
        <td>${secondsToClock(e.best_lap_seconds)}</td>
        <td>${Array.isArray(e.laps) ? e.laps.length : ""}</td>
        <td class="small">${e.start_time_iso ?? ""}</td>
      `;
      tb.appendChild(tr);
    });
    card.appendChild(t);
    container.appendChild(card);
  });
};

// summary banner
(async () => {
  const s = await loadSummary().catch(() => null);
  if (s) {
    const source = document.getElementById("source");
    const updated = document.getElementById("updated");
    const heatsCount = document.getElementById("heatsCount");
    const maxHeat = document.getElementById("maxHeat");
    if (source) source.textContent = s.source || "";
    if (updated) updated.textContent = s.last_updated_utc || "";
    if (heatsCount) heatsCount.textContent = s.heats_count ?? "";
    if (maxHeat) maxHeat.textContent = s.max_heat_no ?? "";
  }
  // deep-link support: index.html#82271
  if (location.hash && /^\#\d+$/.test(location.hash)) {
    const h = parseInt(location.hash.slice(1), 10);
    const jump = document.getElementById("jump");
    if (jump) jump.value = String(h);
    if (window.renderHeat) window.renderHeat(h);
  }
})();
