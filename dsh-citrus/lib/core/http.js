/**
 * 限速 HTTP 客户端 —— 所有平台共用的「一张嘴」。
 *
 * 用 Node 内置 fetch（零依赖），但补齐 citrus 的三件事：
 *   * 串行 + 最小间隔 + 随机抖动（不把请求打成节拍器）；
 *   * 429 / 5xx / 网络抖动退避重试（尊重 Retry-After）；
 *   * 把「登录失效 / 验证页 / 限流」翻译成统一错误码。
 *
 * 这不是绕过风控：撞上验证页就如实报 challenge。
 */

import { CitrusError } from './errors.js';

export const DEFAULT_HEADERS = {
  accept: 'application/json, text/plain, */*',
  'accept-language': 'zh-CN,zh;q=0.9,en;q=0.6',
  'accept-encoding': 'identity'
};

const CHALLENGE_MARKERS = [
  'acw_sc__v2',
  '__jsl_clearance',
  'zh-zse-ck',
  'var arg1',
  '安全验证',
  '请开启 JavaScript',
  'unhuman'
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function looksLikeChallenge(body, contentType) {
  const head = String(body || '').slice(0, 20000);
  for (const marker of CHALLENGE_MARKERS) {
    if (head.includes(marker)) return true;
  }
  if (String(contentType || '').toLowerCase().includes('json')) return false;
  const lowered = head.replace(/^\s+/, '').toLowerCase();
  return lowered.startsWith('<!doctype html') || lowered.startsWith('<html');
}

function retryAfterSeconds(value) {
  if (!value) return null;
  const seconds = Number.parseFloat(String(value).trim());
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export class PacedHttpClient {
  /**
   * @param {object} options
   * @param {string} [options.baseUrl]
   * @param {number} [options.gapMs]
   * @param {number} [options.jitterMs]
   * @param {number} [options.burstEvery]
   * @param {number} [options.burstMinMs]
   * @param {number} [options.burstMaxMs]
   * @param {number} [options.timeoutMs]
   * @param {number} [options.maxRetries]
   * @param {number} [options.maxBackoffMs]
   * @param {Record<string,string>} [options.headers]
   * @param {(message: string) => void} [options.logger]
   */
  constructor(options = {}) {
    this.baseUrl = String(options.baseUrl || '').replace(/\/+$/, '');
    this.gapMs = Math.max(0, Number(options.gapMs ?? 350));
    this.jitterMs = Math.max(0, Number(options.jitterMs ?? 250));
    this.burstEvery = Math.max(0, Number(options.burstEvery ?? 15));
    this.burstMinMs = Math.max(0, Number(options.burstMinMs ?? 1200));
    this.burstMaxMs = Math.max(this.burstMinMs, Number(options.burstMaxMs ?? 3000));
    this.timeoutMs = Math.max(1, Number(options.timeoutMs ?? 20000));
    this.maxRetries = Math.max(0, Number(options.maxRetries ?? 2));
    this.maxBackoffMs = Math.max(0, Number(options.maxBackoffMs ?? 8000));
    this.headers = { ...DEFAULT_HEADERS, ...(options.headers || {}) };
    this.logger = options.logger || (() => {});
    this.requestCount = 0;
    this.lastAt = 0;
    this.sinceBreak = 0;
    this.chain = Promise.resolve();
  }

  urlFor(path, params) {
    let url = /^https?:\/\//i.test(path)
      ? path
      : this.baseUrl + (path.startsWith('/') ? path : '/' + path);
    if (params) {
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null) continue;
        if (Array.isArray(value)) value.forEach((item) => search.append(key, String(item)));
        else search.append(key, String(value));
      }
      const query = search.toString();
      if (query) url += (url.includes('?') ? '&' : '?') + query;
    }
    return url;
  }

  /** 串行化：同一客户端的请求永远一个接一个，节奏才算数。 */
  withLock(fn) {
    const run = this.chain.then(fn, fn);
    this.chain = run.catch(() => {});
    return run;
  }

  async pace() {
    if (this.gapMs <= 0 && this.jitterMs <= 0 && this.burstEvery <= 0) return;
    const target = this.gapMs + (this.jitterMs > 0 ? Math.random() * this.jitterMs : 0);
    const wait = target - (Date.now() - this.lastAt);
    if (wait > 0) await sleep(wait);
    this.lastAt = Date.now();

    this.sinceBreak += 1;
    if (this.burstEvery > 0 && this.sinceBreak >= this.burstEvery) {
      this.sinceBreak = 0;
      const pause = this.burstMinMs + Math.random() * (this.burstMaxMs - this.burstMinMs);
      if (pause > 0) {
        this.logger('连续请求 ' + this.burstEvery + ' 次，歇 ' + Math.round(pause) + 'ms 再继续');
        await sleep(pause);
        this.lastAt = Date.now();
      }
    }
  }

  /**
   * 发一次请求（含重试）。
   * @param {string} path
   * @param {{ method?: string, params?: object, headers?: object, signal?: AbortSignal, timeoutMs?: number }} [options]
   * @returns {Promise<{ status: number, headers: Headers, body: string, url: string, json: () => any }>}
   */
  async request(path, options = {}) {
    const url = this.urlFor(path, options.params);
    const headers = { ...this.headers };
    for (const [key, value] of Object.entries(options.headers || {})) {
      if (value !== undefined && value !== null) headers[key.toLowerCase()] = value;
    }
    const method = (options.method || 'GET').toUpperCase();
    let attempt = 0;
    let lastError = null;

    while (attempt <= this.maxRetries) {
      attempt += 1;
      let response;
      try {
        response = await this.withLock(async () => {
          await this.pace();
          this.requestCount += 1;
          const timeout = options.timeoutMs || this.timeoutMs;
          const signals = [AbortSignal.timeout(timeout)];
          if (options.signal) signals.push(options.signal);
          const composed = signals.length > 1 ? AbortSignal.any(signals) : signals[0];
          try {
            const raw = await fetch(url, {
              method,
              headers,
              signal: composed,
              redirect: 'follow'
            });
            const body = await raw.text();
            return { status: raw.status, headers: raw.headers, body, url: raw.url || url };
          } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            throw new CitrusError('network', '请求没发出去：' + (error && error.message ? error.message : String(error)), '', { platform: 'zhihu' });
          }
        });
      } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        const code = error instanceof CitrusError ? error.code : 'network';
        if ((code === 'network' || code === 'upstream' || code === 'rate_limited') && attempt <= this.maxRetries) {
          lastError = error;
          await this.backoff(attempt, null);
          continue;
        }
        throw error;
      }

      if ([429, 500, 502, 503, 504].includes(response.status) && attempt <= this.maxRetries) {
        await this.backoff(attempt, retryAfterSeconds(response.headers.get('retry-after')));
        continue;
      }
      this.raiseForStatus(response);
      return {
        ...response,
        json: () => {
          const text = String(response.body || '').trim();
          if (!text) return {};
          try {
            return JSON.parse(text);
          } catch (error) {
            throw new CitrusError('bad_upstream_response', '上游返回的不是合法 JSON（' + error.message + '）。', '多半又被塞了一张网页/验证页；过一会儿再试。', { platform: 'zhihu' });
          }
        }
      };
    }
    if (lastError) throw lastError;
    throw new CitrusError('upstream', '上游请求失败（重试 ' + this.maxRetries + ' 次后仍失败）。', '', { platform: 'zhihu' });
  }

  async backoff(attempt, retryAfter) {
    const delay = retryAfter !== null
      ? Math.min(retryAfter * 1000, this.maxBackoffMs)
      : Math.min(700 * Math.pow(2, attempt - 1), this.maxBackoffMs);
    const total = delay + Math.random() * 250;
    if (total > 0) {
      this.logger('上游限流/抖动，' + Math.round(total) + 'ms 后重试（第 ' + attempt + ' 次）');
      await sleep(total);
    }
  }

  raiseForStatus(response) {
    const status = response.status;
    const contentType = response.headers.get('content-type') || '';
    const body = response.body || '';
    if (status >= 200 && status < 300) {
      if (looksLikeChallenge(body, contentType)) {
        throw new CitrusError('challenge', '上游返回的是验证页，不是数据（HTTP ' + status + '）。', '', { platform: 'zhihu' });
      }
      return;
    }
    if (status === 401) throw new CitrusError('not_logged_in', '上游说：身份未经过验证（401）。', '', { platform: 'zhihu' });
    if (status === 403) {
      if (looksLikeChallenge(body, contentType)) {
        throw new CitrusError('challenge', '上游返回了风控验证页（403）。', '', { platform: 'zhihu' });
      }
      throw new CitrusError('forbidden', '上游返回 403。', '', { platform: 'zhihu' });
    }
    if (status === 404) throw new CitrusError('not_found', '上游返回 404：内容不存在或已删除。', '', { platform: 'zhihu' });
    if (status === 429) throw new CitrusError('rate_limited', '上游限流（429）。', '', { platform: 'zhihu' });
    if (status === 400 || status === 422) {
      throw new CitrusError('bad_upstream_response', '上游拒绝了请求（HTTP ' + status + '）。', '', { platform: 'zhihu' });
    }
    throw new CitrusError('upstream', '上游返回 HTTP ' + status + '。', '', { platform: 'zhihu' });
  }

  async getJson(path, options = {}) {
    const response = await this.request(path, options);
    return response.json();
  }
}
