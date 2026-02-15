const Sections = {
  overview(el, db) {
    el.appendChild(UI.sectionHeader('Overview', 'Dashboard summary'));

    // --- 1. Summary Cards ---
    var tables = [
      { label: 'Conditions', table: 'conditions', section: 'conditions' },
      { label: 'Medications', table: 'medications', section: 'medications' },
      { label: 'Lab Results', table: 'lab_results', section: 'lab_results' },
      { label: 'Encounters', table: 'encounters', section: 'encounters' },
      { label: 'Imaging', table: 'imaging_reports', section: 'imaging' },
      { label: 'Pathology', table: 'pathology_reports', section: 'pathology' },
      { label: 'Clinical Notes', table: 'clinical_notes', section: 'clinical_notes' },
      { label: 'Procedures', table: 'procedures', section: 'procedures' },
      { label: 'Vitals', table: 'vitals', section: 'vitals' },
      { label: 'Immunizations', table: 'immunizations', section: 'immunizations' },
      { label: 'Allergies', table: 'allergies', section: 'allergies' },
    ];

    var cardGrid = UI.el('div', { className: 'card-grid' });
    for (var i = 0; i < tables.length; i++) {
      var t = tables[i];
      try {
        var row = db.queryOne('SELECT COUNT(*) AS n FROM "' + t.table + '"');
        var count = row ? row.n : 0;
        if (count > 0) {
          var section = t.section;
          cardGrid.appendChild(UI.card(t.label, count, {
            onClick: (function(sec) { return function() { Router.navigate(sec); }; })(section)
          }));
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
        "AND result_date >= date('now', '-30 days') " +
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
  },

  conditions(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM conditions');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Conditions', n + ' conditions'));
    el.appendChild(UI.empty('Conditions section coming soon.'));
  },

  medications(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM medications');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Medications', n + ' medications'));
    el.appendChild(UI.empty('Medications section coming soon.'));
  },

  lab_results(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM lab_results');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Lab Results', n + ' lab results'));
    el.appendChild(UI.empty('Lab results section coming soon.'));
  },

  encounters(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM encounters');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Encounters', n + ' encounters'));
    el.appendChild(UI.empty('Encounters section coming soon.'));
  },

  imaging(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM imaging_reports');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Imaging', n + ' imaging reports'));
    el.appendChild(UI.empty('Imaging section coming soon.'));
  },

  pathology(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM pathology_reports');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Pathology', n + ' pathology reports'));
    el.appendChild(UI.empty('Pathology section coming soon.'));
  },

  allergies(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM allergies');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Allergies', n + ' allergies'));
    el.appendChild(UI.empty('Allergies section coming soon.'));
  },

  clinical_notes(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM clinical_notes');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Clinical Notes', n + ' clinical notes'));
    el.appendChild(UI.empty('Clinical notes section coming soon.'));
  },

  procedures(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM procedures');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Procedures', n + ' procedures'));
    el.appendChild(UI.empty('Procedures section coming soon.'));
  },

  vitals(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM vitals');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Vitals', n + ' vitals'));
    el.appendChild(UI.empty('Vitals section coming soon.'));
  },

  immunizations(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM immunizations');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Immunizations', n + ' immunizations'));
    el.appendChild(UI.empty('Immunizations section coming soon.'));
  },

  sources(el, db) {
    var row = db.queryOne('SELECT COUNT(*) AS n FROM source_assets');
    var n = row ? row.n : 0;
    el.appendChild(UI.sectionHeader('Sources', n + ' source assets'));
    el.appendChild(UI.empty('Sources section coming soon.'));
  },

  analysis(el, db) {
    var n = 0;
    try {
      var data = JSON.parse(
        document.getElementById('chartfold-analysis').textContent
      );
      if (Array.isArray(data)) n = data.length;
    } catch (e) {
      // ignore
    }
    el.appendChild(UI.sectionHeader('Analysis', n + ' analyses'));
    el.appendChild(UI.empty('Analysis section coming soon.'));
  },

  sql_console(el, db) {
    el.appendChild(UI.sectionHeader('SQL Console', 'Query your data directly'));
    el.appendChild(UI.empty('SQL console coming soon.'));
  }
};
