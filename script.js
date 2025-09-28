async function loadBoard(){
  // Load driver allowlist
  let allowedDrivers = null;
  try {
    const driverRes = await fetch('data/drivers.csv', { cache: 'no-store' });
    if (driverRes.ok) {
      const driverText = await driverRes.text();
      allowedDrivers = driverText
        .split(/\r?\n/)
        .map(s => s.trim())
        .filter(Boolean)
        .map(s => s.toLowerCase());
    }
  } catch (_) {
    // drivers.csv is optional; if missing, show everyone
  }

  // Load leaderboard data
  const res = await fetch('data/leaderboard.json', { cache: 'no-store' });
  const data = await res.json();

  const tbody = document.querySelector('#board tbody');
  let racers = data.racers || [];

  // Filter to drivers.csv if present
  if (Array.isArray(allowedDrivers) && allowedDrivers.length > 0) {
    racers = racers.filter(r => r.name && allowedDrivers.includes(r.name.toLowerCase()));
  }

  // Render helper
  const render = (list) => {
    tbody.innerHTML = '';
    for (const r of list) {
      const tr = document.createElement('tr');
      const cells = [
        r.name || '',
        (r.best_lap_seconds != null ? Number(r.best_lap_seconds).toFixed(3) : ''),
        (r.best_heat_no || '')
      ];
      for (const c of cells) {
        const td = document.createElement('td');
        td.textContent = c;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  };

  // Updated timestamp
  const updated = document.getElementById('updated');
  updated.textContent = 'Last updated: ' + (data.last_updated_utc || '—');

  // Search
  const search = document.getElementById('search');
  const apply = () => {
    const q = (search.value || '').toLowerCase();
    const filtered = racers.filter(r => (r.name || '').toLowerCase().includes(q));
    render(filtered);
  };
  search.addEventListener('input', apply);

  // Sort buttons
  document.getElementById('sortBest').addEventListener('click', () => {
    racers.sort((a, b) => (a.best_lap_seconds ?? Infinity) - (b.best_lap_seconds ?? Infinity));
    apply();
  });
  document.getElementById('sortName').addEventListener('click', () => {
    racers.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    apply();
  });

  // Initial render
  render(racers);
}
loadBoard();
