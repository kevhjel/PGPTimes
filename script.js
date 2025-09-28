async function loadBoard(){
  // Load driver allowlist + IDs
  let driverMap = {};
  try {
    const driverRes = await fetch('data/drivers.csv', { cache: 'no-store' });
    if (driverRes.ok) {
      const driverText = await driverRes.text();
      driverText.split(/\r?\n/).forEach(line => {
        const parts = line.split(',').map(s => s.trim());
        if (parts.length >= 2) {
          driverMap[parts[0].toLowerCase()] = {
            name: parts[0],
            id: parts[1]
          };
        }
      });
    }
  } catch (_) {
    // drivers.csv optional
  }

  // Load leaderboard data
  const res = await fetch('data/leaderboard.json', { cache: 'no-store' });
  const data = await res.json();

  const tbody = document.querySelector('#board tbody');
  let racers = data.racers || [];

  // Filter: only keep racers that exist in drivers.csv
  if (Object.keys(driverMap).length > 0) {
    racers = racers.filter(r => driverMap.hasOwnProperty((r.name || '').toLowerCase()));
  }

  // Render helper
  const render = (list) => {
    tbody.innerHTML = '';
    for (const r of list) {
      const tr = document.createElement('tr');

      // Name as hyperlink to local profile page (with fallback to plain text)
      const tdName = document.createElement('td');
      const key = (r.name || '').toLowerCase();
      if (driverMap[key]) {
        const a = document.createElement('a');
        const id = driverMap[key].id;
        const nameParam = encodeURIComponent(r.name || '');
        a.href = `profile.html?id=${encodeURIComponent(id)}&name=${nameParam}`;
        a.textContent = r.name || '';
        tdName.appendChild(a);
      } else {
        tdName.textContent = r.name || '';
      }
      tr.appendChild(tdName);


      // Best lap
      const tdLap = document.createElement('td');
      tdLap.textContent = (r.best_lap_seconds != null ? Number(r.best_lap_seconds).toFixed(3) : '');
      tr.appendChild(tdLap);

      // HeatNo hyperlink
      const tdHeat = document.createElement('td');
      if (r.best_heat_no) {
        const a = document.createElement('a');
        a.href = `https://pgpkent.clubspeedtiming.com/sp_center/HeatDetails.aspx?HeatNo=${r.best_heat_no}`;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = r.best_heat_no;
        tdHeat.appendChild(a);
      }
      tr.appendChild(tdHeat);

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

  render(racers);
}
loadBoard();
