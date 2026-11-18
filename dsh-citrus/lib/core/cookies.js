/**
 * Cookie 解析 —— 用户能粘什么，这里就得认什么。
 *
 * 支持四种输入：
 *   1. DevTools 的 Copy as cURL；
 *   2. 一整段请求头（含 Cookie: 行）；
 *   3. 裸 Cookie 串：name=value; name2=value2；
 *   4. JSON 对象：{"z_c0": "..."}。
 *
 * 只取 cookie 和 user-agent，其它头一概不碰、不存、不打印。
 */

import { createHash } from 'node:crypto';
import { CitrusError } from './errors.js';

export const MAX_INPUT_BYTES = 20000;
export const MAX_COOKIE_BYTES = 8192;

const HEADER_RE = /(-H|--header)\s+(?:'([^']*)'|"([^"]*)")/g;
const COOKIE_FLAG_RE = /(-b|--cookie)\s+(?:'([^']*)'|"([^"]*)")/;
const COOKIE_LINE_RE = /^\s*cookie\s*:\s*(.+)$/i;
const USER_AGENT_LINE_RE = /^\s*user-agent\s*:\s*(.+)$/i;
const PAIR_RE = /^([^=;\s]+)=(.*)$/;

function unquote(value) {
  return String(value || '').trim().replace(/^['"]+|['"]+$/g, '').trim();
}

/** name=value; name2=value2 -> 保序对象（重名后者覆盖）。 */
export function parsePairs(cookie) {
  const pairs = new Map();
  if (!cookie) return pairs;
  for (const chunk of String(cookie).split(';')) {
    const text = chunk.trim();
    if (!text) continue;
    const match = PAIR_RE.exec(text);
    if (!match) continue;
    pairs.set(match[1].trim(), match[2].trim());
  }
  return pairs;
}

export function pairsToCookie(pairs) {
  return [...pairs.entries()].map(([key, value]) => key + '=' + value).join('; ');
}

/** 给日志/状态看的指纹：只露名字，值一律遮掉。 */
export function maskCookie(cookie, keep = 3) {
  const names = [...parsePairs(cookie).keys()];
  if (!names.length) return '';
  const digest = createHash('sha256').update(String(cookie || ''), 'utf8').digest('hex').slice(0, 8);
  const shown = names.slice(0, keep);
  if (names.length > keep) shown.push('+' + (names.length - keep));
  return shown.join(', ') + ' · #' + digest;
}

function fromJsonObject(raw) {
  if (!raw.trimStart().startsWith('{')) return '';
  let obj;
  try {
    obj = JSON.parse(raw);
  } catch {
    return '';
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return '';
  const pairs = new Map();
  for (const [key, value] of Object.entries(obj)) {
    if (typeof value === 'string' || typeof value === 'number') pairs.set(String(key), String(value));
  }
  return pairs.size ? pairsToCookie(pairs) : '';
}

/**
 * 把粘进来的任何东西变成一条干净的 Cookie 串。
 * @param {string} text
 * @param {{ authCookieNames?: string[], platform?: string }} [options]
 */
export function parseCookieInput(text, options = {}) {
  const platform = options.platform || 'zhihu';
  const authNames = options.authCookieNames || [];
  const raw = String(text || '').trim();
  if (!raw) {
    throw new CitrusError('no_credential', '粘进来的内容是空的。', '把浏览器里的 cURL 或 Cookie 复制过来。', { platform });
  }
  if (Buffer.byteLength(raw, 'utf8') > MAX_INPUT_BYTES) {
    throw new CitrusError('bad_request', '粘进来的内容太长了（超过 20 KB）。', '只复制 Cookie 那一行或一条请求的 cURL 就够了。', { platform });
  }

  let cookie = '';
  let userAgent = '';
  let source = 'raw';

  // ④ JSON 对象
  const jsonCookie = fromJsonObject(raw);
  if (jsonCookie) {
    cookie = jsonCookie;
    source = 'json';
  }

  // ① cURL
  if (!cookie && /(^|\s)curl\s/i.test(raw)) {
    source = 'curl';
    const flat = raw.replace(/\\\r?\n/g, ' ').replace(/\r?\n/g, ' ');
    HEADER_RE.lastIndex = 0;
    let match;
    while ((match = HEADER_RE.exec(flat)) !== null) {
      const line = match[2] !== undefined ? match[2] : match[3];
      if (!line || !line.includes(':')) continue;
      const index = line.indexOf(':');
      const name = line.slice(0, index).trim().toLowerCase();
      const value = line.slice(index + 1).trim();
      if (name === 'cookie') cookie = value;
      else if (name === 'user-agent') userAgent = value;
    }
    if (!cookie) {
      const flag = COOKIE_FLAG_RE.exec(flat);
      if (flag) cookie = flag[2] !== undefined ? flag[2] : flag[3];
    }
  }

  // ② 请求头块
  if (!cookie) {
    for (const line of raw.split(/\r?\n/)) {
      const match = COOKIE_LINE_RE.exec(line);
      if (match) {
        cookie = match[1];
        source = 'header';
        break;
      }
    }
    for (const line of raw.split(/\r?\n/)) {
      const match = USER_AGENT_LINE_RE.exec(line);
      if (match) {
        userAgent = match[1];
        break;
      }
    }
  }

  // ③ 裸 Cookie 串
  if (!cookie) {
    cookie = raw.replace(/^\s*cookie\s*:\s*/i, '');
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(cookie)) {
      throw new CitrusError('bad_request', '这看起来是一个网址，不是 Cookie。', '在浏览器里按 F12 -> Network -> 右键请求 -> Copy -> Copy as cURL，再粘过来。', { platform });
    }
    source = 'raw';
  }

  cookie = unquote(cookie)
    .replace(/\\u003b/g, ';')
    .replace(/\\u003d/g, '=')
    .replace(/[\r\n]+/g, ' ')
    .replace(/^\s*cookie\s*:\s*/i, '')
    .trim();

  if (Buffer.byteLength(cookie, 'utf8') > MAX_COOKIE_BYTES) {
    throw new CitrusError('bad_request', 'Cookie 太长了（超过 8 KB），不像是一条正常的 Cookie。', '', { platform });
  }
  if (!cookie.includes('=')) {
    throw new CitrusError('bad_request', '这段内容里没有 name=value 形式的 Cookie。', '选 Copy as cURL 复制整条请求，别只复制网页正文。', { platform });
  }

  const pairs = parsePairs(cookie);
  if (!pairs.size) {
    throw new CitrusError('bad_request', '解析不出任何 Cookie 键值对。', '', { platform });
  }

  return {
    cookie,
    userAgent: unquote(userAgent),
    source,
    names: [...pairs.keys()],
    hasLogin: authNames.some((name) => pairs.has(name)),
    xsrf: pairs.get('_xsrf') || '',
    fingerprint: maskCookie(cookie)
  };
}
