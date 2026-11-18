/**
 * dsh-citrus 插件入口（Cordis 插件）。
 *
 * 两套配置并存：
 *   * 组合配置（cordis.patch.yml 的 config）—— 部署默认值；
 *   * 运行时设置（settings 命名空间 dsh-citrus）—— 用户在面板卡片里改，热生效。
 *
 * 工具、运行时、提示词都通过 getConfig() 读取当前值，所以设置一保存就换源。
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

/** 面板卡片写入的 settings 命名空间。 */
export const SETTINGS_NAMESPACE = 'dsh-citrus';

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
      clientModules: Boolean(ctx.get('clientModules'))
    });
  } catch (error) {
    diag('apply-error', { message: String(error) });
  }

  // 组合配置是底座；settings 服务在时，用户层覆盖它。
  let current = () => config;
  const getConfig = () => current() || {};

  ctx.inject(['settings'], (settingsCtx) => {
    diag('settings-inject', {
      hasInstallSection: Boolean(settingsCtx.settings && typeof settingsCtx.settings.installSection === 'function')
    });
    log('settings 服务可用，注册命名空间 ' + SETTINGS_NAMESPACE);
    const settings = settingsCtx.settings;
    try {
      if (typeof settings.installSection === 'function') {
        settings.installSection(ctx, SETTINGS_NAMESPACE, Config, config, {
          setSource: (source) => {
            current = source;
            try {
              diag('config-source', {
                hotLimit: source().hotLimit,
                cookieFile: source().cookieFile
              });
            } catch {
              /* 诊断不影响写入 */
            }
          },
          onChange: () => {}
        });
      } else if (typeof settings.register === 'function') {
        // 桌面端自带的 settings 服务没有 installSection 便捷方法，直接用 register。
        const scope = settings.register(SETTINGS_NAMESPACE, Config, { base: config });
        const read = () => {
          if (typeof scope.get === 'function') return scope.get();
          if (typeof scope.getSnapshot === 'function') {
            const snapshot = scope.getSnapshot();
            return snapshot && snapshot.value !== undefined ? snapshot.value : snapshot;
          }
          return config;
        };
        current = read;
        if (typeof scope.watch === 'function') {
          scope.watch(() => {
            try {
              diag('config-source', {
                hotLimit: read().hotLimit,
                cookieFile: read().cookieFile
              });
            } catch {
              /* 诊断不影响写入 */
            }
          });
        }
        diag('settings-register-fallback', {
          register: true,
          scopeGet: typeof scope.get,
          scopeWatch: typeof scope.watch
        });
      } else {
        throw new Error('settings 服务既没有 installSection 也没有 register');
      }
      diag('settings-registered', {
        namespaces: settings.describe({ redactSecrets: true }).map((row) => row.ns)
      });
    } catch (error) {
      diag('settings-install-error', { message: String(error) });
    }
  });

  const runtime = new CitrusRuntime(getConfig, log);
  ctx.effect(() => () => runtime.dispose());
  registerTools(ctx, getConfig, runtime, defineTool);
  registerPrompt(ctx, getConfig);
  log('已加载（知乎工具：zhihu_hot / zhihu_search / zhihu_read / zhihu_comments）');
}