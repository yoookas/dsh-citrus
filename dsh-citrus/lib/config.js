/**
 * 插件配置（cordis.patch.yml 里那个 config）。
 *
 * 结构按平台分组，方便一个插件装多个平台：
 *
 *   platforms:
 *     zhihu: { cookie, hotLimit, ... }
 *     <下一个平台>: { ... }
 *
 * 新增平台的步骤：
 *   1. 这里加一个 `xxx: z.object({...})`；
 *   2. lib/platforms/ 下加适配器，并在 registry.js 的 PLATFORM_IDS 里登记；
 *   3. lib/client.js 的 PLATFORMS 数组里加一项（配置页会自动多一个 tab）。
 *
 * 数字都有上下界：模型/用户写错不会把请求节奏或上下文搞崩。
 */

import z from '@deepseek-ai/schemastery';
import { PLATFORM_DEFAULTS } from './platforms/registry.js';

/** 默认值只在 registry 里写一份，schema 和工具层都从它取。 */
const zhihu = PLATFORM_DEFAULTS.zhihu;

/**
 * 各家平台共有的连接与节流设置。
 * 每个平台一份：不同站点的限流策略不该互相牵连。
 * @param {object} defaults 该平台的默认值
 */
const transportFields = (defaults) => ({
  gapMs: z.natural().default(defaults.gapMs).max(10000).description('请求最小间隔（毫秒）。别长期设 0，那是给自己找风控'),
  jitterMs: z.natural().default(defaults.jitterMs).max(10000).description('请求随机抖动（毫秒）'),
  timeoutMs: z.natural().default(defaults.timeoutMs).min(1000).max(120000).description('单次上游请求超时（毫秒）'),
  maxRetries: z.natural().default(defaults.maxRetries).max(5).description('429/5xx/网络错误的重试次数')
});

/** 知乎：登录态 + 各工具默认条数。 */
export const ZhihuConfig = z.object({
  cookie: z.string().role('secret').default('').description(
    '知乎 Cookie：粘贴浏览器里的 Copy as cURL（也认 Cookie 头 / 裸 Cookie 串 / JSON）。留空则读 cookieFile。'
  ),
  cookieFile: z.string().default('').description(
    'Cookie 文件路径，留空使用 <DSH_HOME>/dsh-citrus/zhihu.cookie（推荐用 dsh-citrus auth 写入）。'
  ),
  hotLimit: z.natural().default(zhihu.hotLimit).min(1).max(30).description('热榜默认条数（知乎热榜最多 30 条，不给翻页）'),
  searchLimit: z.natural().default(zhihu.searchLimit).min(1).max(20).description('搜索默认条数'),
  commentLimit: z.natural().default(zhihu.commentLimit).min(1).max(100).description('评论默认条数'),
  contentChars: z.natural().default(zhihu.contentChars).min(200).max(16000).description('单条正文字数上限'),
  commentChars: z.natural().default(zhihu.commentChars).min(40).max(800).description('单条评论字数上限'),
  excerptChars: z.natural().default(zhihu.excerptChars).min(20).max(600).description('列表摘要字数上限'),
  relatedAnswers: z.natural().default(zhihu.relatedAnswers).min(0).max(5).description('读问题时附带几条高赞回答'),
  promptHint: z.boolean().default(zhihu.promptHint).description('消息提到知乎时，在系统提示词里提醒模型调用工具'),
  ...transportFields(zhihu)
});

export const Config = z.object({
  platforms: z.object({
    zhihu: ZhihuConfig
  })
});

// settings 只把带 volatile 标记的字段投影成表单；整棵 schema 标成可热更新，
// 界面上就能改下面这些字段，保存后 Loader 原地更新 config。
//
// 注意这是 schema 的 meta 标记（settings 读 Config.meta.volatile），不是 z(...).volatile()：
// 后者改的是校验输出类型（Volatile<T> 引用），跟表单无关。
Config.meta.volatile = true;
