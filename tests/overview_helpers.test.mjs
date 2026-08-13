import assert from 'node:assert/strict';
import {
  chartCopyForRange,
  cacheChartPlan,
  cacheTooltipRows,
  costChartPlan,
  costTooltipRows,
  isTodayRange,
  projectTooltipRows,
  rangeBounds,
  usageChartPlan,
  usageTooltipRows,
  usageEndpointForRange,
  visualTotalTokens,
} from '../web/routes/overview-helpers.js';

const today = { key: 'today' };
const sevenDays = { key: '7d', days: 7 };
const allTime = { key: 'all', days: null };

assert.equal(isTodayRange(today), true);
assert.equal(isTodayRange(sevenDays), false);
assert.equal(usageEndpointForRange(today, '/api/daily?since=x'), '/api/today-hourly');
assert.equal(usageEndpointForRange(sevenDays, '/api/daily?since=x'), '/api/daily?since=x');
assert.equal(chartCopyForRange(today).usageTitle, '今日用量');
assert.equal(chartCopyForRange(sevenDays).usageTitle, '每日用量');
assert.equal(chartCopyForRange(today).costTitle, '今日总金额');
assert.equal(chartCopyForRange(sevenDays).costTitle, '每日总金额');
assert.equal(
  chartCopyForRange(today).usageSubtitle,
  '北京时间今日 00:00-24:00，按小时展示新输入/缓存写入、缓存读取和输出。',
);
assert.equal(
  chartCopyForRange(sevenDays).usageSubtitle,
  '按北京时间自然日展示新输入/缓存写入、缓存读取和输出。',
);

const bounds = rangeBounds(today, new Date('2026-05-26T04:00:00.000Z'));
assert.equal(bounds.since, '2026-05-25T16:00:00.000Z');
assert.equal(bounds.until, '2026-05-26T16:00:00.000Z');
assert.equal(rangeBounds(allTime).since, null);
assert.equal(rangeBounds(allTime).until, null);

const tooltipRow = {
  input_tokens: 10,
  output_tokens: 3,
  cache_read_tokens: 99,
  cache_create_tokens: 4,
  input_cost_usd: 0.01,
  output_cost_usd: 0.11,
  cache_create_cost_usd: 0.003456,
  usage_cost_usd: 0.133332,
  cache_read_cost_usd: 0.009876,
  models: [
    {
      model: 'deepseek-v4-pro',
      input_tokens: 7,
      output_tokens: 11,
      cache_read_tokens: 13,
      cache_create_tokens: 17,
      total_tokens: 48,
      cost_usd: 0.004321,
    },
  ],
};
assert.deepEqual(usageTooltipRows(tooltipRow), [
  { label: '新输入/缓存写入', value: 14, kind: 'int' },
  { label: '缓存读取', value: 99, kind: 'int' },
  { label: '输出', value: 3, kind: 'int' },
  { label: '合计 tokens', value: 116, kind: 'int' },
  { label: '金额预估', value: 0.133332, kind: 'usd4' },
  { label: '按模型', value: '', kind: 'text' },
  { label: 'deepseek v4 pro', value: '输入 24 · 输出 11 · 缓存读取 13 · 合计 48', kind: 'text' },
]);
assert.deepEqual(cacheTooltipRows(tooltipRow), [
  { label: '缓存读取', value: 99, kind: 'int' },
  { label: '金额预估', value: 0.009876, kind: 'usd4' },
  { label: '按模型', value: '', kind: 'text' },
  { label: 'deepseek v4 pro', value: '缓存读取 13', kind: 'text' },
]);
assert.deepEqual(costTooltipRows(tooltipRow), [
  { label: '输入金额', value: 0.013456, kind: 'usd4' },
  { label: '缓存读取金额', value: 0.009876, kind: 'usd4' },
  { label: '输出金额', value: 0.11, kind: 'usd4' },
  { label: '总金额', value: 0.133332, kind: 'usd4' },
  { label: '按模型', value: '', kind: 'text' },
  { label: 'deepseek v4 pro', value: '$0.0043', kind: 'text' },
]);

assert.equal(visualTotalTokens({
  total_input_tokens: 100,
  input_tokens: 12,
  output_tokens: 7,
}), 107);
assert.equal(visualTotalTokens({
  input_tokens: 12,
  output_tokens: 7,
}), 19);
assert.equal(visualTotalTokens({
  total_input_tokens: 0,
  output_tokens: 0,
}), 0);
assert.equal(visualTotalTokens({}), 428765312);

assert.deepEqual(projectTooltipRows({
  billable_tokens: 30,
  output_tokens: 8,
  cache_read_tokens: 5,
  total_tokens: 35,
  cost_usd: 0.123456,
}), [
  { label: '输入', value: 22, kind: 'int' },
  { label: '输出', value: 8, kind: 'int' },
  { label: '缓存读取', value: 5, kind: 'int' },
  { label: '总 tokens', value: 35, kind: 'int' },
  { label: '金额预估', value: 0.123456, kind: 'usd4' },
]);

const dailyRows = [
  { day: '2026-05-25', input_tokens: 10, output_tokens: 3, cache_read_tokens: 10, cache_create_tokens: 4, total_input_tokens: 24 },
  { day: '2026-05-26', input_tokens: 20, output_tokens: 6, cache_read_tokens: 20, cache_create_tokens: 5, total_input_tokens: 45 },
];
const dailyPlan = usageChartPlan(sevenDays, dailyRows, 'bar');
assert.equal(dailyPlan.kind, 'stackedBar');
assert.deepEqual(dailyPlan.categories, ['2026-05-25', '2026-05-26']);
assert.deepEqual(dailyPlan.series.map(s => s.name), ['新输入/缓存写入', '缓存读取', '输出']);
assert.deepEqual(dailyPlan.series.map(s => s.values), [
  [14, 25],
  [10, 20],
  [3, 6],
]);

const dailyLinePlan = usageChartPlan(sevenDays, dailyRows, 'line');
assert.equal(dailyLinePlan.kind, 'line');
assert.deepEqual(dailyLinePlan.x, ['2026-05-25', '2026-05-26']);
assert.deepEqual(dailyLinePlan.series.map(s => s.name), ['合计 tokens']);
assert.deepEqual(dailyLinePlan.series[0].data, [27, 51]);

const hourlyRows = [
  { hour: '00:00', input_tokens: 10, output_tokens: 5, cache_create_tokens: 2, cache_read_tokens: 100 },
  { hour: '01:00', input_tokens: 20, output_tokens: 6, cache_create_tokens: 3, cache_read_tokens: 200 },
];
const todayPlan = usageChartPlan(today, hourlyRows, 'bar');
assert.equal(todayPlan.kind, 'stackedBar');
assert.deepEqual(todayPlan.categories, ['00:00', '01:00']);
assert.deepEqual(todayPlan.series.map(s => s.name), ['新输入/缓存写入', '缓存读取', '输出']);
assert.deepEqual(todayPlan.series.map(s => s.values), [
  [12, 23],
  [100, 200],
  [5, 6],
]);

const todayLinePlan = usageChartPlan(today, hourlyRows, 'line');
assert.equal(todayLinePlan.kind, 'line');
assert.deepEqual(todayLinePlan.x, ['00:00', '01:00']);
assert.deepEqual(todayLinePlan.series.map(s => s.name), ['合计 tokens']);
assert.deepEqual(todayLinePlan.series[0].data, [117, 229]);

const cacheBarPlan = cacheChartPlan(today, hourlyRows, 'bar');
assert.equal(cacheBarPlan.kind, 'stackedBar');
assert.deepEqual(cacheBarPlan.series.map(s => s.name), ['缓存读取']);
assert.deepEqual(cacheBarPlan.series[0].values, [100, 200]);

const costRows = [
  { hour: '00:00', input_cost_usd: 0.25, output_cost_usd: 1, cache_create_cost_usd: 0.125, cache_read_cost_usd: 0.25 },
  { hour: '01:00', input_cost_usd: 0.5, output_cost_usd: 2, cache_create_cost_usd: 0.25, cache_read_cost_usd: 0.75 },
];
const costBarPlan = costChartPlan(today, costRows, 'bar');
assert.equal(costBarPlan.kind, 'stackedBar');
assert.deepEqual(costBarPlan.categories, ['00:00', '01:00']);
assert.deepEqual(costBarPlan.series.map(s => s.name), ['输入金额', '缓存读取金额', '输出金额']);
assert.deepEqual(costBarPlan.series.map(s => s.color), ['#A86F18', '#C98A24', '#F2C94C']);
assert.deepEqual(costBarPlan.series[0].values, [0.375, 0.75]);
assert.deepEqual(costBarPlan.series[1].values, [0.25, 0.75]);
assert.deepEqual(costBarPlan.series[2].values, [1, 2]);

const bridgedInputCostPlan = costChartPlan(sevenDays, [
  {
    day: '2026-06-09',
    input_tokens: 0,
    cache_create_tokens: 1000000,
    input_cost_usd: 0,
    output_cost_usd: 1,
    cache_create_cost_usd: 1.25,
    cache_read_cost_usd: 0.5,
  },
], 'bar');
assert.deepEqual(bridgedInputCostPlan.series.map(s => s.name), ['输入金额', '缓存读取金额', '输出金额']);
assert.deepEqual(bridgedInputCostPlan.series[0].values, [1.25]);
assert.deepEqual(bridgedInputCostPlan.series[1].values, [0.5]);
assert.deepEqual(bridgedInputCostPlan.series[2].values, [1]);
assert.deepEqual(costTooltipRows({
  input_tokens: 0,
  cache_create_tokens: 1000000,
  input_cost_usd: 0,
  output_cost_usd: 1,
  cache_create_cost_usd: 1.25,
  cache_read_cost_usd: 0.5,
}), [
  { label: '输入金额', value: 1.25, kind: 'usd4' },
  { label: '缓存读取金额', value: 0.5, kind: 'usd4' },
  { label: '输出金额', value: 1, kind: 'usd4' },
  { label: '总金额', value: 2.75, kind: 'usd4' },
]);

const costLinePlan = costChartPlan(sevenDays, [
  { day: '2026-05-25', input_cost_usd: 0.25, output_cost_usd: 0.75, cache_create_cost_usd: 0, cache_read_cost_usd: 0.5 },
  { day: '2026-05-26', input_cost_usd: 0.5, output_cost_usd: 1.25, cache_create_cost_usd: 0.25, cache_read_cost_usd: 0.25 },
], 'line');
assert.equal(costLinePlan.kind, 'line');
assert.deepEqual(costLinePlan.x, ['2026-05-25', '2026-05-26']);
assert.deepEqual(costLinePlan.series.map(s => s.name), ['总金额']);
assert.equal(costLinePlan.series[0].color, '#D9A441');
assert.deepEqual(costLinePlan.series[0].data, [1.5, 2.25]);

const cacheLinePlan = cacheChartPlan(sevenDays, [
  { day: '2026-05-25', cache_read_tokens: 12 },
  { day: '2026-05-26', cache_read_tokens: 34 },
], 'line');
assert.equal(cacheLinePlan.kind, 'line');
assert.deepEqual(cacheLinePlan.x, ['2026-05-25', '2026-05-26']);
assert.deepEqual(cacheLinePlan.series.map(s => s.name), ['缓存读取']);
assert.deepEqual(cacheLinePlan.series[0].data, [12, 34]);
