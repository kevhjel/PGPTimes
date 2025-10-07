async function jget(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(path + " => " + res.status);
  return res.json();
}

function secondsToClock(s) {
  if (s == null || isNaN(s)) return "";
  return `${parseFloat(s).toFixed(3)} s`;
}


// ---------- GAP CHART HELPERS ----------
let GAP_CHART = null;

function niceSeconds(s) {
  if (s == null || isNaN(s)) return "";
  return Number(s).toFixed(3) + " s";
}
function colorForIndex(i) {
  const palette = [
    "#36A2EB","#FF6384","#4BC0C0","#FF9F40","#9966FF",
    "#FFCD56","#2ecc71","#e67e22","#1abc9c","#c0392b",
    "#8e44ad","#16a085","#2c3e50","#d35400","#7f8c8d"
  ];
  return palette[i % palette.length];
}

// Build gap-from-leader series from a heat doc
function buildGapSeriesFromHeat(heat) {
  const drivers = Array.isArray(heat.drivers) ? heat.drivers.slice() : [];
  const series = drivers
    .filter(d => Array.isArray(d.laps) && d.laps.length > 0 && typeof d.name === "string")
    .map(d => {
      const cum = [];
      let sum = 0;
      for (const t of d.laps) {
        const v = Number(t);
        if (!isNaN(v)) sum += v;
        cum.push(sum);
      }
      return { name: d.name, cumulative: cum };
    });

  if (!series.length) return { labels: [], datasets: [] };

  const maxLaps = Math.max(...series.map(s => s.cumulative.length));
  const labels = Array.from({length: maxLaps}, (_,i) => i+1);

  const leaderCum = labels.map((_, i) => {
    let minVal = Infinity;
    for (const s of series) {
      if (s.cumulative.length > i) {
        const val = s.cumulative[i];
        if (val < minVal) minVal = val;
      }
    }
    return isFinite(minVal) ? minVal : null;
  });

  const datasets = series.map((s, idx) => {
    const data = s.cumulative.map((v, i) => {
      const base = leaderCum[i];
      return (base == null) ? null : v - base;
    });
    return {
      label: s.name,
      data,
      borderColor: colorForIndex(idx),
      backgroundColor: colorForIndex(idx),
      showLine: true,
      type: "line",
      pointRadius: 0,
      borderWidth: 2,
      tension: 0.15,
      spanGaps: true
    };
  });

  return { labels, datasets };
}

function renderGapChartInto(containerEl, heat) {
  // create (or reuse) a card with canvas
  let card = document.getElementById("gapChartCard");
  if (!card) {
    card = document.createElement("div");
    card.className = "card";
    card.id = "gapChartCard";
    card.innerHTML = `
      <div class="row" style="justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap;">
        <div><strong>Gap from Leader by Lap</strong> 
          <span id="gapChartSubtitle" class="small mono"></span>
        </div>
      </div>
      <canvas id="gapChart" height="140"></canvas>
    `;
    // Insert the chart card just after the header row the page renders
    containerEl.appendChild(card);
  }

  const ctx = document.getElementById("gapChart").getContext("2d");
  const { labels, datasets } = buildGapSeriesFromHeat(heat);

  if (GAP_CHART) GAP_CHART.destroy();
  GAP_CHART = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      scales: {
        x: { title: { display: true, text: "Lap Index" }, ticks: { autoSkip: true } },
        y: { title: { display: true, text: "Gap from Leader (s)" } }
      },
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const name = ctx.dataset?.label || "";
              const val = ctx.parsed?.y;
              return `${name}: ${niceSeconds(val)}`;
            }
          }
        }
      }
    }
  });

  const sub = document.getElementById("gapChartSubtitle");
  if (sub) {
    const tt = heat.heat_type || "";
    const ts = heat.start_time_iso || "";
    sub.textContent = ts ? `• ${tt} • ${ts}` : tt;
  }
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

   renderGapChartInto(el, doc);
  
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

// ---- Driver Watchlist with live filter ----
window.renderWatchlist = async function() {
  const container = document.getElementById("drivers");
  container.innerHTML = "";

  // Load data
  const [watch, idx] = await Promise.all([loadWatchlist(), loadDriverIndex()]);
  const drivers = idx.drivers || {};

  // Wire the filter input once
  const filterEl = document.getElementById("filterInput");
  if (filterEl && !filterEl._wired) {
    filterEl.addEventListener("input", () => {
      // Re-render on each keystroke
      window.renderWatchlist();
    });
    filterEl._wired = true;
  }

  // Filter names by “contains” (case-insensitive)
  const q = (filterEl?.value || "").trim().toLowerCase();
  const names = Array.isArray(watch) ? watch.filter(n => !q || (n || "").toLowerCase().includes(q)) : [];

  if (!names.length) {
    const msg = Array.isArray(watch) && watch.length
      ? `No drivers match "${q}".`
      : "No drivers in watchlist yet.";
    container.innerHTML = `<div class="card small">${msg}</div>`;
    return;
  }

  // Render each driver card
  names.forEach(name => {
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
