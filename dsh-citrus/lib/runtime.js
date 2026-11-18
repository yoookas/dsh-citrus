/**
 * 运行时：把「配置 -> Cookie -> 适配器」这条链路管起来。
 *
 * 换 Cookie（重新 dsh-citrus auth）后，指纹变了就会换一个新的适配器，
 * 旧适配器连同它的缓存一起丢掉。
 */

import { ZhihuAdapter } from './platforms/zhihu/adapter.js';
import { resolveCookie } from './store.js';

const MAX_ADAPTERS = 4;

export class CitrusRuntime {
  /**
   * @param {object} config 已解析的插件配置
   * @param {(message: string) => void} [logger]
   */
  constructor(config, logger = () => {}) {
    this.config = config || {};
    this.logger = logger;
    this.adapters = new Map();
    this.lastFingerprint = '';
  }

  /** 当前 Cookie 对应的知乎适配器。 */
  adapter() {
    const resolved = resolveCookie(this.config, 'zhihu');
    if (resolved.fingerprint !== this.lastFingerprint) {
      this.lastFingerprint = resolved.fingerprint;
      this.logger('知乎 Cookie 已载入（' + resolved.fingerprint + '，登录态：' + (resolved.hasLogin ? '有' : '缺 z_c0') + '）');
    }
    const cached = this.adapters.get(resolved.fingerprint);
    if (cached) return cached;

    const adapter = new ZhihuAdapter({
      cookie: resolved.cookie,
      userAgent: resolved.userAgent,
      baseUrl: process.env.CITRUS_ZHIHU_BASE_URL || undefined,
      gapMs: this.config.gapMs,
      jitterMs: this.config.jitterMs,
      timeoutMs: this.config.timeoutMs,
      maxRetries: this.config.maxRetries,
      logger: this.logger
    });
    this.adapters.set(resolved.fingerprint, adapter);
    while (this.adapters.size > MAX_ADAPTERS) {
      const oldest = this.adapters.keys().next();
      if (oldest.done) break;
      this.adapters.delete(oldest.value);
    }
    return adapter;
  }

  /** 当前 Cookie 的指纹与来源，用于状态展示。 */
  describeCookie() {
    const resolved = resolveCookie(this.config, 'zhihu');
    return {
      configured: true,
      fingerprint: resolved.fingerprint,
      cookie_count: resolved.names.length,
      has_login: resolved.hasLogin,
      source: resolved.source,
      cookie_file: resolved.sourcePath
    };
  }

  dispose() {
    this.adapters.clear();
  }
}
