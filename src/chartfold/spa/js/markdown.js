var Markdown = {
  render: function(text) {
    if (!text) return '';
    var lines = text.split('\n');
    var html = [];
    var inCode = false, codeLines = [];
    var inList = false, listType = '';
    var i, line;

    function esc(s) {
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function inline(s) {
      s = esc(s);
      // bold+italic
      s = s.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
      // bold
      s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      // italic
      s = s.replace(/\*(.*?)\*/g, '<em>$1</em>');
      // inline code
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      // links — sanitize URL to block dangerous protocols and prevent attribute breakout
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(m, text, url) {
        var trimmed = url.replace(/\s/g, '').toLowerCase();
        if (trimmed.match(/^(javascript|data|vbscript):/)) return text;
        // Re-encode &quot; as %22 to prevent attribute breakout (esc() already ran)
        var safeUrl = url.replace(/&quot;/g, '%22').replace(/&#39;/g, '%27');
        return '<a href="' + safeUrl + '">' + text + '</a>';
      });
      return s;
    }

    function closeList() {
      if (inList) {
        html.push(listType === 'ol' ? '</ol>' : '</ul>');
        inList = false;
        listType = '';
      }
    }

    // Collect paragraph lines
    var paraLines = [];
    function flushPara() {
      if (paraLines.length > 0) {
        html.push('<p>' + paraLines.join('<br>') + '</p>');
        paraLines = [];
      }
    }

    for (i = 0; i < lines.length; i++) {
      line = lines[i];

      // Fenced code blocks
      if (line.match(/^```/)) {
        if (inCode) {
          html.push('<pre><code>' + esc(codeLines.join('\n')) + '</code></pre>');
          inCode = false;
          codeLines = [];
        } else {
          flushPara();
          closeList();
          inCode = true;
          codeLines = [];
        }
        continue;
      }
      if (inCode) { codeLines.push(line); continue; }

      // Blank line
      if (line.match(/^\s*$/)) {
        flushPara();
        closeList();
        continue;
      }

      // Horizontal rule
      if (line.match(/^(\-{3,}|\*{3,})$/)) {
        flushPara();
        closeList();
        html.push('<hr>');
        continue;
      }

      // Headings
      var hMatch = line.match(/^(#{1,4})\s+(.*)$/);
      if (hMatch) {
        flushPara();
        closeList();
        var level = hMatch[1].length;
        html.push('<h' + level + '>' + inline(hMatch[2]) + '</h' + level + '>');
        continue;
      }

      // Blockquote
      if (line.match(/^>\s?/)) {
        flushPara();
        closeList();
        var bqText = line.replace(/^>\s?/, '');
        // Gather consecutive blockquote lines
        while (i + 1 < lines.length && lines[i + 1].match(/^>\s?/)) {
          i++;
          bqText += '\n' + lines[i].replace(/^>\s?/, '');
        }
        html.push('<blockquote>' + inline(bqText).replace(/\n/g, '<br>') + '</blockquote>');
        continue;
      }

      // Table: detect header + separator
      if (line.indexOf('|') !== -1 && i + 1 < lines.length && lines[i + 1].match(/^\|?\s*[-:]+[-|:\s]*$/)) {
        flushPara();
        closeList();
        var headerCells = line.split('|').map(function(c) { return c.trim(); }).filter(function(c) { return c !== ''; });
        i++; // skip separator
        var trows = [];
        while (i + 1 < lines.length && lines[i + 1].indexOf('|') !== -1) {
          i++;
          var cells = lines[i].split('|').map(function(c) { return c.trim(); }).filter(function(c) { return c !== ''; });
          trows.push(cells);
        }
        var thtml = '<table><thead><tr>';
        for (var hi = 0; hi < headerCells.length; hi++) {
          thtml += '<th>' + inline(headerCells[hi]) + '</th>';
        }
        thtml += '</tr></thead><tbody>';
        for (var ri = 0; ri < trows.length; ri++) {
          thtml += '<tr>';
          for (var ci = 0; ci < headerCells.length; ci++) {
            thtml += '<td>' + (trows[ri][ci] !== undefined ? inline(trows[ri][ci]) : '') + '</td>';
          }
          thtml += '</tr>';
        }
        thtml += '</tbody></table>';
        html.push(thtml);
        continue;
      }

      // Unordered list
      var ulMatch = line.match(/^[\-\*]\s+(.*)$/);
      if (ulMatch) {
        flushPara();
        if (!inList || listType !== 'ul') {
          closeList();
          html.push('<ul>');
          inList = true;
          listType = 'ul';
        }
        html.push('<li>' + inline(ulMatch[1]) + '</li>');
        continue;
      }

      // Ordered list
      var olMatch = line.match(/^\d+\.\s+(.*)$/);
      if (olMatch) {
        flushPara();
        if (!inList || listType !== 'ol') {
          closeList();
          html.push('<ol>');
          inList = true;
          listType = 'ol';
        }
        html.push('<li>' + inline(olMatch[1]) + '</li>');
        continue;
      }

      // Regular text -> paragraph accumulator
      closeList();
      paraLines.push(inline(line));
    }

    // Close any open blocks
    if (inCode) {
      html.push('<pre><code>' + esc(codeLines.join('\n')) + '</code></pre>');
    }
    flushPara();
    closeList();

    return html.join('\n');
  }
};
