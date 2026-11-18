/**
 * 包级约定：客户端半侧必须能被 DSH 的 client-modules 发现。
 *
 * 这里不启动浏览器，只检查清单与产物是否齐备，防止改包时漏掉 dsh.client。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const bundle = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8');

test('package.json 声明了 web 客户端半侧', () => {
  assert.equal(pkg.type, 'module');
  assert.equal(pkg.exports['./client'], './lib/client.js');
  assert.equal(pkg.dsh.client.platform, 'web');
  assert.ok(Array.isArray(pkg.dsh.client.inject));
  assert.ok(pkg.files.includes('lib'));
});

test('client.js 是 ModuleLoader 包并按命名空间注册卡片', () => {
  assert.ok(bundle.includes('window.__ModuleLoader__.load'));
  assert.ok(bundle.includes('id: "dsh-citrus"'));
  assert.ok(bundle.includes('settings.plugin.item'));
  assert.ok(bundle.includes('dsh-citrus'));
  assert.ok(bundle.includes('settingsScope'));
});
