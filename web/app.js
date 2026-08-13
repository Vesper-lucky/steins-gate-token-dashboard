// app.js — router, state, fetch helpers
import { installPrivacyMode } from '/web/privacy.js';
import { disposeCharts } from '/web/charts.js';

export const $  = (sel, root=document) => root.querySelector(sel);
export const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

const COMPACT = new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 });
export const fmt = {
  int:   n => (n ?? 0).toLocaleString(),
  compact: n => COMPACT.format(n ?? 0),
  usd:   n => n == null ? '—' : '$' + Number(n).toFixed(2),
  usd4:  n => n == null ? '—' : '$' + Number(n).toFixed(4),
  pct:   n => n == null ? '—' : (n * 100).toFixed(0) + '%',
  short: (s, n=80) => s == null ? '' : (s.length > n ? s.slice(0, n - 1) + '…' : s),
  htmlSafe: s => (s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  modelClass: m => {
    const s = (m || '').toLowerCase();
    if (s.includes('opus'))   return 'opus';
    if (s.includes('sonnet')) return 'sonnet';
    if (s.includes('haiku'))  return 'haiku';
    if (s.includes('deepseek')) return 'deepseek';
    if (s.includes('gpt'))    return 'gpt';
    return '';
  },
  modelShort: m => (m || '').replace('claude-', '').replace('deepseek-', 'deepseek '),
  ts: t => (t || '').slice(0, 16).replace('T', ' '),
};

export async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const state = { plan: 'api', pricing: null };

function planName(plan) {
  const meta = state.pricing && state.pricing.plans && state.pricing.plans[plan];
  if (plan === 'api') return 'API';
  return (meta && meta.label) || plan;
}

const ROUTES = {
  '/overview': () => import('/web/routes/overview.js'),
  '/prompts':  () => import('/web/routes/prompts.js'),
  '/sessions': () => import('/web/routes/sessions.js'),
  '/projects': () => import('/web/routes/projects.js'),
  '/skills':   () => import('/web/routes/skills.js'),
  '/tips':     () => import('/web/routes/tips.js'),
  '/settings': () => import('/web/routes/settings.js'),
};

function buildTopbar() {
  const wrap = document.createElement('header');
  wrap.className = 'topbar';
  wrap.innerHTML = `
    <div class="brand">Divergence Ledger <span class="muted">世界线 Token 记录仪</span></div>
    <nav>
      ${Object.keys(ROUTES).map(p => `<a href="#${p}" data-route="${p}">${routeLabel(p)}</a>`).join('')}
    </nav>
    <span class="route-status" aria-live="polite" aria-atomic="true"></span>
    <div class="spacer"></div>
    <span class="pill" id="plan-pill">API</span>
    <button class="pill privacy-toggle" id="privacy-toggle" type="button"
      aria-pressed="false" aria-keyshortcuts="Control+B Meta+B"
      title="模糊敏感文本，方便截图">Cmd/Ctrl+B 模糊</button>
  `;
  document.body.prepend(wrap);
}

let pendingRouteKey = null;

function routeKeyForLocation() {
  const path = (location.hash.replace(/^#/, '') || '/overview').split('?')[0];
  if (path.startsWith('/sessions/')) return '/sessions';
  return ROUTES[path] ? path : '/overview';
}

function setActiveTab(routeKey) {
  $$('header.topbar nav a').forEach(a => {
    const active = a.dataset.route === routeKey;
    a.classList.toggle('active', active);
    a.setAttribute('aria-current', active ? 'page' : 'false');
  });
}

function setPendingTab(routeKey) {
  pendingRouteKey = routeKey;
  $$('header.topbar nav a').forEach(a => {
    const pending = a.dataset.route === routeKey;
    a.classList.toggle('pending', pending);
    a.setAttribute('aria-busy', pending ? 'true' : 'false');
  });
  const status = $('.route-status');
  if (status) status.textContent = `正在加载${routeLabel(routeKey)}…`;
}

function settlePendingTab(routeKey, success) {
  if (pendingRouteKey !== routeKey) return;
  pendingRouteKey = null;
  $$('header.topbar nav a').forEach(a => {
    a.classList.remove('pending');
    a.setAttribute('aria-busy', 'false');
  });
  const status = $('.route-status');
  if (status) status.textContent = success ? '' : '切换失败，已保留当前板块';
  if (success) setActiveTab(routeKey);
}

let renderPromise = null;
let renderQueued = false;
let renderGeneration = 0;
let currentRouteModule = null;
let currentRouteRoot = null;

function disposeCurrentRoute() {
  const mod = currentRouteModule;
  const root = currentRouteRoot || $('#app');
  currentRouteModule = null;
  currentRouteRoot = null;
  if (mod && typeof mod.dispose === 'function') {
    try {
      mod.dispose(root);
    } catch {}
  }
  disposeCharts(root);
}

function createRouteStage(app) {
  const stage = app.cloneNode(false);
  stage.removeAttribute('id');
  stage.classList.add('route-staging');
  stage.innerHTML = '';
  document.body.append(stage);
  return stage;
}

function showInitialRouteError(app, error) {
  app.innerHTML = `<div class="card"><h2>错误</h2><pre>${fmt.htmlSafe(String(error.stack || error))}</pre></div>`;
}

async function renderNow() {
  const generation = renderGeneration;
  const hash = location.hash.replace(/^#/, '') || '/overview';
  const path = hash.split('?')[0];
  let key = path;
  if (path.startsWith('/sessions/')) key = '/sessions';
  if (!ROUTES[key]) key = '/overview';
  if (!currentRouteModule && !pendingRouteKey) setActiveTab(key);
  const loader = ROUTES[key];
  const app = $('#app');
  let mod;
  try {
    mod = await loader();
    if (generation !== renderGeneration) return;
    const stage = createRouteStage(app);
    try {
      await mod.default(stage);
    } catch (e) {
      if (typeof mod.dispose === 'function') {
        try { mod.dispose(stage); } catch {}
      }
      disposeCharts(stage);
      stage.remove();
      settlePendingTab(key, false);
      if (!currentRouteModule) showInitialRouteError(app, e);
      return;
    }

    // A newer hashchange wins. Do not let a slow response replace the latest route.
    if (generation !== renderGeneration) {
      if (typeof mod.dispose === 'function') {
        try { mod.dispose(stage); } catch {}
      }
      disposeCharts(stage);
      stage.remove();
      return;
    }

    disposeCurrentRoute();
    app.replaceWith(stage);
    stage.id = 'app';
    stage.classList.remove('route-staging');
    currentRouteModule = mod;
    currentRouteRoot = stage;
    settlePendingTab(key, true);
  } catch (e) {
    settlePendingTab(key, false);
    if (!currentRouteModule) showInitialRouteError(app, e);
  }
}

export async function render() {
  renderGeneration += 1;
  if (renderPromise) {
    renderQueued = true;
    return renderPromise;
  }
  renderPromise = (async () => {
    do {
      renderQueued = false;
      await renderNow();
    } while (renderQueued);
  })();
  try {
    await renderPromise;
  } finally {
    renderPromise = null;
  }
}

function routeLabel(path) {
  return {
    '/overview': '总览',
    '/prompts': '提示词',
    '/sessions': '会话',
    '/projects': '项目',
    '/skills': '技能',
    '/tips': '建议',
    '/settings': '设置',
  }[path] || path.replace(/^\//, '');
}

async function routeHandledStreamEvent(evt) {
  const handler = currentRouteModule && currentRouteModule.handleStreamEvent;
  if (typeof handler !== 'function') return false;
  try {
    return await handler(currentRouteRoot || $('#app'), evt) === true;
  } catch {
    return false;
  }
}

async function handleServerEvent(evt) {
  if (evt.type !== 'scan') return;
  const handled = await routeHandledStreamEvent(evt);
  if (!handled) render();
}

async function firstRun() {
  if (localStorage.getItem('td.plan-set')) return;
  const plans = Object.entries(state.pricing.plans);
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <h2>欢迎，选择计费方式</h2>
      <p>这会决定费用的展示方式，之后也可以在设置里修改。</p>
      <select id="firstplan" style="width:100%">
        ${plans.map(([k,v]) => `<option value="${k}">${v.label}${v.monthly ? ` - $${v.monthly}/月` : ''}</option>`).join('')}
      </select>
      <div class="actions">
        <div class="spacer"></div>
        <button class="primary" id="firstsave">继续</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  await new Promise(res => $('#firstsave', overlay).addEventListener('click', async () => {
    const plan = $('#firstplan', overlay).value;
    await fetch('/api/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan }) });
    localStorage.setItem('td.plan-set', '1');
    overlay.remove();
    res();
  }));
  state.plan = (await api('/api/plan')).plan;
}

async function boot() {
  buildTopbar();
  installPrivacyMode();
  const planResp = await api('/api/plan');
  state.plan = planResp.plan;
  state.pricing = planResp.pricing;
  $('#plan-pill').textContent = planName(state.plan);

  await firstRun();

  const nav = $('header.topbar nav');
  nav.addEventListener('click', event => {
    const link = event.target.closest('a[data-route]');
    if (link && link.dataset.route !== routeKeyForLocation()) setPendingTab(link.dataset.route);
  });
  window.addEventListener('hashchange', () => {
    setPendingTab(routeKeyForLocation());
    render();
  });
  await render();

  // SSE diff stream
  try {
    const es = new EventSource('/api/stream');
    es.onmessage = ev => {
      try {
        const evt = JSON.parse(ev.data);
        if (evt.type === 'scan') handleServerEvent(evt);
      } catch {}
    };
  } catch {}
}

boot();
