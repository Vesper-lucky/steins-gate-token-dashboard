import assert from 'node:assert/strict';
import { createTokenIdleRefresh, TOKEN_IDLE_REFRESH_MS } from '../web/token-idle-refresh.js';

assert.equal(TOKEN_IDLE_REFRESH_MS, 30 * 60 * 1000);

let now = 0;
let nextId = 1;
const timers = new Map();
const setTimer = (callback, delay) => {
  const id = nextId++;
  timers.set(id, { callback, at: now + delay });
  return id;
};
const clearTimer = id => timers.delete(id);
const advance = ms => {
  now += ms;
  for (const [id, timer] of [...timers]) {
    if (timer.at > now) continue;
    timers.delete(id);
    timer.callback();
  }
};

const refreshes = [];
const idle = createTokenIdleRefresh(() => refreshes.push(now), { setTimer, clearTimer });
idle.observe(100);
advance(20 * 60 * 1000);
idle.observe(100);
advance(9 * 60 * 1000);
assert.deepEqual(refreshes, [], 'unchanged counts must keep the original inactivity window');

idle.observe(101);
advance(29 * 60 * 1000);
assert.deepEqual(refreshes, [], 'a token increase must restart the full 30 minute window');
idle.observe(102);
advance(29 * 60 * 1000);
assert.deepEqual(refreshes, [], 'repeated increases must reset, not accumulate, idle time');
advance(60 * 1000);
assert.deepEqual(refreshes, [88 * 60 * 1000]);
advance(60 * 60 * 1000);
idle.observe(102);
assert.deepEqual(refreshes, [88 * 60 * 1000], 'one inactive period must refresh only once');
idle.observe(103);
advance(30 * 60 * 1000);
assert.deepEqual(refreshes, [88 * 60 * 1000, 178 * 60 * 1000]);
idle.dispose();

const afterDrop = [];
const dropped = createTokenIdleRefresh(() => afterDrop.push(now), { setTimer, clearTimer });
dropped.observe(200);
advance(20 * 60 * 1000);
dropped.observe(100);
dropped.observe(101);
advance(29 * 60 * 1000);
assert.deepEqual(afterDrop, [], 'growth after a lower range total must restart the full window');
advance(60 * 1000);
assert.deepEqual(afterDrop, [228 * 60 * 1000]);
dropped.dispose();
