import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../web/routes/overview.js', import.meta.url), 'utf8');
const labels = Array.from(source.matchAll(/\$\{kpi\('([^']+)'/g), match => match[1]);

assert.deepEqual(labels, [
  '会话数', '轮次', '总输入', '输出', '缓存读取', '缓存写入',
]);
assert.match(source, /<div class="label">预估费用<\/div>/);
assert.doesNotMatch(source, /\$\{kpi\('(根线程|子代理线程|真实提问|模型调用)'/);
assert.match(source, /overviewLastIdleRefreshRangeKey !== range\.key \|\| actual > overviewLastIdleRefreshValue/);
