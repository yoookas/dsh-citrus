/**
 * 系统提示词指引：让模型知道「知乎内容要现场抓，不要凭记忆编」。
 *
 * 只有工具在当前会话可见时才输出这段文字（和 web 工具的做法一致）。
 */

const HINT = [
  '需要知乎内容（热榜、某个问题、回答正文、评论区观点）时，调用 zhihu_hot / zhihu_search / zhihu_read / zhihu_comments 获取真实数据。',
  '不要凭记忆编造知乎上的内容、数字或链接；引用时附上工具返回的知乎链接。',
  '工具返回的正文已经是纯文本；如果内容被截断，可以再用 zhihu_read 读同一条并调整 content_chars。'
].join(' ');

export function registerPrompt(ctx, config) {
  if (config.promptHint === false) return null;
  return ctx.systemPrompt.section({
    name: 'tool:zhihu',
    order: 3000,
    text: ({ scope }) => {
      const visible = ctx.tools.get('zhihu_hot', scope) !== undefined
        || ctx.tools.get('zhihu_search', scope) !== undefined;
      return visible && config.promptHint !== false ? HINT : '';
    }
  });
}
