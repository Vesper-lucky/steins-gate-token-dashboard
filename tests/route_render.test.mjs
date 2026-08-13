import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');

assert.match(source, /function createRouteStage\(app\)/);
assert.match(source, /await mod\.default\(stage\)/);
assert.match(source, /disposeCurrentRoute\(\);\s*app\.replaceWith\(stage\);/s);
assert.doesNotMatch(source, /disposeCurrentRoute\(\);\s*app\.innerHTML\s*=\s*''/s);
assert.match(source, /if \(generation !== renderGeneration\)/);
assert.match(source, /if \(!currentRouteModule\) showInitialRouteError\(app, e\);/);
assert.match(source, /app\.replaceWith\(stage\);/);
assert.match(source, /setPendingTab\(routeKeyForLocation\(\)\)/);
assert.match(source, /nav\.addEventListener\('click'/);
assert.match(source, /link\.dataset\.route !== routeKeyForLocation\(\)/);
assert.match(source, /正在加载/);
assert.match(source, /settlePendingTab\(key, true\)/);
assert.match(source, /切换失败，已保留当前板块/);

const overview = readFileSync(new URL('../web/routes/overview.js', import.meta.url), 'utf8');
assert.doesNotMatch(overview, /document\.getElementById\('ch-/);
const skills = readFileSync(new URL('../web/routes/skills.js', import.meta.url), 'utf8');
assert.doesNotMatch(skills, /document\.getElementById\('ch-/);
const settings = readFileSync(new URL('../web/routes/settings.js', import.meta.url), 'utf8');
assert.match(settings, /root\.querySelector\('#save'\)/);
assert.doesNotMatch(settings, /import .*\$ .*from/);
const charts = readFileSync(new URL('../web/charts.js', import.meta.url), 'utf8');
assert.match(charts, /export function disposeCharts\(root\)/);
assert.match(source, /disposeCharts\(stage\)/);
