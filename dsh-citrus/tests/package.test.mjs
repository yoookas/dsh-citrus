/**
 * 包级约定：dsh-citrus 必须是一个可被 profile 组合的 bundle。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const patch = readFileSync(new URL('../cordis.patch.yml', import.meta.url), 'utf8');

test('package.json 声明 bundle patch', () => {
  assert.equal(pkg.type, 'module');
  assert.equal(pkg.dsh.bundle.patch, './cordis.patch.yml');
  assert.ok(pkg.files.includes('lib'));
});

test('package.json 声明 web 客户端半侧，否则浏览器端永远不会被加载', () => {
  // dsh-client-modules 只扫描 dsh.client.platform === 'web' 的包，并请求 ./client 导出。
  assert.equal(pkg.dsh.client?.platform, 'web');
  const client = pkg.exports['./client'];
  assert.ok(client, '缺少 exports["./client"]');
  assert.equal(typeof client === 'string' ? client : client.default, './lib/client.js');
  assert.ok(pkg.files.includes('lib'), 'lib/client.js 必须随包发布');
});

test('bundle patch 插入 dsh-citrus 行', () => {
  assert.ok(patch.includes('id: dsh-citrus'));
  assert.ok(patch.includes("name: 'dsh-citrus'"));
});
