const DAY_MS = 86400 * 1000;
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const CHART_COLORS = {
  usageInput: '#E8A23B',
  usageOutput: '#7C5CFF',
  usageTotal: '#4A9EFF',
  cacheRead: '#3FB68B',
  costOutputDeep: '#A86F18',
  costInputMid: '#C98A24',
  costOutputTop: '#F2C94C',
  costLine: '#D9A441',
};

export function isTodayRange(range) {
  return range && range.key === 'today';
}

export function rangeBounds(range, now = new Date()) {
  if (isTodayRange(range)) {
    const shifted = new Date(now.getTime() + BEIJING_OFFSET_MS);
    const startUtcMs = Date.UTC(
      shifted.getUTCFullYear(),
      shifted.getUTCMonth(),
      shifted.getUTCDate(),
    ) - BEIJING_OFFSET_MS;
    return {
      since: new Date(startUtcMs).toISOString(),
      until: new Date(startUtcMs + DAY_MS).toISOString(),
    };
  }
  if (range && range.days) {
    return {
      since: new Date(now.getTime() - range.days * DAY_MS).toISOString(),
      until: null,
    };
  }
  return { since: null, until: null };
}

export function withRange(url, bounds) {
  const parts = [];
  if (bounds && bounds.since) parts.push('since=' + encodeURIComponent(bounds.since));
  if (bounds && bounds.until) parts.push('until=' + encodeURIComponent(bounds.until));
  if (!parts.length) return url;
  return url + (url.includes('?') ? '&' : '?') + parts.join('&');
}

export function usageEndpointForRange(range, dailyEndpoint) {
  return isTodayRange(range) ? '/api/today-hourly' : dailyEndpoint;
}

export function chartCopyForRange(range) {
  if (isTodayRange(range)) {
    return {
      usageTitle: '今日用量',
      usageSubtitle: '北京时间今日 00:00-24:00，按小时展示新输入/缓存写入、缓存读取和输出。',
      costTitle: '今日总金额',
      costSubtitle: '北京时间今日 00:00-24:00，按小时展示预估总金额。',
      cacheTitle: '今日缓存读取',
      cacheSubtitle: '北京时间今日 00:00-24:00，按小时展示模型复用已缓存上下文的 token。',
    };
  }
  return {
    usageTitle: '每日用量',
    usageSubtitle: '按北京时间自然日展示新输入/缓存写入、缓存读取和输出。',
    costTitle: '每日总金额',
    costSubtitle: '按天展示输出、输入（含缓存写入）和缓存读取的预估总金额。',
    cacheTitle: '每日缓存读取',
    cacheSubtitle: '<b>缓存读取</b>是模型复用已缓存上下文的 token，按官方缓存输入价格计算。',
  };
}

export function rangeSummary(range) {
  if (isTodayRange(range)) return '北京时间今天';
  if (range && range.days) return `最近 ${range.days} 天`;
  return '全部时间';
}

function rowInputTokens(row) {
  return (row.input_tokens || 0) + (row.cache_create_tokens || 0);
}

function rowUsageTokens(row) {
  return row.usage_tokens ?? (
    rowInputTokens(row)
    + (row.cache_read_tokens || 0)
    + (row.output_tokens || 0)
  );
}

function projectInputTokens(row) {
  return Math.max(0, (row.billable_tokens || 0) - (row.output_tokens || 0));
}

function projectTotalTokens(row) {
  return row.total_tokens ?? ((row.billable_tokens || 0) + (row.cache_read_tokens || 0));
}

function rowTotalCost(row) {
  return Number((
    rowInputCost(row)
    + rowOutputCost(row)
    + rowCacheReadCost(row)
  ).toFixed(6));
}

function rowInputCost(row) {
  const hasInputCost = row.input_cost_usd != null;
  const hasCacheCreateCost = row.cache_create_cost_usd != null;
  if (hasInputCost || hasCacheCreateCost) {
    return (row.input_cost_usd || 0) + (row.cache_create_cost_usd || 0);
  }
  return Math.max(0, (row.usage_cost_usd || 0) - rowOutputCost(row));
}

function rowOutputCost(row) {
  return row.output_cost_usd || 0;
}

function rowCacheReadCost(row) {
  return row.cache_read_cost_usd || 0;
}

function modelDisplayName(model) {
  return String(model || 'unknown').replace(/[-_]+/g, ' ');
}

function formatIntText(value) {
  return Math.round(Number(value) || 0).toLocaleString();
}

function formatUsd4Text(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(4)}` : '未计价';
}

function modelRows(row) {
  return Array.isArray(row?.models) ? row.models : [];
}

function appendModelRows(rows, detailRows) {
  if (!detailRows.length) return rows;
  return [
    ...rows,
    { label: '按模型', value: '', kind: 'text' },
    ...detailRows,
  ];
}

export function visualTotalTokens(totals, fallback = 428765312) {
  const hasTotalInput = Number.isFinite(totals?.total_input_tokens);
  const hasInput = Number.isFinite(totals?.input_tokens);
  const hasOutput = Number.isFinite(totals?.output_tokens);
  if (!hasTotalInput && !hasInput && !hasOutput) return fallback;
  const input = hasTotalInput
    ? totals.total_input_tokens
    : (hasInput ? totals.input_tokens : 0);
  return input + (hasOutput ? totals.output_tokens : 0);
}

function axisLabels(range, rows) {
  return isTodayRange(range) ? rows.map(d => d.hour) : rows.map(d => d.day);
}

export function usageTooltipRows(row) {
  const rows = [
    { label: '新输入/缓存写入', value: rowInputTokens(row), kind: 'int' },
    { label: '缓存读取', value: row.cache_read_tokens || 0, kind: 'int' },
    { label: '输出', value: row.output_tokens || 0, kind: 'int' },
    { label: '合计 tokens', value: rowUsageTokens(row), kind: 'int' },
    { label: '金额预估', value: row.usage_cost_usd, kind: 'usd4' },
  ];
  return appendModelRows(rows, modelRows(row).map(m => ({
    label: modelDisplayName(m.model),
    value: [
      `输入 ${formatIntText(rowInputTokens(m))}`,
      `输出 ${formatIntText(m.output_tokens || 0)}`,
      `缓存读取 ${formatIntText(m.cache_read_tokens || 0)}`,
      `合计 ${formatIntText(m.total_tokens || 0)}`,
    ].join(' · '),
    kind: 'text',
  })));
}

export function cacheTooltipRows(row) {
  const rows = [
    { label: '缓存读取', value: row.cache_read_tokens || 0, kind: 'int' },
    { label: '金额预估', value: row.cache_read_cost_usd, kind: 'usd4' },
  ];
  return appendModelRows(rows, modelRows(row).map(m => ({
    label: modelDisplayName(m.model),
    value: `缓存读取 ${formatIntText(m.cache_read_tokens || 0)}`,
    kind: 'text',
  })));
}

export function costTooltipRows(row) {
  const rows = [
    { label: '输入金额', value: rowInputCost(row), kind: 'usd4' },
    { label: '缓存读取金额', value: rowCacheReadCost(row), kind: 'usd4' },
    { label: '输出金额', value: rowOutputCost(row), kind: 'usd4' },
    { label: '总金额', value: rowTotalCost(row), kind: 'usd4' },
  ];
  return appendModelRows(rows, modelRows(row).map(m => ({
    label: modelDisplayName(m.model),
    value: formatUsd4Text(m.cost_usd),
    kind: 'text',
  })));
}

export function projectTooltipRows(row) {
  return [
    { label: '输入', value: projectInputTokens(row), kind: 'int' },
    { label: '输出', value: row.output_tokens || 0, kind: 'int' },
    { label: '缓存读取', value: row.cache_read_tokens || 0, kind: 'int' },
    { label: '总 tokens', value: projectTotalTokens(row), kind: 'int' },
    { label: '金额预估', value: row.cost_usd, kind: 'usd4' },
  ];
}

export function usageChartPlan(range, rows, chartType = 'bar') {
  const labels = axisLabels(range, rows);
  if (chartType === 'line') {
    return {
      kind: 'line',
      x: labels,
      series: [
        { name: '合计 tokens', data: rows.map(rowUsageTokens), color: CHART_COLORS.usageTotal },
      ],
    };
  }
  return {
    kind: 'stackedBar',
    categories: labels,
    series: [
      { name: '新输入/缓存写入', values: rows.map(rowInputTokens), color: CHART_COLORS.usageInput },
      { name: '缓存读取', values: rows.map(d => d.cache_read_tokens || 0), color: CHART_COLORS.cacheRead },
      { name: '输出', values: rows.map(d => d.output_tokens || 0), color: CHART_COLORS.usageOutput },
    ],
  };
}

export function cacheChartPlan(range, rows, chartType = 'bar') {
  const labels = axisLabels(range, rows);
  if (chartType === 'line') {
    return {
      kind: 'line',
      x: labels,
      series: [
        { name: '缓存读取', data: rows.map(d => d.cache_read_tokens || 0), color: CHART_COLORS.cacheRead },
      ],
    };
  }
  return {
    kind: 'stackedBar',
    categories: labels,
    series: [
      { name: '缓存读取', values: rows.map(d => d.cache_read_tokens || 0), color: CHART_COLORS.cacheRead },
    ],
  };
}

export function costChartPlan(range, rows, chartType = 'bar') {
  const labels = axisLabels(range, rows);
  const values = rows.map(rowTotalCost);
  if (chartType === 'line') {
    return {
      kind: 'line',
      x: labels,
      series: [
        { name: '总金额', data: values, color: CHART_COLORS.costLine },
      ],
    };
  }
  return {
    kind: 'stackedBar',
    categories: labels,
    series: [
      { name: '输入金额', values: rows.map(rowInputCost), color: CHART_COLORS.costOutputDeep },
      { name: '缓存读取金额', values: rows.map(rowCacheReadCost), color: CHART_COLORS.costInputMid },
      { name: '输出金额', values: rows.map(rowOutputCost), color: CHART_COLORS.costOutputTop },
    ],
  };
}
