var Chat = {
  // State
  messages: [],
  db: null,
  proxyUrl: null,
  systemPrompt: null,
  busy: false,
  _container: null,
  MAX_MESSAGES: 40,

  // DOM references
  messagesEl: null,
  inputEl: null,
  sendBtn: null,
  statusDot: null,
  statusText: null,

  init: function(el, db) {
    // Reattach existing container if navigating back
    if (Chat._container) {
      el.appendChild(Chat._container);
      this.inputEl.focus();
      return;
    }

    this.messages = [];
    this.db = db;
    this.busy = false;

    // Proxy URL: localStorage override > embedded config > null
    this.proxyUrl = this._readProxyUrl();

    // Read system prompt from embedded script tag
    var promptEl = document.getElementById('chartfold-system-prompt');
    this.systemPrompt = (promptEl && promptEl.textContent.trim()) || null;

    this._buildUI(el);
    this._syncStatus();
  },

  _readProxyUrl: function() {
    var lsOverride = localStorage.getItem('chartfold_proxy_url');
    if (lsOverride) return lsOverride;
    try {
      var configEl = document.getElementById('chartfold-chat-config');
      if (configEl) {
        var config = JSON.parse(configEl.textContent);
        return config.proxyUrl || null;
      }
    } catch (e) { /* ignore parse errors */ }
    return null;
  },

  _syncStatus: function() {
    if (this.proxyUrl) {
      this._updateStatus('ready', 'Ready');
    } else {
      this._updateStatus('error', 'No proxy URL configured');
    }
  },

  _buildUI: function(container) {
    var self = this;

    this._container = UI.el('div');

    this._container.appendChild(
      UI.sectionHeader('Ask AI', 'Ask questions about this medical record')
    );

    var chatContainer = UI.el('div', { className: 'chat-container' });

    // Message history (scrollable)
    this.messagesEl = UI.el('div', { className: 'chat-messages' });
    chatContainer.appendChild(this.messagesEl);

    // Status bar
    this.statusDot = UI.el('span', { className: 'dot' });
    this.statusText = UI.el('span', { textContent: 'Initializing...' });
    // Clear button
    var clearBtn = UI.el('button', {
      className: 'chat-clear-btn',
      textContent: 'Clear',
      onClick: function() { self._onClear(); }
    });

    var statusBar = UI.el('div', { className: 'chat-status' }, [
      this.statusDot,
      this.statusText,
      clearBtn
    ]);
    chatContainer.appendChild(statusBar);

    // Input area
    this.inputEl = UI.el('textarea', {
      className: 'chat-input',
      placeholder: 'Ask a question about the medical record...',
      rows: '1'
    });

    // Auto-resize on input
    this.inputEl.addEventListener('input', function() {
      self.inputEl.style.height = 'auto';
      var scrollH = self.inputEl.scrollHeight;
      self.inputEl.style.height = Math.min(scrollH, 120) + 'px';
    });

    // Enter sends, Shift+Enter for newline
    this.inputEl.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self._onSend();
      }
    });

    this.sendBtn = UI.el('button', {
      className: 'chat-send-btn',
      textContent: 'Send',
      onClick: function() { self._onSend(); }
    });

    var inputArea = UI.el('div', { className: 'chat-input-area' }, [
      this.inputEl,
      this.sendBtn
    ]);
    chatContainer.appendChild(inputArea);

    // Settings link
    var settingsLink = UI.el('a', {
      textContent: 'Proxy settings',
      href: '#',
      onClick: function(e) {
        e.preventDefault();
        self._showSettings();
      }
    });
    var settingsDiv = UI.el('div', { className: 'chat-settings' }, [settingsLink]);
    chatContainer.appendChild(settingsDiv);

    this._container.appendChild(chatContainer);

    container.appendChild(this._container);

    // Focus input after brief delay
    setTimeout(function() {
      self.inputEl.focus();
    }, 100);
  },

  _onSend: function() {
    var text = this.inputEl.value.trim();
    if (this.busy || !text || !this.proxyUrl) return;

    this.inputEl.value = '';
    this.inputEl.style.height = 'auto';
    this.messages.push({ role: 'user', content: text });
    this._renderMessage('user', text);
    this._agentLoop();
  },

  _trimHistory: function() {
    if (this.messages.length <= this.MAX_MESSAGES) return;
    this.messages = this.messages.slice(-this.MAX_MESSAGES);
    // Don't start with an orphaned tool_result (its paired tool_use was trimmed)
    while (
      this.messages.length > 0 &&
      this.messages[0].role === 'user' &&
      Array.isArray(this.messages[0].content)
    ) {
      this.messages.shift();
    }
  },

  _onClear: function() {
    if (this.busy) return;
    this.messages = [];
    this.messagesEl.textContent = '';
  },

  _agentLoop: async function() {
    var self = this;
    this.busy = true;
    this.sendBtn.disabled = true;
    this._updateStatus('thinking', 'Thinking...');

    var runSqlTool = {
      name: 'run_sql',
      description: 'Execute a read-only SQL query against the patient health database. Returns results as an array of objects. Use SELECT only.',
      input_schema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'SQL SELECT query to execute' }
        },
        required: ['query']
      }
    };

    var renderChartTool = {
      name: 'render_chart',
      description: 'Render a line chart inline in the chat. Use after querying time-series lab data to visualize trends.',
      input_schema: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'Chart title' },
          y_label: { type: 'string', description: 'Y-axis label (units)' },
          data: { type: 'array', items: { type: 'object', properties: { date: { type: 'string' }, value: { type: 'number' }, source: { type: 'string' } }, required: ['date', 'value'] } },
          ref_range: { type: 'object', properties: { low: { type: 'number' }, high: { type: 'number' } } }
        },
        required: ['title', 'data']
      }
    };

    var MAX_TOOL_ROUNDS = 10;
    var iterations = 0;

    try {
      while (true) {
        if (++iterations > MAX_TOOL_ROUNDS) {
          throw new Error('Too many tool use rounds (' + MAX_TOOL_ROUNDS + ') — stopping to prevent runaway API calls.');
        }

        var body = {
          model: 'unused',
          max_tokens: 4096,
          messages: self.messages,
          tools: [runSqlTool, renderChartTool]
        };
        if (self.systemPrompt) {
          body.system = self.systemPrompt;
        }

        var response = await fetch(self.proxyUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });

        if (!response.ok) {
          var errText = await response.text();
          throw new Error('API error (' + response.status + '): ' + errText);
        }

        var data = await response.json();

        if (!data.content || !Array.isArray(data.content)) {
          throw new Error('Unexpected API response format');
        }

        var textParts = [];
        var toolResults = [];

        for (var i = 0; i < data.content.length; i++) {
          var block = data.content[i];
          if (block.type === 'text') {
            textParts.push(block.text);
          } else if (block.type === 'tool_use') {
            if (block.name === 'render_chart') {
              self._executeRenderChart(block.input || {});
              toolResults.push({
                type: 'tool_result',
                tool_use_id: block.id,
                content: 'Chart rendered: ' + ((block.input && block.input.title) || 'chart'),
                is_error: false
              });
            } else {
              var queryStr = (block.input && block.input.query) ? block.input.query : '';
              self._renderToolUse(queryStr);
              var result = self._executeSql(queryStr);
              toolResults.push({
                type: 'tool_result',
                tool_use_id: block.id,
                content: result.content,
                is_error: result.is_error
              });
            }
          }
        }

        if (toolResults.length > 0) {
          // Show any thinking/explanation text alongside tool calls
          if (textParts.length > 0) {
            self._renderMessage('assistant', textParts.join('\n'));
          }
          // Push assistant message with raw content blocks, then tool results
          self.messages.push({ role: 'assistant', content: data.content });
          self.messages.push({ role: 'user', content: toolResults });
          // Continue the loop for the next API call
          continue;
        }

        // Text-only response: render and break
        var fullText = textParts.join('\n');
        self.messages.push({ role: 'assistant', content: fullText });
        self._renderMessage('assistant', fullText);
        break;
      }

      self._trimHistory();
      self._updateStatus('ready', 'Ready');
    } catch (err) {
      self._renderMessage('error', 'Error: ' + err.message);
      self._updateStatus('error', 'Error');
    } finally {
      self.busy = false;
      self.sendBtn.disabled = false;
      self.inputEl.focus();
    }
  },

  _executeSql: function(query) {
    try {
      // Strip trailing semicolon and whitespace once for all checks
      var sql = query.trim().replace(/;?\s*$/, '');
      var upper = sql.toUpperCase();
      if (!upper.startsWith('SELECT') && !upper.startsWith('WITH') && !upper.startsWith('EXPLAIN')) {
        return { content: 'SQL error: only SELECT, WITH, and EXPLAIN statements are allowed.', is_error: true };
      }

      // Reject multi-statement queries (defense-in-depth; sql.js prepare() only
      // compiles the first statement, and PRAGMA query_only prevents writes).
      // Note: may false-positive on semicolons inside string literals; acceptable
      // since the engine-level protections are the real safety net.
      if (sql.indexOf(';') !== -1) {
        return { content: 'SQL error: multi-statement queries are not allowed.', is_error: true };
      }

      // Auto-add LIMIT 100 if not present
      if (upper.replace(/\s+/g, ' ').indexOf('LIMIT') === -1) {
        sql += ' LIMIT 100';
      }

      var rows = this.db.query(sql);
      var content = rows.length + ' rows returned.\n' + JSON.stringify(rows, null, 2);

      // Cap result string at 50000 chars
      if (content.length > 50000) {
        content = content.substring(0, 50000) + '\n... (truncated, result exceeded 50000 characters)';
      }

      return { content: content, is_error: false };
    } catch (e) {
      return { content: 'SQL error: ' + e.message, is_error: true };
    }
  },

  _appendToChat: function(el) {
    this.messagesEl.appendChild(el);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },

  _executeRenderChart: function(input) {
    var chartDiv = UI.el('div', { className: 'chat-chart' });

    if (input.title) {
      chartDiv.appendChild(UI.el('div', {
        textContent: input.title,
        style: 'font-weight: 600; font-size: 13px; margin-bottom: 4px;'
      }));
    }

    // Map {date, value, source} to ChartRenderer's {x, y, source}
    var data = input.data || [];
    var dataPoints = data.map(function(d) {
      return { x: d.date, y: d.value, source: d.source || '' };
    });

    var canvas = UI.el('canvas');
    chartDiv.appendChild(canvas);

    var opts = {};
    if (input.y_label) opts.yLabel = input.y_label;
    if (input.ref_range) opts.refRange = input.ref_range;

    ChartRenderer.line(canvas, [{ label: input.title || 'Values', data: dataPoints }], opts);

    this._appendToChat(chartDiv);
  },

  _renderMessage: function(role, text) {
    var msgDiv = UI.el('div', { className: 'chat-message ' + role });

    if (role === 'user') {
      msgDiv.textContent = text;
    } else {
      // Markdown.render() escapes all HTML entities via its esc() function
      // before applying formatting — safe against injection.
      // Same pattern as sections.js analysis renderer (line 1455).
      var rendered = Markdown.render(text);
      msgDiv.appendChild(UI.el('div', { innerHTML: rendered }));
    }

    this._appendToChat(msgDiv);
  },

  _renderToolUse: function(queryPreview) {
    var display = queryPreview.length > 100 ? queryPreview.substring(0, 100) + '...' : queryPreview;
    this._appendToChat(UI.el('div', {
      className: 'chat-tool-use',
      textContent: 'Running SQL: ' + display
    }));
  },

  _updateStatus: function(state, text) {
    if (this.statusDot) {
      this.statusDot.className = state === 'ready' ? 'dot' : 'dot ' + state;
    }
    if (this.statusText) {
      this.statusText.textContent = text || '';
    }
  },

  _showSettings: function() {
    var current = localStorage.getItem('chartfold_proxy_url') || '';
    var hint = current || '(using default from config)';
    var input = prompt('Enter proxy URL (leave empty to use default):\n\nCurrent: ' + hint, current);

    if (input === null) return; // cancelled

    if (input === '') {
      localStorage.removeItem('chartfold_proxy_url');
      this.proxyUrl = this._readProxyUrl();
    } else if (input.startsWith('https://') || input.startsWith('http://localhost')) {
      localStorage.setItem('chartfold_proxy_url', input);
      this.proxyUrl = input;
    } else {
      alert('Proxy URL must start with https:// (or http://localhost for development).');
      return;
    }

    this._syncStatus();
  }
};
