var Chat = {
  // State
  messages: [],
  db: null,
  proxyUrl: null,
  systemPrompt: null,
  busy: false,

  // DOM references
  messagesEl: null,
  inputEl: null,
  sendBtn: null,
  statusDot: null,
  statusText: null,

  init: function(el, db) {
    this.messages = [];
    this.db = db;
    this.busy = false;
    this.proxyUrl = null;
    this.systemPrompt = null;

    // Read config from embedded script tag
    try {
      var configEl = document.getElementById('chartfold-chat-config');
      if (configEl) {
        var config = JSON.parse(configEl.textContent);
        this.proxyUrl = config.proxyUrl || null;
      }
    } catch (e) { /* ignore parse errors */ }

    // Check localStorage override
    var lsOverride = localStorage.getItem('chartfold_proxy_url');
    if (lsOverride !== null && lsOverride !== '') {
      this.proxyUrl = lsOverride;
    }

    // Read system prompt from embedded script tag
    try {
      var promptEl = document.getElementById('chartfold-system-prompt');
      if (promptEl) {
        this.systemPrompt = promptEl.textContent.trim() || null;
      }
    } catch (e) { /* ignore */ }

    this._buildUI(el);

    if (this.proxyUrl) {
      this._updateStatus('ready', 'Ready');
    } else {
      this._updateStatus('error', 'No proxy URL configured');
    }
  },

  _buildUI: function(container) {
    var self = this;

    container.appendChild(
      UI.sectionHeader('Ask AI', 'Ask questions about this medical record')
    );

    var chatContainer = UI.el('div', { className: 'chat-container' });

    // Message history (scrollable)
    this.messagesEl = UI.el('div', { className: 'chat-messages' });
    chatContainer.appendChild(this.messagesEl);

    // Status bar
    this.statusDot = UI.el('span', { className: 'dot' });
    this.statusText = UI.el('span', { textContent: 'Initializing...' });
    var statusBar = UI.el('div', { className: 'chat-status' }, [
      this.statusDot,
      this.statusText
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

    container.appendChild(chatContainer);

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
          tools: [runSqlTool]
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
      var trimmed = query.trim();
      var upper = trimmed.toUpperCase();
      if (!upper.startsWith('SELECT') && !upper.startsWith('WITH') && !upper.startsWith('EXPLAIN')) {
        return { content: 'SQL error: only SELECT, WITH, and EXPLAIN statements are allowed.', is_error: true };
      }

      // Reject multi-statement queries (defense-in-depth; sql.js prepare() only
      // compiles the first statement, and PRAGMA query_only prevents writes)
      var body = trimmed.replace(/;?\s*$/, '');
      if (body.indexOf(';') !== -1) {
        return { content: 'SQL error: multi-statement queries are not allowed.', is_error: true };
      }

      // Auto-add LIMIT 100 if not present
      var upperFull = upper.replace(/\s+/g, ' ');
      if (upperFull.indexOf('LIMIT') === -1) {
        trimmed = trimmed.replace(/;?\s*$/, '') + ' LIMIT 100';
      }

      var rows = this.db.query(trimmed);
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

  _renderMessage: function(role, text) {
    var cls = 'chat-message';
    if (role === 'user') cls += ' user';
    else if (role === 'assistant') cls += ' assistant';
    else if (role === 'error') cls += ' error';

    var msgDiv = UI.el('div', { className: cls });

    if (role === 'user') {
      msgDiv.textContent = text;
    } else {
      // Markdown.render() escapes all HTML entities via its esc() function
      // before applying formatting — safe against injection.
      // Same pattern as sections.js analysis renderer (line 1455).
      var rendered = Markdown.render(text);
      msgDiv.appendChild(UI.el('div', { innerHTML: rendered }));
    }

    this.messagesEl.appendChild(msgDiv);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },

  _renderToolUse: function(queryPreview) {
    var display = queryPreview;
    if (display.length > 100) {
      display = display.substring(0, 100) + '...';
    }
    var div = UI.el('div', {
      className: 'chat-tool-use',
      textContent: 'Running SQL: ' + display
    });
    this.messagesEl.appendChild(div);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  },

  _updateStatus: function(state, text) {
    if (this.statusDot) {
      this.statusDot.className = 'dot';
      if (state === 'thinking') {
        this.statusDot.className = 'dot thinking';
      } else if (state === 'error') {
        this.statusDot.className = 'dot error';
      }
    }
    if (this.statusText) {
      this.statusText.textContent = text || '';
    }
  },

  _showSettings: function() {
    var current = localStorage.getItem('chartfold_proxy_url') || '';
    var hint = current ? current : '(using default from config)';
    var input = prompt('Enter proxy URL (leave empty to use default):\n\nCurrent: ' + hint, current);

    if (input === null) return; // cancelled

    if (input === '') {
      localStorage.removeItem('chartfold_proxy_url');
      // Re-read default from config
      this.proxyUrl = null;
      try {
        var configEl = document.getElementById('chartfold-chat-config');
        if (configEl) {
          var config = JSON.parse(configEl.textContent);
          this.proxyUrl = config.proxyUrl || null;
        }
      } catch (e) { /* ignore */ }
    } else if (input.startsWith('https://') || input.startsWith('http://localhost')) {
      localStorage.setItem('chartfold_proxy_url', input);
      this.proxyUrl = input;
    } else {
      alert('Proxy URL must start with https:// (or http://localhost for development).');
      return;
    }

    if (this.proxyUrl) {
      this._updateStatus('ready', 'Ready');
    } else {
      this._updateStatus('error', 'No proxy URL configured');
    }
  }
};
