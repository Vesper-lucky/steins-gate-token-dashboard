import { api, state } from '/web/app.js';

export default async function (root) {
  const cur = await api('/api/plan');
  const plans = Object.entries(cur.pricing.plans);
  root.innerHTML = `
    <div class="card">
      <h2>设置</h2>
      <h3 style="margin-top:16px">计费方式</h3>
      <p class="muted" style="margin:0 0 12px">设置费用的展示方式。API 模式按 token 单价估算，订阅模式显示你的月费参考。</p>
      <div class="flex">
        <select id="plan">
          ${plans.map(([k,v]) => `<option value="${k}" ${k===cur.plan?'selected':''}>${v.label}${v.monthly?` - $${v.monthly}/月`:''}</option>`).join('')}
        </select>
        <button class="primary" id="save">保存</button>
        <span id="msg" class="muted"></span>
      </div>

      <hr class="divider">

      <h3>价格表</h3>
      <p class="muted" style="margin:0 0 12px">价格来自官方价格页。下表为当前价格；GPT-5.6 Terra/Luna 新价格自北京时间 2026-07-31 01:00 起生效，之前的记录按历史价格计算。修改 <code>pricing.json</code> 后刷新页面即可生效。</p>
      <table>
        <thead><tr><th>模型</th><th class="num">输入</th><th class="num">输出</th><th class="num">缓存读取</th><th class="num">缓存 5m</th><th class="num">缓存 1h</th></tr></thead>
        <tbody>
          ${Object.entries(cur.pricing.models).map(([k,v]) => `
            <tr><td><span class="badge ${v.tier}">${k}</span></td>
              <td class="num">$${v.input.toFixed(2)}</td>
              <td class="num">$${v.output.toFixed(2)}</td>
              <td class="num">$${v.cache_read.toFixed(2)}</td>
              <td class="num">$${v.cache_create_5m.toFixed(2)}</td>
              <td class="num">$${v.cache_create_1h.toFixed(2)}</td>
            </tr>`).join('')}
        </tbody>
      </table>
      <p class="muted" style="margin-top:8px;font-size:11px">单位：美元 / 100 万 tokens。</p>

      <hr class="divider">

      <h3>隐私</h3>
      <p class="muted">点击顶部隐私按钮，或在任意位置按 <code>Cmd/Ctrl + B</code>，可以模糊提示词、项目名、会话标识和建议内容；状态在当前标签页内保持。</p>
    </div>`;

  root.querySelector('#save').addEventListener('click', async () => {
    const plan = root.querySelector('#plan').value;
    await fetch('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan }) });
    state.plan = plan;
    document.getElementById('plan-pill').textContent = plan === 'api' ? 'API' : cur.pricing.plans[plan].label;
    root.querySelector('#msg').textContent = '已保存。';
    root.querySelector('#msg').style.color = 'var(--good)';
  });
}
