const Sections = {
  overview(el, db) {
    el.appendChild(UI.sectionHeader('Overview', 'Dashboard summary'));
    el.appendChild(UI.empty('Overview dashboard coming soon.'));
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
