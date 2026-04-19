const UI = {
  el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') e.className = v;
      else if (k === 'textContent') e.textContent = v;
      else if (k === 'innerHTML') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    }
    for (const child of children) {
      if (typeof child === 'string') e.appendChild(document.createTextNode(child));
      else if (child) e.appendChild(child);
    }
    return e;
  },

  table(columns, rows, opts = {}) {
    const { sortable = true, className = '' } = opts;
    let sortCol = null;
    let sortDir = null; // null, 'asc', 'desc'

    const container = UI.el('div', { className: 'table-container' + (className ? ' ' + className : '') });

    function render() {
      let sorted = [...rows];
      if (sortCol !== null && sortDir !== null) {
        const key = columns[sortCol].key;
        sorted.sort((a, b) => {
          let va = a[key], vb = b[key];
          if (va == null && vb == null) return 0;
          if (va == null) return 1;
          if (vb == null) return -1;
          const na = Number(va), nb = Number(vb);
          const numeric = !isNaN(na) && va !== '' && !isNaN(nb) && vb !== '';
          let cmp;
          if (numeric) {
            cmp = na - nb;
          } else {
            cmp = String(va).localeCompare(String(vb));
          }
          return sortDir === 'desc' ? -cmp : cmp;
        });
      }

      container.innerHTML = '';
      const tbl = UI.el('table');
      const thead = UI.el('thead');
      const headerRow = UI.el('tr');

      columns.forEach((col, i) => {
        let label = col.label;
        if (sortable && sortCol === i && sortDir) {
          label += sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
        }
        const th = UI.el('th', {
          textContent: label,
          ...(sortable ? {
            onClick: () => {
              if (sortCol === i) {
                sortDir = sortDir === 'asc' ? 'desc' : sortDir === 'desc' ? null : 'asc';
                if (sortDir === null) sortCol = null;
              } else {
                sortCol = i;
                sortDir = 'asc';
              }
              render();
            }
          } : {})
        });
        headerRow.appendChild(th);
      });

      thead.appendChild(headerRow);
      tbl.appendChild(thead);

      const tbody = UI.el('tbody');
      for (const row of sorted) {
        const tr = UI.el('tr');
        for (const col of columns) {
          const raw = row[col.key];
          const td = UI.el('td');
          if (col.format) {
            const formatted = col.format(raw, row);
            if (typeof formatted === 'string') {
              td.textContent = formatted;
            } else if (formatted instanceof HTMLElement) {
              td.appendChild(formatted);
            } else {
              td.textContent = formatted != null ? String(formatted) : '';
            }
          } else {
            td.textContent = raw != null ? String(raw) : '';
          }
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      tbl.appendChild(tbody);
      container.appendChild(tbl);
    }

    render();
    return container;
  },

  card(title, value, opts = {}) {
    const { onClick, className = '', subtitle } = opts;
    const cls = 'card' + (className ? ' ' + className : '') + (onClick ? ' clickable' : '');
    const children = [
      UI.el('div', { className: 'card-value', textContent: String(value) }),
      UI.el('div', { className: 'card-label', textContent: title })
    ];
    if (subtitle) {
      children.push(UI.el('div', { className: 'card-label', textContent: subtitle }));
    }
    const card = UI.el('div', {
      className: cls,
      ...(onClick ? { onClick } : {})
    }, children);
    return card;
  },

  clinicalCard(title, meta, body, opts = {}) {
    const { onClick, className = '', badge: badgeOpt, impression } = opts;
    const cls = 'clinical-card' + (className ? ' ' + className : '') + (onClick ? ' clickable' : '');

    const headerChildren = [UI.el('strong', { textContent: title })];
    if (badgeOpt) {
      headerChildren.push(document.createTextNode(' '));
      headerChildren.push(UI.badge(badgeOpt.text, badgeOpt.variant));
    }
    const header = UI.el('div', {}, headerChildren);

    const metaEl = typeof meta === 'string'
      ? UI.el('div', { className: 'text-secondary', textContent: meta })
      : meta;

    let bodyEl;
    if (impression) {
      const impText = typeof impression === 'string' ? impression : '';
      bodyEl = UI.el('div', {}, [
        typeof body === 'string' ? UI.el('div', { textContent: body }) : body,
        UI.el('blockquote', {
          textContent: impText,
          style: 'border-left: 3px solid var(--accent); padding: 8px 16px; margin: 8px 0 0; color: var(--text-secondary); background: rgba(0,113,227,0.03); border-radius: 0 8px 8px 0;'
        })
      ]);
    } else {
      bodyEl = typeof body === 'string'
        ? UI.el('div', { textContent: body })
        : body;
    }

    const card = UI.el('div', {
      className: cls,
      ...(onClick ? { onClick } : {})
    }, [header, metaEl, bodyEl].filter(Boolean));
    return card;
  },

  badge(text, variant = 'gray') {
    return UI.el('span', {
      className: 'badge badge-' + variant,
      textContent: text
    });
  },

  pagination(total, pageSize, currentPage, onPage) {
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const container = UI.el('div', { className: 'pagination' });

    // Prev button
    const prev = UI.el('button', {
      textContent: '\u2190 Prev',
      ...(currentPage <= 1 ? { disabled: 'disabled' } : {}),
      onClick: () => { if (currentPage > 1) onPage(currentPage - 1); }
    });
    if (currentPage <= 1) prev.disabled = true;
    container.appendChild(prev);

    // Page number buttons (max 7 visible)
    const pages = _paginationRange(currentPage, totalPages, 7);
    for (const p of pages) {
      if (p === '...') {
        container.appendChild(UI.el('span', { textContent: '\u2026', style: 'padding: 6px 4px; color: var(--text-secondary);' }));
      } else {
        const btn = UI.el('button', {
          textContent: String(p),
          className: p === currentPage ? 'active' : '',
          onClick: () => onPage(p)
        });
        container.appendChild(btn);
      }
    }

    // Next button
    const next = UI.el('button', {
      textContent: 'Next \u2192',
      onClick: () => { if (currentPage < totalPages) onPage(currentPage + 1); }
    });
    if (currentPage >= totalPages) next.disabled = true;
    container.appendChild(next);

    // Page info
    container.appendChild(UI.el('span', {
      textContent: 'Page ' + currentPage + ' of ' + totalPages,
      style: 'margin-left: 12px; font-size: 13px; color: var(--text-secondary);'
    }));

    return container;
  },

  filterBar(filters, values, onChange) {
    const bar = UI.el('div', { className: 'filter-bar' });

    for (const f of filters) {
      if (f.type === 'select') {
        const select = UI.el('select', {
          onChange: (e) => onChange(f.key, e.target.value)
        });
        // "All" option first
        const allOpt = UI.el('option', { value: '', textContent: 'All' });
        select.appendChild(allOpt);
        if (f.options) {
          for (const opt of f.options) {
            const o = UI.el('option', { value: opt.value, textContent: opt.label });
            if (values[f.key] === opt.value) o.selected = true;
            select.appendChild(o);
          }
        }
        if (f.label) {
          bar.appendChild(UI.el('label', { textContent: f.label, style: 'font-size: 13px; font-weight: 600; color: var(--text-secondary);' }));
        }
        bar.appendChild(select);
      } else if (f.type === 'checkbox') {
        const id = 'filter-' + f.key;
        const input = UI.el('input', {
          type: 'checkbox',
          id: id,
          onChange: (e) => onChange(f.key, e.target.checked)
        });
        if (values[f.key]) input.checked = true;
        const label = UI.el('label', {
          textContent: f.label || f.key,
          style: 'font-size: 13px; cursor: pointer; display: flex; align-items: center; gap: 4px;'
        }, [input, document.createTextNode(' ' + (f.label || f.key))]);
        bar.appendChild(label);
      } else if (f.type === 'text') {
        const input = UI.el('input', {
          type: 'text',
          placeholder: f.label || '',
          value: values[f.key] || '',
          onInput: (e) => onChange(f.key, e.target.value)
        });
        bar.appendChild(input);
      } else if (f.type === 'date') {
        if (f.label) {
          bar.appendChild(UI.el('label', { textContent: f.label, style: 'font-size: 13px; font-weight: 600; color: var(--text-secondary);' }));
        }
        const input = UI.el('input', {
          type: 'date',
          value: values[f.key] || '',
          onChange: (e) => onChange(f.key, e.target.value)
        });
        bar.appendChild(input);
      }
    }

    return bar;
  },

  sparkline(values, width = 120, height = 32, color = '#0071e3') {
    const canvas = UI.el('canvas', { width: String(width), height: String(height) });
    if (!values || values.length < 2) return canvas;

    // Defer drawing until the canvas is in the DOM or draw immediately
    const draw = () => {
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const pad = 2;
      const w = width - pad * 2;
      const h = height - pad * 2;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = max - min || 1;

      ctx.clearRect(0, 0, width, height);
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';

      for (let i = 0; i < values.length; i++) {
        const x = pad + (i / (values.length - 1)) * w;
        const y = pad + h - ((values[i] - min) / range) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };

    draw();
    return canvas;
  },

  empty(message) {
    return UI.el('div', { className: 'empty-state', textContent: message });
  },

  sectionHeader(title, description) {
    const children = [UI.el('h2', { textContent: title })];
    if (description) {
      children.push(UI.el('p', { textContent: description }));
    }
    return UI.el('div', { className: 'section-header' }, children);
  }
};

/**
 * Compute which page numbers to show, with ellipsis for gaps.
 * Returns an array of numbers and '...' strings.
 */
function _paginationRange(current, total, maxVisible) {
  if (total <= maxVisible) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages = [];
  const half = Math.floor(maxVisible / 2);

  // Always show first page
  pages.push(1);

  let start = Math.max(2, current - half + 1);
  let end = Math.min(total - 1, current + half - 1);

  // Adjust if near the beginning
  if (current <= half) {
    end = Math.min(total - 1, maxVisible - 2);
    start = 2;
  }
  // Adjust if near the end
  if (current > total - half) {
    start = Math.max(2, total - maxVisible + 3);
    end = total - 1;
  }

  if (start > 2) pages.push('...');
  for (let i = start; i <= end; i++) pages.push(i);
  if (end < total - 1) pages.push('...');

  // Always show last page
  pages.push(total);

  return pages;
}
