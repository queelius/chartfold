(async function() {
  try {
    await DB.init();

    // Fetch patient info and generation date
    const patient = DB.queryOne("SELECT name FROM patients LIMIT 1");
    const lastLoad = DB.queryOne("SELECT loaded_at FROM load_log ORDER BY loaded_at DESC LIMIT 1");

    const patientName = patient ? patient.name : "Patient";
    const genDate = lastLoad ? lastLoad.loaded_at : "";

    // Sidebar section definitions
    // { id, label, table (for COUNT), group }
    const sidebarSections = [
      { id: "overview",       label: "Overview",         table: null,                group: "" },
      { id: "conditions",     label: "Conditions",       table: "conditions",        group: "Clinical" },
      { id: "medications",    label: "Medications",      table: "medications",       group: "Clinical" },
      { id: "lab_results",    label: "Lab Results",      table: "lab_results",       group: "Clinical" },
      { id: "encounters",     label: "Encounters",       table: "encounters",        group: "Clinical" },
      { id: "imaging",        label: "Imaging",          table: "imaging_reports",   group: "Clinical" },
      { id: "pathology",      label: "Pathology",        table: "pathology_reports", group: "Clinical" },
      { id: "allergies",      label: "Allergies",        table: "allergies",         group: "Clinical" },
      { id: "clinical_notes", label: "Clinical Notes",   table: "clinical_notes",    group: "Clinical" },
      { id: "procedures",     label: "Procedures",       table: "procedures",        group: "Clinical" },
      { id: "vitals",         label: "Vitals",           table: "vitals",            group: "Clinical" },
      { id: "immunizations",  label: "Immunizations",    table: "immunizations",     group: "Clinical" },
      { id: "sources",        label: "Sources",          table: "source_assets",     group: "Tools" },
      { id: "analysis",       label: "Analysis",         table: null,                group: "Tools" },
      { id: "sql_console",    label: "SQL Console",      table: null,                group: "Tools" },
    ];

    // Get counts for each section with a table
    const counts = {};
    for (const sec of sidebarSections) {
      if (sec.table) {
        try {
          const row = DB.queryOne('SELECT COUNT(*) AS n FROM "' + sec.table + '"');
          counts[sec.id] = row ? row.n : 0;
        } catch (e) {
          counts[sec.id] = 0;
        }
      }
    }

    // Analysis count from embedded data
    try {
      const analysisData = JSON.parse(
        document.getElementById('chartfold-analysis').textContent
      );
      if (Array.isArray(analysisData)) {
        counts["analysis"] = analysisData.length;
      }
    } catch (e) {
      // ignore
    }

    // Clear #app
    const app = document.getElementById('app');
    app.textContent = '';

    // --- Build topbar ---
    const hamburger = UI.el('button', {
      className: 'hamburger',
      textContent: '\u2630',
      'aria-label': 'Toggle menu',
      onClick: function() {
        document.querySelector('.sidebar').classList.toggle('open');
        document.querySelector('.sidebar-overlay').classList.toggle('open');
      }
    });

    const topbarLeft = UI.el('div', { className: 'topbar-left' }, [
      hamburger,
      UI.el('span', { className: 'topbar-title', textContent: 'Chartfold' })
    ]);

    const topbarRightChildren = [];
    if (patientName) {
      topbarRightChildren.push(
        UI.el('span', { className: 'topbar-patient', textContent: patientName })
      );
    }
    if (genDate) {
      topbarRightChildren.push(
        UI.el('span', { className: 'topbar-date', textContent: genDate })
      );
    }
    const topbarRight = UI.el('div', { className: 'topbar-right' }, topbarRightChildren);

    const topbar = UI.el('div', { className: 'topbar' }, [topbarLeft, topbarRight]);
    app.appendChild(topbar);

    // --- Build sidebar overlay (for mobile) ---
    const overlay = UI.el('div', {
      className: 'sidebar-overlay',
      onClick: function() {
        document.querySelector('.sidebar').classList.remove('open');
        document.querySelector('.sidebar-overlay').classList.remove('open');
      }
    });
    app.appendChild(overlay);

    // --- Build sidebar ---
    const sidebar = UI.el('div', { className: 'sidebar' });
    let currentGroup = null;

    for (const sec of sidebarSections) {
      // Render group label if new group
      if (sec.group !== currentGroup) {
        currentGroup = sec.group;
        if (sec.group) {
          sidebar.appendChild(
            UI.el('div', { className: 'sidebar-group-label', textContent: sec.group })
          );
        }
      }

      const itemChildren = [
        UI.el('span', { textContent: sec.label })
      ];

      // Add count badge if we have a count
      if (counts[sec.id] !== undefined) {
        itemChildren.push(
          UI.el('span', { className: 'count', textContent: String(counts[sec.id]) })
        );
      }

      const item = UI.el('div', {
        className: 'sidebar-item',
        'data-section': sec.id
      }, itemChildren);

      sidebar.appendChild(item);
    }

    app.appendChild(sidebar);

    // --- Build content area (empty — Router will populate it) ---
    const content = UI.el('div', { className: 'content', id: 'content' });
    app.appendChild(content);

    // --- Initialize Router and register all sections ---
    Router.init(content, sidebar);

    for (const sec of sidebarSections) {
      Router.register(
        sec.id,
        sec.label,
        sec.group,
        counts[sec.id] !== undefined ? counts[sec.id] : null,
        Sections[sec.id]
      );
    }

    // --- Start routing (navigates to hash or default 'overview') ---
    Router.start();

  } catch (err) {
    const app = document.getElementById('app');
    app.textContent = '';
    const h1 = UI.el('h1', { textContent: 'Error' });
    const pre = UI.el('pre', { textContent: err.message + '\n' + err.stack });
    app.appendChild(h1);
    app.appendChild(pre);
  }
})();
