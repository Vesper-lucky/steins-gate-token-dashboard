import { api, fmt } from '/web/app.js';

const SORTS = [
  { key: 'tokens', label: 'Token 最多' },
  { key: 'recent', label: '最近' },
];

function readSort() {
  const q = (location.hash.split('?')[1] || '');
  const m = /(?:^|&)sort=([^&]+)/.exec(q);
  const k = m && decodeURIComponent(m[1]);
  return SORTS.find(s => s.key === k) || SORTS[0];
}

function writeSort(key) {
  const base = (location.hash.replace(/^#/, '').split('?')[0]) || '/prompts';
  location.hash = '#' + base + '?sort=' + encodeURIComponent(key);
}

export default async function (root) {
  const sort = readSort();
  const rows = await api('/api/prompts?limit=100&sort=' + encodeURIComponent(sort.key));

  const sortTabs = `
    <div class="range-tabs" role="tablist">
      ${SORTS.map(s => `<button data-sort="${s.key}" class="${s.key === sort.key ? 'active' : ''}">${s.label}</button>`).join('')}
    </div>`;

  const subtitle = sort.key === 'recent'
    ? '最近的提示词以及对应的模型回复轮次。点击一行查看详情。'
    : '按普通输入、缓存写入、缓存读取和输出的完整 token 总量排序。';

  root.innerHTML = `
    <div class="flex" style="margin-bottom:14px">
      <h2 style="margin:0;font-size:16px;letter-spacing:-0.01em">提示词</h2>
      <div class="spacer"></div>
      ${sortTabs}
    </div>

    <div class="card">
      <p class="muted" style="margin:0 0 14px">${subtitle}</p>
      <table id="prompts">
        <thead><tr>
          <th>${sort.key === 'recent' ? '时间' : '估算费用'}</th>
          <th>提示词</th>
          <th>模型</th>
          <th class="num">总 tokens</th>
          <th class="num">缓存读取</th>
          <th>会话</th>
        </tr></thead>
        <tbody>
          ${rows.map((r,i) => `
            <tr data-i="${i}" style="cursor:pointer">
              <td class="${sort.key === 'recent' ? 'mono' : 'num mono'}">${sort.key === 'recent' ? fmt.ts(r.timestamp) : fmt.usd4(r.estimated_cost_usd)}</td>
              <td class="blur-sensitive">${fmt.htmlSafe(fmt.short(r.prompt_text, 110))}</td>
              <td><span class="badge ${fmt.modelClass(r.model)}">${fmt.htmlSafe(fmt.modelShort(r.model))}</span></td>
              <td class="num">${fmt.int(r.billable_tokens)}</td>
              <td class="num">${fmt.int(r.cache_read_tokens)}</td>
              <td class="blur-sensitive"><a href="#/sessions/${encodeURIComponent(r.session_id)}" class="mono" onclick="event.stopPropagation()">${fmt.htmlSafe(r.session_id.slice(0,8))}…</a></td>
            </tr>`).join('') || '<tr><td colspan="6" class="muted">暂无提示词记录</td></tr>'}
        </tbody>
      </table>
    </div>
    <div id="drawer"></div>
  `;

  root.querySelectorAll('.range-tabs button').forEach(btn => {
    btn.addEventListener('click', () => writeSort(btn.dataset.sort));
  });

  root.querySelectorAll('#prompts tbody tr').forEach(tr => {
    tr.addEventListener('click', () => {
      const r = rows[Number(tr.dataset.i)];
      const drawer = root.querySelector('#drawer');
      drawer.innerHTML = `
        <div class="card">
          <h3 style="display:flex;align-items:center">
            <span>提示词详情</span>
            <span class="spacer"></span>
            <span class="badge ${fmt.modelClass(r.model)}">${fmt.htmlSafe(fmt.modelShort(r.model))}</span>
          </h3>
          <pre class="blur-sensitive">${fmt.htmlSafe(r.prompt_text || '')}</pre>
          <div class="flex" style="margin-top:12px;flex-wrap:wrap;gap:14px">
            <span class="muted">${fmt.ts(r.timestamp)}</span>
            <span class="muted">${fmt.int(r.billable_tokens)} 总 tokens · ${fmt.int(r.cache_read_tokens)} 缓存读取 · 约 ${fmt.usd4(r.estimated_cost_usd)}</span>
            <span class="spacer"></span>
            <a href="#/sessions/${encodeURIComponent(r.session_id)}">打开会话 →</a>
          </div>
        </div>`;
      drawer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  });
}
