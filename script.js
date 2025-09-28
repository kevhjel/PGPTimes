async function loadBoard(){
  // Load driver filter list
  const driverRes = await fetch('data/drivers.csv', {cache:'no-store'});
  const driverText = await driverRes.text();
  const allowedDrivers = driverText
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(s => s.length > 0)
    .map(s => s.toLowerCase());

  // Load leaderboard data
  const res = await fetch('data/leaderboard.json', {cache:'no-store'});
  const data = await res.json();
  const tbody = document.querySelector('#board tbody');
  let racers = (data.racers || []).filter(r =>
    allowedDrivers.includes(r.name.toLowerCase())
  );

  const updated = document.getElementById('updated');
  updated.textContent = 'Last updated: ' + (data.last_updated_utc || '—');

  const render = (list) => {
    tbody.innerHTML = '';
    for(const r of list){
      const tr = document.createElement('tr');
      const cells = [
        r.name,
        (r.best_lap_seconds != null ? r.best_lap_seconds.toFixed(3) : ''),
        (r.best_kart || ''),
        (r.best_heat_no || '')
      ];
      for(const c of cells){
        const td = document.createElement('td');
        td.textContent = c;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  };

  // Search
  const search = document.getElementById('search');
  const apply = () => {
    const q = (search.value || '').toLowerCase();
    const filtered = racers.filter(r => r.name.toLowerCase().includes(q));
    render(filtered);
  };
  search.addEventListener('input', apply);

  // Sort buttons
  document.getElementById('sortBest').addEventListener('click', () => {
    racers.sort((a,b) => (a.best_lap_seconds||Infinity) - (b.best_lap_seconds||Infinity));
    apply();
  });
  document.getElementById('sortName').addEventListener('click', () => {
    racers.sort((a,b) => a.name.localeCompare(b.name));
    apply();
  });

  render(racers);
}
loadBoard();
