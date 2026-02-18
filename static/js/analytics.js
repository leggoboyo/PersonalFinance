(function () {
  function getJson(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return null;
    }
  }

  function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!canvas.dataset.baseHeight) {
      const attrHeight = Number(canvas.getAttribute("height"));
      const fallbackHeight = Math.max(220, Math.floor(rect.height) || 260);
      canvas.dataset.baseHeight = String(attrHeight || fallbackHeight);
    }
    const heightAttr = Number(canvas.dataset.baseHeight) || 260;
    canvas.style.width = "100%";
    canvas.style.height = `${heightAttr}px`;
    canvas.width = Math.max(300, Math.floor(rect.width * dpr));
    canvas.height = Math.max(220, Math.floor(heightAttr * dpr));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: heightAttr };
  }

  function moneyLabel(value) {
    const abs = Math.abs(value);
    if (abs >= 1000) return `${value < 0 ? "-" : ""}$${(abs / 1000).toFixed(1)}k`;
    return `${value < 0 ? "-" : ""}$${abs.toFixed(0)}`;
  }

  function drawLine(ctx, points, color, width) {
    if (!points.length) return;
    ctx.beginPath();
    points.forEach((point, idx) => {
      if (idx === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.stroke();
  }

  function drawArea(ctx, points, baseY, fillStyle) {
    if (!points.length) return;
    ctx.beginPath();
    ctx.moveTo(points[0].x, baseY);
    points.forEach((point) => ctx.lineTo(point.x, point.y));
    ctx.lineTo(points[points.length - 1].x, baseY);
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
  }

  function drawLineChart(canvas, payload) {
    if (!canvas || !payload || !payload.labels || !payload.labels.length) return;

    const { ctx, width, height } = setupCanvas(canvas);
    const labels = payload.labels;
    const income = payload.income || [];
    const expenses = payload.expenses || [];
    const net = payload.net || [];

    const padding = { top: 26, right: 20, bottom: 42, left: 58 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    const allValues = income.concat(expenses).concat(net);
    const maxVal = Math.max(...allValues, 0);
    const minVal = Math.min(...allValues, 0);
    const range = Math.max(1, maxVal - minVal);

    const x = (index) =>
      padding.left + (chartW * index) / Math.max(labels.length - 1, 1);
    const y = (value) => padding.top + ((maxVal - value) / range) * chartH;

    ctx.clearRect(0, 0, width, height);

    const gridSteps = 5;
    ctx.strokeStyle = "#d6dee8";
    ctx.lineWidth = 1;
    for (let i = 0; i <= gridSteps; i += 1) {
      const yPos = padding.top + (chartH * i) / gridSteps;
      ctx.beginPath();
      ctx.moveTo(padding.left, yPos);
      ctx.lineTo(width - padding.right, yPos);
      ctx.stroke();

      const value = maxVal - (range * i) / gridSteps;
      ctx.fillStyle = "#627285";
      ctx.font = "11px Manrope, sans-serif";
      ctx.fillText(moneyLabel(value), 6, yPos + 4);
    }

    const zeroY = y(0);
    ctx.strokeStyle = "#9eb0c4";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY);
    ctx.lineTo(width - padding.right, zeroY);
    ctx.stroke();

    const netPoints = net.map((value, index) => ({ x: x(index), y: y(value), value }));
    const incomePoints = income.map((value, index) => ({ x: x(index), y: y(value), value }));
    const expensePoints = expenses.map((value, index) => ({ x: x(index), y: y(value), value }));

    const netGradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
    netGradient.addColorStop(0, "rgba(34, 91, 150, 0.22)");
    netGradient.addColorStop(1, "rgba(34, 91, 150, 0.02)");
    drawArea(ctx, netPoints, zeroY, netGradient);

    drawLine(ctx, incomePoints, "#1f8f5f", 2.2);
    drawLine(ctx, expensePoints, "#cb3f49", 2.2);
    drawLine(ctx, netPoints, "#225b96", 2.6);

    [incomePoints, expensePoints, netPoints].forEach((series, seriesIndex) => {
      const color = ["#1f8f5f", "#cb3f49", "#225b96"][seriesIndex];
      series.forEach((point) => {
        ctx.beginPath();
        ctx.arc(point.x, point.y, 2.6, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
    });

    const step = Math.ceil(labels.length / 6);
    ctx.fillStyle = "#5b6776";
    ctx.font = "11px Manrope, sans-serif";
    labels.forEach((label, index) => {
      if (index % step !== 0 && index !== labels.length - 1) return;
      const px = x(index);
      ctx.fillText(label, px - 20, height - 10);
    });

    const legends = [
      { name: "Income", color: "#1f8f5f" },
      { name: "Expenses", color: "#cb3f49" },
      { name: "Net", color: "#225b96" },
    ];
    let legendX = padding.left;
    legends.forEach((item) => {
      ctx.fillStyle = item.color;
      ctx.fillRect(legendX, 5, 11, 11);
      ctx.fillStyle = "#334154";
      ctx.font = "12px Manrope, sans-serif";
      ctx.fillText(item.name, legendX + 15, 14);
      legendX += 88;
    });
  }

  function drawCategoryBars(canvas, payload) {
    if (!canvas || !payload || !payload.labels || !payload.labels.length) return;

    const { ctx, width, height } = setupCanvas(canvas);
    ctx.clearRect(0, 0, width, height);

    const labels = payload.labels;
    const values = payload.values || [];
    const maxVal = Math.max(...values, 1);

    const leftPad = Math.min(126, width * 0.36);
    const rightPad = 16;
    const topPad = 14;
    const rowGap = 12;
    const barHeight = Math.max(14, (height - topPad * 2 - rowGap * labels.length) / labels.length);

    labels.forEach((label, index) => {
      const value = values[index] || 0;
      const y = topPad + index * (barHeight + rowGap);
      const fullWidth = width - leftPad - rightPad;
      const barWidth = (fullWidth * value) / maxVal;

      ctx.fillStyle = "#ecf2f9";
      ctx.fillRect(leftPad, y, fullWidth, barHeight);

      const grad = ctx.createLinearGradient(leftPad, y, leftPad + barWidth, y);
      grad.addColorStop(0, "#225b96");
      grad.addColorStop(1, "#2f7dc8");
      ctx.fillStyle = grad;
      ctx.fillRect(leftPad, y, barWidth, barHeight);

      ctx.fillStyle = "#2f3f51";
      ctx.font = "12px Manrope, sans-serif";
      ctx.fillText(label.slice(0, 16), 8, y + barHeight * 0.72);

      ctx.fillStyle = "#5e6d7e";
      ctx.fillText(`$${value.toFixed(0)}`, leftPad + Math.min(barWidth + 6, fullWidth - 34), y + barHeight * 0.72);
    });
  }

  function boot() {
    const trendData = getJson("trend-data");
    const categoryData = getJson("category-data");
    const trendCanvas = document.getElementById("cashflow-chart");
    const categoryCanvas = document.getElementById("category-chart");

    const redraw = function () {
      if (trendCanvas) drawLineChart(trendCanvas, trendData);
      if (categoryCanvas) drawCategoryBars(categoryCanvas, categoryData);
    };

    redraw();

    let frame;
    window.addEventListener("resize", function () {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(redraw);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
