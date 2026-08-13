// charts.js — themed ECharts wrappers

const PALETTE = ['#4A9EFF', '#7C5CFF', '#3FB68B', '#E8A23B', '#E5484D', '#5BCEDA', '#F472B6'];

const BASE = {
  textStyle: { color: '#E6EDF3', fontFamily: 'Inter' },
  color: PALETTE,
  grid: { left: 36, right: 12, top: 24, bottom: 24, containLabel: true },
};

const X_AXIS = {
  axisLine:  { lineStyle: { color: '#1F2630' } },
  axisLabel: { color: '#8B98A6' },
  axisTick:  { show: false },
};

const Y_AXIS = {
  axisLine:  { show: false },
  axisTick:  { show: false },
  splitLine: { lineStyle: { color: '#1F2630' } },
  axisLabel: { color: '#8B98A6' },
};

const TOOLTIP = {
  trigger: 'axis',
  backgroundColor: '#0F1419',
  borderColor: '#283040',
  borderWidth: 1,
  textStyle: { color: '#E6EDF3', fontFamily: 'Inter', fontSize: 12 },
  padding: [8, 12],
};

const resizeHandlers = new WeakMap();

function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function axisTooltip(extraRows, valueFormatter = v => Number(v).toLocaleString(), opts = {}) {
  return params => {
    const rows = Array.isArray(params) ? params : [params];
    const title = escapeHtml(rows[0]?.axisValueLabel ?? rows[0]?.axisValue ?? rows[0]?.name ?? '');
    const showSeriesRows = opts.showSeriesRows !== false;
    const seriesRows = showSeriesRows ? rows.map(p => `
      <div style="display:flex;align-items:center;gap:8px;min-width:140px">
        <span>${p.marker || ''}${escapeHtml(p.seriesName)}</span>
        <span style="flex:1"></span>
        <b>${escapeHtml(valueFormatter(p.value))}</b>
      </div>`).join('') : '';
    const extras = typeof extraRows === 'function' ? extraRows(rows) : (extraRows || []);
    const extraHtml = extras.length ? `
      <div style="height:1px;background:#283040;margin:6px 0"></div>
      ${extras.map(r => `
        <div style="display:flex;align-items:center;gap:8px;min-width:140px">
          <span>${escapeHtml(r.label)}</span>
          <span style="flex:1"></span>
          <b>${escapeHtml(r.value)}</b>
        </div>`).join('')}` : '';
    return `<div><b>${title}</b>${seriesRows}${extraHtml}</div>`;
  };
}

function mount(el) {
  const existing = echarts.getInstanceByDom(el);
  if (existing) {
    const oldResize = resizeHandlers.get(el);
    if (oldResize) window.removeEventListener('resize', oldResize);
    existing.dispose();
  }
  const c = echarts.init(el, null, { renderer: 'svg' });
  const resize = () => c.resize();
  resizeHandlers.set(el, resize);
  window.addEventListener('resize', resize);
  return c;
}

export function disposeChart(el) {
  if (!el) return;
  const instance = echarts.getInstanceByDom(el);
  const resize = resizeHandlers.get(el);
  if (resize) window.removeEventListener('resize', resize);
  resizeHandlers.delete(el);
  if (instance) instance.dispose();
}

export function disposeCharts(root) {
  if (!root) return;
  disposeChart(root);
  root.querySelectorAll('*').forEach(disposeChart);
}

export function lineChart(el, { x, series, tooltipExtraRows, tooltipShowSeriesRows, formatter }) {
  const c = mount(el);
  c.setOption({
    ...BASE,
    tooltip: { ...TOOLTIP, formatter: axisTooltip(tooltipExtraRows, formatter, { showSeriesRows: tooltipShowSeriesRows }) },
    legend: { textStyle: { color: '#8B98A6' }, top: 0, right: 0, icon: 'roundRect', itemWidth: 8, itemHeight: 8 },
    xAxis: { ...X_AXIS, type: 'category', data: x, boundaryGap: false },
    yAxis: { ...Y_AXIS, type: 'value' },
    series: series.map(s => ({
      ...s, type: 'line', smooth: true, showSymbol: false,
      areaStyle: { opacity: 0.12 }, lineStyle: { width: 2 },
    })),
  });
  return c;
}

export function barChart(el, { categories, values, color }) {
  const c = mount(el);
  c.setOption({
    ...BASE,
    tooltip: { ...TOOLTIP, axisPointer: { type: 'shadow' } },
    xAxis: { ...X_AXIS, type: 'category', data: categories, axisLabel: { ...X_AXIS.axisLabel, interval: 0, rotate: categories.length > 5 ? 25 : 0 } },
    yAxis: { ...Y_AXIS, type: 'value' },
    series: [{
      type: 'bar', data: values,
      itemStyle: { color: color || PALETTE[0], borderRadius: [4, 4, 0, 0] },
      barMaxWidth: 32,
    }],
  });
  return c;
}

export function stackedBarChart(el, { categories, series, formatter, tooltipExtraRows, tooltipShowSeriesRows }) {
  const c = mount(el);
  c.setOption({
    ...BASE,
    tooltip: {
      ...TOOLTIP,
      axisPointer: { type: 'shadow' },
      valueFormatter: formatter || (v => Number(v).toLocaleString()),
      formatter: axisTooltip(tooltipExtraRows, formatter || (v => Number(v).toLocaleString()), { showSeriesRows: tooltipShowSeriesRows }),
    },
    legend: {
      textStyle: { color: '#8B98A6' },
      top: 0, right: 0, icon: 'roundRect',
      itemWidth: 8, itemHeight: 8,
    },
    xAxis: {
      ...X_AXIS, type: 'category', data: categories,
      axisLabel: { ...X_AXIS.axisLabel, interval: categories.length > 20 ? 'auto' : 0, rotate: categories.length > 12 ? 45 : 0 },
    },
    yAxis: { ...Y_AXIS, type: 'value' },
    series: series.map((s, i) => ({
      name: s.name,
      type: 'bar',
      stack: 'total',
      data: s.values,
      itemStyle: { color: s.color || PALETTE[i % PALETTE.length] },
      barMaxWidth: 24,
      emphasis: { focus: 'series' },
    })),
  });
  return c;
}

export function groupedBarChart(el, { categories, series, formatter, tooltipExtraRows, tooltipShowSeriesRows }) {
  const c = mount(el);
  c.setOption({
    ...BASE,
    tooltip: {
      ...TOOLTIP,
      axisPointer: { type: 'shadow' },
      valueFormatter: formatter || (v => Number(v).toLocaleString()),
      formatter: axisTooltip(tooltipExtraRows, formatter || (v => Number(v).toLocaleString()), { showSeriesRows: tooltipShowSeriesRows }),
    },
    legend: {
      textStyle: { color: '#8B98A6' },
      top: 0, right: 0, icon: 'roundRect',
      itemWidth: 8, itemHeight: 8,
    },
    xAxis: {
      ...X_AXIS, type: 'category', data: categories,
      axisLabel: { ...X_AXIS.axisLabel, interval: 0, rotate: categories.length > 5 ? 25 : 0 },
    },
    yAxis: { ...Y_AXIS, type: 'value' },
    series: series.map((s, i) => ({
      name: s.name,
      type: 'bar',
      data: s.values,
      itemStyle: { color: s.color || PALETTE[i % PALETTE.length], borderRadius: [4, 4, 0, 0] },
      barMaxWidth: 24,
      emphasis: { focus: 'series' },
    })),
  });
  return c;
}

export function donutTooltip(params) {
  const rawCost = params.data?.cost_usd;
  const cost = Number(rawCost);
  const costText = rawCost != null && Number.isFinite(cost) ? `$${cost.toFixed(4)}` : '未计价';
  return `${escapeHtml(params.name)}<br/><b>${Number(params.value).toLocaleString()}</b> tokens（${params.percent.toFixed(1)}%）<br/>总金额 <b>${costText}</b>`;
}

export function donutChart(el, data) {
  const c = mount(el);
  c.setOption({
    color: PALETTE,
    tooltip: {
      trigger: 'item',
      backgroundColor: '#0F1419', borderColor: '#283040', borderWidth: 1,
      textStyle: { color: '#E6EDF3', fontFamily: 'Inter' },
      formatter: donutTooltip,
    },
    legend: {
      textStyle: { color: '#8B98A6' },
      bottom: 10, icon: 'roundRect', itemWidth: 8, itemHeight: 8,
      type: 'scroll',
    },
    series: [{
      type: 'pie',
      center: ['50%', '44%'],
      radius: ['48%', '68%'],
      avoidLabelOverlap: true,
      padAngle: 2,
      itemStyle: { borderColor: '#0F1419', borderWidth: 2, borderRadius: 4 },
      label: {
        show: true,
        position: 'inside',
        color: '#fff',
        fontSize: 12,
        fontWeight: 600,
        formatter: ({ percent }) => percent >= 6 ? percent.toFixed(0) + '%' : '',
      },
      labelLine: { show: false },
      data,
    }],
  });
  return c;
}
