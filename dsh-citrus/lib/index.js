/**
 * dsh-citrus 插件入口（Cordis 插件）。
 *
 * 配置来源：
 *   * 组合配置（cordis.patch.yml / bundle patch 里的 config）——默认值；
 *   * 桌面端 settings 会自动从本插件导出的 Config 生成表单（namespace = 条目 id
 *     dsh-citrus），保存后 Loader 会用新 config 重新应用本插件。
 *
 * 所以这里不需要手动注册 settings 命名空间：桌面端没有 installSection / register，
 * 它靠 Config schema 自动投影表单。
 */

import { appendFileSync, mkdirSync } from 'node:fs';
import { defineTool } from '@deepseek-ai/dsh-tools';
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

  const diag = (event, data = {}) => {
    try {
      appendFileSync(
        dataDir() + '/diag.log',
        JSON.stringify({ at: new Date().toISOString(), event, ...data }) + '\n',
        'utf8'
      );
    } catch {
      /* 诊断日志失败不影响插件 */
    }
  };

  try {
    mkdirSync(dataDir(), { recursive: true });
  } catch {
    /* 建不了目录不影响工具，真正写 Cookie 时会再报错 */
  }

  try {
    const settingsNow = ctx.get('settings');
    diag('apply', {
      settingsNow: Boolean(settingsNow),
      hasInstallSection: Boolean(settingsNow && typeof settingsNow.installSection === 'function'),
      hasRegister: Boolean(settingsNow && typeof settingsNow.register === 'function'),
      clientModules: Boolean(ctx.get('clientModules'))
    });
  } catch (error) {
    diag('apply-error', { message: String(error) });
  }

  // 配置由 Loader 传入；桌面端设置保存后会以新 config 重新应用插件。
  const getConfig = () => config || {};

  const runtime = new CitrusRuntime(getConfig, log);
  ctx.effect(() => () => runtime.dispose());
  registerTools(ctx, getConfig, runtime, defineTool);
  registerPrompt(ctx, getConfig);
  log('已加载（知乎工具：zhihu_hot / zhihu_search / zhihu_read / zhihu_comments）');
}
