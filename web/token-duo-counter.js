export const TOKEN_COUNTER_RATE_PER_SEC = 10000;

const DIVERGENCE_METER_ASSET_ROOT = '/web/assets/divergence-meter';
const DIVERGENCE_METER_DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];
const DIVERGENCE_METER_INACTIVE_ZERO = 'inactive-0';
const MIN_DIGIT_SLOTS = 16;
const FRAME_STEP_DEALIGNMENT_TOKENS = 17;
const FRAME_STEP_DEALIGNMENT_MIN = FRAME_STEP_DEALIGNMENT_TOKENS * 2;
const FRAME_STEP_DEALIGNMENT_MAX = 340;
const controllers = new WeakMap();
let digitAssetsPreloaded = false;

export function mountTokenDuoCounter(root, actualValue, rangeKey, opts = {}) {
  disposeTokenDuoCounter(root);
  preloadTokenDuoDigitAssets();
  const actual = normalizeTokenValue(actualValue);
  const state = {
    root,
    mountedRoot: root,
    rangeKey,
    actualValue: actual,
    visualValue: actual,
    frame: null,
    lastFrameAt: null,
    lastRenderedValue: null,
    lastRenderedActualValue: null,
    stepDealignmentSign: 1,
    pendingSettledTarget: null,
    onSettled: typeof opts.onSettled === 'function' ? opts.onSettled : null,
  };
  controllers.set(root, state);
  renderCounter(state);
  startTicker(state);
  return state;
}

export function syncTokenDuoCounter(root, actualValue, rangeKey, opts = {}) {
  const actual = normalizeTokenValue(actualValue);
  let state = controllers.get(root);
  if (!state) {
    return mountTokenDuoCounter(root, actual, rangeKey, opts);
  }

  if (typeof opts.onSettled === 'function') {
    state.onSettled = opts.onSettled;
  }

  if (state.rangeKey !== rangeKey) {
    state.rangeKey = rangeKey;
    state.actualValue = actual;
    state.visualValue = actual;
    state.lastFrameAt = null;
    state.lastRenderedValue = null;
    state.lastRenderedActualValue = null;
    state.stepDealignmentSign = 1;
    state.pendingSettledTarget = null;
    renderCounter(state);
    startTicker(state);
    return state;
  }

  if (actual > state.actualValue) {
    state.actualValue = actual;
    if (actual > state.visualValue) {
      state.pendingSettledTarget = actual;
    }
  } else if (actual < state.actualValue) {
    state.actualValue = actual;
    state.visualValue = actual;
    state.pendingSettledTarget = null;
    state.lastFrameAt = null;
  }
  renderCounter(state);
  notifySettledIfNeeded(state);
  startTicker(state);
  return state;
}

export function disposeTokenDuoCounter(root) {
  const state = controllers.get(root);
  if (!state) return;
  if (state.frame != null) {
    cancelAnimationFrame(state.frame);
    state.frame = null;
  }
  controllers.delete(root);
}

function startTicker(state) {
  if (state.frame != null) return;
  state.frame = requestAnimationFrame(now => tickCounter(state, now));
}

function tickCounter(state, now) {
  state.frame = null;
  if (controllers.get(state.root) !== state) return;

  const elapsedMs = state.lastFrameAt == null ? now : Math.max(0, now - state.lastFrameAt);
  state.lastFrameAt = now;

  if (state.actualValue > state.visualValue) {
    if (prefersReducedMotion()) {
      state.visualValue = state.actualValue;
    } else {
      const step = visualStepForFrame(state, elapsedMs);
      state.visualValue = Math.min(state.actualValue, state.visualValue + step);
    }
  }

  renderCounter(state);
  notifySettledIfNeeded(state);
  startTicker(state);
}

function notifySettledIfNeeded(state) {
  const target = state.pendingSettledTarget;
  if (target == null || state.visualValue < target) return;
  state.pendingSettledTarget = null;
  if (typeof state.onSettled !== 'function') return;
  try {
    state.onSettled({
      actualValue: normalizeTokenValue(state.actualValue),
      visualValue: normalizeTokenValue(state.visualValue),
      rangeKey: state.rangeKey,
    });
  } catch {}
}

function visualStepForFrame(state, elapsedMs) {
  const step = TOKEN_COUNTER_RATE_PER_SEC * (elapsedMs / 1000);
  if (step < FRAME_STEP_DEALIGNMENT_MIN || step > FRAME_STEP_DEALIGNMENT_MAX) {
    return step;
  }
  const nudge = FRAME_STEP_DEALIGNMENT_TOKENS * state.stepDealignmentSign;
  state.stepDealignmentSign *= -1;
  return Math.max(1, step + nudge);
}

function renderCounter(state) {
  const roundedVisual = normalizeTokenValue(state.visualValue);
  const roundedActual = normalizeTokenValue(state.actualValue);
  if (
    state.lastRenderedValue === roundedVisual &&
    state.lastRenderedActualValue === roundedActual
  ) return;

  state.lastRenderedValue = roundedVisual;
  state.lastRenderedActualValue = roundedActual;

  const card = state.root.querySelector('.token-duo-card');
  const counter = state.root.querySelector('.token-duo-counter');
  if (!card || !counter) return;

  const fullActualTokens = formatInt(roundedActual);
  const digitSlots = tokenDuoDigitSlots(roundedVisual, Number(card.dataset.tokenDuoSlots) || MIN_DIGIT_SLOTS);
  card.style.setProperty('--digit-count', digitSlots.length);
  card.dataset.tokenDuoSlots = String(digitSlots.length);
  card.setAttribute('aria-label', `${fullActualTokens} confirmed total tokens`);
  counter.style.setProperty('--counter-scale', tokenDuoCounterScale(digitSlots.length));
  counter.setAttribute('title', `${fullActualTokens} confirmed total tokens`);
  counter.setAttribute('aria-label', `${fullActualTokens} confirmed total tokens`);
  renderCounterDigits(counter, digitSlots);
}

function renderCounterDigits(counter, digitSlots) {
  const doc = counter.ownerDocument || (typeof document !== 'undefined' ? document : null);
  if (!doc || typeof counter.replaceChildren !== 'function' || counter.children == null) {
    counter.innerHTML = digitSlots.map(slot => `
    <span class="token-duo-digit token-duo-meter-digit${slot.inactive ? ' inactive' : ''}" data-digit="${slot.digit}">
      <span class="token-duo-meter-tube" aria-hidden="true">
        <img class="token-duo-meter-img" src="${tokenDuoSlotAsset(slot)}" alt="" decoding="async" loading="eager">
      </span>
      <span class="token-duo-digit-core">${slot.digit}</span>
    </span>
  `).join('');
    return;
  }

  if (counter.childElementCount !== digitSlots.length) {
    counter.replaceChildren(...digitSlots.map(() => createDigitElement(doc)));
  }

  digitSlots.forEach((slot, index) => updateDigitElement(counter.children[index], slot));
}

function createDigitElement(doc) {
  const digit = doc.createElement('span');
  digit.className = 'token-duo-digit token-duo-meter-digit';

  const tube = doc.createElement('span');
  tube.className = 'token-duo-meter-tube';
  tube.setAttribute('aria-hidden', 'true');

  const img = doc.createElement('img');
  img.className = 'token-duo-meter-img';
  img.alt = '';
  img.decoding = 'async';
  img.loading = 'eager';

  const core = doc.createElement('span');
  core.className = 'token-duo-digit-core';

  tube.appendChild(img);
  digit.appendChild(tube);
  digit.appendChild(core);
  return digit;
}

function updateDigitElement(digit, slot) {
  if (!digit) return;
  digit.className = `token-duo-digit token-duo-meter-digit${slot.inactive ? ' inactive' : ''}`;
  const renderKey = `${slot.digit}:${slot.inactive ? 'inactive' : 'active'}`;
  if (digit.dataset.renderKey === renderKey) return;

  digit.dataset.digit = slot.digit;
  digit.dataset.renderKey = renderKey;
  const img = digit.querySelector('.token-duo-meter-img');
  if (img) img.src = tokenDuoSlotAsset(slot);
  const core = digit.querySelector('.token-duo-digit-core');
  if (core) core.textContent = slot.digit;
}

function normalizeTokenValue(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.round(n)) : 0;
}

function tokenDuoDigitString(value) {
  return String(value).replace(/\D/g, '') || '0';
}

function tokenDuoDigitSlots(value, minSlots = MIN_DIGIT_SLOTS) {
  const digits = tokenDuoDigitString(value);
  const totalSlots = Math.max(minSlots, digits.length);
  const leadingInactive = Math.max(0, totalSlots - digits.length);
  return Array.from({ length: totalSlots }, (_, index) => {
    const digitIndex = index - leadingInactive;
    const inactive = digitIndex < 0 || digitIndex >= digits.length;
    return {
      digit: inactive ? '0' : digits[digitIndex],
      inactive,
    };
  });
}

function tokenDuoCounterScale(digitCount) {
  return digitCount > 16 ? Math.max(0.58, 16 / digitCount).toFixed(3) : '1';
}

function tokenDuoDigitAsset(digit) {
  return `${DIVERGENCE_METER_ASSET_ROOT}/${digit}.png`;
}

function tokenDuoSlotAsset(slot) {
  return tokenDuoDigitAsset(slot.inactive ? DIVERGENCE_METER_INACTIVE_ZERO : slot.digit);
}

function preloadTokenDuoDigitAssets() {
  if (digitAssetsPreloaded || typeof Image === 'undefined') return;
  digitAssetsPreloaded = true;
  [...DIVERGENCE_METER_DIGITS, DIVERGENCE_METER_INACTIVE_ZERO].forEach(digit => {
    const img = new Image();
    img.decoding = 'async';
    img.src = tokenDuoDigitAsset(digit);
  });
}

function formatInt(value) {
  return normalizeTokenValue(value).toLocaleString();
}

function prefersReducedMotion() {
  return Boolean(
    globalThis.window &&
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}
