/**
 * Cookie 的唯一来源：插件配置里的 `platforms.<平台>.cookie`。
 *
 * 只有面板会写它（存进当前 profile 的 Cordis patch），插件不再读本地文件——
 * 两套来源曾经让「面板改了却没生效」这种问题很难查。
 * 这里顺带给出插件自己的数据目录（诊断快照等）。
 */

import { homedir } from 'node:os';
import { join } from 'node:path';
import { CitrusError } from './core/errors.js';
import { parseCookieInput } from './core/cookies.js';

export const AUTH_COOKIE_NAMES = ['z_c0'];

export function dshHome() {
  return process.env.DSH_HOME ? process.env.DSH_HOME : join(homedir(), '.dsh');
}

export function dataDir() {
  return join(dshHome(), 'dsh-citrus');
}

/**
 * 解析出当前生效的 Cookie。
 * @param {{ cookie?: string }} config 该平台的配置段
 * @param {string} [platform] 平台 id
 * @returns {object} 解析结果（含指纹、登录态，不含原文）
 */
export function resolveCookie(config = {}, platform = 'zhihu') {
  const raw = String(config.cookie || '').trim();
  if (!raw) {
    throw new CitrusError(
      'no_credential',
      '还没有配置知乎 Cookie。',
      '在「设置 → citrus」里粘贴浏览器复制的 cURL；留空保存表示不修改。',
      { platform }
    );
  }
  return parseCookieInput(raw, { authCookieNames: AUTH_COOKIE_NAMES, platform });
}
