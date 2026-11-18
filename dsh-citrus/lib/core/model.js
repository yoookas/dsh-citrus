/**
 * 统一数据模型 —— 不管底层是知乎还是别的平台，模型看到的是同一个形状。
 *
 * 键永远存在、类型永远稳定：列表项不会一会儿有 content 一会儿没有。
 */

export const CONTENT_KINDS = new Set([
  'answer', 'article', 'question', 'post', 'pin',
  'video', 'zvideo', 'user', 'topic', 'collection', 'other'
]);

export function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/** epoch 秒/毫秒或 ISO 字符串 -> ISO 8601（UTC，带 Z）。 */
export function toIso(value) {
  if (value === null || value === undefined || value === '' || value === 0) return null;
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return null;
    if (text.endsWith('Z') || text.endsWith('+00:00')) return text;
    const numeric = Number(text);
    if (Number.isFinite(numeric)) return toIso(numeric);
    return text;
  }
  let number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return null;
  if (number > 1e12) number /= 1000;
  try {
    return new Date(number * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
  } catch {
    return null;
  }
}

export function makeAuthor(fields = {}) {
  return {
    id: fields.id || '',
    name: fields.name || '',
    handle: fields.handle || '',
    url: fields.url || '',
    headline: fields.headline || '',
    avatar: fields.avatar || ''
  };
}

export function makeStats(fields = {}) {
  return {
    likes: Number(fields.likes || 0),
    comments: Number(fields.comments || 0),
    shares: Number(fields.shares || 0),
    views: Number(fields.views || 0),
    heat: Number(fields.heat || 0)
  };
}

export function makeItem(platform, kind, id, fields = {}) {
  return {
    platform,
    kind: CONTENT_KINDS.has(kind) ? kind : 'other',
    id: String(id || ''),
    url: fields.url || '',
    title: fields.title || '',
    excerpt: fields.excerpt || '',
    content: fields.content || '',
    content_truncated: Boolean(fields.contentTruncated),
    author: fields.author || makeAuthor(),
    parent: fields.parent || null,
    stats: fields.stats || makeStats(),
    created_at: toIso(fields.createdAt),
    updated_at: toIso(fields.updatedAt),
    source: fields.source || '',
    related: fields.related || [],
    extra: fields.extra || {}
  };
}

export function makeParent(kind, id, title = '', url = '') {
  if (!id) return null;
  return { kind, id: String(id), title: title || '', url: url || '' };
}

export function makePage(items, fields = {}) {
  const rows = [...items];
  return {
    items: rows,
    count: rows.length,
    page: Number(fields.page || 1),
    has_more: Boolean(fields.hasMore),
    next_page: fields.hasMore ? Number(fields.page || 1) + 1 : null,
    source: fields.source || '',
    ...(fields.total !== undefined && fields.total !== null ? { total: Number(fields.total) } : {}),
    ...(fields.errors && fields.errors.length ? { errors: fields.errors } : {})
  };
}

export function makeComment(platform, id, fields = {}) {
  return {
    platform,
    id: String(id || ''),
    author: fields.author || makeAuthor(),
    content: fields.content || '',
    likes: Number(fields.likes || 0),
    replies: Number(fields.replies || 0),
    created_at: toIso(fields.createdAt),
    url: fields.url || '',
    parent_id: fields.parentId || ''
  };
}
