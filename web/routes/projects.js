import { api, fmt } from '/web/app.js';

export default async function (root) {
  const rows = await api('/api/projects');
  root.innerHTML = `
    <div class="card">
      <h2>项目</h2>
      <p class="muted" style="margin:-8px 0 14px">按普通输入、缓存写入、缓存读取和输出的完整 token 总量排序。</p>
      <table>
        <thead><tr><th>项目</th><th class="num">会话</th><th class="num">轮次</th><th class="num">输入/输出 tokens</th><th class="num">缓存读取</th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td class="blur-sensitive" title="${fmt.htmlSafe(r.project_slug)}">${fmt.htmlSafe(r.project_name || r.project_slug)}</td>
              <td class="num">${fmt.int(r.sessions)}</td>
              <td class="num">${fmt.int(r.turns)}</td>
              <td class="num">${fmt.int(r.billable_tokens)}</td>
              <td class="num">${fmt.int(r.cache_read_tokens)}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
