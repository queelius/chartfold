(async function() {
  try {
    await DB.init();
    const tables = DB.query(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    );
    const app = document.getElementById('app');
    app.textContent = '';
    const h1 = document.createElement('h1');
    h1.textContent = 'Chartfold';
    app.appendChild(h1);
    const p = document.createElement('p');
    p.textContent = 'Database loaded: ' + tables.length + ' tables';
    app.appendChild(p);
    const list = document.createElement('ul');
    for (const t of tables) {
      const count = DB.queryOne('SELECT COUNT(*) as n FROM "' + t.name + '"');
      const li = document.createElement('li');
      li.textContent = t.name + ': ' + (count ? count.n : 0) + ' rows';
      list.appendChild(li);
    }
    app.appendChild(list);
  } catch (err) {
    const app = document.getElementById('app');
    app.textContent = '';
    const h1 = document.createElement('h1');
    h1.textContent = 'Error';
    app.appendChild(h1);
    const pre = document.createElement('pre');
    pre.textContent = err.message + '\n' + err.stack;
    app.appendChild(pre);
  }
})();
