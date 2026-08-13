import assert from 'node:assert/strict';

let now = 0;
let nextFrameId = 1;
const frames = [];

globalThis.window = {
  matchMedia: () => ({ matches: false }),
};

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

const fakeDocument = new FakeDocument();
globalThis.document = fakeDocument;

globalThis.requestAnimationFrame = callback => {
  const id = nextFrameId++;
  frames.push({ id, callback });
  return id;
};

globalThis.cancelAnimationFrame = id => {
  const index = frames.findIndex(frame => frame.id === id);
  if (index >= 0) frames.splice(index, 1);
};

function flushFrame(ms) {
  now += ms;
  const frame = frames.shift();
  assert.ok(frame, 'expected one scheduled animation frame');
  frame.callback(now);
}

function pendingFrames() {
  return frames.length;
}

function clearFrames() {
  frames.splice(0, frames.length);
}

class FakeElement {
  constructor(tagName = 'div', ownerDocument = fakeDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.dataset = {};
    this.attributes = new Map();
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.textContent = '';
    this.src = '';
    this.alt = '';
    this.decoding = '';
    this.loading = '';
    this.innerHTMLWrites = 0;
    this._innerHTML = '';
    this.style = {
      values: new Map(),
      setProperty: (name, value) => this.style.values.set(name, value),
    };
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) || null;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children.forEach(child => { child.parentNode = null; });
    this.children = children;
    this.children.forEach(child => { child.parentNode = this; });
  }

  get childElementCount() {
    return this.children.length;
  }

  querySelector(selector) {
    for (const child of this.children) {
      if (child.matches(selector)) return child;
      const descendant = child.querySelector(selector);
      if (descendant) return descendant;
    }
    return null;
  }

  matches(selector) {
    if (selector.startsWith('.')) {
      return this.className.split(/\s+/).includes(selector.slice(1));
    }
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }

  set innerHTML(value) {
    this.innerHTMLWrites += 1;
    this._innerHTML = String(value);
    this.children = [];
  }

  get innerHTML() {
    if (!this.children.length) return this._innerHTML;
    return this.children.map(serializeElement).join('');
  }
}

function makeRoot() {
  const card = new FakeElement('section');
  card.dataset.tokenDuoSlots = '16';
  const counter = new FakeElement('div');
  return {
    card,
    counter,
    querySelector(selector) {
      if (selector === '.token-duo-card') return card;
      if (selector === '.token-duo-counter') return counter;
      return null;
    },
  };
}

function displayedValue(root) {
  if (root.counter.children.length) {
    const digits = root.counter.children
      .map(child => child.querySelector('.token-duo-digit-core')?.textContent || '')
      .join('');
    return Number(digits) || 0;
  }
  const digits = Array.from(root.counter.innerHTML.matchAll(/<span class="token-duo-digit-core">(\d)<\/span>/g))
    .map(match => match[1])
    .join('');
  return Number(digits) || 0;
}

function digitImageSrcs(root) {
  return root.counter.children
    .map(child => child.querySelector('.token-duo-meter-img')?.src || '');
}

function secondLastDigit(value) {
  return Math.floor(value / 10) % 10;
}

function serializeElement(element) {
  const attrs = [];
  if (element.className) attrs.push(`class="${element.className}"`);
  if (element.dataset.digit != null) attrs.push(`data-digit="${element.dataset.digit}"`);
  if (element.src) attrs.push(`src="${element.src}"`);
  const text = element.textContent || '';
  const children = element.children.map(serializeElement).join('');
  return `<${element.tagName.toLowerCase()}${attrs.length ? ' ' + attrs.join(' ') : ''}>${text}${children}</${element.tagName.toLowerCase()}>`;
}

const {
  TOKEN_COUNTER_RATE_PER_SEC,
  mountTokenDuoCounter,
  syncTokenDuoCounter,
  disposeTokenDuoCounter,
} = await import('../web/token-duo-counter.js');

assert.equal(TOKEN_COUNTER_RATE_PER_SEC, 10000);

function resetClock() {
  now = 0;
  nextFrameId = 1;
  clearFrames();
}

resetClock();
{
  const root = makeRoot();
  const settled = [];
  mountTokenDuoCounter(root, 1000, '30d');
  syncTokenDuoCounter(root, 11000, '30d', {
    onSettled: info => settled.push(info),
  });
  flushFrame(500);
  assert.equal(displayedValue(root), 1000 + TOKEN_COUNTER_RATE_PER_SEC / 2);
  assert.equal(settled.length, 0, 'settled callback must not run before the counter catches up');
  flushFrame(500);
  assert.equal(displayedValue(root), 1000 + TOKEN_COUNTER_RATE_PER_SEC);
  assert.deepEqual(settled, [{ actualValue: 11000, visualValue: 11000, rangeKey: '30d' }]);
  flushFrame(500);
  assert.equal(settled.length, 1, 'settled callback must run once per confirmed target');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 10000, '30d');
  syncTokenDuoCounter(root, 9000, '30d');
  assert.equal(displayedValue(root), 9000, 'a sliding range decrease must update immediately');
  syncTokenDuoCounter(root, 10000, '30d');
  flushFrame(1000);
  assert.equal(displayedValue(root), 10000, 'growth after a decrease must animate from the new baseline');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  const settled = [];
  mountTokenDuoCounter(root, 1000, '30d');
  syncTokenDuoCounter(root, 7000, '30d', {
    onSettled: info => settled.push(info.actualValue),
  });
  flushFrame(300);
  syncTokenDuoCounter(root, 12000, '30d', {
    onSettled: info => settled.push(info.actualValue),
  });
  flushFrame(700);
  assert.equal(displayedValue(root), 11000);
  assert.deepEqual(settled, [], 'segmented confirmed updates should not settle intermediate targets');
  flushFrame(100);
  assert.equal(displayedValue(root), 12000);
  assert.deepEqual(settled, [12000]);
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  const settled = [];
  mountTokenDuoCounter(root, 10000, '30d');
  syncTokenDuoCounter(root, 20000, '30d', {
    onSettled: info => settled.push(info),
  });
  flushFrame(500);
  syncTokenDuoCounter(root, 5000, '7d', {
    onSettled: info => settled.push(info),
  });
  assert.equal(displayedValue(root), 5000);
  flushFrame(1000);
  assert.deepEqual(settled, [], 'range changes should reset without firing stale settled callbacks');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  const digits = [];
  mountTokenDuoCounter(root, 1000, '30d');
  syncTokenDuoCounter(root, 100000, '30d');
  for (let i = 0; i < 6; i += 1) {
    flushFrame(1000 / 60);
    digits.push(secondLastDigit(displayedValue(root)));
  }
  assert.ok(new Set(digits).size > 1, 'second-last digit should visibly change at 60fps');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 12345, '30d');
  assert.match(
    root.counter.innerHTML,
    /src="\/web\/assets\/divergence-meter\/5\.png"/,
    'counter should render Divergence Meter digit images',
  );
  assert.equal(displayedValue(root), 12345);
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 1005, '30d');
  const srcs = digitImageSrcs(root);
  assert.match(srcs[0], /\/web\/assets\/divergence-meter\/inactive-0\.png$/);
  assert.match(srcs[11], /\/web\/assets\/divergence-meter\/inactive-0\.png$/);
  assert.match(srcs[12], /\/web\/assets\/divergence-meter\/1\.png$/);
  assert.match(srcs[13], /\/web\/assets\/divergence-meter\/0\.png$/);
  assert.match(srcs[14], /\/web\/assets\/divergence-meter\/0\.png$/);
  assert.match(srcs[15], /\/web\/assets\/divergence-meter\/5\.png$/);
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 1000, '30d');
  assert.equal(root.counter.children.length, 16);
  assert.equal(root.counter.innerHTMLWrites, 0, 'counter should not build digit images via innerHTML');
  const firstDigitNode = root.counter.children[15];
  const firstImgNode = firstDigitNode.querySelector('.token-duo-meter-img');
  syncTokenDuoCounter(root, 2000, '30d');
  flushFrame(100);
  assert.equal(root.counter.children[15], firstDigitNode, 'digit rolling should keep existing digit DOM nodes');
  assert.equal(root.counter.children[15].querySelector('.token-duo-meter-img'), firstImgNode, 'digit rolling should keep existing img nodes');
  assert.equal(root.counter.innerHTMLWrites, 0, 'rolling should not rebuild the digit strip');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 1000, '30d');
  syncTokenDuoCounter(root, 1500, '30d');
  flushFrame(5000);
  assert.equal(displayedValue(root), 1500);
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 10000, '30d');
  syncTokenDuoCounter(root, 5000, '30d');
  flushFrame(500);
  assert.equal(displayedValue(root), 5000, 'a same-range decrease must not retain a stale high-water mark');
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 10000, '30d');
  syncTokenDuoCounter(root, 100000, '30d');
  flushFrame(500);
  assert.equal(displayedValue(root), 10000 + TOKEN_COUNTER_RATE_PER_SEC / 2);
  syncTokenDuoCounter(root, 5000, '7d');
  assert.equal(displayedValue(root), 5000);
  disposeTokenDuoCounter(root);
}

resetClock();
{
  const root = makeRoot();
  mountTokenDuoCounter(root, 1000, '30d');
  syncTokenDuoCounter(root, 2000, '30d');
  syncTokenDuoCounter(root, 3000, '30d');
  syncTokenDuoCounter(root, 4000, '30d');
  assert.equal(pendingFrames(), 1);
  disposeTokenDuoCounter(root);
  assert.equal(pendingFrames(), 0);
}
