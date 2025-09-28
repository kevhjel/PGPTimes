// Simple CSV parser for unquoted CSV
function parseCSV(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  const header = lines.shift().split(',').map(s => s.trim());
  return lines.map(line => {
    const parts = line.split(',').map(s => s.trim());
    const obj = {};
    header.forEach((h, i) => obj[h] = parts[i] ?? '');
    return obj;
  });
}

function getQuery() {
  const p = new URLSearchParams(location.search);
  return { id: p.get('id') || '', name: p.get('name') || '' };
}

// ------- Stats helpers -------
function median(arr) {
  if (!arr.length) return NaN;
  const a = [...arr].sort((x, y) => x - y);
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}
function mean(arr) {
  if (!arr.length) return NaN;
  return arr.reduce((s, v) => s + v, 0) / arr.length;
}
function stdev(arr) {
  if (arr.length < 2) return NaN;
  const m = mean(arr);
  const v = arr.reduce((s, v) => s + (v - m) ** 2, 0) / (arr.length - 1);
  return Math.sqrt(v);
}
// Robust MAD-based outlier mask: |0.6745*(x - med)/MAD| > 3.5
function mad(arr) {
  if (!arr.length) return NaN;
  const m = median(arr);
  const absDev = arr.map(v => Math.abs(v - m));
  return median(absDev);
}
function makeOutlierMask(arr) {
  const m = median(arr);
  const madVal = mad(arr);
  if (!isFinite(m) || !isFinite(madVal) || madVal === 0) {
    // If MAD is zero (e.g., all same), treat as no outliers
    return arr.map(() => true);
  }
  return arr.map(v => {
    const robustZ = 0.6745 * (v - m) / madVal;
    return Math.abs(robustZ) <= 3.5;
  });
}

(async function init(){
  const { id, name } = getQuery();
  const driverName = decodeURIComponent(name || '').trim();
  const driverId = id;

  // Titles & link
  const title = document.getElementById('driverTitle');
  title.textContent = driverName ? `Driver Profile — ${driverName}` : 'Driver Profile';

  const driverLink = document.getElementById('driverLink');
  if (driverId) {
    driverLink.href = `https://pgpkent.clubspeedtiming.com/sp_center/RacerHistory.aspx?CustID=${encodeURIComponent(driverId)}`;
  } else {
    driverLink.style.display = 'none';
  }

  // Pull all laps for this driver (2025+ is enforced by the scraper)
  let rows = [];
  try {
    const res = await fetch('data/all_laps.csv', { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to load all_laps.csv');
    const text = await res.text();
    const data = parseCSV(text);
    rows = data.filter(r => r.driver_id === driverId);
  } catch (e) {
    console.error(e);
  }

  // Prepare base point set
  const allPoints = [];
  const allY = [];
  const heatsSet = new Set();

  rows.forEach((r, idx) => {
    const y = Number(r.lap_seconds);
    if (!Number.isFinite(y)) return;
    const p = {
      x: idx + 1, // simple index
      y,
      heat_no: r.heat_no,
      when: r.heat_datetime_iso,
      lap_number: r.lap_number
    };
    allPoints.push(p);
    allY.push(y);
    heatsSet.add(r.heat_no);
  });

  // UI elements
  const summary = document.getElementById('summary');
  const statsRow = document.getElementById('statsRow');
  const hideOutliersEl = document.getElementById('hideOutliers');

  // Chart.js
  const ctx = document.getElementById('lapChart').getContext('2d');
  const chart = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{ label: 'Lap seconds', data: [], pointRadius: 3 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => {
              const p = c.raw;
              return `Lap ${p.lap_number}: ${p.y.toFixed(3)}s (Heat ${p.heat_no})`;
            },
            afterLabel: (c) => {
              const p = c.raw;
              return p.when ? `Date: ${p.when}` : '';
            }
          }
        },
        title: {
          display: true,
          text: driverName ? `All laps for ${driverName}` : 'All laps'
        }
      },
      scales: {
        x: { title: { display: true, text: 'Lap index (across all heats)' }, ticks: { autoSkip: true, maxTicksLimit: 12 } },
        y: { title: { display: true, text: 'Lap time (s)' } }
      }
    }
  });

  function updateSummaryAndStats(points) {
    if (!points.length) {
      summary.textContent = 'No laps found for this driver (check that all_laps.csv is present and START_YEAR is set).';
      statsRow.textContent = '';
      return;
    }
    const yvals = points.map(p => p.y);
    const fastest = Math.min(...yvals);
    const med = median(yvals);
    const mu = mean(yvals);
    const sd = stdev(yvals);

    summary.textContent = `Total laps: ${points.length} · Heats: ${heatsSet.size} · Fastest: ${fastest.toFixed(3)}s`;

    statsRow.innerHTML = `
      Laps: <strong>${points.length}</strong> &nbsp; | &nbsp;
      Heats: <strong>${heatsSet.size}</strong> &nbsp; | &nbsp;
      Best: <strong>${fastest.toFixed(3)}s</strong> &nbsp; | &nbsp;
      Median: <strong>${isFinite(med) ? med.toFixed(3) : '—'}s</strong> &nbsp; | &nbsp;
      Mean: <strong>${isFinite(mu) ? mu.toFixed(3) : '—'}s</strong> &nbsp; | &nbsp;
      Stdev: <strong>${isFinite(sd) ? sd.toFixed(3) : '—'}s</strong>
    `;
  }

  function applyOutlierFilter(points, hideOutliers) {
    if (!hideOutliers || points.length < 5) return points; // not enough data to bother
    const yvals = points.map(p => p.y);
    const keepMask = makeOutlierMask(yvals);
    return points.filter((_, i) => keepMask[i]);
  }

  function render() {
    const filtered = applyOutlierFilter(allPoints, hideOutliersEl.checked);
    chart.data.datasets[0].data = filtered;
    chart.update();
    updateSummaryAndStats(filtered);
  }

  // Initial paint
  chart.data.datasets[0].data = allPoints;
  chart.update();
  updateSummaryAndStats(allPoints);

  // Toggle outliers
  hideOutliersEl.addEventListener('change', render);
})();
