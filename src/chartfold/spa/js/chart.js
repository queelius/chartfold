var ChartRenderer = {
  _palette: ['#0071e3', '#ff9500', '#34c759', '#ff3b30', '#af52de', '#5856d6'],

  createTooltip: function(container) {
    var existing = container.querySelector('.chart-tooltip');
    if (existing) return existing;
    var tip = document.createElement('div');
    tip.className = 'chart-tooltip';
    tip.style.cssText = 'position:absolute;z-index:200;background:#fff;color:#1d1d1f;' +
      'padding:8px 12px;border-radius:8px;font-size:13px;line-height:1.4;' +
      'box-shadow:0 4px 12px rgba(0,0,0,0.12);pointer-events:none;display:none;' +
      'white-space:nowrap;border:1px solid #d2d2d7;';
    container.style.position = 'relative';
    container.appendChild(tip);
    return tip;
  },

  _setTooltipContent: function(tooltip, label, value, dateStr, source) {
    while (tooltip.firstChild) tooltip.removeChild(tooltip.firstChild);
    var bold = document.createElement('strong');
    bold.textContent = label;
    tooltip.appendChild(bold);
    tooltip.appendChild(document.createElement('br'));
    tooltip.appendChild(document.createTextNode('Value: ' + value));
    tooltip.appendChild(document.createElement('br'));
    tooltip.appendChild(document.createTextNode('Date: ' + dateStr));
    tooltip.appendChild(document.createElement('br'));
    tooltip.appendChild(document.createTextNode('Source: ' + source));
  },

  line: function(canvas, datasets, opts) {
    opts = opts || {};
    var width = opts.width || 800;
    var height = opts.height || 300;
    var dpr = window.devicePixelRatio || 1;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';

    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // Chart area padding
    var padLeft = 60;
    var padRight = 20;
    var padTop = 20;
    var padBottom = 40;

    // If legend needed, add top padding
    if (datasets.length > 1) {
      padTop = 40;
    }

    var chartW = width - padLeft - padRight;
    var chartH = height - padTop - padBottom;

    // Gather all data points for scaling
    var allY = [];
    var allX = [];
    for (var di = 0; di < datasets.length; di++) {
      var ds = datasets[di];
      for (var pi = 0; pi < ds.data.length; pi++) {
        var pt = ds.data[pi];
        var ts = new Date(pt.x).getTime();
        if (!isNaN(ts) && pt.y != null && !isNaN(pt.y)) {
          allY.push(pt.y);
          allX.push(ts);
        }
      }
    }

    if (allY.length === 0) return;

    // Y-axis range
    var yMin = Math.min.apply(null, allY);
    var yMax = Math.max.apply(null, allY);

    // Include ref range in scale
    var refRange = opts.refRange || null;
    if (refRange) {
      if (refRange.low != null && !isNaN(refRange.low)) {
        yMin = Math.min(yMin, refRange.low);
      }
      if (refRange.high != null && !isNaN(refRange.high)) {
        yMax = Math.max(yMax, refRange.high);
      }
    }

    // Add 10% padding to Y range
    var yRange = yMax - yMin;
    if (yRange === 0) yRange = 1;
    var yPad = yRange * 0.1;
    yMin = yMin - yPad;
    yMax = yMax + yPad;
    yRange = yMax - yMin;

    // X-axis range
    var xMin = Math.min.apply(null, allX);
    var xMax = Math.max.apply(null, allX);
    var xRange = xMax - xMin;
    if (xRange === 0) xRange = 86400000; // 1 day fallback

    // Helper: data coords to canvas coords
    function toCanvasX(xVal) {
      return padLeft + ((xVal - xMin) / xRange) * chartW;
    }
    function toCanvasY(yVal) {
      return padTop + chartH - ((yVal - yMin) / yRange) * chartH;
    }

    // --- Clear ---
    ctx.clearRect(0, 0, width, height);

    // --- Y-axis gridlines and labels ---
    ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    var yTicks = 5;
    var yStep = yRange / yTicks;
    ctx.strokeStyle = '#e5e5ea';
    ctx.lineWidth = 1;
    for (var yi = 0; yi <= yTicks; yi++) {
      var yVal = yMin + yi * yStep;
      var cy = toCanvasY(yVal);
      // gridline
      ctx.beginPath();
      ctx.moveTo(padLeft, cy);
      ctx.lineTo(width - padRight, cy);
      ctx.stroke();
      // label
      ctx.fillStyle = '#86868b';
      var yLabel = yVal;
      if (Math.abs(yVal) >= 100) {
        yLabel = Math.round(yVal);
      } else if (Math.abs(yVal) >= 1) {
        yLabel = Math.round(yVal * 10) / 10;
      } else {
        yLabel = Math.round(yVal * 100) / 100;
      }
      ctx.fillText(String(yLabel), padLeft - 8, cy);
    }

    // Y-axis label
    if (opts.yLabel) {
      ctx.save();
      ctx.translate(14, padTop + chartH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#86868b';
      ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
      ctx.fillText(opts.yLabel, 0, 0);
      ctx.restore();
    }

    // --- Reference range shading ---
    if (refRange && refRange.low != null && refRange.high != null) {
      var refY1 = toCanvasY(refRange.high);
      var refY2 = toCanvasY(refRange.low);
      ctx.fillStyle = 'rgba(52, 199, 89, 0.08)';
      ctx.fillRect(padLeft, refY1, chartW, refY2 - refY1);
      // Draw dashed borders
      ctx.strokeStyle = 'rgba(52, 199, 89, 0.3)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padLeft, refY1);
      ctx.lineTo(width - padRight, refY1);
      ctx.moveTo(padLeft, refY2);
      ctx.lineTo(width - padRight, refY2);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // --- X-axis labels ---
    var sortedX = allX.slice().sort(function(a, b) { return a - b; });
    var uniqueX = [];
    for (var ui = 0; ui < sortedX.length; ui++) {
      if (ui === 0 || sortedX[ui] !== sortedX[ui - 1]) {
        uniqueX.push(sortedX[ui]);
      }
    }
    var maxXLabels = 10;
    var xLabelStep = Math.max(1, Math.ceil(uniqueX.length / maxXLabels));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#86868b';
    ctx.font = '10px -apple-system, BlinkMacSystemFont, sans-serif';
    for (var xi = 0; xi < uniqueX.length; xi += xLabelStep) {
      var xts = uniqueX[xi];
      var cx = toCanvasX(xts);
      var d = new Date(xts);
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      var dateLabel = months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
      ctx.save();
      ctx.translate(cx, height - padBottom + 8);
      ctx.rotate(-Math.PI / 6);
      ctx.fillText(dateLabel, 0, 0);
      ctx.restore();
    }

    // --- Draw lines and points ---
    // Store screen coords for hover
    var screenPoints = [];
    for (var dj = 0; dj < datasets.length; dj++) {
      var dsj = datasets[dj];
      var color = dsj.color || ChartRenderer._palette[dj % ChartRenderer._palette.length];
      var points = [];
      for (var pj = 0; pj < dsj.data.length; pj++) {
        var ptj = dsj.data[pj];
        var tsx = new Date(ptj.x).getTime();
        if (!isNaN(tsx) && ptj.y != null && !isNaN(ptj.y)) {
          points.push({
            sx: toCanvasX(tsx),
            sy: toCanvasY(ptj.y),
            y: ptj.y,
            dateStr: ptj.x,
            label: dsj.label,
            color: color,
            source: ptj.source || dsj.label
          });
        }
      }

      // Sort points by x for line drawing
      points.sort(function(a, b) { return a.sx - b.sx; });

      // Draw line
      if (points.length > 1) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.moveTo(points[0].sx, points[0].sy);
        for (var lk = 1; lk < points.length; lk++) {
          ctx.lineTo(points[lk].sx, points[lk].sy);
        }
        ctx.stroke();
      }

      // Draw data points
      for (var pk = 0; pk < points.length; pk++) {
        ctx.beginPath();
        ctx.arc(points[pk].sx, points[pk].sy, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        screenPoints.push(points[pk]);
      }
    }

    // --- Legend ---
    if (datasets.length > 1) {
      var legendX = padLeft;
      var legendY = 10;
      ctx.font = '12px -apple-system, BlinkMacSystemFont, sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      for (var li = 0; li < datasets.length; li++) {
        var lColor = datasets[li].color || ChartRenderer._palette[li % ChartRenderer._palette.length];
        // Color swatch
        ctx.fillStyle = lColor;
        ctx.fillRect(legendX, legendY - 5, 12, 10);
        legendX += 16;
        // Label text
        ctx.fillStyle = '#1d1d1f';
        ctx.fillText(datasets[li].label, legendX, legendY);
        legendX += ctx.measureText(datasets[li].label).width + 20;
      }
    }

    // --- Hover interaction ---
    var tooltip = ChartRenderer.createTooltip(canvas.parentNode);

    canvas.addEventListener('mousemove', function(e) {
      var rect = canvas.getBoundingClientRect();
      var mx = (e.clientX - rect.left);
      var my = (e.clientY - rect.top);

      // Find closest point
      var closest = null;
      var closestDist = Infinity;
      for (var hi = 0; hi < screenPoints.length; hi++) {
        var sp = screenPoints[hi];
        var dx = sp.sx - mx;
        var dy = sp.sy - my;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < closestDist && dist < 40) {
          closestDist = dist;
          closest = sp;
        }
      }

      if (closest) {
        tooltip.style.display = 'block';
        ChartRenderer._setTooltipContent(tooltip, closest.label, closest.y, closest.dateStr, closest.source);

        // Position tooltip near the point
        var tipX = closest.sx + 12;
        var tipY = closest.sy - 12;

        // Keep tooltip in bounds
        var containerW = canvas.parentNode.offsetWidth;
        if (tipX + 160 > containerW) {
          tipX = closest.sx - 170;
        }
        if (tipY < 0) tipY = 0;

        tooltip.style.left = tipX + 'px';
        tooltip.style.top = tipY + 'px';
      } else {
        tooltip.style.display = 'none';
      }
    });

    canvas.addEventListener('mouseleave', function() {
      tooltip.style.display = 'none';
    });
  }
};
