/**
 * dsh-citrus 插件入口（Cordis 插件）。
 *
 * 配置来源：
 *   * 组合配置（cordis.patch.yml / bundle patch 里的 config）——默认值；
 *   * settings 里的用户覆盖（namespace = 条目 id `dsh-citrus`）——保存后 Loader 用新
 *     config 重新应用本插件，下一次工具调用就生效。
 *
 * 能不能在界面上改，取决于 config.js 里的 Config.meta.volatile 标记：settings 只把
 * volatile 字段投影成表单，且只认 cwd 里唯一命中的那个 profile 条目。
 *
 * 表单界面在浏览器半侧（lib/client.js），它通过 ctx.configForms 读写同一个命名空间；
 * 宿主这一侧只要导出 Config，不用注册任何 settings 命名空间。
 */

import { appendFileSync, mkdirSync } from 'node:fs';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { Config } from './config.js';
import { resolveConfig } from './platforms/registry.js';
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

  // 配置由 Loader 传入。标了 volatile 的 Config 拿到的是 Volatile 引用，
  // 每次调用都 resolve 一遍：面板保存后引用内容就地更新，下一次工具调用立即读到新值。
  const getConfig = () => resolveConfig(config);

  const runtime = new CitrusRuntime(getConfig, log);
  ctx.effect(() => () => runtime.dispose());
  registerTools(ctx, getConfig, runtime, defineTool);
  registerPrompt(ctx, getConfig);
  log('已加载（知乎工具：zhihu_hot / zhihu_search / zhihu_read / zhihu_comments）');
}
