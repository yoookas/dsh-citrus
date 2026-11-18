/**
 * 打包 dsh-citrus：产出 npm tarball（.tgz）和 sha256。
 *
 *   node scripts/build.mjs            # 版本号取 dsh-citrus/package.json
 *   node scripts/build.mjs 26.11.03   # 指定版本号（只影响文件名，不改 package.json）
 *
 * 产物在 dist/：dsh-citrus-<版本>.tgz + .sha256
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PLUGIN = join(ROOT, 'dsh-citrus');
const DIST = join(ROOT, 'dist');

const pkg = JSON.parse(readFileSync(join(PLUGIN, 'package.json'), 'utf8'));
const version = process.argv[2] || pkg.version;
if (!/^\d{2}\.\d{2}\.\d{2}$/.test(version)) {
  console.warn('警告：版本号 ' + version + ' 不是 YY.MM.TT 格式');
}

if (!existsSync(DIST)) mkdirSync(DIST, { recursive: true });
for (const name of readdirSync(DIST)) {
  if (name.startsWith('dsh-citrus-')) rmSync(join(DIST, name), { force: true });
}

const npm = process.platform === 'win32' ? 'npm' : 'npm';
const output = execFileSync(npm, ['pack', PLUGIN, '--pack-destination', DIST, '--json'], {
  cwd: ROOT,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'inherit'],
  shell: process.platform === 'win32'
});
const packed = JSON.parse(output)[0];
const source = join(DIST, packed.filename);
const target = join(DIST, 'dsh-citrus-' + version + '.tgz');
renameSync(source, target);

const digest = createHash('sha256').update(readFileSync(target)).digest('hex');
const checksum = target + '.sha256';
const line = digest + '  ' + 'dsh-citrus-' + version + '.tgz\n';
writeFileSync(checksum, line, 'utf8');

console.log('打包完成：dist/dsh-citrus-' + version + '.tgz（' + Math.round(readFileSync(target).length / 1024) + ' KB）');
console.log('sha256：' + digest);