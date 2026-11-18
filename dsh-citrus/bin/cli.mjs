#!/usr/bin/env node
/**
 * dsh-citrus 命令行工具。
 *
 *   dsh-citrus auth            从 stdin 读 cURL / Cookie，写进默认 Cookie 文件
 *   dsh-citrus auth --file x   从文件读
 *   dsh-citrus status          看 Cookie 指纹 + 上游连通性（会请求一次 /me）
 *   dsh-citrus hot [--limit 5] 直接打印热榜（不发模型，纯调试用）
 *
 * Cookie 只写本地文件、只打印指纹；任何命令都不会回显原文。
 */

import { readFileSync } from 'node:fs';
import { defaultCookieFile, readCookieFile, removeCookieFile, resolveCookie, writeCookieFile } from '../lib/store.js';
import { PLATFORM_DEFAULTS } from '../lib/platforms/registry.js';
import { ZhihuAdapter } from '../lib/platforms/zhihu/adapter.js';
import { friendlyMessage } from '../lib/core/errors.js';
import { renderHot } from '../lib/render.js';

const args = process.argv.slice(2);
const command = args[0] || 'help';

function option(name, fallback = '') {
  const index = args.indexOf(name);
  if (index >= 0 && args[index + 1]) return args[index + 1];
  const inline = args.find((arg) => arg.startsWith(name + '='));
  return inline ? inline.slice(name.length + 1) : fallback;
}

function hasFlag(name) {
  return args.includes(name);
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function makeConfig(cookie) {
  const defaults = PLATFORM_DEFAULTS.zhihu;
  return {
    cookie,
    baseUrl: process.env.CITRUS_ZHIHU_BASE_URL || undefined,
    gapMs: defaults.gapMs,
    jitterMs: defaults.jitterMs,
    timeoutMs: defaults.timeoutMs,
    maxRetries: defaults.maxRetries
  };
}

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

const HELP = [
  'dsh-citrus —— 知乎内容插件（DeepSeek Harness）',
  '',
  '用法：',
  '  dsh-citrus auth [--file <路径>]',
  '      从 stdin 或文件读入浏览器复制的内容（cURL / Cookie 头 / 裸串 / JSON），',
  '      解析后写入 ' + defaultCookieFile(),
  '',
  '  dsh-citrus status',
  '      显示 Cookie 指纹与上游连通性（发一次 /me 请求）',
  '',
  '  dsh-citrus hot [--limit 5]',
  '      直接打印知乎热榜（调试用）',
  '',
  '  dsh-citrus logout',
  '      删除默认 Cookie 文件',
  '',
  '示例：',
  '  # Windows：把剪贴板里的 cURL 粘进去，Ctrl+Z 回车结束',
  '  dsh-citrus auth',
  '',
  '  # 或者直接读文件',
  '  dsh-citrus auth --file cookie.txt',
  '',
  'Cookie 文件默认位置：' + defaultCookieFile(),
  '也可以用 DSH_HOME 环境变量改 DSH 主目录。'
].join('\n');

async function cmdAuth() {
  const target = defaultCookieFile();
  let raw = '';
  const file = option('--file');
  if (file) {
    raw = readFileSync(file, 'utf8');
  } else {
    if (process.stdin.isTTY) {
      console.error('把浏览器里 Copy as cURL 的内容粘进来，然后按 Ctrl+Z 回车（Linux/macOS 是 Ctrl+D）：');
    }
    raw = await readStdin();
  }
  if (!raw.trim()) {
    fail('没有读到内容。用 --file 指定文件，或从 stdin 粘贴。');
    return;
  }
  try {
    const resolved = resolveCookie({ cookie: raw }, 'zhihu');
    writeCookieFile(target, resolved.cookie);
    console.log('已保存知乎 Cookie');
    console.log('  文件：' + target);
    console.log('  指纹：' + resolved.fingerprint);
    console.log('  条目：' + resolved.names.length + ' 项');
    console.log('  登录态：' + (resolved.hasLogin ? '有（z_c0）' : '缺 z_c0 —— 大概率会被上游判成未登录'));
    if (!resolved.hasLogin) {
      console.log('提示：在浏览器重新登录知乎后，重新 Copy as cURL 一次。');
    }
  } catch (error) {
    fail(friendlyMessage(error));
  }
}

async function withAdapter(fn) {
  try {
    const resolved = resolveCookie({}, 'zhihu');
    const adapter = new ZhihuAdapter({ ...makeConfig(resolved.cookie), baseUrl: process.env.CITRUS_ZHIHU_BASE_URL || undefined });
    return await fn(adapter, resolved);
  } catch (error) {
    fail(friendlyMessage(error));
    return undefined;
  }
}

async function cmdStatus() {
  await withAdapter(async (adapter, resolved) => {
    console.log('知乎 Cookie');
    console.log('  文件：' + (resolved.sourcePath || resolved.source));
    console.log('  指纹：' + resolved.fingerprint);
    console.log('  登录态：' + (resolved.hasLogin ? '有（z_c0）' : '缺 z_c0'));
    console.log('');
    const account = await adapter.account();
    console.log('上游连通：正常');
    console.log('  账号：' + account.profile.name + (account.profile.headline ? '（' + account.profile.headline + '）' : ''));
    const page = await adapter.hot(3);
    console.log('  热榜：拿到 ' + page.count + ' 条');
  });
}

async function cmdHot() {
  const limit = Number.parseInt(option('--limit', '5'), 10) || 5;
  await withAdapter(async (adapter) => {
    const page = await adapter.hot(limit);
    console.log(renderHot(page, { maxItems: limit, excerptChars: 120 }));
  });
}

async function cmdLogout() {
  const target = defaultCookieFile();
  removeCookieFile(target);
  console.log('已删除 ' + target);
}

async function main() {
  if (hasFlag('--help') || hasFlag('-h') || command === 'help') {
    console.log(HELP);
    return;
  }
  if (command === 'auth') return cmdAuth();
  if (command === 'status') return cmdStatus();
  if (command === 'hot') return cmdHot();
  if (command === 'logout') return cmdLogout();
  console.error('不认识的命令：' + command);
  console.log(HELP);
  process.exitCode = 2;
}

main().catch((error) => {
  fail(friendlyMessage(error));
});
