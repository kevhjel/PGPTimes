// Small CSV parser for simple, unquoted CSV (our all_laps.csv has no quoted commas)
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
  return {
    id: p.get('id') || '',
    name: p.get('name') || ''
  };
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

  // Pull all laps and filter for this driver (2025+ is already enforced by the scraper)
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

  // Prepare scatter data: x = index across laps, y = lap_seconds
  // We’ll also include tooltip info (heat_no and heat_datetime_iso)
  const points = [];
  let fastest = Infinity;
  let slowest = -Infinity;
  let heatsSet = new Set();

  rows.forEach((r, idx) => {
    const y = Number(r.lap_seconds);
    if (!Number.isFinite(y)) return;
    points.push({
      x: idx + 1,
      y,
      heat_no: r.heat_no,
      when: r.heat_datetime_iso,
      lap_number: r.lap_number
    });
    if (y < fastest) fastest = y;
    if (y > slowest) slowest = y;
    heatsSet.add(r.heat_no);
  });

  const summary = document.getElementById('summary');
  if (points.length === 0) {
    summary.textContent = 'No laps found for this driver (check that all_laps.csv is present and START_YEAR is set).';
  } else {
    summary.textContent = `Total laps: ${points.length} · Heats: ${heatsSet.size} · Fastest: ${fastest.toFixed(3)}s · Slowest: ${slowest.toFixed(3)}s`;
  }

  // Build scatter chart
  const ctx = document.getElementById('lapChart').getContext('2d');
  // Chart.js v4 scatter
  new Chart(ctx, {
    type: 'scatter',
    data: {
      datasets: [{
        label: 'Lap seconds',
        data: points,
        pointRadius: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const p = ctx.raw;
              return `Lap ${p.lap_number}: ${p.y.toFixed(3)}s (Heat ${p.heat_no})`;
            },
            afterLabel: (ctx) => {
              const p = ctx.raw;
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
        x: {
          title: { display: true, text: 'Lap index (across all heats)' },
          ticks: { autoSkip: true, maxTicksLimit: 12 }
        },
        y: {
          title: { display: true, text: 'Lap time (s)' }
        }
      }
    }
  });
})();
