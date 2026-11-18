/**
 * dsh-citrus 插件入口（Cordis 插件）。
 *
 * 工具注册与提示词段落都是 fiber 作用域的：插件被卸载/重载时自动清理。
 */

import { mkdirSync } from 'node:fs';
import { Config } from './config.js';
import { registerPrompt } from './prompt.js';
import { CitrusRuntime } from './runtime.js';
import { dataDir } from './store.js';
import { registerTools } from './tools.js';

export const name = 'dsh-citrus';

/** 依赖的服务：没有工具注册表或系统提示词就不激活。 */
export const inject = ['tools', 'systemPrompt'];

export { Config };

/**
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {object} config
 */
export function apply(ctx, config) {
  const logger = typeof ctx.logger === 'function' ? ctx.logger('dsh-citrus') : console;
  const log = (message) => {
    try {
      logger.info(message);
    } catch {
      /* 日志失败不该影响工具 */
    }
  };

  try {
    mkdirSync(dataDir(), { recursive: true });
  } catch {
    /* 建不了目录不影响工具，真正写 Cookie 时会再报错 */
  }

  const runtime = new CitrusRuntime(config, log);
  ctx.effect(() => () => runtime.dispose());
  registerTools(ctx, config, runtime);
  registerPrompt(ctx, config);
  log('已加载（知乎工具：zhihu_hot / zhihu_search / zhihu_read / zhihu_comments）');
}
