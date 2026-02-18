(function () {
  function getJson(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!canvas.dataset.baseHeight) {
      const attrHeight = Number(canvas.getAttribute("height"));
      const fallbackHeight = Math.max(220, Math.floor(rect.height) || 240);
      canvas.dataset.baseHeight = String(attrHeight || fallbackHeight);
    }
    const height = Number(canvas.dataset.baseHeight) || 240;
    const width = Math.max(320, Math.floor(rect.width));

    canvas.style.width = "100%";
    canvas.style.height = `${height}px`;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width, height };
  }

  function money(value) {
    if (Math.abs(value) >= 1000) return `$${(value / 1000).toFixed(1)}k`;
    return `$${value.toFixed(0)}`;
  }

  function drawEmptyState(ctx, width, height, text) {
    ctx.fillStyle = "#6f7f93";
    ctx.font = "600 13px Manrope, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(text, width / 2, height / 2);
    ctx.textAlign = "left";
  }

  function drawMonthlyChart(canvas, data) {
    if (!canvas) return;
    const { ctx, width, height } = setupCanvas(canvas);
    const labels = (data && data.labels) || [];
    const income = (data && data.income) || [];
    const expenses = (data && data.expenses) || [];
    const net = (data && data.net) || [];
    if (!labels.length) {
      drawEmptyState(ctx, width, height, "No monthly data available");
      return;
    }

    const pad = { top: 34, right: 22, bottom: 46, left: 56 };
    const chartW = width - pad.left - pad.right;
    const chartH = height - pad.top - pad.bottom;
    const high = Math.max(...income, ...expenses, ...net, 1);
    const low = Math.min(...income, ...expenses, ...net, 0);
    const range = Math.max(1, high - low);

    const x = (index) => pad.left + (chartW * index) / Math.max(labels.length - 1, 1);
    const y = (value) => pad.top + ((high - value) / range) * chartH;

    const panel = ctx.createLinearGradient(0, 0, 0, height);
    panel.addColorStop(0, "rgba(255,255,255,0.04)");
    panel.addColorStop(1, "rgba(255,255,255,0.01)");
    ctx.fillStyle = panel;
    ctx.fillRect(0, 0, width, height);

    for (let i = 0; i <= 5; i += 1) {
      const yPos = pad.top + (chartH * i) / 5;
      const value = high - (range * i) / 5;
      ctx.strokeStyle = "rgba(180, 205, 233, 0.18)";
      ctx.beginPath();
      ctx.moveTo(pad.left, yPos);
      ctx.lineTo(width - pad.right, yPos);
      ctx.stroke();

      ctx.fillStyle = "rgba(227, 237, 248, 0.72)";
      ctx.font = "11px Manrope, sans-serif";
      ctx.fillText(money(value), 8, yPos + 4);
    }

    const zeroY = y(0);
    ctx.strokeStyle = "rgba(225, 238, 250, 0.4)";
    ctx.beginPath();
    ctx.moveTo(pad.left, zeroY);
    ctx.lineTo(width - pad.right, zeroY);
    ctx.stroke();

    const expensePoints = expenses.map((v, i) => ({ x: x(i), y: y(v) }));
    const incomePoints = income.map((v, i) => ({ x: x(i), y: y(v) }));
    const netPoints = net.map((v, i) => ({ x: x(i), y: y(v) }));

    ctx.beginPath();
    ctx.moveTo(expensePoints[0].x, zeroY);
    expensePoints.forEach((p) => ctx.lineTo(p.x, p.y));
    ctx.lineTo(expensePoints[expensePoints.length - 1].x, zeroY);
    ctx.closePath();
    const expGrad = ctx.createLinearGradient(0, pad.top, 0, zeroY);
    expGrad.addColorStop(0, "rgba(242, 92, 108, 0.32)");
    expGrad.addColorStop(1, "rgba(242, 92, 108, 0.04)");
    ctx.fillStyle = expGrad;
    ctx.fill();

    function strokeSeries(points, color, widthPx, glow) {
      ctx.save();
      if (glow) {
        ctx.shadowBlur = 18;
        ctx.shadowColor = color;
      }
      ctx.beginPath();
      points.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = widthPx;
      ctx.stroke();
      ctx.restore();
    }

    strokeSeries(expensePoints, "#f25c6c", 2.2, false);
    strokeSeries(incomePoints, "#1cc48d", 2.2, false);
    strokeSeries(netPoints, "#73a7ff", 2.8, true);

    [incomePoints, expensePoints, netPoints].forEach((series, idx) => {
      const color = ["#1cc48d", "#f25c6c", "#73a7ff"][idx];
      series.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.7, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
    });

    const labelStep = Math.ceil(labels.length / 6);
    labels.forEach((label, i) => {
      if (i % labelStep !== 0 && i !== labels.length - 1) return;
      ctx.fillStyle = "rgba(235, 243, 251, 0.8)";
      ctx.font = "11px Manrope, sans-serif";
      ctx.fillText(label, x(i) - 18, height - 12);
    });

    const legend = [
      ["Income", "#1cc48d"],
      ["Expenses", "#f25c6c"],
      ["Net", "#73a7ff"],
    ];
    let lx = pad.left;
    legend.forEach(([name, color]) => {
      ctx.fillStyle = color;
      ctx.fillRect(lx, 10, 10, 10);
      ctx.fillStyle = "rgba(232, 241, 250, 0.9)";
      ctx.font = "12px Manrope, sans-serif";
      ctx.fillText(name, lx + 14, 19);
      lx += 88;
    });
  }

  function drawDonut(canvas, data, options) {
    if (!canvas) return;
    const { ctx, width, height } = setupCanvas(canvas);
    const labels = (data && data.labels) || [];
    const values = (data && data.values) || [];
    if (!labels.length) {
      drawEmptyState(ctx, width, height, "No data in this range");
      return;
    }

    const total = values.reduce((sum, value) => sum + value, 0);
    if (total <= 0) {
      drawEmptyState(ctx, width, height, "No spending totals");
      return;
    }

    const palette = options.palette;
    const cx = Math.min(width * 0.37, 155);
    const cy = height / 2;
    const radius = Math.min(78, height * 0.36);
    const ring = Math.max(18, radius * 0.36);

    let angle = -Math.PI / 2;
    values.forEach((value, index) => {
      const arc = (value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, angle, angle + arc);
      ctx.strokeStyle = palette[index % palette.length];
      ctx.lineWidth = ring;
      ctx.stroke();
      angle += arc;
    });

    ctx.fillStyle = options.centerColor;
    ctx.font = "700 12px Manrope, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(options.centerLabel, cx, cy - 6);
    ctx.fillStyle = options.valueColor;
    ctx.font = "800 20px Manrope, sans-serif";
    ctx.fillText(`$${total.toFixed(0)}`, cx, cy + 18);
    ctx.textAlign = "left";

    let ly = 24;
    labels.slice(0, 7).forEach((label, index) => {
      const color = palette[index % palette.length];
      const value = values[index] || 0;
      const share = (value / total) * 100;
      const legendX = Math.max(cx + radius + 22, width * 0.58);
      ctx.fillStyle = color;
      ctx.fillRect(legendX, ly, 10, 10);

      ctx.fillStyle = options.legendColor;
      ctx.font = "600 12px Manrope, sans-serif";
      ctx.fillText(label.slice(0, 18), legendX + 16, ly + 9);

      ctx.fillStyle = options.legendSubColor;
      ctx.font = "500 11px Manrope, sans-serif";
      ctx.fillText(`${share.toFixed(1)}%`, width - 42, ly + 9);
      ly += 20;
    });
  }

  function drawHeatmap(canvas, points) {
    if (!canvas) return;
    const { ctx, width, height } = setupCanvas(canvas);
    if (!points || !points.length) {
      drawEmptyState(ctx, width, height, "No heatmap data");
      return;
    }

    const cols = 20;
    const rows = 7;
    const maxValue = Math.max(...points.map((p) => p.total), 1);
    const pad = { top: 26, left: 12, right: 12, bottom: 12 };
    const cellGap = 4;
    const cellW = (width - pad.left - pad.right - (cols - 1) * cellGap) / cols;
    const cellH = (height - pad.top - pad.bottom - (rows - 1) * cellGap) / rows;

    ctx.fillStyle = "#6a7a8f";
    ctx.font = "11px Manrope, sans-serif";
    ctx.fillText("Mon", 2, pad.top + cellH * 0.7);
    ctx.fillText("Wed", 2, pad.top + (cellH + cellGap) * 2.7);
    ctx.fillText("Fri", 2, pad.top + (cellH + cellGap) * 4.7);

    points.forEach((point, index) => {
      const col = Math.floor(index / rows);
      const row = index % rows;
      if (col >= cols) return;

      const x = pad.left + col * (cellW + cellGap);
      const y = pad.top + row * (cellH + cellGap);
      const intensity = point.total / maxValue;

      const red = Math.round(20 + intensity * 70);
      const green = Math.round(56 + intensity * 148);
      const blue = Math.round(110 + intensity * 120);
      ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${0.18 + intensity * 0.82})`;
      ctx.fillRect(x, y, cellW, cellH);
    });

    const monthStep = 4;
    for (let week = 0; week < cols; week += monthStep) {
      const point = points[week * rows];
      if (!point) continue;
      const date = new Date(point.date + "T00:00:00");
      const label = date.toLocaleDateString(undefined, { month: "short" });
      const x = pad.left + week * (cellW + cellGap);
      ctx.fillStyle = "#526378";
      ctx.font = "11px Manrope, sans-serif";
      ctx.fillText(label, x, 12);
    }
  }

  function drawWeekdayRadar(canvas, weekdayData) {
    if (!canvas) return;
    const { ctx, width, height } = setupCanvas(canvas);
    const labels = (weekdayData && weekdayData.labels) || [];
    const values = (weekdayData && weekdayData.values) || [];
    if (!labels.length || !values.length) {
      drawEmptyState(ctx, width, height, "No weekday pattern available");
      return;
    }

    const cx = width / 2;
    const cy = height / 2 + 10;
    const radius = Math.min(width, height) * 0.33;
    const maxVal = Math.max(...values, 1);

    for (let ring = 1; ring <= 4; ring += 1) {
      const ringRadius = (radius * ring) / 4;
      ctx.beginPath();
      for (let i = 0; i < labels.length; i += 1) {
        const angle = (-Math.PI / 2) + (Math.PI * 2 * i) / labels.length;
        const x = cx + Math.cos(angle) * ringRadius;
        const y = cy + Math.sin(angle) * ringRadius;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = "rgba(86, 108, 134, 0.25)";
      ctx.stroke();
    }

    const points = values.map((value, i) => {
      const angle = (-Math.PI / 2) + (Math.PI * 2 * i) / labels.length;
      const length = (value / maxVal) * radius;
      return { x: cx + Math.cos(angle) * length, y: cy + Math.sin(angle) * length };
    });

    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(54, 124, 224, 0.25)";
    ctx.fill();
    ctx.strokeStyle = "#2f7dc8";
    ctx.lineWidth = 2;
    ctx.stroke();

    points.forEach((point) => {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = "#1b5ca4";
      ctx.fill();
    });

    labels.forEach((label, i) => {
      const angle = (-Math.PI / 2) + (Math.PI * 2 * i) / labels.length;
      const x = cx + Math.cos(angle) * (radius + 16);
      const y = cy + Math.sin(angle) * (radius + 16);
      ctx.fillStyle = "#495a70";
      ctx.font = "600 12px Manrope, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, x, y);
    });
    ctx.textAlign = "left";
  }

  function boot() {
    const payload = getJson("visualization-data");
    if (!payload) return;

    const draw = function () {
      drawMonthlyChart(document.getElementById("viz-monthly-canvas"), payload.monthly);
      drawDonut(document.getElementById("viz-category-canvas"), payload.categories, {
        palette: ["#60a5fa", "#34d399", "#fbbf24", "#f472b6", "#fb7185", "#22d3ee", "#f97316"],
        centerLabel: "Categories",
        centerColor: "rgba(222, 236, 255, 0.9)",
        valueColor: "#ffffff",
        legendColor: "rgba(225, 238, 255, 0.95)",
        legendSubColor: "rgba(196, 214, 236, 0.95)",
      });
      drawHeatmap(document.getElementById("viz-heatmap-canvas"), payload.heatmap);
      drawDonut(document.getElementById("viz-account-canvas"), payload.accounts, {
        palette: ["#225b96", "#2f7dc8", "#4d9be3", "#5fd0c8", "#86efac", "#f59e0b"],
        centerLabel: "Accounts",
        centerColor: "#30445a",
        valueColor: "#1f3044",
        legendColor: "#2b3e53",
        legendSubColor: "#5f7084",
      });
      drawWeekdayRadar(document.getElementById("viz-weekday-canvas"), payload.weekdays);
    };

    draw();

    let raf = null;
    window.addEventListener("resize", function () {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(draw);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
