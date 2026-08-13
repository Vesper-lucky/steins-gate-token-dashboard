import { api, fmt, render, state } from '/web/app.js';
import { barChart, donutChart, groupedBarChart, lineChart, stackedBarChart } from '/web/charts.js';
import { disposeTokenDuoCounter, mountTokenDuoCounter, syncTokenDuoCounter } from '/web/token-duo-counter.js';
import { createTokenIdleRefresh } from '/web/token-idle-refresh.js';
import {
  cacheChartPlan,
  cacheTooltipRows,
  chartCopyForRange,
  costChartPlan,
  costTooltipRows,
  projectTooltipRows,
  rangeBounds,
  rangeSummary,
  usageChartPlan,
  usageEndpointForRange,
  visualTotalTokens,
  usageTooltipRows,
  withRange,
} from './overview-helpers.js';

const RANGES = [
  { key: 'today', label: '今天', days: null },
  { key: '7d',  label: '7 天',  days: 7 },
  { key: '30d', label: '30 天', days: 30 },
  { key: '90d', label: '90 天', days: 90 },
  { key: 'all', label: '全部', days: null },
];
const DEFAULT_RANGE = RANGES.find(r => r.key === '30d');
const chartModes = { usage: 'bar', cost: 'bar', cache: 'bar' };
const TOKEN_DUO_SYNC_INTERVAL_MS = 1000;
let overviewTokenRefreshPromise = null;
let overviewTokenRefreshQueued = false;
let overviewTokenRefreshNeedsScan = false;
let overviewTokenSyncTimer = null;
let overviewIdleRefresh = null;
let overviewActiveRoot = null;
let overviewLastIdleRefreshRangeKey = null;
let overviewLastIdleRefreshValue = null;
let overviewTokenDuoActualValue = null;
let overviewTokenDuoRangeKey = null;
const CHART_MODE_LABELS = [
  { key: 'bar', label: '柱状图' },
  { key: 'line', label: '折线图' },
];

function readRange() {
  const q = (location.hash.split('?')[1] || '');
  const m = /(?:^|&)range=([^&]+)/.exec(q);
  const k = m && decodeURIComponent(m[1]);
  return RANGES.find(r => r.key === k) || DEFAULT_RANGE;
}

function isOverviewRoute() {
  const hash = location.hash.replace(/^#/, '') || '/overview';
  return (hash.split('?')[0] || '/overview') === '/overview';
}

function writeRange(key) {
  const base = (location.hash.replace(/^#/, '').split('?')[0]) || '/overview';
  location.hash = '#' + base + '?range=' + encodeURIComponent(key);
}

export function handleStreamEvent(root, evt) {
  if (!evt || evt.type !== 'scan' || !isOverviewRoute()) return false;
  queueOverviewTokenRefresh(root);
  return true;
}

export function dispose(root) {
  if (root === overviewActiveRoot) stopOverviewTokenSync();
  disposeTokenDuoCounter(root);
}

function startOverviewTokenSync(root) {
  overviewActiveRoot = root;
  if (overviewTokenSyncTimer != null) clearInterval(overviewTokenSyncTimer);
  if (overviewIdleRefresh) overviewIdleRefresh.dispose();
  overviewIdleRefresh = createTokenIdleRefresh(() => {
    if (!isOverviewRoute()) return;
    overviewLastIdleRefreshRangeKey = overviewTokenDuoRangeKey;
    overviewLastIdleRefreshValue = overviewTokenDuoActualValue;
    render();
  });
  overviewTokenSyncTimer = setInterval(() => {
    if (isOverviewRoute()) queueOverviewTokenRefresh(root, { refresh: true });
  }, TOKEN_DUO_SYNC_INTERVAL_MS);
  queueOverviewTokenRefresh(root, { refresh: true });
}

function stopOverviewTokenSync() {
  if (overviewTokenSyncTimer != null) {
    clearInterval(overviewTokenSyncTimer);
    overviewTokenSyncTimer = null;
  }
  if (overviewIdleRefresh) {
    overviewIdleRefresh.dispose();
    overviewIdleRefresh = null;
  }
  overviewTokenRefreshQueued = false;
  overviewTokenRefreshNeedsScan = false;
  overviewTokenDuoActualValue = null;
  overviewTokenDuoRangeKey = null;
  overviewActiveRoot = null;
}

function queueOverviewTokenRefresh(root, opts = {}) {
  overviewTokenRefreshQueued = true;
  overviewTokenRefreshNeedsScan = overviewTokenRefreshNeedsScan || opts.refresh === true;
  if (overviewTokenRefreshPromise) return overviewTokenRefreshPromise;
  overviewTokenRefreshPromise = (async () => {
    try {
      while (overviewTokenRefreshQueued) {
        const shouldRefresh = overviewTokenRefreshNeedsScan;
        overviewTokenRefreshQueued = false;
        overviewTokenRefreshNeedsScan = false;
        try {
          await refreshOverviewTokenDuo(root, { refresh: shouldRefresh });
        } catch {}
      }
    } finally {
      overviewTokenRefreshPromise = null;
    }
  })();
  return overviewTokenRefreshPromise;
}

async function refreshOverviewTokenDuo(root, opts = {}) {
  if (!isOverviewRoute()) return;
  const range = readRange();
  const bounds = rangeBounds(range);
  const endpoint = opts.refresh ? '/api/token-duo?refresh=1' : '/api/token-duo';
  const totals = await api(withRange(endpoint, bounds));
  if (!isOverviewRoute()) return;
  if (readRange().key !== range.key) return;
  const actual = Number(totals.total_tokens) || 0;
  if (overviewTokenDuoRangeKey !== range.key) {
    overviewTokenDuoRangeKey = range.key;
    overviewTokenDuoActualValue = actual;
    if (
      overviewIdleRefresh &&
      (overviewLastIdleRefreshRangeKey !== range.key || actual > overviewLastIdleRefreshValue)
    ) {
      overviewIdleRefresh.observe(actual);
    }
  } else if (overviewTokenDuoActualValue == null) {
    overviewTokenDuoActualValue = actual;
    if (overviewIdleRefresh) overviewIdleRefresh.observe(actual);
  } else if (actual > overviewTokenDuoActualValue) {
    overviewTokenDuoActualValue = actual;
    if (overviewIdleRefresh) overviewIdleRefresh.observe(actual);
  } else if (actual < overviewTokenDuoActualValue) {
    overviewTokenDuoActualValue = actual;
    if (overviewIdleRefresh) overviewIdleRefresh.observe(actual);
  }
  syncTokenDuoCounter(root, actual, range.key);
}

function chartToggle(name, active) {
  return `
    <div class="range-tabs" role="tablist">
      ${CHART_MODE_LABELS.map(m => `
        <button data-chart="${name}" data-chart-mode="${m.key}" class="${m.key === active ? 'active' : ''}">${m.label}</button>
      `).join('')}
    </div>`;
}

function formatTooltipRows(rows) {
  return rows.map(r => ({
    label: r.label,
    value: r.kind === 'text'
      ? String(r.value ?? '')
      : (r.kind === 'usd4' ? fmt.usd4(r.value) : fmt.int(r.value)),
  }));
}

function periodTooltipRows(rows, buildRows) {
  return params => {
    const first = Array.isArray(params) ? params[0] : params;
    const row = rows[first?.dataIndex] || {};
    return formatTooltipRows(buildRows(row));
  };
}

export default async function (root) {
  const range = readRange();
  const bounds = rangeBounds(range);
  const ranged = url => withRange(url, bounds);
  const usageEndpoint = usageEndpointForRange(range, ranged('/api/daily'));

  const [totals, projects, sessions, tools, byModel, usageRows, skills, quality] = await Promise.all([
    api(ranged('/api/overview')),
    api(ranged('/api/projects')),
    api(ranged('/api/sessions?limit=10')),
    api(ranged('/api/tools')),
    api(ranged('/api/by-model')),
    api(usageEndpoint),
    api(ranged('/api/skills')),
    api('/api/data-quality'),
  ]);
  const chartCopy = chartCopyForRange(range);

  const cacheCreate =
    (totals.cache_create_5m_tokens || 0) +
    (totals.cache_create_1h_tokens || 0);
  const totalInput = totals.total_input_tokens ?? totals.input_tokens;
  const visualTokens = visualTotalTokens(totals);

  const kpi = (label, compactVal, fullVal, cls = '') => `
    <div class="card kpi ${cls}">
      <div class="label">${label}</div>
      <div class="value" title="${fullVal}">${compactVal}</div>
      </div>`;
  const rangeTabs = `
    <div class="range-tabs" role="tablist">
      ${RANGES.map(r => `<button data-range="${r.key}" class="${r.key === range.key ? 'active' : ''}">${r.label}</button>`).join('')}
    </div>`;

  root.innerHTML = `
    <div class="flex" style="margin-bottom:14px">
      <h2 style="margin:0;font-size:16px;letter-spacing:-0.01em">总览</h2>
      <span class="muted" style="font-size:12px">${rangeSummary(range)}</span>
      <div class="spacer"></div>
      ${rangeTabs}
    </div>

    ${(quality.warnings || []).length || (quality.errors || []).length ? `<div class="card" style="margin-bottom:14px;border-color:#B86A53"><strong>数据质量警告</strong><span class="muted" style="margin-left:10px">${[...(quality.errors || []), ...(quality.warnings || [])].map(fmt.htmlSafe).join('；')}</span></div>` : ''}

    <div class="row cols-7">
      ${kpi('会话数',       fmt.int(totals.sessions),            fmt.int(totals.sessions))}
      ${kpi('轮次',         fmt.int(totals.turns),               fmt.int(totals.turns))}
      ${kpi('总输入',       fmt.compact(totalInput),                 fmt.int(totalInput) + ' tokens')}
      ${kpi('输出',         fmt.compact(totals.output_tokens),      fmt.int(totals.output_tokens) + ' tokens')}
      ${kpi('缓存读取',     fmt.compact(totals.cache_read_tokens),  fmt.int(totals.cache_read_tokens) + ' tokens')}
      ${kpi('缓存写入',     fmt.compact(cacheCreate),               fmt.int(cacheCreate) + ' tokens')}
      <div class="card kpi cost">
        <div class="label">预估费用</div>
        <div class="value" title="${fmt.usd(totals.cost_usd)}">${fmt.usd(totals.cost_usd)}</div>
        ${planSubtitle()}
      </div>
    </div>

    <details class="card glossary" style="margin-top:16px">
      <summary><h3 style="display:inline-block;margin:0">这些数字是什么意思？</h3><span class="muted" style="font-size:12px">- 点击展开</span></summary>
      <dl>
        <dt>会话</dt><dd>按稳定线程关系去重后的 Codex/Claude Code 会话；续接日志和复制历史不会重复新增。</dd>
        <dt>轮次</dt><dd>按稳定消息 ID 去重的真实用户提问数。提示词正文默认不持久化。</dd>
        <dt>总输入 tokens</dt><dd>普通输入 + 缓存读取 + 缓存写入。新格式按三个原始桶拆分，旧格式沿用兼容口径。</dd>
        <dt>输出 tokens</dt><dd>模型生成的文本 token，通常是单价最高的部分。</dd>
        <dt>缓存读取</dt><dd>模型从缓存复用的输入 token，按官方缓存输入价格计费，通常比新输入便宜。</dd>
        <dt>缓存写入</dt><dd>写入缓存或未命中缓存的新输入 token。OpenAI 价格表没有单独的缓存写入费率时，这里按普通输入价格处理。</dd>
        <dt>总 tokens</dt><dd>新输入/缓存写入 + 缓存读取 + 输出。每日/今日用量图的堆叠合计与顶部总量使用同一口径。</dd>
      </dl>
    </details>

    <div class="row cols-2 metric-visual-row" style="margin-top:16px">
      ${tokenDuoVisualCard(visualTokens)}
    </div>

    <div class="row cols-2" style="margin-top:16px">
      <div class="card">
        <div class="flex" style="align-items:center;margin-bottom:4px">
          <h3 style="margin:0">${chartCopy.costTitle}</h3>
          <div class="spacer"></div>
          ${chartToggle('cost', chartModes.cost)}
        </div>
        <p class="muted" style="margin:-4px 0 10px;font-size:12px">${chartCopy.costSubtitle}</p>
        <div id="ch-daily-cost" style="height:260px"></div>
      </div>
      <div class="card">
        <div class="flex" style="align-items:center;margin-bottom:4px">
          <h3 style="margin:0">${chartCopy.usageTitle}</h3>
          <div class="spacer"></div>
          ${chartToggle('usage', chartModes.usage)}
        </div>
        <p class="muted" style="margin:-4px 0 10px;font-size:12px">${chartCopy.usageSubtitle}</p>
        <div id="ch-daily-billable" style="height:260px"></div>
      </div>
      <div class="card">
        <div class="flex" style="align-items:center;margin-bottom:4px">
          <h3 style="margin:0">${chartCopy.cacheTitle}</h3>
          <div class="spacer"></div>
          ${chartToggle('cache', chartModes.cache)}
        </div>
        <p class="muted" style="margin:-4px 0 10px;font-size:12px">${chartCopy.cacheSubtitle}</p>
        <div id="ch-daily-cache" style="height:260px"></div>
      </div>
      <div class="card">
        <h3>常用技能（按调用次数）</h3>
        <p class="muted" style="margin:-4px 0 10px;font-size:12px">沿用当前时间范围，显示加载次数最高的技能。</p>
        <div id="ch-overview-skills" style="height:260px"></div>
      </div>
    </div>

    <div class="row cols-2" style="margin-top:16px">
      <div class="card"><h3>按项目统计总 token</h3><div id="ch-projects" class="blur-sensitive" style="height:320px"></div></div>
      <div class="card">
        <h3>按模型统计 token</h3>
        <p class="muted" style="margin:-4px 0 4px;font-size:12px">各模型的计费 token 占比。</p>
        <div id="ch-model" style="height:300px"></div>
      </div>
    </div>

    <div class="row cols-2" style="margin-top:16px">
      <div class="card"><h3>常用工具（按调用次数）</h3><div id="ch-tools" style="height:320px"></div></div>
      <div class="card">
        <h3 style="display:flex;align-items:center"><span>最近会话</span><span class="spacer"></span><a href="#/sessions" style="font-weight:400;font-size:12px">全部 →</a></h3>
        <table>
          <thead><tr><th>开始时间</th><th>项目</th><th class="num">tokens</th></tr></thead>
          <tbody>
            ${sessions.map(s => `
              <tr>
                <td class="mono">${fmt.ts(s.started)}</td>
                <td class="blur-sensitive"><a href="#/sessions/${encodeURIComponent(s.session_id)}">${fmt.htmlSafe(s.project_name || s.project_slug)}</a></td>
                <td class="num">${fmt.compact(s.tokens)}</td>
              </tr>`).join('') || '<tr><td colspan="3" class="muted">这个时间范围内没有会话</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  overviewTokenDuoRangeKey = range.key;
  overviewTokenDuoActualValue = visualTokens;
  mountTokenDuoCounter(root, visualTokens, range.key);
  startOverviewTokenSync(root);

  // range buttons
  root.querySelectorAll('[data-range]').forEach(btn => {
    btn.addEventListener('click', () => writeRange(btn.dataset.range));
  });

  root.querySelectorAll('[data-chart]').forEach(btn => {
    btn.addEventListener('click', () => {
      chartModes[btn.dataset.chart] = btn.dataset.chartMode;
      renderUsageCharts();
    });
  });

  function drawPlan(el, plan, tooltipRows) {
    if (plan.kind === 'line') {
      lineChart(el, {
        x: plan.x,
        series: plan.series,
        tooltipExtraRows: tooltipRows,
        tooltipShowSeriesRows: false,
      });
      return;
    }
    stackedBarChart(el, {
      categories: plan.categories,
      series: plan.series,
      tooltipExtraRows: tooltipRows,
      tooltipShowSeriesRows: false,
    });
  }

  function renderUsageCharts() {
    root.querySelectorAll('[data-chart]').forEach(btn => {
      btn.classList.toggle('active', chartModes[btn.dataset.chart] === btn.dataset.chartMode);
    });
    drawPlan(
      root.querySelector('#ch-daily-billable'),
      usageChartPlan(range, usageRows, chartModes.usage),
      periodTooltipRows(usageRows, usageTooltipRows),
    );
    drawPlan(
      root.querySelector('#ch-daily-cost'),
      costChartPlan(range, usageRows, chartModes.cost),
      periodTooltipRows(usageRows, costTooltipRows),
    );
    drawPlan(
      root.querySelector('#ch-daily-cache'),
      cacheChartPlan(range, usageRows, chartModes.cache),
      periodTooltipRows(usageRows, cacheTooltipRows),
    );
  }

  renderUsageCharts();

  const topSkills = skills.slice(0, 8);
  barChart(root.querySelector('#ch-overview-skills'), {
    categories: topSkills.map(t => t.skill.length > 22 ? t.skill.slice(0, 21) + '…' : t.skill),
    values: topSkills.map(t => t.invocations),
    color: '#3FB68B',
  });

  // by-model doughnut
  donutChart(root.querySelector('#ch-model'),
    byModel.map(m => ({
      name: fmt.modelShort(m.model) || '未知模型',
      value: (m.input_tokens || 0) + (m.output_tokens || 0)
           + (m.cache_read_tokens || 0)
           + (m.cache_create_5m_tokens || 0) + (m.cache_create_1h_tokens || 0),
      cost_usd: m.cost_usd,
    })).filter(d => d.value > 0),
  );

  const projectNewInput = p => {
    const billable = p.billable_tokens || 0;
    const output = p.output_tokens || 0;
    const cacheRead = p.cache_read_tokens || 0;
    return Math.max(0, billable - output - cacheRead);
  };

  // Tokens by project, using the same all-bucket total as the overview counter.
  const topProjects = [...projects]
    .sort((a, b) => (b.total_tokens || 0) - (a.total_tokens || 0))
    .slice(0, 8);
  groupedBarChart(root.querySelector('#ch-projects'), {
    categories: topProjects.map(p => {
      const name = p.project_name || p.project_slug;
      return name.length > 20 ? name.slice(0, 19) + '…' : name;
    }),
    series: [
      { name: '输入', values: topProjects.map(projectNewInput),          color: '#E8A23B' },
      { name: '缓存读取',      values: topProjects.map(p => p.cache_read_tokens || 0), color: '#3FB68B' },
      { name: '输出',            values: topProjects.map(p => p.output_tokens || 0), color: '#7C5CFF' },
    ],
    tooltipExtraRows: periodTooltipRows(topProjects, projectTooltipRows),
    tooltipShowSeriesRows: false,
  });

  // top tools
  const topTools = tools.slice(0, 8);
  barChart(root.querySelector('#ch-tools'), {
    categories: topTools.map(t => t.tool_name),
    values: topTools.map(t => t.calls),
    color: '#7C5CFF',
  });

}

function tokenDuoVisualCard(totalTokens) {
  return `
    <section class="card token-duo-card" style="--digit-count:16" data-token-duo-slots="16" aria-label="${fmt.htmlSafe(fmt.int(totalTokens))} confirmed total tokens">
      <div class="token-duo-worldline" aria-hidden="true"></div>
      <img class="token-duo-character token-duo-character--kurisu" src="/web/assets/token-analysis-sources/reference-04.png" alt="" aria-hidden="true">
      <img class="token-duo-character token-duo-character--okabe" src="/web/assets/token-analysis-sources/reference-08-cutout.png" alt="" aria-hidden="true">
      <div class="token-duo-center-shadow" aria-hidden="true"></div>
      <div class="token-duo-counter" style="--counter-scale:1" title="${fmt.htmlSafe(fmt.int(totalTokens))} confirmed total tokens" aria-label="${fmt.htmlSafe(fmt.int(totalTokens))} confirmed total tokens"></div>
    </section>`;
}

function planSubtitle() {
  if (!state.pricing || state.plan === 'api') return '';
  const p = state.pricing.plans[state.plan];
  if (!p || !p.monthly) return '';
  return `<div class="sub">${fmt.htmlSafe(p.label)}：$${p.monthly}/月</div>`;
}
