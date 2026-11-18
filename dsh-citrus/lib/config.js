/**
 * 插件配置（cordis.patch.yml 里那个 config）。
 *
 * 数字都有上下界：模型/用户写错不会把请求节奏或上下文搞崩。
 */

import z from '@deepseek-ai/schemastery';

export const Config = z.object({
  cookie: z.string().role('secret').default('').description(
    '知乎 Cookie：粘贴浏览器里的 Copy as cURL（也认 Cookie 头 / 裸 Cookie 串 / JSON）。留空则读 cookieFile。'
  ),
  cookieFile: z.string().default('').description(
    'Cookie 文件路径，留空使用 <DSH_HOME>/dsh-citrus/zhihu.cookie（推荐用 dsh-citrus auth 写入）。'
  ),
  hotLimit: z.natural().default(10).min(1).max(30).description('热榜默认条数（知乎热榜最多 30 条，不给翻页）'),
  searchLimit: z.natural().default(8).min(1).max(20).description('搜索默认条数'),
  commentLimit: z.natural().default(20).min(1).max(100).description('评论默认条数'),
  contentChars: z.natural().default(1500).min(200).max(16000).description('单条正文字数上限'),
  commentChars: z.natural().default(200).min(40).max(800).description('单条评论字数上限'),
  excerptChars: z.natural().default(120).min(20).max(600).description('列表摘要字数上限'),
  relatedAnswers: z.natural().default(3).min(0).max(5).description('读问题时附带几条高赞回答'),
  gapMs: z.natural().default(350).max(10000).description('请求最小间隔（毫秒）。别长期设 0，那是给自己找风控'),
  jitterMs: z.natural().default(250).max(10000).description('请求随机抖动（毫秒）'),
  timeoutMs: z.natural().default(20000).min(1000).max(120000).description('单次上游请求超时（毫秒）'),
  maxRetries: z.natural().default(2).max(5).description('429/5xx/网络错误的重试次数'),
  promptHint: z.boolean().default(true).description('消息提到知乎时，在系统提示词里提醒模型调用工具')
});

// 桌面端设置只给标了 volatile 的字段生成表单；把整棵 schema 标成可热更新，
// 插件页会自动出现 Cookie/条数等配置表单，保存后 Loader 原地更新 config。
Config.meta.volatile = true;