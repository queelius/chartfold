function _renderLinkedAssets(card, db, refTable, refId) {
  try {
    var assets = db.query('SELECT file_name FROM source_assets WHERE ref_table = ? AND ref_id = ?', [refTable, refId]);
    if (assets.length > 0) {
      var assetRow = UI.el('div', { style: 'margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap;' });
      for (var i = 0; i < assets.length; i++) {
        assetRow.appendChild(UI.badge(assets[i].file_name, 'gray'));
      }
      card.appendChild(assetRow);
    }
  } catch (e) { /* source_assets may not exist */ }
}

// Returns the record count for the section, or -1 if the section is empty
// (in which case the header and empty message are already appended).
// Optional subtitle overrides the default "n label" pattern.
function _sectionPreamble(el, db, table, label, emptyMsg, subtitle) {
  var row = db.queryOne('SELECT COUNT(*) AS n FROM ' + table);
  var n = row ? row.n : 0;
  el.appendChild(UI.sectionHeader(label, n + ' ' + (subtitle || label.toLowerCase())));
  if (n === 0) { el.appendChild(UI.empty(emptyMsg)); return -1; }
  return n;
}

// Renders a <details> block with a <pre> for long text (reports, operative notes).
function _renderExpandableText(el, label, text, opts) {
  opts = opts || {};
  var detailsStyle = opts.detailsStyle || 'margin: 0 0 12px 0;';
  var summaryStyle = opts.summaryStyle || 'cursor: pointer; font-size: 13px; color: var(--text-secondary); padding: 4px 0;';
  var details = UI.el('details', { style: detailsStyle });
  details.appendChild(UI.el('summary', { textContent: label, style: summaryStyle }));
  details.appendChild(UI.el('pre', {
    textContent: text,
    style: 'white-space: pre-wrap; font-size: 13px; margin: 8px 0; padding: 12px; background: var(--surface); border-radius: 8px; border: 1px solid var(--border);'
  }));
  el.appendChild(details);
}

function parseRefRange(rangeStr) {
  if (!rangeStr) return null;
  var dashMatch = rangeStr.match(/([\d.]+)\s*[-\u2013]\s*([\d.]+)/);
  if (dashMatch) {
    return { low: parseFloat(dashMatch[1]), high: parseFloat(dashMatch[2]) };
  }
  var ltMatch = rangeStr.match(/[<≤]\s*([\d.]+)/);
  if (ltMatch) {
    return { low: null, high: parseFloat(ltMatch[1]) };
  }
  var gtMatch = rangeStr.match(/[>≥]\s*([\d.]+)/);
  if (gtMatch) {
    return { low: parseFloat(gtMatch[1]), high: null };
  }
  return null;
}

const Sections = {
  overview(el, db) {
    el.appendChild(UI.sectionHeader('Overview', 'Dashboard summary'));

    // --- 1. Summary Cards ---
    var tables = [
      { label: 'Conditions', table: 'conditions', section: 'conditions', dateCol: 'onset_date' },
      { label: 'Medications', table: 'medications', section: 'medications', dateCol: 'start_date' },
      { label: 'Lab Results', table: 'lab_results', section: 'lab_results', dateCol: 'result_date' },
      { label: 'Encounters', table: 'encounters', section: 'encounters', dateCol: 'encounter_date' },
      { label: 'Imaging', table: 'imaging_reports', section: 'imaging', dateCol: 'study_date' },
      { label: 'Pathology', table: 'pathology_reports', section: 'pathology', dateCol: 'report_date' },
      { label: 'Clinical Notes', table: 'clinical_notes', section: 'clinical_notes', dateCol: 'note_date' },
      { label: 'Procedures', table: 'procedures', section: 'procedures', dateCol: 'procedure_date' },
      { label: 'Vitals', table: 'vitals', section: 'vitals', dateCol: 'recorded_date' },
      { label: 'Immunizations', table: 'immunizations', section: 'immunizations', dateCol: 'admin_date' },
      { label: 'Allergies', table: 'allergies', section: 'allergies', dateCol: 'onset_date' },
      { label: 'Social History', table: 'social_history', section: 'social_history', dateCol: 'recorded_date' },
      { label: 'Family History', table: 'family_history', section: 'family_history', dateCol: null },
      { label: 'Mental Status', table: 'mental_status', section: 'mental_status', dateCol: 'recorded_date' },
    ];

    var cardGrid = UI.el('div', { className: 'card-grid' });
    for (var i = 0; i < tables.length; i++) {
      var t = tables[i];
      try {
        var row = db.queryOne('SELECT COUNT(*) AS n FROM "' + t.table + '"');
        var count = row ? row.n : 0;
        if (count > 0) {
          var section = t.section;
          // Query latest date for this table
          var latestDate = null;
          if (t.dateCol) {
            try {
              var dateRow = db.queryOne('SELECT MAX("' + t.dateCol + '") AS latest FROM "' + t.table + '"');
              if (dateRow && dateRow.latest) latestDate = dateRow.latest;
            } catch (e2) { /* ignore */ }
          }
          var cardOpts = {
            onClick: (function(sec) { return function() { Router.navigate(sec); }; })(section)
          };
          if (latestDate) cardOpts.subtitle = 'Latest: ' + latestDate;
          cardGrid.appendChild(UI.card(t.label, count, cardOpts));
        }
      } catch (e) {
        // table may not exist, skip
      }
    }
    if (cardGrid.children.length > 0) {
      el.appendChild(cardGrid);
    }

    // --- 2. Key Lab Sparklines ---
    try {
      var configEl = document.getElementById('chartfold-config');
      var config = configEl ? JSON.parse(configEl.textContent) : {};
      if (config.key_tests && config.key_tests.tests && config.key_tests.tests.length > 0) {
        var sparkRows = [];
        for (var ti = 0; ti < config.key_tests.tests.length; ti++) {
          var testName = config.key_tests.tests[ti];
          var aliases = (config.key_tests.aliases && config.key_tests.aliases[testName])
            ? config.key_tests.aliases[testName]
            : [testName];

          // Build WHERE clause for aliases
          var placeholders = aliases.map(function() { return '?'; }).join(',');
          var sql = 'SELECT value_numeric, unit, result_date FROM lab_results WHERE test_name IN (' + placeholders + ') AND value_numeric IS NOT NULL ORDER BY result_date DESC LIMIT 20';
          var labRows = db.query(sql, aliases);

          if (labRows.length > 0) {
            // Values are DESC, reverse for sparkline (chronological left-to-right)
            var values = [];
            for (var vi = labRows.length - 1; vi >= 0; vi--) {
              values.push(labRows[vi].value_numeric);
            }
            var latestValue = labRows[0].value_numeric;
            var latestUnit = labRows[0].unit || '';
            sparkRows.push({
              testName: testName,
              values: values,
              latestValue: latestValue,
              latestUnit: latestUnit
            });
          }
        }

        if (sparkRows.length > 0) {
          var sparkCard = UI.el('div', { className: 'card mt-16', style: 'padding: 20px;' });
          sparkCard.appendChild(UI.el('h3', { textContent: 'Key Lab Trends', style: 'margin: 0 0 12px 0;' }));

          var sparkTable = UI.el('table', { style: 'width: 100%; border-collapse: collapse;' });
          for (var si = 0; si < sparkRows.length; si++) {
            var sr = sparkRows[si];
            var tr = UI.el('tr', {
              style: 'cursor: pointer; border-bottom: 1px solid var(--border);',
              onClick: function() { Router.navigate('lab_results'); }
            });
            tr.appendChild(UI.el('td', {
              textContent: sr.testName,
              style: 'padding: 8px 12px 8px 0; font-weight: 500;'
            }));
            tr.appendChild(UI.el('td', {
              textContent: sr.latestValue + (sr.latestUnit ? ' ' + sr.latestUnit : ''),
              style: 'padding: 8px 12px; color: var(--text-secondary);'
            }));
            var sparkTd = UI.el('td', { style: 'padding: 8px 0; text-align: right;' });
            sparkTd.appendChild(UI.sparkline(sr.values, 120, 32));
            tr.appendChild(sparkTd);
            sparkTable.appendChild(tr);
          }
          sparkCard.appendChild(sparkTable);
          el.appendChild(sparkCard);
        }
      }
    } catch (e) {
      // config parsing failed or key_tests not available, skip sparklines
    }

    // --- 3. Recent Abnormal Labs (Alerts) ---
    try {
      var alertRows = db.query(
        "SELECT test_name, value, unit, interpretation, result_date, source " +
        "FROM lab_results " +
        "WHERE interpretation IN ('H','L','HH','LL','HIGH','LOW','ABNORMAL','A') " +
        "AND result_date >= date((SELECT MAX(result_date) FROM lab_results), '-30 days') " +
        "ORDER BY result_date DESC LIMIT 10"
      );

      var alertCard = UI.el('div', { className: 'card mt-16', style: 'padding: 20px;' });
      alertCard.appendChild(UI.el('h3', { textContent: 'Recent Alerts', style: 'margin: 0 0 12px 0;' }));

      if (alertRows.length > 0) {
        alertCard.appendChild(UI.table(
          [
            { label: 'Test Name', key: 'test_name' },
            { label: 'Value', key: 'value', format: function(val, row) {
              var container = UI.el('span');
              container.appendChild(document.createTextNode(val || ''));
              if (row.interpretation) {
                container.appendChild(document.createTextNode(' '));
                container.appendChild(UI.badge(row.interpretation, 'red'));
              }
              return container;
            }},
            { label: 'Date', key: 'result_date' },
            { label: 'Source', key: 'source' }
          ],
          alertRows,
          { sortable: false }
        ));
      } else {
        var noAlerts = UI.el('div', { style: 'padding: 8px 0;' }, [
          UI.badge('No abnormal results in the last 30 days', 'green')
        ]);
        alertCard.appendChild(noAlerts);
      }
      el.appendChild(alertCard);
    } catch (e) {
      // lab_results table may not exist, skip alerts
    }

    // --- 4. Recent Activity ---
    try {
      var activityQueries = [
        { sql: "SELECT result_date AS event_date, test_name AS description, source, 'Lab' AS event_type FROM lab_results ORDER BY result_date DESC LIMIT 3", section: 'lab_results' },
        { sql: "SELECT study_date AS event_date, study_name AS description, source, 'Imaging' AS event_type FROM imaging_reports ORDER BY study_date DESC LIMIT 3", section: 'imaging' },
        { sql: "SELECT procedure_date AS event_date, name AS description, source, 'Procedure' AS event_type FROM procedures ORDER BY procedure_date DESC LIMIT 3", section: 'procedures' },
        { sql: "SELECT encounter_date AS event_date, COALESCE(encounter_type, '') || ' - ' || COALESCE(facility, '') AS description, source, 'Encounter' AS event_type FROM encounters ORDER BY encounter_date DESC LIMIT 3", section: 'encounters' }
      ];
      var activityRows = [];
      for (var aqi = 0; aqi < activityQueries.length; aqi++) {
        try {
          var aqRows = db.query(activityQueries[aqi].sql);
          for (var ari = 0; ari < aqRows.length; ari++) {
            aqRows[ari]._section = activityQueries[aqi].section;
            activityRows.push(aqRows[ari]);
          }
        } catch (e2) { /* table may not exist */ }
      }
      // Sort by date descending, take top 10
      activityRows.sort(function(a, b) {
        return (b.event_date || '').localeCompare(a.event_date || '');
      });
      activityRows = activityRows.slice(0, 10);

      if (activityRows.length > 0) {
        var activityCard = UI.el('div', { className: 'card mt-16', style: 'padding: 20px;' });
        activityCard.appendChild(UI.el('h3', { textContent: 'Recent Activity', style: 'margin: 0 0 12px 0;' }));
        var typeBadgeColors = { Lab: 'blue', Imaging: 'green', Procedure: 'orange', Encounter: 'gray' };
        activityCard.appendChild(UI.table(
          [
            { label: 'Date', key: 'event_date' },
            { label: 'Type', key: 'event_type', format: function(v) {
              return UI.badge(v, typeBadgeColors[v] || 'gray');
            }},
            { label: 'Description', key: 'description' },
            { label: 'Source', key: 'source' }
          ],
          activityRows,
          { sortable: false }
        ));
        el.appendChild(activityCard);
      }
    } catch (e) {
      // ignore activity errors
    }
  },

  conditions(el, db) {
    var n = _sectionPreamble(el, db, 'conditions', 'Conditions', 'No conditions recorded.');
    if (n === -1) return;

    var cols = [
      { label: 'Condition', key: 'condition_name', format: function(v, row) {
        if (v) return v;
        if (row.icd10_code) {
          var container = UI.el('span');
          container.appendChild(UI.el('span', { textContent: row.icd10_code }));
          container.appendChild(document.createTextNode(' '));
          container.appendChild(UI.badge('code only', 'gray'));
          return container;
        }
        return UI.el('span', { textContent: '\u2014', style: 'color: var(--text-secondary);' });
      }},
      { label: 'Status', key: 'clinical_status', format: function(v) {
        if (!v) return UI.badge('Unknown', 'orange');
        var lv = v.toLowerCase();
        if (lv === 'active') return UI.badge('Active', 'green');
        if (lv === 'resolved') return UI.badge('Resolved', 'gray');
        return UI.badge(v, 'orange');
      }},
      { label: 'ICD-10', key: 'icd10_code', format: function(v) {
        return v ? UI.badge(v, 'gray') : '';
      }},
      { label: 'Onset Date', key: 'onset_date' },
      { label: 'Source', key: 'source' }
    ];

    // Active conditions
    var active = db.query("SELECT * FROM conditions WHERE LOWER(clinical_status) = 'active' ORDER BY condition_name");
    if (active.length > 0) {
      el.appendChild(UI.el('h3', { textContent: 'Active Conditions (' + active.length + ')', style: 'margin: 16px 0 8px;' }));
      el.appendChild(UI.table(cols, active));
    } else {
      el.appendChild(UI.el('p', { textContent: 'No active conditions.', style: 'color: var(--text-secondary); margin: 16px 0;' }));
    }

    // Resolved & other
    var other = db.query("SELECT * FROM conditions WHERE LOWER(clinical_status) != 'active' OR clinical_status IS NULL ORDER BY condition_name");
    if (other.length > 0) {
      var details = UI.el('details', { style: 'margin-top: 16px;' });
      details.appendChild(UI.el('summary', { textContent: 'Resolved & Other (' + other.length + ')', style: 'cursor: pointer; font-weight: 600; padding: 8px 0;' }));
      details.appendChild(UI.table(cols, other));
      el.appendChild(details);
    }
  },

  medications(el, db) {
    var n = _sectionPreamble(el, db, 'medications', 'Medications', 'No medications recorded.');
    if (n === -1) return;

    var allMeds = db.query('SELECT * FROM medications ORDER BY status, name');

    // Build cross-source map: lowercase name -> { source: status }
    var sourceMap = {};
    for (var i = 0; i < allMeds.length; i++) {
      var key = (allMeds[i].name || '').toLowerCase().trim();
      if (!sourceMap[key]) sourceMap[key] = {};
      if (allMeds[i].source) sourceMap[key][allMeds[i].source] = allMeds[i].status || 'Unknown';
    }

    // --- Tab bar ---
    var activeTab = 'active';
    var tabBar = UI.el('div', { style: 'display: flex; gap: 4px; margin-bottom: 16px;' });
    var tabs = [
      { key: 'active', label: 'Active Medications' },
      { key: 'all', label: 'All Medications' },
      { key: 'reconciliation', label: 'Reconciliation' }
    ];
    var tabBtns = {};
    for (var tbi = 0; tbi < tabs.length; tbi++) {
      (function(tab) {
        var btn = UI.el('button', {
          textContent: tab.label,
          style: 'padding: 8px 20px; border-radius: 100px; font-size: 14px; font-weight: 600; border: 1px solid var(--border); cursor: pointer;'
        });
        btn.addEventListener('click', function() { setMedTab(tab.key); });
        tabBtns[tab.key] = btn;
        tabBar.appendChild(btn);
      })(tabs[tbi]);
    }
    el.appendChild(tabBar);

    var activeView = UI.el('div');
    var allView = UI.el('div', { style: 'display: none;' });
    var reconView = UI.el('div', { style: 'display: none;' });
    el.appendChild(activeView);
    el.appendChild(allView);
    el.appendChild(reconView);

    function setMedTab(tab) {
      activeTab = tab;
      var views = { active: activeView, all: allView, reconciliation: reconView };
      for (var vk in views) {
        views[vk].style.display = vk === tab ? '' : 'none';
        tabBtns[vk].style.background = vk === tab ? 'var(--accent)' : 'var(--surface)';
        tabBtns[vk].style.color = vk === tab ? '#fff' : 'var(--text)';
        tabBtns[vk].style.borderColor = vk === tab ? 'var(--accent)' : 'var(--border)';
      }
    }
    setMedTab('active');

    // === ACTIVE VIEW ===
    var activeMeds = [];
    var otherGroups = {};
    for (var j = 0; j < allMeds.length; j++) {
      var med = allMeds[j];
      var status = (med.status || '').toLowerCase();
      if (status === 'active') {
        activeMeds.push(med);
      } else {
        var groupLabel = med.status || 'Unknown';
        if (!otherGroups[groupLabel]) otherGroups[groupLabel] = [];
        otherGroups[groupLabel].push(med);
      }
    }

    if (activeMeds.length > 0) {
      activeView.appendChild(UI.el('h3', { textContent: 'Active Medications (' + activeMeds.length + ')', style: 'margin: 16px 0 8px;' }));
      for (var a = 0; a < activeMeds.length; a++) {
        var m = activeMeds[a];
        var parts = [];
        if (m.route) parts.push('Route: ' + m.route);
        if (m.start_date) parts.push('Started: ' + m.start_date);
        if (m.prescriber) parts.push('Prescriber: ' + m.prescriber);
        var multiSource = Object.keys(sourceMap[(m.name || '').toLowerCase().trim()] || {}).length > 1;
        var badgeOpt = multiSource ? { text: 'Multi-source', variant: 'blue' } : null;
        var cardOpts = {};
        if (badgeOpt) cardOpts.badge = badgeOpt;
        activeView.appendChild(UI.clinicalCard(m.name || 'Unknown', m.sig || '', parts.join(' | '), cardOpts));
      }
    } else {
      activeView.appendChild(UI.empty('No active medications.'));
    }

    // === ALL VIEW ===
    var tableCols = [
      { label: 'Name', key: 'name' },
      { label: 'Sig', key: 'sig' },
      { label: 'Route', key: 'route' },
      { label: 'Status', key: 'status', format: function(v) {
        if (!v) return UI.badge('Unknown', 'gray');
        var lv = v.toLowerCase();
        if (lv === 'active') return UI.badge(v, 'green');
        if (lv === 'completed' || lv === 'stopped') return UI.badge(v, 'gray');
        return UI.badge(v, 'orange');
      }},
      { label: 'Start Date', key: 'start_date' },
      { label: 'Stop Date', key: 'stop_date' },
      { label: 'Source', key: 'source' }
    ];
    allView.appendChild(UI.table(tableCols, allMeds));

    // === RECONCILIATION VIEW ===
    // Group by normalized name, show per-source status
    var reconGroups = {};
    var reconOrder = [];
    for (var ri = 0; ri < allMeds.length; ri++) {
      var rKey = (allMeds[ri].name || '').toLowerCase().trim();
      if (!reconGroups[rKey]) {
        reconGroups[rKey] = { name: allMeds[ri].name || rKey, entries: [] };
        reconOrder.push(rKey);
      }
      reconGroups[rKey].entries.push(allMeds[ri]);
    }

    // Multi-source groups with discrepancies first
    var multiSourceGroups = [];
    var singleSourceGroups = [];
    for (var rgi = 0; rgi < reconOrder.length; rgi++) {
      var rg = reconGroups[reconOrder[rgi]];
      var sources = {};
      for (var rei = 0; rei < rg.entries.length; rei++) {
        var src = rg.entries[rei].source || 'Unknown';
        sources[src] = rg.entries[rei].status || 'Unknown';
      }
      rg.sources = sources;
      var srcKeys = Object.keys(sources);
      if (srcKeys.length > 1) {
        // Check for status discrepancy
        var statuses = {};
        for (var sk = 0; sk < srcKeys.length; sk++) statuses[sources[srcKeys[sk]].toLowerCase()] = true;
        rg.hasDiscrepancy = Object.keys(statuses).length > 1;
        multiSourceGroups.push(rg);
      } else {
        singleSourceGroups.push(rg);
      }
    }

    if (multiSourceGroups.length > 0) {
      reconView.appendChild(UI.el('h3', { textContent: 'Cross-Source Medications (' + multiSourceGroups.length + ')', style: 'margin: 16px 0 8px;' }));
      for (var mg = 0; mg < multiSourceGroups.length; mg++) {
        var group = multiSourceGroups[mg];
        var badgeRow = UI.el('div', { style: 'display: flex; gap: 6px; flex-wrap: wrap; align-items: center;' });
        var srcList = Object.keys(group.sources);
        for (var si = 0; si < srcList.length; si++) {
          var srcStatus = group.sources[srcList[si]];
          var srcVariant = srcStatus.toLowerCase() === 'active' ? 'green' : 'gray';
          badgeRow.appendChild(UI.badge(srcList[si] + ': ' + srcStatus, srcVariant));
        }
        if (group.hasDiscrepancy) {
          badgeRow.appendChild(UI.badge('Status differs', 'orange'));
        }
        var cardOpts2 = {};
        if (group.hasDiscrepancy) cardOpts2.badge = { text: 'Discrepancy', variant: 'orange' };
        reconView.appendChild(UI.clinicalCard(group.name, badgeRow, ''));
      }
    } else {
      reconView.appendChild(UI.el('p', { textContent: 'No medications appear in multiple sources.', style: 'color: var(--text-secondary); margin: 16px 0;' }));
    }

    if (singleSourceGroups.length > 0) {
      var singleDetails = UI.el('details', { style: 'margin-top: 16px;' });
      singleDetails.appendChild(UI.el('summary', {
        textContent: 'Single-Source Medications (' + singleSourceGroups.length + ')',
        style: 'cursor: pointer; font-weight: 600; padding: 8px 0;'
      }));
      var singleList = UI.el('div', { style: 'padding: 4px 0;' });
      for (var sg = 0; sg < singleSourceGroups.length; sg++) {
        var sGroup = singleSourceGroups[sg];
        var srcName = Object.keys(sGroup.sources)[0] || '';
        var srcStat = sGroup.sources[srcName] || '';
        var sRow = UI.el('div', { style: 'display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--border);' });
        sRow.appendChild(UI.el('span', { textContent: sGroup.name, style: 'flex: 1;' }));
        sRow.appendChild(UI.badge(srcStat, srcStat.toLowerCase() === 'active' ? 'green' : 'gray'));
        sRow.appendChild(UI.el('span', { textContent: srcName, style: 'font-size: 12px; color: var(--text-secondary);' }));
        singleList.appendChild(sRow);
      }
      singleDetails.appendChild(singleList);
      reconView.appendChild(singleDetails);
    }
  },

  lab_results(el, db) {
    var n = _sectionPreamble(el, db, 'lab_results', 'Lab Results', 'No lab results recorded.');
    if (n === -1) return;

    // --- Tab buttons ---
    var activeTab = 'charts';
    var tabBar = UI.el('div', { style: 'display: flex; gap: 4px; margin-bottom: 16px;' });
    var chartTabBtn = UI.el('button', {
      textContent: 'Charts',
      style: 'padding: 8px 20px; border-radius: 100px; font-size: 14px; font-weight: 600; border: 1px solid var(--border); cursor: pointer;'
    });
    var tableTabBtn = UI.el('button', {
      textContent: 'Table',
      style: 'padding: 8px 20px; border-radius: 100px; font-size: 14px; font-weight: 600; border: 1px solid var(--border); cursor: pointer;'
    });
    tabBar.appendChild(chartTabBtn);
    tabBar.appendChild(tableTabBtn);
    el.appendChild(tabBar);

    var chartsView = UI.el('div');
    var tableView = UI.el('div', { style: 'display: none;' });
    el.appendChild(chartsView);
    el.appendChild(tableView);

    function setActiveTab(tab) {
      activeTab = tab;
      if (tab === 'charts') {
        chartTabBtn.style.background = 'var(--accent)';
        chartTabBtn.style.color = '#fff';
        chartTabBtn.style.borderColor = 'var(--accent)';
        tableTabBtn.style.background = 'var(--surface)';
        tableTabBtn.style.color = 'var(--text)';
        tableTabBtn.style.borderColor = 'var(--border)';
        chartsView.style.display = '';
        tableView.style.display = 'none';
      } else {
        tableTabBtn.style.background = 'var(--accent)';
        tableTabBtn.style.color = '#fff';
        tableTabBtn.style.borderColor = 'var(--accent)';
        chartTabBtn.style.background = 'var(--surface)';
        chartTabBtn.style.color = 'var(--text)';
        chartTabBtn.style.borderColor = 'var(--border)';
        chartsView.style.display = 'none';
        tableView.style.display = '';
      }
    }

    chartTabBtn.addEventListener('click', function() { setActiveTab('charts'); });
    tableTabBtn.addEventListener('click', function() { setActiveTab('table'); });
    setActiveTab('charts');

    // ====== CHARTS SUB-VIEW ======
    function renderChart(testName, aliases) {
      var placeholders = aliases.map(function() { return '?'; }).join(',');
      var sql = 'SELECT value_numeric, result_date, source, ref_range FROM lab_results ' +
        'WHERE test_name IN (' + placeholders + ') AND value_numeric IS NOT NULL ' +
        'ORDER BY result_date';
      var labRows = db.query(sql, aliases);
      if (labRows.length === 0) return null;

      // Group by source
      var sourceMap = {};
      var refRangeStr = null;
      for (var ri = 0; ri < labRows.length; ri++) {
        var lr = labRows[ri];
        var src = lr.source || 'Unknown';
        if (!sourceMap[src]) sourceMap[src] = [];
        sourceMap[src].push({ x: lr.result_date, y: lr.value_numeric, source: src });
        if (!refRangeStr && lr.ref_range) refRangeStr = lr.ref_range;
      }

      var sources = Object.keys(sourceMap);
      var datasets = [];
      for (var si = 0; si < sources.length; si++) {
        datasets.push({
          label: sources[si],
          data: sourceMap[sources[si]],
          color: ChartRenderer._palette[si % ChartRenderer._palette.length]
        });
      }

      var refRange = parseRefRange(refRangeStr);
      var chartOpts = { width: 760, height: 280 };
      if (refRange) {
        chartOpts.refRange = refRange;
      }

      var card = UI.el('div', { className: 'chart-container', style: 'margin-bottom: 16px;' });
      card.appendChild(UI.el('h3', { textContent: testName, style: 'margin: 0 0 12px 0; font-size: 16px;' }));
      var canvas = UI.el('canvas');
      card.appendChild(canvas);
      ChartRenderer.line(canvas, datasets, chartOpts);
      return card;
    }

    function renderTopTestCharts() {
      var topTests = db.query(
        'SELECT test_name, COUNT(*) AS cnt FROM lab_results ' +
        'WHERE value_numeric IS NOT NULL ' +
        'GROUP BY test_name ORDER BY cnt DESC LIMIT 5'
      );
      for (var tt = 0; tt < topTests.length; tt++) {
        var chartEl = renderChart(topTests[tt].test_name, [topTests[tt].test_name]);
        if (chartEl) chartsView.appendChild(chartEl);
      }
    }

    try {
      var configEl = document.getElementById('chartfold-config');
      var config = configEl ? JSON.parse(configEl.textContent) : {};
      if (config.key_tests && config.key_tests.tests && config.key_tests.tests.length > 0) {
        for (var kt = 0; kt < config.key_tests.tests.length; kt++) {
          var testName = config.key_tests.tests[kt];
          var aliases = (config.key_tests.aliases && config.key_tests.aliases[testName])
            ? config.key_tests.aliases[testName]
            : [testName];
          var chartEl = renderChart(testName, aliases);
          if (chartEl) chartsView.appendChild(chartEl);
        }
      } else {
        renderTopTestCharts();
      }
    } catch (e) {
      renderTopTestCharts();
    }

    if (chartsView.children.length === 0) {
      chartsView.appendChild(UI.empty('No numeric lab data available for charting.'));
    }

    // ====== TABLE SUB-VIEW ======
    var abnormalInterps = ['H', 'L', 'HH', 'LL', 'HIGH', 'LOW', 'ABNORMAL', 'A'];
    var pageSize = 50;
    var filters = { testName: '', abnormalOnly: false, dateFrom: '', dateTo: '' };
    var currentPage = 1;

    // Get distinct test names for filter dropdown
    var testNames = db.query('SELECT DISTINCT test_name FROM lab_results ORDER BY test_name');
    var testOptions = testNames.map(function(r) { return { value: r.test_name, label: r.test_name }; });

    // Filter bar
    var filterBarEl = UI.filterBar([
      { type: 'select', key: 'testName', label: 'Test', options: testOptions },
      { type: 'checkbox', key: 'abnormalOnly', label: 'Abnormal only' },
      { type: 'date', key: 'dateFrom', label: 'From' },
      { type: 'date', key: 'dateTo', label: 'To' }
    ], filters, function(key, value) {
      filters[key] = value;
      currentPage = 1;
      renderTable();
    });
    tableView.appendChild(filterBarEl);

    var tableContainer = UI.el('div');
    var paginationContainer = UI.el('div');
    tableView.appendChild(tableContainer);
    tableView.appendChild(paginationContainer);

    function renderTable() {
      // Build query with filters
      var conditions = [];
      var params = [];
      if (filters.testName) {
        conditions.push('test_name = ?');
        params.push(filters.testName);
      }
      if (filters.abnormalOnly) {
        var interpPlaceholders = abnormalInterps.map(function() { return '?'; }).join(',');
        conditions.push('interpretation IN (' + interpPlaceholders + ')');
        for (var ai = 0; ai < abnormalInterps.length; ai++) {
          params.push(abnormalInterps[ai]);
        }
      }
      if (filters.dateFrom) {
        conditions.push('result_date >= ?');
        params.push(filters.dateFrom);
      }
      if (filters.dateTo) {
        conditions.push('result_date <= ?');
        params.push(filters.dateTo);
      }

      var whereClause = conditions.length > 0 ? ' WHERE ' + conditions.join(' AND ') : '';

      // Get total count for pagination
      var countRow = db.queryOne('SELECT COUNT(*) AS n FROM lab_results' + whereClause, params);
      var total = countRow ? countRow.n : 0;

      // Clamp currentPage
      var totalPages = Math.max(1, Math.ceil(total / pageSize));
      if (currentPage > totalPages) currentPage = totalPages;

      // Query current page
      var offset = (currentPage - 1) * pageSize;
      var dataParams = params.slice();
      dataParams.push(pageSize);
      dataParams.push(offset);
      var rows = db.query(
        'SELECT test_name, value, value_numeric, unit, ref_range, interpretation, result_date, source FROM lab_results' +
        whereClause + ' ORDER BY result_date DESC, test_name LIMIT ? OFFSET ?',
        dataParams
      );

      // Render table
      tableContainer.textContent = '';
      if (rows.length === 0) {
        tableContainer.appendChild(UI.empty('No lab results match the current filters.'));
      } else {
        var cols = [
          { label: 'Test Name', key: 'test_name' },
          { label: 'Value', key: 'value', format: function(val, row) {
            var container = UI.el('span');
            container.appendChild(document.createTextNode(val != null ? String(val) : ''));
            if (row.interpretation && abnormalInterps.indexOf(row.interpretation) !== -1) {
              container.appendChild(document.createTextNode(' '));
              container.appendChild(UI.badge(row.interpretation, 'red'));
            }
            return container;
          }},
          { label: 'Unit', key: 'unit' },
          { label: 'Ref Range', key: 'ref_range' },
          { label: 'Date', key: 'result_date' },
          { label: 'Source', key: 'source' }
        ];
        tableContainer.appendChild(UI.table(cols, rows));

        // Highlight abnormal rows
        var trs = tableContainer.querySelectorAll('tbody tr');
        for (var tri = 0; tri < trs.length; tri++) {
          if (tri < rows.length) {
            var rowInterp = rows[tri].interpretation;
            if (rowInterp && abnormalInterps.indexOf(rowInterp) !== -1) {
              trs[tri].style.background = 'rgba(255, 59, 48, 0.04)';
            }
          }
        }
      }

      // Render pagination
      paginationContainer.textContent = '';
      if (total > pageSize) {
        paginationContainer.appendChild(UI.pagination(total, pageSize, currentPage, function(page) {
          currentPage = page;
          renderTable();
        }));
      }
    }

    renderTable();
  },

  encounters(el, db) {
    var n = _sectionPreamble(el, db, 'encounters', 'Encounters', 'No encounters recorded.');
    if (n === -1) return;

    var pageSize = 20;
    var currentPage = 1;
    var tableContainer = UI.el('div');
    var paginationContainer = UI.el('div');
    el.appendChild(tableContainer);
    el.appendChild(paginationContainer);

    function encounterTypeBadge(type) {
      if (!type) return UI.badge('Unknown', 'gray');
      var lt = type.toLowerCase();
      if (lt.indexOf('emergency') !== -1 || lt === 'er') return UI.badge(type, 'red');
      if (lt.indexOf('inpatient') !== -1) return UI.badge(type, 'orange');
      if (lt.indexOf('office') !== -1 || lt.indexOf('visit') !== -1) return UI.badge(type, 'blue');
      return UI.badge(type, 'gray');
    }

    function renderPage() {
      var offset = (currentPage - 1) * pageSize;
      var rows = db.query(
        'SELECT * FROM encounters ORDER BY encounter_date DESC LIMIT ? OFFSET ?',
        [pageSize, offset]
      );
      tableContainer.textContent = '';
      tableContainer.appendChild(UI.table([
        { label: 'Date', key: 'encounter_date' },
        { label: 'Type', key: 'encounter_type', format: function(v) { return encounterTypeBadge(v); } },
        { label: 'Facility', key: 'facility' },
        { label: 'Provider', key: 'provider' },
        { label: 'Reason', key: 'reason' },
        { label: 'Source', key: 'source' }
      ], rows));

      paginationContainer.textContent = '';
      if (n > pageSize) {
        paginationContainer.appendChild(UI.pagination(n, pageSize, currentPage, function(page) {
          currentPage = page;
          renderPage();
        }));
      }
    }
    renderPage();
  },

  imaging(el, db) {
    var n = _sectionPreamble(el, db, 'imaging_reports', 'Imaging', 'No imaging reports recorded.', 'imaging reports');
    if (n === -1) return;

    var reports = db.query('SELECT * FROM imaging_reports ORDER BY study_date DESC');
    for (var i = 0; i < reports.length; i++) {
      var r = reports[i];
      // Build meta element with date, modality badge, and provider
      var metaParts = [];
      if (r.study_date) metaParts.push(UI.el('span', { textContent: r.study_date }));
      if (r.modality) { metaParts.push(document.createTextNode(' ')); metaParts.push(UI.badge(r.modality, 'blue')); }
      if (r.ordering_provider) { metaParts.push(document.createTextNode(' \u2022 ')); metaParts.push(UI.el('span', { textContent: r.ordering_provider })); }
      var metaEl = UI.el('div', { className: 'text-secondary' }, metaParts);

      // Body: truncated findings
      var bodyText = '';
      if (r.findings) {
        bodyText = r.findings.length > 200 ? r.findings.substring(0, 200) + '...' : r.findings;
      }

      // Card options
      var cardOpts = {};
      if (r.impression) cardOpts.impression = r.impression;

      var card = UI.clinicalCard(r.study_name || 'Imaging Report', metaEl, bodyText, cardOpts);

      _renderLinkedAssets(card, db, 'imaging_reports', r.id);

      el.appendChild(card);

      // Expandable full text
      if (r.full_text) {
        var combined = (r.findings || '') + (r.impression || '');
        if (r.full_text !== combined && r.full_text.length > combined.length) {
          _renderExpandableText(el, 'Full Report Text', r.full_text);
        }
      }
    }
  },

  pathology(el, db) {
    var n = _sectionPreamble(el, db, 'pathology_reports', 'Pathology', 'No pathology reports recorded.', 'pathology reports');
    if (n === -1) return;

    var reports = db.query('SELECT * FROM pathology_reports ORDER BY report_date DESC');
    for (var i = 0; i < reports.length; i++) {
      var r = reports[i];
      var title = r.specimen || 'Pathology Report';
      var metaText = (r.report_date || '') + (r.source ? ' \u2022 ' + r.source : '');

      // Badge for staging
      var cardOpts = {};
      if (r.staging) {
        var stageMatch = r.staging.match(/stage\s+[IVX\d]+[A-C]?/i);
        if (stageMatch) cardOpts.badge = { text: stageMatch[0], variant: 'orange' };
      }

      // Build body from diagnosis, margins, lymph_nodes
      var bodyParts = [];
      if (r.margins) bodyParts.push('Margins: ' + r.margins);
      if (r.lymph_nodes) bodyParts.push('Lymph Nodes: ' + r.lymph_nodes);
      var bodyText = bodyParts.join('\n');

      // Impression from diagnosis
      if (r.diagnosis) cardOpts.impression = r.diagnosis;

      var card = UI.clinicalCard(title, metaText, bodyText, cardOpts);

      _renderLinkedAssets(card, db, 'pathology_reports', r.id);

      el.appendChild(card);

      // Expandable full text
      if (r.full_text) {
        _renderExpandableText(el, 'Full Report Text', r.full_text);
      }
    }
  },

  allergies(el, db) {
    var n = _sectionPreamble(el, db, 'allergies', 'Allergies', 'No allergies recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM allergies ORDER BY allergen');
    el.appendChild(UI.table([
      { label: 'Allergen', key: 'allergen' },
      { label: 'Reaction', key: 'reaction' },
      { label: 'Severity', key: 'severity', format: function(v) {
        if (!v) return '';
        var lv = v.toLowerCase();
        if (lv === 'severe') return UI.badge(v, 'red');
        if (lv === 'moderate') return UI.badge(v, 'orange');
        return UI.badge(v, 'gray');
      }},
      { label: 'Status', key: 'status', format: function(v) {
        if (!v) return '';
        var lv = v.toLowerCase();
        if (lv === 'active') return UI.badge(v, 'green');
        return UI.badge(v, 'gray');
      }},
      { label: 'Onset Date', key: 'onset_date' },
      { label: 'Source', key: 'source' }
    ], rows));
  },

  clinical_notes(el, db) {
    var n = _sectionPreamble(el, db, 'clinical_notes', 'Clinical Notes', 'No clinical notes recorded.');
    if (n === -1) return;

    var allNotes = db.query('SELECT * FROM clinical_notes ORDER BY note_date DESC');
    var searchText = '';
    var currentPage = 1;
    var pageSize = 20;

    var searchInput = UI.el('input', {
      type: 'text', placeholder: 'Search notes...', className: 'filter-bar',
      style: 'display: block; width: 100%; padding: 8px 12px; margin-bottom: 16px; font-size: 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text); outline: none;',
      onInput: function(e) { searchText = e.target.value.toLowerCase(); currentPage = 1; renderNotes(); }
    });
    el.appendChild(searchInput);

    var notesContainer = UI.el('div');
    var paginationContainer = UI.el('div');
    el.appendChild(notesContainer);
    el.appendChild(paginationContainer);

    function renderNotes() {
      var filtered = allNotes;
      if (searchText) {
        filtered = allNotes.filter(function(note) {
          return (note.content || '').toLowerCase().indexOf(searchText) !== -1 ||
            (note.note_type || '').toLowerCase().indexOf(searchText) !== -1 ||
            (note.author || '').toLowerCase().indexOf(searchText) !== -1;
        });
      }
      var total = filtered.length;
      var totalPages = Math.max(1, Math.ceil(total / pageSize));
      if (currentPage > totalPages) currentPage = totalPages;
      var start = (currentPage - 1) * pageSize;
      var pageNotes = filtered.slice(start, start + pageSize);

      notesContainer.textContent = '';
      if (pageNotes.length === 0) {
        notesContainer.appendChild(UI.empty('No notes match the search.'));
      } else {
        for (var i = 0; i < pageNotes.length; i++) {
          var note = pageNotes[i];
          var title = note.note_type || 'Clinical Note';
          var meta = (note.note_date || '') + (note.author ? ' \u2022 ' + note.author : '');
          var content = note.content || '';
          var bodyEl;
          if (content.length > 300) {
            var details = UI.el('details');
            details.appendChild(UI.el('summary', {
              textContent: content.substring(0, 300) + '... (Show full)',
              style: 'cursor: pointer;'
            }));
            details.appendChild(UI.el('pre', {
              textContent: content,
              style: 'white-space: pre-wrap; font-size: 13px; margin: 8px 0; padding: 12px; background: var(--surface); border-radius: 8px; border: 1px solid var(--border);'
            }));
            bodyEl = details;
          } else {
            bodyEl = UI.el('div', { textContent: content });
          }
          notesContainer.appendChild(UI.clinicalCard(title, meta, bodyEl));
        }
      }

      paginationContainer.textContent = '';
      if (total > pageSize) {
        paginationContainer.appendChild(UI.pagination(total, pageSize, currentPage, function(page) {
          currentPage = page;
          renderNotes();
        }));
      }
    }
    renderNotes();
  },

  procedures(el, db) {
    var n = _sectionPreamble(el, db, 'procedures', 'Procedures', 'No procedures recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM procedures ORDER BY procedure_date DESC');
    var tableContainer = UI.el('div');
    el.appendChild(tableContainer);

    tableContainer.appendChild(UI.table([
      { label: 'Name', key: 'name' },
      { label: 'Date', key: 'procedure_date' },
      { label: 'Provider', key: 'provider' },
      { label: 'Facility', key: 'facility' },
      { label: 'Status', key: 'status', format: function(v) {
        if (!v) return '';
        var lv = v.toLowerCase();
        if (lv === 'completed') return UI.badge(v, 'green');
        if (lv === 'active' || lv === 'in-progress') return UI.badge(v, 'blue');
        return UI.badge(v, 'gray');
      }},
      { label: 'Source', key: 'source' }
    ], rows));

    // Show operative notes as expandable details below the table
    var hasNotes = false;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].operative_note) {
        if (!hasNotes) {
          el.appendChild(UI.el('h3', { textContent: 'Operative Notes', style: 'margin: 24px 0 8px;' }));
          hasNotes = true;
        }
        var label = (rows[i].name || 'Procedure') + ' (' + (rows[i].procedure_date || 'Unknown date') + ')';
        _renderExpandableText(el, label, rows[i].operative_note, {
          detailsStyle: 'margin-bottom: 8px;',
          summaryStyle: 'cursor: pointer; font-weight: 500; padding: 6px 0;'
        });
      }
    }
  },

  vitals(el, db) {
    var n = _sectionPreamble(el, db, 'vitals', 'Vitals', 'No vitals recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM vitals ORDER BY recorded_date DESC, vital_type');
    el.appendChild(UI.table([
      { label: 'Date', key: 'recorded_date' },
      { label: 'Type', key: 'vital_type' },
      { label: 'Value', key: 'value', format: function(v, row) {
        var display = row.value_text || (v != null ? String(v) : '');
        if (row.unit) display += ' ' + row.unit;
        return display;
      }},
      { label: 'Source', key: 'source' }
    ], rows));
  },

  immunizations(el, db) {
    var n = _sectionPreamble(el, db, 'immunizations', 'Immunizations', 'No immunizations recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM immunizations ORDER BY admin_date DESC');
    el.appendChild(UI.table([
      { label: 'Vaccine Name', key: 'vaccine_name' },
      { label: 'Date', key: 'admin_date' },
      { label: 'Lot Number', key: 'lot_number' },
      { label: 'Site', key: 'site' },
      { label: 'Status', key: 'status', format: function(v) {
        if (!v) return '';
        var lv = v.toLowerCase();
        if (lv === 'completed') return UI.badge(v, 'green');
        return UI.badge(v, 'gray');
      }},
      { label: 'Source', key: 'source' }
    ], rows));
  },

  patients(el, db) {
    var n = _sectionPreamble(el, db, 'patients', 'Patient Demographics', 'No patient demographics recorded.', 'patients');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM patients');
    for (var i = 0; i < rows.length; i++) {
      var p = rows[i];
      var fields = [];
      if (p.date_of_birth) fields.push(UI.el('div', {}, [
        UI.el('strong', { textContent: 'Date of Birth: ' }),
        UI.el('span', { textContent: p.date_of_birth })
      ]));
      if (p.gender) fields.push(UI.el('div', {}, [
        UI.el('strong', { textContent: 'Gender: ' }),
        UI.el('span', { textContent: p.gender })
      ]));
      if (p.mrn) fields.push(UI.el('div', {}, [
        UI.el('strong', { textContent: 'MRN: ' }),
        UI.badge(p.mrn, 'gray')
      ]));
      if (p.address) fields.push(UI.el('div', {}, [
        UI.el('strong', { textContent: 'Address: ' }),
        UI.el('span', { textContent: p.address })
      ]));
      if (p.phone) fields.push(UI.el('div', {}, [
        UI.el('strong', { textContent: 'Phone: ' }),
        UI.el('span', { textContent: p.phone })
      ]));
      var fieldList = UI.el('div', { style: 'display: flex; flex-direction: column; gap: 8px; padding: 4px 0;' }, fields);
      var meta = 'Source: ' + (p.source || 'Unknown');
      el.appendChild(UI.clinicalCard(p.name || 'Unknown Patient', meta, fieldList));
    }
  },

  social_history(el, db) {
    var n = _sectionPreamble(el, db, 'social_history', 'Social History', 'No social history recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM social_history ORDER BY category, recorded_date DESC');
    el.appendChild(UI.table([
      { label: 'Category', key: 'category', format: function(v) {
        return v ? UI.badge(v, 'blue') : '';
      }},
      { label: 'Value', key: 'value' },
      { label: 'Date', key: 'recorded_date' },
      { label: 'Source', key: 'source' }
    ], rows));
  },

  family_history(el, db) {
    var n = _sectionPreamble(el, db, 'family_history', 'Family History', 'No family history recorded.');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM family_history ORDER BY relation, condition');

    // Group by relation
    var groups = {};
    var groupOrder = [];
    for (var i = 0; i < rows.length; i++) {
      var rel = rows[i].relation || 'Unknown';
      if (!groups[rel]) { groups[rel] = []; groupOrder.push(rel); }
      groups[rel].push(rows[i]);
    }

    for (var gi = 0; gi < groupOrder.length; gi++) {
      var rel = groupOrder[gi];
      var members = groups[rel];
      var items = [];
      for (var mi = 0; mi < members.length; mi++) {
        var m = members[mi];
        var parts = [];
        parts.push(UI.el('span', { textContent: m.condition || 'Unknown condition' }));
        if (m.age_at_onset) { parts.push(document.createTextNode(' ')); parts.push(UI.badge('onset: ' + m.age_at_onset, 'gray')); }
        if (m.deceased) { parts.push(document.createTextNode(' ')); parts.push(UI.badge('deceased', 'red')); }
        items.push(UI.el('div', { style: 'padding: 4px 0;' }, parts));
      }
      var body = UI.el('div', {}, items);
      el.appendChild(UI.clinicalCard(rel, members.length + ' condition' + (members.length !== 1 ? 's' : ''), body));
    }
  },

  mental_status(el, db) {
    var n = _sectionPreamble(el, db, 'mental_status', 'Mental Status', 'No mental status assessments recorded.', 'assessments');
    if (n === -1) return;

    var rows = db.query('SELECT * FROM mental_status ORDER BY recorded_date DESC, instrument, question');

    // Group by instrument + date
    var groups = {};
    var groupOrder = [];
    for (var i = 0; i < rows.length; i++) {
      var key = (rows[i].instrument || 'Unknown') + '|' + (rows[i].recorded_date || '');
      if (!groups[key]) { groups[key] = { instrument: rows[i].instrument, date: rows[i].recorded_date, items: [] }; groupOrder.push(key); }
      groups[key].items.push(rows[i]);
    }

    for (var gi = 0; gi < groupOrder.length; gi++) {
      var g = groups[groupOrder[gi]];
      var totalScore = null;
      var qaParts = [];
      for (var qi = 0; qi < g.items.length; qi++) {
        var item = g.items[qi];
        if (item.total_score != null) totalScore = item.total_score;
        if (item.question) {
          var qRow = UI.el('div', { style: 'padding: 2px 0; font-size: 13px;' }, [
            UI.el('span', { textContent: item.question + ': ', style: 'color: var(--text-secondary);' }),
            UI.el('span', { textContent: item.answer || '' }),
            item.score != null ? (function() { var s = UI.el('span', {}); s.appendChild(document.createTextNode(' ')); s.appendChild(UI.badge(String(item.score), 'gray')); return s; })() : document.createTextNode('')
          ]);
          qaParts.push(qRow);
        }
      }
      var body = UI.el('div', {}, qaParts);
      var meta = (g.date || 'No date') + (g.items[0].source ? ' \u2022 ' + g.items[0].source : '');
      var cardOpts = {};
      if (totalScore != null) cardOpts.badge = { text: 'Score: ' + totalScore, variant: 'orange' };
      el.appendChild(UI.clinicalCard(g.instrument || 'Assessment', meta, body, cardOpts));
    }
  },

  personal_notes(el, db) {
    // Check if notes table exists and has data
    var row;
    try { row = db.queryOne('SELECT COUNT(*) AS n FROM notes'); } catch (e) { row = null; }
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Personal Notes', n + ' notes'));
    if (n === 0) { el.appendChild(UI.empty('No personal notes recorded. Use the CLI or MCP server to create notes.')); return; }

    var notes = db.query('SELECT * FROM notes ORDER BY updated_at DESC');
    for (var i = 0; i < notes.length; i++) {
      var note = notes[i];
      // Fetch tags for this note
      var tags = [];
      try { tags = db.query('SELECT tag FROM note_tags WHERE note_id = ?', [note.id]); } catch (e) { /* ignore */ }

      var meta = 'Updated: ' + (note.updated_at || note.created_at || '');
      if (note.ref_table) meta += ' \u2022 Linked to: ' + note.ref_table + (note.ref_id ? ' #' + note.ref_id : '');

      var contentEl;
      var content = note.content || '';
      if (content.length > 300) {
        contentEl = UI.el('details');
        contentEl.appendChild(UI.el('summary', {
          textContent: content.substring(0, 300) + '... (Show full)',
          style: 'cursor: pointer;'
        }));
        contentEl.appendChild(UI.el('pre', {
          textContent: content,
          style: 'white-space: pre-wrap; font-size: 13px; margin: 8px 0; padding: 12px; background: var(--surface); border-radius: 8px; border: 1px solid var(--border);'
        }));
      } else {
        contentEl = UI.el('div', { textContent: content });
      }

      var card = UI.clinicalCard(note.title || 'Untitled', meta, contentEl);

      // Render tags
      if (tags.length > 0) {
        var tagRow = UI.el('div', { style: 'margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap;' });
        for (var ti = 0; ti < tags.length; ti++) {
          tagRow.appendChild(UI.badge(tags[ti].tag, 'blue'));
        }
        card.appendChild(tagRow);
      }

      el.appendChild(card);
    }
  },

  sources(el, db) {
    var n = _sectionPreamble(el, db, 'source_assets', 'Sources', 'No source assets recorded.', 'source assets');
    if (n === -1) return;

    // Load embedded images
    var images = {};
    try {
      var imgEl = document.getElementById('chartfold-images');
      if (imgEl) images = JSON.parse(imgEl.textContent);
    } catch (e) { /* ignore */ }

    var assets = db.query('SELECT * FROM source_assets ORDER BY encounter_date DESC, asset_type, file_name');

    // Group by encounter_date
    var groups = {};
    var groupOrder = [];
    for (var i = 0; i < assets.length; i++) {
      var dateKey = assets[i].encounter_date || 'No date';
      if (!groups[dateKey]) { groups[dateKey] = []; groupOrder.push(dateKey); }
      groups[dateKey].push(assets[i]);
    }

    for (var gi = 0; gi < groupOrder.length; gi++) {
      var gDate = groupOrder[gi];
      var gAssets = groups[gDate];
      var details = UI.el('details', { style: 'margin-bottom: 8px;' });
      if (gi === 0) details.setAttribute('open', '');
      details.appendChild(UI.el('summary', {
        textContent: gDate + ' (' + gAssets.length + ' assets)',
        style: 'cursor: pointer; font-weight: 600; padding: 8px 0;'
      }));

      var assetList = UI.el('div', { style: 'padding: 4px 0 8px 16px;' });
      for (var ai = 0; ai < gAssets.length; ai++) {
        var asset = gAssets[ai];
        var assetRow = UI.el('div', { style: 'display: flex; align-items: center; gap: 8px; padding: 4px 0;' });
        var typeBadge = (asset.asset_type || '').toLowerCase().indexOf('pdf') !== -1
          ? UI.badge(asset.asset_type || 'file', 'blue')
          : UI.badge(asset.asset_type || 'file', 'gray');
        assetRow.appendChild(typeBadge);
        assetRow.appendChild(UI.el('span', { textContent: asset.file_name || asset.title || 'Unknown' }));

        // Thumbnail for embedded images
        var assetId = String(asset.id);
        if (images[assetId]) {
          var thumb = UI.el('img', {
            src: images[assetId],
            style: 'max-height: 80px; border-radius: 4px; border: 1px solid var(--border); margin-left: 8px;'
          });
          assetRow.appendChild(thumb);
        }
        assetList.appendChild(assetRow);
      }
      details.appendChild(assetList);
      el.appendChild(details);
    }
  },

  analysis(el, db) {
    // Try DB table first, fall back to embedded JSON (--external-data)
    var data = [];
    var fromDB = false;
    try {
      var dbRows = db.query(
        "SELECT slug, title, category, summary, content, source, " +
        "json_extract(frontmatter, '$.status') AS status, " +
        "json_extract(frontmatter, '$.date') AS doc_date, " +
        "updated_at FROM analyses ORDER BY updated_at DESC"
      );
      if (dbRows.length > 0) {
        data = dbRows.map(function(r) {
          return {
            slug: r.slug, title: r.title, body: r.content,
            filename: r.slug + '.md', category: r.category,
            summary: r.summary, source: r.source,
            status: r.status || 'current',
            doc_date: r.doc_date || '',
            updated_at: r.updated_at || ''
          };
        });
        fromDB = true;
      }
    } catch (e) { /* analyses table may not exist */ }

    // Fetch tags from DB if available
    var tagMap = {};
    if (fromDB) {
      try {
        var tagRows = db.query(
          "SELECT at.analysis_id, at.tag, a.slug " +
          "FROM analysis_tags at JOIN analyses a ON at.analysis_id = a.id"
        );
        for (var ti = 0; ti < tagRows.length; ti++) {
          var slug = tagRows[ti].slug;
          if (!tagMap[slug]) tagMap[slug] = [];
          tagMap[slug].push(tagRows[ti].tag);
        }
      } catch (e) { /* ignore */ }
    }

    if (!fromDB) {
      try {
        var raw = JSON.parse(document.getElementById('chartfold-analysis').textContent);
        if (Array.isArray(raw)) {
          data = raw.map(function(r) {
            return {
              slug: r.slug || '', title: r.title || '', body: r.body || '',
              filename: r.filename || '', category: r.category || '',
              summary: r.summary || '', source: r.source || '',
              status: 'current', doc_date: '', updated_at: ''
            };
          });
        }
      } catch (e) { /* ignore */ }
    }

    el.appendChild(UI.sectionHeader('Analysis', data.length + ' analyses'));

    if (data.length === 0) {
      el.appendChild(UI.empty('No analyses found. Use "chartfold load analyses <dir>" to load analysis files, or --external-data with HTML export.'));
      return;
    }

    // Split into current vs archived
    var currentAnalyses = [];
    var archivedAnalyses = [];
    for (var si = 0; si < data.length; si++) {
      if ((data[si].status || '').toLowerCase() === 'archived') {
        archivedAnalyses.push(data[si]);
      } else {
        currentAnalyses.push(data[si]);
      }
    }

    // Build filename -> anchor-id map for cross-linking between analysis files
    var filenameMap = {};
    for (var j = 0; j < data.length; j++) {
      var fn = data[j].filename || data[j].slug || '';
      if (fn) filenameMap[fn] = 'analysis-' + fn.replace(/\.md$/i, '').replace(/[^a-z0-9-]/gi, '-').toLowerCase();
    }

    function renderAnalysisCard(entry, container) {
      var anchorId = filenameMap[entry.filename || entry.slug] || ('analysis-' + entry.slug);

      // Build summary card content (always visible)
      var summaryParts = [];

      // Title line with badges
      var titleLine = UI.el('div', { style: 'display: flex; align-items: center; gap: 8px; flex-wrap: wrap;' });
      titleLine.appendChild(UI.el('strong', { textContent: entry.title, style: 'font-size: 15px;' }));
      if (entry.category) titleLine.appendChild(UI.badge(entry.category, 'blue'));
      var statusVariant = (entry.status || '').toLowerCase() === 'archived' ? 'gray' : 'green';
      titleLine.appendChild(UI.badge(entry.status || 'current', statusVariant));
      summaryParts.push(titleLine);

      // Date and source line
      var metaLine = UI.el('div', { style: 'font-size: 13px; color: var(--text-secondary); margin-top: 4px;' });
      var metaParts = [];
      if (entry.doc_date) metaParts.push(entry.doc_date);
      if (entry.source) metaParts.push('by ' + entry.source);
      metaLine.textContent = metaParts.join(' \u2022 ');
      if (metaParts.length > 0) summaryParts.push(metaLine);

      // Summary text
      if (entry.summary) {
        summaryParts.push(UI.el('p', {
          textContent: entry.summary,
          style: 'margin: 8px 0 0 0; font-size: 14px; color: var(--text-secondary); line-height: 1.5;'
        }));
      }

      // Tag chips
      var tags = tagMap[entry.slug] || [];
      if (tags.length > 0) {
        var tagRow = UI.el('div', { style: 'margin-top: 8px; display: flex; gap: 4px; flex-wrap: wrap;' });
        for (var tgi = 0; tgi < tags.length; tgi++) {
          tagRow.appendChild(UI.badge(tags[tgi], 'gray'));
        }
        summaryParts.push(tagRow);
      }

      var summaryEl = UI.el('div', { style: 'padding: 4px 0;' }, summaryParts);

      // Full content (hidden by default)
      var contentDiv = UI.el('div', { className: 'analysis-content', style: 'margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);' });
      contentDiv.innerHTML = Markdown.render(entry.body);

      // Rewrite .md file links to scroll to the corresponding inline section
      var links = contentDiv.querySelectorAll('a[href]');
      for (var li = 0; li < links.length; li++) {
        var href = links[li].getAttribute('href');
        if (href && /\.md$/i.test(href)) {
          var targetFn = href.replace(/^.*\//, '');
          var targetId = filenameMap[targetFn];
          if (targetId) {
            links[li].setAttribute('href', '#' + targetId);
            links[li].setAttribute('data-analysis-target', targetId);
          }
        }
      }

      // Wrap in collapsible details
      var details = UI.el('details', { className: 'card', style: 'margin-bottom: 12px; padding: 16px;' });
      details.id = anchorId;
      var summaryTag = UI.el('summary', { style: 'cursor: pointer; list-style: none;' });
      summaryTag.appendChild(summaryEl);
      details.appendChild(summaryTag);
      details.appendChild(contentDiv);
      container.appendChild(details);
    }

    // Render current analyses
    if (currentAnalyses.length > 0) {
      for (var ci = 0; ci < currentAnalyses.length; ci++) {
        renderAnalysisCard(currentAnalyses[ci], el);
      }
    }

    // Render archived analyses in a collapsed group
    if (archivedAnalyses.length > 0) {
      var archivedGroup = UI.el('details', { style: 'margin-top: 16px;' });
      archivedGroup.appendChild(UI.el('summary', {
        textContent: 'Archived (' + archivedAnalyses.length + ')',
        style: 'cursor: pointer; font-weight: 600; padding: 8px 0; color: var(--text-secondary);'
      }));
      for (var ai = 0; ai < archivedAnalyses.length; ai++) {
        renderAnalysisCard(archivedAnalyses[ai], archivedGroup);
      }
      el.appendChild(archivedGroup);
    }

    // Handle clicks on .md links: expand the target <details> and scroll to it
    el.addEventListener('click', function(e) {
      var link = e.target.closest('a[data-analysis-target]');
      if (!link) return;
      e.preventDefault();
      var targetId = link.getAttribute('data-analysis-target');
      var targetEl = document.getElementById(targetId);
      if (targetEl) {
        if (targetEl.tagName === 'DETAILS') targetEl.open = true;
        targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  },

  sql_console(el, db) {
    el.appendChild(UI.sectionHeader('SQL Console', 'Query your data directly'));

    var wrapper = UI.el('div', { className: 'sql-console' });

    // Schema reference (lazy-loaded on first open)
    var schemaDetails = UI.el('details', { style: 'margin-bottom: 12px;' });
    schemaDetails.appendChild(UI.el('summary', {
      textContent: 'Schema Reference',
      style: 'cursor: pointer; font-weight: 600; font-size: 14px; padding: 6px 0; color: var(--text-secondary);'
    }));
    var schemaLoaded = false;
    var runRaw = db['exec'].bind(db);
    schemaDetails.addEventListener('toggle', function() {
      if (schemaDetails.open && !schemaLoaded) {
        schemaLoaded = true;
        var schemaContent = UI.el('div', { style: 'padding: 8px 0; font-family: monospace; font-size: 13px; line-height: 1.8;' });
        try {
          var tables = runRaw("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
          if (tables && tables[0] && tables[0].values) {
            for (var sti = 0; sti < tables[0].values.length; sti++) {
              var tableName = tables[0].values[sti][0];
              var cols = runRaw("PRAGMA table_info('" + tableName.replace(/'/g, "''") + "')");
              var colNames = [];
              if (cols && cols[0] && cols[0].values) {
                for (var ci = 0; ci < cols[0].values.length; ci++) {
                  var colName = cols[0].values[ci][1];
                  var colType = cols[0].values[ci][2] || '';
                  colNames.push(colName + (colType ? ' ' + colType : ''));
                }
              }
              var line = UI.el('div', { style: 'padding: 2px 0;' });
              line.appendChild(UI.el('strong', { textContent: tableName }));
              line.appendChild(UI.el('span', {
                textContent: ' (' + colNames.join(', ') + ')',
                style: 'color: var(--text-secondary);'
              }));
              schemaContent.appendChild(line);
            }
          }
        } catch (e) {
          schemaContent.appendChild(UI.el('div', { textContent: 'Error loading schema: ' + e.message, style: 'color: #ff3b30;' }));
        }
        schemaDetails.appendChild(schemaContent);
      }
    });
    wrapper.appendChild(schemaDetails);

    // Example query chips
    var chips = [
      { label: 'Recent abnormal labs', sql: "SELECT test_name, value, interpretation, result_date FROM lab_results WHERE interpretation IN ('H','L','HH','LL') ORDER BY result_date DESC LIMIT 20" },
      { label: 'Active medications', sql: "SELECT name, sig, route, start_date FROM medications WHERE LOWER(status) = 'active' ORDER BY name" },
      { label: 'Encounter timeline', sql: "SELECT encounter_date, encounter_type, facility, provider FROM encounters ORDER BY encounter_date DESC LIMIT 30" }
    ];
    var chipBar = UI.el('div', { style: 'display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;' });
    for (var ci = 0; ci < chips.length; ci++) {
      (function(chip) {
        var btn = UI.el('button', {
          textContent: chip.label,
          style: 'padding: 4px 12px; font-size: 13px; border-radius: 100px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer;',
          onClick: function() { textarea.value = chip.sql; }
        });
        chipBar.appendChild(btn);
      })(chips[ci]);
    }
    wrapper.appendChild(chipBar);

    // Textarea
    var textarea = UI.el('textarea', {
      placeholder: 'Enter SQL query (SELECT only)...',
      rows: '5'
    });
    wrapper.appendChild(textarea);

    // Run button + shortcut hint
    var btnRow = UI.el('div', { style: 'display: flex; align-items: center; gap: 12px;' });
    var runBtn = UI.el('button', {
      className: 'run-btn',
      textContent: 'Run Query',
      onClick: function() { runQuery(); }
    });
    btnRow.appendChild(runBtn);
    btnRow.appendChild(UI.el('span', {
      textContent: 'Ctrl+Enter to run',
      style: 'font-size: 12px; color: var(--text-secondary);'
    }));
    wrapper.appendChild(btnRow);

    // Results area
    var statusEl = UI.el('div', { style: 'margin-top: 12px; font-size: 13px; color: var(--text-secondary);' });
    var resultsEl = UI.el('div', { style: 'margin-top: 8px;' });
    wrapper.appendChild(statusEl);
    wrapper.appendChild(resultsEl);

    // Query history
    var history = [];
    try {
      var stored = sessionStorage.getItem('chartfold-sql-history');
      if (stored) history = JSON.parse(stored);
    } catch (e) { /* ignore */ }

    var historyDetails = UI.el('details', { style: 'margin-top: 16px;' });
    historyDetails.appendChild(UI.el('summary', {
      textContent: 'Query History',
      style: 'cursor: pointer; font-weight: 600; padding: 4px 0; font-size: 13px; color: var(--text-secondary);'
    }));
    var historyList = UI.el('div', { style: 'padding: 4px 0;' });
    historyDetails.appendChild(historyList);
    wrapper.appendChild(historyDetails);

    function renderHistory() {
      historyList.textContent = '';
      for (var hi = history.length - 1; hi >= 0; hi--) {
        (function(sql) {
          var item = UI.el('div', {
            textContent: sql.length > 80 ? sql.substring(0, 80) + '...' : sql,
            style: 'padding: 4px 8px; font-size: 12px; font-family: monospace; cursor: pointer; color: var(--text-secondary); border-bottom: 1px solid var(--border);',
            onClick: function() { textarea.value = sql; }
          });
          historyList.appendChild(item);
        })(history[hi]);
      }
    }
    renderHistory();

    // Ctrl+Enter shortcut
    textarea.addEventListener('keydown', function(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        runQuery();
      }
    });

    function runQuery() {
      var sql = textarea.value.trim();
      if (!sql) return;

      // Read-only enforcement
      var forbidden = /\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|PRAGMA|ATTACH|DETACH)\b/i;
      if (forbidden.test(sql)) {
        statusEl.textContent = '';
        resultsEl.textContent = '';
        resultsEl.appendChild(UI.el('div', {
          textContent: 'Error: Only SELECT queries are allowed. Write operations (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE) and system commands (PRAGMA, ATTACH, DETACH) are not permitted.',
          style: 'color: #ff3b30; font-size: 14px; padding: 8px 0;'
        }));
        return;
      }

      // Add to history
      var idx = history.indexOf(sql);
      if (idx !== -1) history.splice(idx, 1);
      history.push(sql);
      if (history.length > 20) history.shift();
      try { sessionStorage.setItem('chartfold-sql-history', JSON.stringify(history)); } catch (e) { /* ignore */ }
      renderHistory();

      // Run the query
      var startTime = performance.now();
      try {
        var results = db.exec(sql);
        var elapsed = (performance.now() - startTime).toFixed(1);

        resultsEl.textContent = '';
        if (!results || results.length === 0 || !results[0].columns) {
          statusEl.textContent = '0 rows in ' + elapsed + 'ms';
          resultsEl.appendChild(UI.empty('Query returned no results.'));
          return;
        }

        var columns = results[0].columns;
        var values = results[0].values;
        statusEl.textContent = values.length + ' rows in ' + elapsed + 'ms';

        // Convert to row objects for UI.table
        var rowObjects = [];
        for (var ri = 0; ri < values.length; ri++) {
          var obj = {};
          for (var colIdx = 0; colIdx < columns.length; colIdx++) {
            obj[columns[colIdx]] = values[ri][colIdx];
          }
          rowObjects.push(obj);
        }

        var tableCols = columns.map(function(c) {
          return { label: c, key: c };
        });
        resultsEl.appendChild(UI.table(tableCols, rowObjects));
      } catch (e) {
        var elapsed2 = (performance.now() - startTime).toFixed(1);
        statusEl.textContent = 'Error in ' + elapsed2 + 'ms';
        resultsEl.textContent = '';
        resultsEl.appendChild(UI.el('div', {
          textContent: 'SQL Error: ' + e.message,
          style: 'color: #ff3b30; font-size: 14px; padding: 8px 0;'
        }));
      }
    }

    el.appendChild(wrapper);
  }
};
