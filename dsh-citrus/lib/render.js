/**
 * 把统一数据模型渲染成给模型看的紧凑文本（Native 模式用；PTC 模式拿到的是结构化 JSON）。
 *
 * 原则：够判断、又不撑爆上下文；链接永远保留；绝不输出 cookie。
 */

const KIND_LABELS = {
  answer: '回答', article: '文章', question: '问题', pin: '想法',
  video: '视频', zvideo: '视频', user: '用户', topic: '话题', collection: '收藏夹'
};

export const kindLabel = (kind) => KIND_LABELS[kind] || '内容';

export function compactNumber(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return '';
  if (number >= 1e8) return (number / 1e8).toFixed(1) + '亿';
  if (number >= 1e4) return (number / 1e4).toFixed(1) + '万';
  return String(Math.round(number));
}

export function oneline(value, limit = 0) {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  if (limit > 0 && text.length > limit) text = text.slice(0, limit).replace(/\s+$/, '') + '…';
  return text;
}

export function multiline(value, limit = 0) {
  const lines = String(value || '').trim().split(/\r?\n/).map((line) => line.replace(/\s+$/, ''));
  let text = lines.filter((line) => line.trim()).join('\n');
  if (!text) return '';
  if (limit > 0 && text.length > limit) text = text.slice(0, limit).replace(/\s+$/, '') + '…';
  return text;
}

function statsLine(stats = {}) {
  const parts = [];
  for (const [key, label] of [['likes', '赞'], ['comments', '评论'], ['heat', '热度'], ['views', '浏览']]) {
    const value = compactNumber(stats[key]);
    if (value) parts.push(value + label);
  }
  return parts.join(' · ');
}

function itemMeta(item) {
  const parts = [];
  if (item.heat_text) parts.push(item.heat_text);
  const stats = statsLine(item.stats || {});
  if (stats) parts.push(stats);
  if (item.answer_count) parts.push(compactNumber(item.answer_count) + ' 个回答');
  return parts.join(' · ');
}

function itemLine(index, item, excerptLimit = 120) {
  const lines = [];
  const title = oneline(item.title || item.excerpt, 90) || '（无标题）';
  const meta = itemMeta(item);
  lines.push(index + '. 【' + kindLabel(item.kind) + '】' + title + (meta ? '｜' + meta : ''));
  if (item.url) lines.push('   ' + item.url);
  const excerpt = oneline(item.excerpt, excerptLimit);
  if (excerpt && excerpt !== title) lines.push('   摘要：' + excerpt);
  return lines;
}

/** 把统一 item 压成工具返回里的紧凑条目。 */
export function summarizeItem(item) {
  return {
    kind: item.kind,
    id: item.id,
    title: item.title,
    url: item.url,
    excerpt: oneline(item.excerpt, 300),
    stats: item.stats,
    ...(item.extra && item.extra.hot_text ? { heat_text: item.extra.hot_text } : {}),
    ...(item.extra && item.extra.answer_count ? { answer_count: item.extra.answer_count } : {})
  };
}

export function renderHot(result, options = {}) {
  const items = (result.items || []).slice(0, options.maxItems || 10);
  if (!items.length) return '知乎热榜这次没有拿到内容。';
  const lines = ['知乎热榜（共 ' + (result.count || items.length) + ' 条）'];
  items.forEach((item, index) => lines.push(...itemLine(index + 1, item, options.excerptChars || 120)));
  return lines.join('\n');
}

export function renderSearch(result, options = {}) {
  const items = (result.items || []).slice(0, options.maxItems || 8);
  const head = result.query ? '知乎搜索「' + result.query + '」' : '知乎搜索结果';
  if (!items.length) return head + '：没有匹配结果。';
  const lines = [head + '（本次 ' + items.length + ' 条）'];
  items.forEach((item, index) => lines.push(...itemLine(index + 1, item, options.excerptChars || 120)));
  return lines.join('\n');
}

export function renderItem(item, options = {}) {
  const title = oneline(item.title, 120);
  const author = (item.author && item.author.name) || '';
  const stats = statsLine(item.stats || {});
  const lines = [];
  let head = '【' + kindLabel(item.kind) + '】' + title;
  if (author) head += '｜作者：' + author;
  if (stats) head += '｜' + stats;
  lines.push(head);

  if (item.parent && item.parent.title) lines.push('所属问题：' + oneline(item.parent.title, 120));
  if (item.url) lines.push('链接：' + item.url);

  const body = multiline(item.content, options.contentChars || 1500);
  if (body) {
    lines.push('正文：');
    lines.push(body);
  } else {
    const excerpt = multiline(item.excerpt, options.contentChars || 1500);
    if (excerpt) {
      lines.push('摘要：');
      lines.push(excerpt);
    }
  }

  const related = (item.related || []).slice(0, options.related || 3);
  if (related.length) {
    lines.push('其他高赞回答（' + related.length + ' 条，已截断）：');
    related.forEach((row, index) => {
      const who = (row.author && row.author.name) || '匿名用户';
      const likes = compactNumber(row.stats && row.stats.likes);
      lines.push((index + 1) + '. ' + who + (likes ? '（' + likes + ' 赞）' : ''));
      const text = multiline(row.content || row.excerpt, options.relatedChars || 600);
      if (text) lines.push(text);
    });
  }
  return lines.join('\n');
}

export function renderComments(result, options = {}) {
  const items = (result.items || []).slice(0, options.maxItems || 30);
  const total = result.total;
  let head = '评论';
  if (total) head += '（上游共 ' + total + ' 条，本次 ' + items.length + ' 条）';
  else head += '（本次 ' + items.length + ' 条）';
  if (!items.length) {
    if (result.errors && result.errors.length) {
      return head + '：这次没读到评论（' + result.errors.map((row) => row.code).join('、') + '）。';
    }
    return head + '：没有评论。';
  }
  const lines = [head];
  items.forEach((row, index) => {
    const who = (row.author && row.author.name) || '匿名用户';
    const meta = [];
    if (row.likes) meta.push(compactNumber(row.likes) + ' 赞');
    if (row.replies) meta.push(compactNumber(row.replies) + ' 回复');
    const suffix = meta.length ? '（' + meta.join(' / ') + '）' : '';
    lines.push((index + 1) + '. ' + who + suffix + '：' + oneline(row.content, options.contentChars || 200));
  });
  return lines.join('\n');
}
