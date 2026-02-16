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
      { id: "social_history", label: "Social History",   table: "social_history",    group: "History" },
      { id: "family_history", label: "Family History",   table: "family_history",    group: "History" },
      { id: "mental_status",  label: "Mental Status",    table: "mental_status",     group: "History" },
      { id: "patients",       label: "Demographics",     table: "patients",          group: "Admin" },
      { id: "personal_notes", label: "Notes",            table: "notes",             group: "Admin" },
      { id: "sources",        label: "Sources",          table: "source_assets",     group: "Tools" },
      { id: "analysis",       label: "Analysis",         table: "analyses",          group: "Tools" },
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

    // Also check for analyses from embedded JSON (--external-data fallback)
    if (!counts["analysis"]) {
      try {
        var analysisData = JSON.parse(
          document.getElementById('chartfold-analysis').textContent
        );
        if (Array.isArray(analysisData)) {
          counts["analysis"] = analysisData.length;
        }
      } catch (e) {
        // ignore
      }
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

    // --- Global search input ---
    var searchInput = UI.el('input', {
      type: 'text',
      className: 'topbar-search',
      placeholder: 'Search...'
    });

    var searchTimeout = null;
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimeout);
      var query = searchInput.value.toLowerCase().trim();
      searchTimeout = setTimeout(function() {
        var content = document.getElementById('content');
        if (!content) return;

        // Filter table rows
        var rows = content.querySelectorAll('table tbody tr');
        rows.forEach(function(row) {
          if (!query || row.textContent.toLowerCase().includes(query)) {
            row.style.display = '';
          } else {
            row.style.display = 'none';
          }
        });

        // Filter cards
        var cards = content.querySelectorAll('.card, .clinical-card');
        cards.forEach(function(card) {
          if (!query || card.textContent.toLowerCase().includes(query)) {
            card.style.display = '';
          } else {
            card.style.display = 'none';
          }
        });
      }, 300);
    });

    // --- Build topbar-right with print button ---
    const topbarRightChildren = [];
    if (patientName) {
      topbarRightChildren.push(
        UI.el('span', { className: 'topbar-patient', textContent: patientName })
      );
    }
    if (genDate) {
      // Format ISO timestamp to human-readable
      var formattedDate = genDate;
      try {
        var d = new Date(genDate);
        if (!isNaN(d.getTime())) {
          formattedDate = d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        }
      } catch (e) { /* keep raw */ }
      topbarRightChildren.push(
        UI.el('span', { className: 'topbar-date', textContent: 'Updated: ' + formattedDate })
      );
    }
    topbarRightChildren.push(
      UI.el('button', {
        className: 'topbar-print',
        textContent: '\u{1F5A8}',
        title: 'Print',
        'aria-label': 'Print',
        onClick: function() { window.print(); }
      })
    );
    const topbarRight = UI.el('div', { className: 'topbar-right' }, topbarRightChildren);

    const topbar = UI.el('div', { className: 'topbar' }, [topbarLeft, searchInput, topbarRight]);
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
