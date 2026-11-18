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

test('bundle patch 插入 dsh-citrus 行', () => {
  assert.ok(patch.includes('id: dsh-citrus'));
  assert.ok(patch.includes("name: 'dsh-citrus'"));
});
