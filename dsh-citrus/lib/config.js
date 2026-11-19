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
import { PLATFORM_BOUNDS, PLATFORM_DEFAULTS } from './platforms/registry.js';

/** 默认值和上下界都只在 registry 里写一份，schema 和工具层都从它取。 */
const zhihu = PLATFORM_DEFAULTS.zhihu;
const bounds = PLATFORM_BOUNDS.zhihu;

/** 按 registry 的上下界给一个自然数补 min/max。 */
const bounded = (key) => z.natural().default(zhihu[key]).min(bounds[key][0]).max(bounds[key][1]);

/**
 * 各家平台共有的连接与节流设置。
 * 每个平台一份：不同站点的限流策略不该互相牵连。
 */
const transportFields = () => ({
  gapMs: bounded('gapMs').description('请求最小间隔（毫秒）。别长期设 0，那是给自己找风控'),
  jitterMs: bounded('jitterMs').description('请求随机抖动（毫秒）'),
  timeoutMs: bounded('timeoutMs').description('单次上游请求超时（毫秒）'),
  maxRetries: bounded('maxRetries').description('429/5xx/网络错误的重试次数')
});

/** 知乎：登录态 + 各工具默认条数。 */
export const ZhihuConfig = z.object({
  cookie: z.string().role('secret').default(zhihu.cookie).description(
    '知乎 Cookie：把浏览器里 Copy as cURL 的内容粘进来（也认 Cookie 头 / 裸 Cookie 串 / JSON）。这是唯一的登录态来源，在「设置 → citrus」里填写。'
  ),
  hotLimit: bounded('hotLimit').description('热榜默认条数（知乎热榜最多 30 条，不给翻页）'),
  searchLimit: bounded('searchLimit').description('搜索默认条数'),
  commentLimit: bounded('commentLimit').description('评论默认条数'),
  contentChars: bounded('contentChars').description('单条正文字数上限'),
  commentChars: bounded('commentChars').description('单条评论字数上限'),
  excerptChars: bounded('excerptChars').description('列表摘要字数上限'),
  relatedAnswers: bounded('relatedAnswers').description('读问题时附带几条高赞回答'),
  promptHint: z.boolean().default(zhihu.promptHint).description('消息提到知乎时，在系统提示词里提醒模型调用工具'),
  ...transportFields()
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
