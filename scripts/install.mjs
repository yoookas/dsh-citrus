/**
 * 把 dsh-citrus 安装到当前 DeepSeek Harness 的 profile 里。
 *
 * 做的事：
 *   1. 复制插件到 <DSH_HOME>/plugins/dsh-citrus；
 *   2. 在插件目录里建一个 node_modules 链接，指向 <DSH_HOME>/profiles/node_modules，
 *      让插件能解析 @deepseek-ai/dsh-tools 这些宿主包；
 *   3. 往 profile 的 cordis.patch.yml 里插入/替换一段带标记的配置。
 *
 * 幂等：重复运行只会更新那段标记块，不会重复插入。
 *
 *   node scripts/install.mjs                 # 装进当前 profile（默认 desktop）
 *   node scripts/install.mjs --profile web   # 装进指定 profile
 *   node scripts/install.mjs --dry-run       # 只看会做什么
 *   node scripts/install.mjs --uninstall     # 移除配置块和插件目录
 */

import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync, rmSync, symlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..');
const SOURCE = join(REPO, 'dsh-citrus');

const args = process.argv.slice(2);
const option = (name, fallback = '') => {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};
const hasFlag = (name) => args.includes(name);

const dryRun = hasFlag('--dry-run');
const uninstall = hasFlag('--uninstall');
const home = resolve(option('--home', process.env.DSH_HOME || join(homedir(), '.dsh')));
const profile = option('--profile', process.env.DSH_PROFILE || 'desktop');
const profileDir = join(home, 'profiles', profile);
const patchFile = join(profileDir, 'cordis.patch.yml');
const target = join(home, 'plugins', 'dsh-citrus');
const sharedModules = join(home, 'profiles', 'node_modules');
const sharedLink = join(sharedModules, 'dsh-citrus');

const START = '# >>> dsh-citrus';
const END = '# <<< dsh-citrus';

const q = (value) => "'" + String(value).replace(/'/g, "''") + "'";

function log(message) {
  console.log((dryRun ? '[dry-run] ' : '') + message);
}

function backupPatch() {
  if (!existsSync(patchFile)) return '';
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const backup = patchFile + '.bak-' + stamp;
  if (!dryRun) cpSync(patchFile, backup);
  return backup;
}

function patchBlock() {
  // 带版本查询串：Node 会按不同 URL 重新加载模块，client-modules 也会重新抓取
  // 客户端 bundle，所以重装后不需要重启 DSH（裸包名会命中 ESM 缓存）。
  const entry = pathToFileURL(join(target, 'lib', 'index.js')).href + '?v=' + Date.now().toString(36);
  return [
    START + ' (由 scripts/install.mjs 管理，重装会覆盖这一段)',
    '- insert:',
    '    - id: dsh-citrus',
    '      name: ' + q(entry),
    '      config:',
    '        cookieFile: ' + q(join(home, 'dsh-citrus', 'zhihu.cookie')),
    END
  ].join('\n');
}

/** 找到标记块的首尾下标；没有返回 null。 */
function findBlock(text) {
  const start = text.indexOf(START);
  if (start < 0) return null;
  const end = text.indexOf(END, start);
  if (end < 0) return null;
  return { start, end: end + END.length };
}

function replaceBlock(text, block) {
  const found = findBlock(text);
  if (!found) return '';
  return text.slice(0, found.start) + block + text.slice(found.end);
}

function updatePatch() {
  if (!existsSync(patchFile)) {
    throw new Error('找不到 ' + patchFile + '：这个 profile 还没初始化过，先启动一次 DeepSeek Harness。');
  }
  let text = readFileSync(patchFile, 'utf8');
  const backup = backupPatch();
  const block = patchBlock();

  if (findBlock(text)) {
    text = replaceBlock(text, block);
    log('已更新 cordis.patch.yml 里的 dsh-citrus 配置块');
  } else if (text.replace(/\s+/g, '') === '[]') {
    const comments = text.split('\n').filter((line) => line.trim().startsWith('#'));
    const header = comments.length ? comments.join('\n') + '\n' : '';
    text = header + block + '\n';
    log('已把 dsh-citrus 配置块写进 cordis.patch.yml');
  } else {
    text = text.replace(/\s*$/, '\n') + '\n' + block + '\n';
    log('已把 dsh-citrus 配置块追加到 cordis.patch.yml');
  }
  if (backup) log('原文件备份：' + backup);
  if (!dryRun) writeFileSync(patchFile, text, 'utf8');
}

function removePatch() {
  if (!existsSync(patchFile)) return;
  const text = readFileSync(patchFile, 'utf8');
  const found = findBlock(text);
  if (!found) {
    log('cordis.patch.yml 里没有 dsh-citrus 配置块');
    return;
  }
  let before = text.slice(0, found.start);
  let after = text.slice(found.end);
  before = before.replace(/\n+$/, '');
  after = after.replace(/^\n+/, '');
  const next = (before ? before + '\n' : '') + (after ? after + '\n' : '');
  const backup = backupPatch();
  if (!dryRun) writeFileSync(patchFile, next, 'utf8');
  log('已从 cordis.patch.yml 移除 dsh-citrus 配置块' + (backup ? '（备份：' + backup + '）' : ''));
}

function linkModules() {
  if (existsSync(join(target, 'node_modules'))) {
    log('node_modules 链接已存在');
    return;
  }
  if (!existsSync(sharedModules)) {
    throw new Error('找不到 ' + sharedModules + '：DeepSeek Harness 还没初始化过 profile。');
  }
  if (dryRun) {
    log('会创建 node_modules 链接 -> ' + sharedModules);
    return;
  }
  try {
    symlinkSync(sharedModules, join(target, 'node_modules'), 'junction');
    log('已创建 node_modules 链接 -> ' + sharedModules);
  } catch (error) {
    throw new Error('创建 node_modules 链接失败：' + error.message + '\n可以手动把 ' + sharedModules + ' 链接到 ' + join(target, 'node_modules'));
  }
}

function linkSharedPackage() {
  const stat = existsSync(sharedLink) ? lstatSync(sharedLink) : null;
  if (stat !== null && !stat.isSymbolicLink()) {
    throw new Error(sharedLink + ' 已存在且不是链接，不敢覆盖；请先手动移走它。');
  }
  if (stat !== null && stat.isSymbolicLink()) {
    try {
      if (resolve(sharedLink) === resolve(target)) {
        log('profiles/node_modules/dsh-citrus 链接已存在');
        return;
      }
    } catch {
      /* 坏链接按需要重建 */
    }
    if (!dryRun) rmSync(sharedLink, { force: true });
  }
  if (dryRun) {
    log('会创建 profiles/node_modules/dsh-citrus 链接 -> ' + target);
    return;
  }
  try {
    symlinkSync(target, sharedLink, 'junction');
    log('已创建 profiles/node_modules/dsh-citrus 链接');
  } catch (error) {
    throw new Error('创建 profiles/node_modules/dsh-citrus 链接失败：' + error.message);
  }
}

function ensureProfileBundle() {
  const pkgPath = join(profileDir, 'package.json');
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
  pkg.dependencies = pkg.dependencies || {};
  pkg.dependencies['dsh-citrus'] = 'file:' + target.replace(/\\/g, '/');
  pkg.dsh = pkg.dsh || {};
  pkg.dsh.profile = pkg.dsh.profile || {};
  const bundles = Array.isArray(pkg.dsh.profile.bundles) ? pkg.dsh.profile.bundles : [];
  if (!bundles.includes('dsh-citrus')) bundles.push('dsh-citrus');
  pkg.dsh.profile.bundles = bundles;
  const backup = pkgPath + '.bak-' + new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  if (!dryRun) {
    cpSync(pkgPath, backup);
    writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
  }
  log('已把 dsh-citrus 加为 profile bundle（依赖 + bundles）');
}

function removeProfileBundle() {
  const pkgPath = join(profileDir, 'package.json');
  if (!existsSync(pkgPath)) return;
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
  let changed = false;
  if (pkg.dependencies && pkg.dependencies['dsh-citrus'] !== undefined) {
    delete pkg.dependencies['dsh-citrus'];
    changed = true;
  }
  const bundles = pkg.dsh?.profile?.bundles;
  if (Array.isArray(bundles) && bundles.includes('dsh-citrus')) {
    pkg.dsh.profile.bundles = bundles.filter((name) => name !== 'dsh-citrus');
    changed = true;
  }
  if (!changed) return;
  if (!dryRun) writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8');
  log('已从 profile bundle 列表移除 dsh-citrus');
}

function installFiles() {
  if (!existsSync(SOURCE)) throw new Error('找不到插件源码：' + SOURCE);
  if (existsSync(target)) {
    log('清理旧版本：' + target);
    if (!dryRun) rmSync(target, { recursive: true, force: true });
  } else {
    log('安装到：' + target);
  }
  if (dryRun) return;
  mkdirSync(target, { recursive: true });
  cpSync(SOURCE, target, {
    recursive: true,
    filter: (path) => {
      const rel = path.slice(SOURCE.length).replace(/\\/g, '/');
      return !/\/node_modules(\/|$)/.test(rel)
        && !/\/tests(\/|$)/.test(rel)
        && !/\/__pycache__(\/|$)/.test(rel)
        && !rel.endsWith('.pyc');
    }
  });
  log('文件已复制（不含 tests / node_modules）');
}

function printNextSteps() {
  const cli = join(target, 'bin', 'cli.mjs');
  console.log('');
  console.log('下一步：');
  console.log('  1. 配置 Cookie：');
  console.log('       node "' + cli + '" auth');
  console.log('     （把浏览器里 Copy as cURL 的内容粘进去，Ctrl+Z 回车）');
  console.log('  2. 检查：');
  console.log('       node "' + cli + '" status');
  console.log('  3. 在 DeepSeek Harness 里直接问：「知乎热榜有什么」');
  console.log('');
  console.log('如果 GUI 里还没看到工具，重启一次 DeepSeek Harness（profile 的 patch 热重载有时不触发）。');
}

function main() {
  console.log('DSH_HOME : ' + home);
  console.log('profile  : ' + profile);
  console.log('');

  if (uninstall) {
    removePatch();
    removeProfileBundle();
    if (existsSync(sharedLink) && lstatSync(sharedLink).isSymbolicLink()) {
      if (!dryRun) rmSync(sharedLink, { force: true });
      log('已删除 profiles/node_modules/dsh-citrus 链接');
    }
    if (existsSync(target)) {
      log('删除插件目录：' + target);
      if (!dryRun) rmSync(target, { recursive: true, force: true });
    }
    console.log('\n已卸载。');
    return;
  }

  if (!existsSync(profileDir)) {
    throw new Error('profile 目录不存在：' + profileDir + '\n先启动一次 DeepSeek Harness，或确认 --profile 名字。');
  }
  installFiles();
  linkModules();
  linkSharedPackage();
  removePatch();
  ensureProfileBundle();
  printNextSteps();
}

try {
  main();
} catch (error) {
  console.error('安装失败：' + error.message);
  process.exitCode = 1;
}