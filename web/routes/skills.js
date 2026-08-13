import { api, fmt } from '/web/app.js';
import { barChart } from '/web/charts.js';
import { rangeBounds, rangeSummary, withRange } from './overview-helpers.js';

const RANGES = [
  { key: 'today', label: '今天', days: null },
  { key: '7d',  label: '7 天',  days: 7 },
  { key: '30d', label: '30 天', days: 30 },
  { key: '90d', label: '90 天', days: 90 },
  { key: 'all', label: '全部', days: null },
];
const DEFAULT_RANGE = RANGES.find(r => r.key === '30d');

function readRange() {
  const q = (location.hash.split('?')[1] || '');
  const m = /(?:^|&)range=([^&]+)/.exec(q);
  const k = m && decodeURIComponent(m[1]);
  return RANGES.find(r => r.key === k) || DEFAULT_RANGE;
}

function writeRange(key) {
  const base = (location.hash.replace(/^#/, '').split('?')[0]) || '/skills';
  location.hash = '#' + base + '?range=' + encodeURIComponent(key);
}

export default async function (root) {
  const range = readRange();
  const url = withRange('/api/skills', rangeBounds(range));
  const skills = await api(url);

  const totalInvocations = skills.reduce((s, r) => s + r.invocations, 0);
  const totalSessions = new Set(); // not exact — we'd need another query; skip.

  const rangeTabs = `
    <div class="range-tabs" role="tablist">
      ${RANGES.map(r => `<button data-range="${r.key}" class="${r.key === range.key ? 'active' : ''}">${r.label}</button>`).join('')}
    </div>`;

  root.innerHTML = `
    <div class="flex" style="margin-bottom:14px">
      <h2 style="margin:0;font-size:16px;letter-spacing:-0.01em">技能</h2>
      <span class="muted" style="font-size:12px">${rangeSummary(range)}</span>
      <div class="spacer"></div>
      ${rangeTabs}
    </div>

    <div class="row cols-2">
      <div class="card kpi"><div class="label">使用过的技能</div><div class="value">${fmt.int(skills.length)}</div></div>
      <div class="card kpi"><div class="label">调用总数</div><div class="value">${fmt.int(totalInvocations)}</div></div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>常用技能（按调用次数）</h3>
      <div id="ch-skills" style="height:320px"></div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>全部技能</h3>
      <p class="muted" style="margin:-4px 0 14px;font-size:12px">Codex 适配：读取 <code>SKILL.md</code> 的工具调用会识别为一次技能调用；“每次调用 tokens”按该文件大小估算，也就是技能被加载进上下文的内容量。</p>
      <table>
        <thead><tr>
          <th>技能</th>
          <th class="num">调用次数</th>
          <th class="num">估算定义 tokens</th>
          <th class="num">会话</th>
          <th>最近使用</th>
        </tr></thead>
        <tbody>
          ${skills.map(s => `
            <tr>
              <td><span class="badge">${fmt.htmlSafe(s.skill)}</span></td>
              <td class="num">${fmt.int(s.invocations)}</td>
              <td class="num">${s.tokens_per_call == null ? '<span class="muted">—</span>' : fmt.int(s.tokens_per_call)}</td>
              <td class="num">${fmt.int(s.sessions)}</td>
              <td class="mono">${fmt.ts(s.last_used)}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">这个时间范围内没有技能调用</td></tr>'}
        </tbody>
      </table>
    </div>
  `;

  root.querySelectorAll('.range-tabs button').forEach(btn => {
    btn.addEventListener('click', () => writeRange(btn.dataset.range));
  });

  const top = skills.slice(0, 12);
  barChart(root.querySelector('#ch-skills'), {
    categories: top.map(t => t.skill.length > 26 ? t.skill.slice(0, 25) + '…' : t.skill),
    values: top.map(t => t.invocations),
    color: '#3FB68B',
  });
}
