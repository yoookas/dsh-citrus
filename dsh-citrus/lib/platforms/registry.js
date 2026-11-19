/**
 * 平台注册表：目前支持哪些平台，以及「配置里怎么取某个平台那一段」。
 *
 * 这个文件故意不 import 任何宿主包（也不 import schemastery）：
 * 工具层和测试都要用它，而 CI 不装宿主依赖。
 * schema 本身在 lib/config.js，适配器在 lib/platforms/<id>/。
 */

/** 目前支持的平台 id（配置结构、配置页 tab 都以它为准）。 */
export const PLATFORM_IDS = ['zhihu'];

/**
 * 各平台的默认值。
 *
 * schema 的默认值（lib/config.js）和工具层的兜底（lib/tools.js）都从这里取：
 * 同一个数字只写一遍，免得改了一处忘了另一处。
 */
export const PLATFORM_DEFAULTS = {
  zhihu: {
    cookie: '',
    hotLimit: 10,
    searchLimit: 8,
    commentLimit: 20,
    contentChars: 1500,
    commentChars: 200,
    excerptChars: 120,
    relatedAnswers: 3,
    gapMs: 350,
    jitterMs: 250,
    timeoutMs: 20000,
    maxRetries: 2,
    promptHint: true
  }
};

/** 翻页上限：页数再多上游也没有内容了（适配器和工具层的 clamp 都用它）。 */
export const PAGE_MAX = 10;

/**
 * 各平台字段的取值上下界，写成 [min, max]。
 *
 * schema（lib/config.js）和工具层（lib/tools.js）都从这里取。
 * 面板（lib/client.js）是独立 bundle、加载不到宿主模块，那边只能写字面量，
 * 由 tests/client.test.mjs 比对两者，防止改了一处忘了另一处。
 */
export const PLATFORM_BOUNDS = {
  zhihu: {
    hotLimit: [1, 30],
    searchLimit: [1, 20],
    commentLimit: [1, 100],
    contentChars: [200, 16000],
    commentChars: [40, 800],
    excerptChars: [20, 600],
    relatedAnswers: [0, 5],
    gapMs: [0, 10000],
    jitterMs: [0, 10000],
    timeoutMs: [1000, 120000],
    maxRetries: [0, 5]
  }
};

/**
 * 解开插件收到的 config。
 *
 * `Config.meta.volatile = true` 时，Cordis 为了「改配置不重挂插件」，交给 apply 的不是
 * 普通对象，而是一个冻结的 Volatile 引用 `{ get() }`（见 cosmokit 的 createVolatile）。
 * 直接读它的字段全拿到 undefined——面板上改完值看起来保存了，实际一次都没生效。
 *
 * 这里 duck-type 认它：Volatile 只有一个可枚举键 `get`（写入符号不是可枚举键），
 * 所以不引入 cosmokit 也能认准，工具层和测试都不用装宿主包。
 * @param {unknown} value apply 收到的 config（普通对象或 Volatile 引用）
 * @returns {object} 当前生效的配置对象
 */
export function resolveConfig(value) {
  if (value === null || value === undefined) return {};
  if (typeof value === 'object' && typeof value.get === 'function' && Object.keys(value).length === 1) {
    const inner = value.get();
    return inner && typeof inner === 'object' ? inner : {};
  }
  return typeof value === 'object' ? value : {};
}

/**
 * 取某个平台那一段配置。
 *
 * 所有消费方都走这里，而不是直接读 `config.xxx`：平台字段的层级只在这一处出现，
 * 以后调整目录结构不用把整仓 grep 一遍。
 *
 * 兼容旧版扁平配置（26.11.03 及以前字段直接在顶层）：那种 config 没有 `platforms`，
 * 就把整份配置当成第一个平台那一段。升级后即使 Loader 还拿着旧结构也不会崩。
 * @param {object} config 插件整体配置
 * @param {string} [platform] 平台 id
 * @returns {object} 该平台的配置段（缺失时返回空对象）
 */
export function platformConfig(config, platform = 'zhihu') {
  if (!config || typeof config !== 'object') return {};
  const platforms = config.platforms;
  if (platforms === undefined) {
    // 旧版扁平结构：只有第一个平台能从顶层字段里读。
    return platform === PLATFORM_IDS[0] ? config : {};
  }
  const section = typeof platforms === 'object' && platforms !== null ? platforms[platform] : undefined;
  return section && typeof section === 'object' ? section : {};
}
