/**
 * 改 dsh-citrus/package.json 的版本号。
 *
 *   node scripts/bump_version.mjs 26.11.03
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const FILE = join(ROOT, 'dsh-citrus', 'package.json');

const version = (process.argv[2] || '').trim();
if (!/^\d{2}\.\d{2}\.\d{2}$/.test(version)) {
  console.error('用法：node scripts/bump_version.mjs <YY.MM.TT>');
  process.exit(2);
}

const pkg = JSON.parse(readFileSync(FILE, 'utf8'));
pkg.version = version;
writeFileSync(FILE, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
console.log('dsh-citrus 版本 -> ' + version);
