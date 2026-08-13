import { api, fmt } from '/web/app.js';

export default async function (root) {
  const tips = await api('/api/tips');
  root.innerHTML = `
    <div class="card">
      <h2>建议</h2>
      ${tips.length === 0
        ? '<p class="muted">当前没有建议。Codex 工具调用、技能加载和 token 用量积累更多后再查看。</p>'
        : `<p class="muted" style="margin:-8px 0 14px">基于最近 7 天 Codex/Claude 活动的规则检测。已忽略的建议会在 14 天后重新出现。</p>`}
      ${tips.map(t => `
        <div class="tip">
          <div class="tip-head">
            <span class="badge">${fmt.htmlSafe(t.category)}</span>
            <strong class="blur-sensitive">${fmt.htmlSafe(t.title)}</strong>
            <span class="spacer"></span>
            <button class="ghost" data-key="${fmt.htmlSafe(t.key)}">忽略</button>
          </div>
          <p class="tip-body blur-sensitive">${fmt.htmlSafe(t.body)}</p>
        </div>`).join('')}
    </div>`;
  root.querySelectorAll('button[data-key]').forEach(b => {
    b.addEventListener('click', async () => {
      await fetch('/api/tips/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: b.dataset.key }),
      });
      location.reload();
    });
  });
}
