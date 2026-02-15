const Router = {
  sections: {},      // {id: {label, group, count, render}}
  contentEl: null,   // #content div
  sidebarEl: null,   // sidebar div
  current: null,     // currently active section id

  init(contentEl, sidebarEl) {
    this.contentEl = contentEl;
    this.sidebarEl = sidebarEl;
    this.current = null;
  },

  register(id, label, group, count, renderFn) {
    this.sections[id] = {
      label: label,
      group: group,
      count: count,
      render: renderFn
    };
  },

  navigate(sectionId) {
    // 1. If section not registered, ignore
    var section = this.sections[sectionId];
    if (!section) return;

    // 2. Update sidebar active state
    var items = this.sidebarEl.querySelectorAll('.sidebar-item');
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove('active');
      if (items[i].getAttribute('data-section') === sectionId) {
        items[i].classList.add('active');
      }
    }

    // 3. Clear content area
    this.contentEl.textContent = '';

    // 4. Call render function or show fallback
    if (typeof section.render === 'function') {
      section.render(this.contentEl, DB);
    } else {
      this.contentEl.appendChild(
        UI.sectionHeader(section.label, '')
      );
      this.contentEl.appendChild(
        UI.empty(section.label + ' section is not yet available.')
      );
    }

    // 5. Update current
    this.current = sectionId;

    // 6. Set location hash for bookmarking
    if (location.hash !== '#' + sectionId) {
      history.pushState(null, '', '#' + sectionId);
    }

    // 7. On mobile, close sidebar
    var sidebar = document.querySelector('.sidebar');
    var overlay = document.querySelector('.sidebar-overlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('open');

    // 8. Scroll content to top
    this.contentEl.scrollTop = 0;
  },

  start() {
    var self = this;

    // 1. Wire click handlers via event delegation on sidebar
    this.sidebarEl.addEventListener('click', function(e) {
      var item = e.target.closest('.sidebar-item');
      if (!item) return;
      var sectionId = item.getAttribute('data-section');
      if (sectionId) {
        self.navigate(sectionId);
      }
    });

    // 2. Handle browser back/forward
    window.addEventListener('popstate', function() {
      var hash = location.hash.replace('#', '');
      if (hash && self.sections[hash]) {
        self.navigate(hash);
      }
    });

    // 3. Check location.hash — navigate there if registered, otherwise 'overview'
    var hash = location.hash.replace('#', '');
    if (hash && this.sections[hash]) {
      this.navigate(hash);
    } else {
      this.navigate('overview');
    }
  }
};
