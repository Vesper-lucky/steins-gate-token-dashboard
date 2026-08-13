import { api, fmt } from '/web/app.js';

export default async function (root) {
  const id = decodeURIComponent(location.hash.split('/')[2] || '');
  if (!id) return renderList(root);
  return renderSession(root, id);
}

async function renderList(root) {
  const list = await api('/api/sessions?limit=100');
  root.innerHTML = `
    <div class="card">
      <h2>会话</h2>
      <table>
        <thead><tr><th>开始时间</th><th>项目</th><th class="num">轮次</th><th class="num">tokens</th><th>会话</th></tr></thead>
        <tbody>
          ${list.map(s => `
            <tr>
              <td class="mono">${fmt.ts(s.started)}</td>
              <td class="blur-sensitive" title="${fmt.htmlSafe(s.project_slug)}">${fmt.htmlSafe(s.project_name || s.project_slug)}</td>
              <td class="num">${fmt.int(s.turns)}</td>
              <td class="num">${fmt.int(s.tokens)}</td>
              <td class="blur-sensitive"><a href="#/sessions/${encodeURIComponent(s.session_id)}" class="mono">${fmt.htmlSafe(s.session_id.slice(0,8))}…</a></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

async function renderSession(root, id) {
  const turns = await api('/api/sessions/' + encodeURIComponent(id));
  let totalIn = 0, totalOut = 0, totalCacheRd = 0, totalCacheCreate = 0;
  let modelCounts = {};
  for (const t of turns) {
    if (t.type !== 'assistant') continue;
    totalIn += t.input_tokens || 0;
    totalOut += t.output_tokens || 0;
    totalCacheRd += t.cache_read_tokens || 0;
    totalCacheCreate += (t.cache_create_5m_tokens || 0) + (t.cache_create_1h_tokens || 0);
    const m = t.model || 'unknown';
    modelCounts[m] = (modelCounts[m] || 0) + 1;
  }
  const slug = (turns[0] && turns[0].project_slug) || '';
  const cwd = (turns.find(t => t.cwd) || {}).cwd || '';
  const base = cwd ? cwd.replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop() : '';
  const project = base || slug;
  const started = (turns[0] && turns[0].timestamp) || '';
  const ended = (turns[turns.length-1] && turns[turns.length-1].timestamp) || '';

  root.innerHTML = `
    <div class="card">
      <h2 style="display:flex;align-items:center">
        <span class="blur-sensitive">会话 ${fmt.htmlSafe(id.slice(0,8))}...</span>
        <span class="spacer"></span>
        <a href="#/sessions" class="muted">← 全部会话</a>
      </h2>
      <div class="flex muted" style="font-family:var(--mono);font-size:12px;flex-wrap:wrap;gap:14px">
        <span class="blur-sensitive">${fmt.htmlSafe(project)}</span>
        <span>${fmt.ts(started)} → ${fmt.ts(ended)}</span>
        <span>${turns.length} 条记录</span>
        <span>${fmt.int(totalIn)} 普通输入 · ${fmt.int(totalCacheCreate)} 缓存写入 · ${fmt.int(totalCacheRd)} 缓存读取 · ${fmt.int(totalOut)} 输出</span>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>逐轮明细</h3>
      <table>
        <thead><tr><th>时间</th><th>类型</th><th>模型</th><th class="blur-sensitive">提示词 / 工具</th><th class="num">普通输入</th><th class="num">缓存写入</th><th class="num">缓存读取</th><th class="num">输出</th></tr></thead>
        <tbody>
          ${turns.map(t => {
            const tools = t.tool_calls_json ? JSON.parse(t.tool_calls_json) : [];
            const summary = t.prompt_text ? fmt.short(t.prompt_text, 110)
              : tools.length ? tools.map(x => x.name).join(' · ')
              : '';
            return `<tr>
              <td class="mono">${(t.timestamp || '').slice(11,19)}</td>
              <td>${t.type}${t.is_sidechain ? ' <span class="badge">旁路</span>' : ''}</td>
              <td>${t.model ? `<span class="badge ${fmt.modelClass(t.model)}">${fmt.htmlSafe(fmt.modelShort(t.model))}</span>` : ''}</td>
              <td class="blur-sensitive">${fmt.htmlSafe(summary)}</td>
              <td class="num">${fmt.int(t.input_tokens)}</td>
              <td class="num">${fmt.int((t.cache_create_5m_tokens || 0) + (t.cache_create_1h_tokens || 0))}</td>
              <td class="num">${fmt.int(t.cache_read_tokens)}</td>
              <td class="num">${fmt.int(t.output_tokens)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}
