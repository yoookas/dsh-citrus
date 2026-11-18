/**
 * Cookie 存放位置。
 *
 * 优先级：
 *   1. 插件配置里的 cookie（直接粘贴 cURL）；
 *   2. 默认文件 <DSH_HOME>/dsh-citrus/<platform>.cookie（由 dsh-citrus auth 写入）。
 *
 * 文件按 mtime 缓存：dsh-citrus auth 换号后，下一次工具调用就会用新的，
 * 不需要重启 DeepSeek Harness。
 */

import { mkdirSync, readFileSync, statSync, writeFileSync, unlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { CitrusError } from './core/errors.js';
import { maskCookie, parseCookieInput } from './core/cookies.js';

export const AUTH_COOKIE_NAMES = ['z_c0'];

export function dshHome() {
  return process.env.DSH_HOME ? process.env.DSH_HOME : join(homedir(), '.dsh');
}

export function dataDir() {
  return join(dshHome(), 'dsh-citrus');
}

export function defaultCookieFile(platform = 'zhihu') {
  return join(dataDir(), platform + '.cookie');
}

const fileCache = new Map();

/** 读文件 Cookie；文件不存在返回空串。 */
export function readCookieFile(path) {
  if (!path) return '';
  try {
    const stat = statSync(path, { bigint: true });
    const stamp = String(stat.mtimeNs) + ':' + String(stat.size);
    const cached = fileCache.get(path);
    if (cached && cached.stamp === stamp) return cached.value;
    const value = readFileSync(path, 'utf8').replace(/^\uFEFF/, '').trim();
    fileCache.set(path, { stamp, value });
    return value;
  } catch {
    fileCache.delete(path);
    return '';
  }
}

/** 写 Cookie 文件（权限尽量 0600）；返回实际路径。 */
export function writeCookieFile(path, cookie) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, cookie.trim() + '\n', { encoding: 'utf8', mode: 0o600 });
  try {
    const stat = statSync(path, { bigint: true });
    fileCache.set(path, { stamp: String(stat.mtimeNs) + ':' + String(stat.size), value: cookie.trim() });
  } catch {
    fileCache.delete(path);
  }
  return path;
}

export function removeCookieFile(path) {
  try {
    unlinkSync(path);
  } catch {
    /* 不存在就算了 */
  }
  fileCache.delete(path);
}

/**
 * 解析出当前生效的 Cookie。
 *
 * 两个来源：配置里的 cookie 优先，否则读 <DSH_HOME>/dsh-citrus/<platform>.cookie
 * （dsh-citrus auth 写的那份）。配置里不再暴露文件路径，路径是固定的。
 * @param {{ cookie?: string }} config
 * @param {string} [platform]
 */
export function resolveCookie(config = {}, platform = 'zhihu') {
  const direct = String(config.cookie || '').trim();
  const path = defaultCookieFile(platform);
  const raw = direct || readCookieFile(path);
  if (!raw) {
    throw new CitrusError(
      'no_credential',
      '还没有配置知乎 Cookie。',
      '在面板里粘贴 cURL，或运行 dsh-citrus auth 写入本地文件。',
      { platform }
    );
  }
  const parsed = parseCookieInput(raw, { authCookieNames: AUTH_COOKIE_NAMES, platform });
  return {
    ...parsed,
    sourcePath: direct ? '' : path
  };
}

export { maskCookie };