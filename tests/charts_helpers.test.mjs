import assert from 'node:assert/strict';
import { donutTooltip } from '../web/charts.js';

assert.equal(
  donutTooltip({
    name: 'GPT 5.4',
    value: 1234567,
    percent: 42.345,
    data: { cost_usd: 12.345678 },
  }),
  'GPT 5.4<br/><b>1,234,567</b> tokens（42.3%）<br/>总金额 <b>$12.3457</b>',
);

assert.match(
  donutTooltip({ name: 'unknown', value: 10, percent: 1, data: { cost_usd: null } }),
  /总金额 <b>未计价<\/b>/,
);
