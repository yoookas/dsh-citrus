/**
 * 运行时：把「配置 -> Cookie -> 适配器」这条链路管起来。
 *
 * 配置来自一个 getter：面板里保存设置后返回的是新对象，适配器随之重建；
 * 换 Cookie（重新 auth）后指纹变了也会换适配器，旧缓存一起丢掉。
 */

import { ZhihuAdapter } from './platforms/zhihu/adapter.js';
import { resolveCookie } from './store.js';

const MAX_ADAPTERS = 4;

export class CitrusRuntime {
  /**
   * @param {() => object} getConfig 当前生效配置（组合配置或 settings 覆盖后的值）
   * @param {(message: string) => void} [logger]
   */
  constructor(getConfig, logger = () => {}) {
    this.getConfig = typeof getConfig === 'function' ? getConfig : () => getConfig;
    this.logger = logger;
    this.adapters = new Map();
    this.lastFingerprint = '';
    this.lastConfig = null;
  }

  /** 当前 Cookie 对应的知乎适配器。 */
  adapter() {
    const config = this.getConfig() || {};
    if (config !== this.lastConfig) {
      // 设置变了：节流/超时/条数都可能变，旧适配器不再可靠
      this.adapters.clear();
      this.lastConfig = config;
      this.lastFingerprint = '';
    }

    const resolved = resolveCookie(config, 'zhihu');
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
      gapMs: config.gapMs,
      jitterMs: config.jitterMs,
      timeoutMs: config.timeoutMs,
      maxRetries: config.maxRetries,
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
    const resolved = resolveCookie(this.getConfig() || {}, 'zhihu');
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
