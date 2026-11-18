/**
 * 统一错误类型与错误码翻译。
 *
 * 和 citrus 保持一致：只抛一种错误，带上 code / hint / retryable，
 * 让模型（和用户）读到的是「下一步做什么」，而不是一段堆栈。
 */

export const ERROR_STATUS = {
  bad_request: 400,
  invalid_argument: 400,
  no_credential: 409,
  not_logged_in: 401,
  challenge: 403,
  forbidden: 403,
  not_found: 404,
  rate_limited: 429,
  network: 502,
  upstream: 502,
  bad_upstream_response: 502,
  internal: 500
};

const RETRYABLE = new Set(['rate_limited', 'network', 'upstream']);

export class CitrusError extends Error {
  /**
   * @param {string} code 机器可判定的短码
   * @param {string} message 发生了什么
   * @param {string} [hint] 下一步做什么
   * @param {{ platform?: string, details?: object, status?: number, retryable?: boolean }} [extra]
   */
  constructor(code, message, hint = '', extra = {}) {
    super(message);
    this.name = 'CitrusError';
    this.code = code;
    this.hint = hint || '';
    this.platform = extra.platform || '';
    this.details = extra.details || {};
    this.status = extra.status === undefined ? (ERROR_STATUS[code] ?? 500) : extra.status;
    this.retryable = extra.retryable === undefined ? RETRYABLE.has(code) : extra.retryable;
  }
}

/** 把这个插件会遇到的失败翻译成一句人话 + 下一步。 */
const MESSAGES = {
  no_credential: '还没有配置知乎 Cookie。',
  not_logged_in: 'Cookie 里的登录态失效了（缺少或过期的 z_c0）。',
  challenge: '被知乎风控拦住了（返回的是验证页，不是数据）。',
  forbidden: '知乎拒绝了这次请求（403）。',
  not_found: '这条知乎内容不存在或已被删除。',
  rate_limited: '知乎限流了，需要等几分钟。',
  network: '请求没能发到知乎（网络/代理/DNS）。',
  upstream: '知乎服务端返回了异常状态。',
  bad_upstream_response: '知乎返回的不是预期的 JSON（多半又是验证页）。',
  bad_request: '参数不合法。',
  invalid_argument: '参数不合法。',
  unsupported_capability: '这个平台不支持该能力。',
  internal: '插件内部出错了。'
};

const NEXT_STEPS = {
  no_credential: '运行 dsh-citrus auth 粘贴浏览器复制的 cURL，或在插件配置里填 cookie。',
  not_logged_in: '在浏览器重新登录知乎，再 Copy as cURL 复制一份，然后重新运行 dsh-citrus auth。',
  challenge: '去浏览器正常打开 zhihu.com 通过验证，等几分钟再试；不要连续重试。',
  rate_limited: '等几分钟再问；citrus 已经自动重试过，连续重试只会更容易被风控。',
  network: '检查这台机器能不能访问 www.zhihu.com（代理 / DNS / 防火墙）。'
};

/** 面向模型和用户的完整说明：一句话原因 + 下一步。 */
export function friendlyMessage(error) {
  if (!(error instanceof CitrusError)) {
    return '获取知乎内容失败：' + (error && error.message ? error.message : String(error));
  }
  const base = MESSAGES[error.code] || error.message || '请求失败。';
  const step = NEXT_STEPS[error.code] || error.hint || '';
  return step ? base + step : base;
}
