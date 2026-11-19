/**
 * 把 dsh-citrus 安装到当前 DeepSeek Harness 的 profile 里。
 *
 * 做的事：
 *   1. 复制插件到 <DSH_HOME>/plugins/dsh-citrus；
 *   2. 在插件目录建一个 node_modules 链接，指向 profile 自己的 node_modules，
 *      让插件能解析 @deepseek-ai/dsh-tools 这些宿主包；
 *   3. 把它登记成 profile bundle（package.json 里的依赖 + dsh.profile.bundles）。
 *
 * 幂等：重复运行只会更新已有登记，不会重复插入。
 *
 *   node scripts/install.mjs                 # 装进当前 profile（默认 desktop）
 *   node scripts/install.mjs --profile web   # 装进指定 profile
 *   node scripts/install.mjs --dry-run       # 只看会做什么
 *   node scripts/install.mjs --uninstall     # 移除 bundle 登记和插件目录
 */

import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync, rmSync, symlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
const target = join(home, 'plugins', 'dsh-citrus');
// 宿主包从 profile 自己的 node_modules 解析。
const profileModules = join(profileDir, 'node_modules');

function log(message) {
  console.log((dryRun ? '[dry-run] ' : '') + message);
}

function linkModules() {
  if (existsSync(join(target, 'node_modules'))) {
    log('node_modules 链接已存在');
    return;
  }
  if (!existsSync(profileModules)) {
    // 没有这个目录也能跑：插件作为 profile bundle 由 Host 自己的模块图解析依赖。
    // 这里只影响「直接 node 跑插件文件」这类场景，所以给个提醒就好。
    log('提示：没找到 ' + profileModules + '，跳过 node_modules 链接（作为 bundle 运行时不影响）');
    return;
  }
  if (dryRun) {
    log('会创建 node_modules 链接 -> ' + profileModules);
    return;
  }
  try {
    symlinkSync(profileModules, join(target, 'node_modules'), 'junction');
    log('已创建 node_modules 链接 -> ' + profileModules);
  } catch (error) {
    throw new Error('创建 node_modules 链接失败：' + error.message + '\n可以手动把 ' + profileModules + ' 链接到 ' + join(target, 'node_modules'));
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
  console.log('');
  console.log('下一步：');
  console.log('  1. 重启一次 DeepSeek Harness（宿主侧的模块缓存不会自动重载）');
  console.log('  2. 打开「设置 → citrus」，把浏览器里 Copy as cURL 的内容粘进 Cookie 框并保存');
  console.log('  3. 在对话里直接问：「知乎热榜有什么」');
  console.log('');
  console.log('排查：让模型跑一次 zhihu_status，或看 <DSH_HOME>/dsh-citrus/status.json。');
}

function main() {
  console.log('DSH_HOME : ' + home);
  console.log('profile  : ' + profile);
  console.log('');

  if (uninstall) {
    removeProfileBundle();
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
  ensureProfileBundle();
  printNextSteps();
}

try {
  main();
} catch (error) {
  console.error('安装失败：' + error.message);
  process.exitCode = 1;
}