export const TOKEN_IDLE_REFRESH_MS = 30 * 60 * 1000;

export function createTokenIdleRefresh(onIdle, opts = {}) {
  const delay = opts.delayMs ?? TOKEN_IDLE_REFRESH_MS;
  const setTimer = opts.setTimer || setTimeout;
  const clearTimer = opts.clearTimer || clearTimeout;
  let timer = null;
  let lastValue = null;

  const reset = () => {
    if (timer != null) clearTimer(timer);
    timer = setTimer(() => {
      timer = null;
      onIdle();
    }, delay);
  };

  return {
    observe(value) {
      const current = Number(value) || 0;
      if (lastValue == null || current > lastValue) {
        lastValue = current;
        reset();
      } else if (current < lastValue) {
        lastValue = current;
      }
    },
    dispose() {
      if (timer != null) clearTimer(timer);
      timer = null;
    },
  };
}
