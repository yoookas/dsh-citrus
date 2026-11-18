/**
 * 把知乎 v3/v4 的原始 JSON 摊平成统一模型。
 *
 * 字段名、卡片结构、热榜的 metric 文案、各种链接形态，全都收敛在这里；
 * adapter 只负责编排，不碰原始字段。
 */

import { htmlToText, plainExcerpt } from '../../core/html.js';
import { makeAuthor, makeComment, makeItem, makeParent, makeStats } from '../../core/model.js';
import { CitrusError } from '../../core/errors.js';

export const PLATFORM = 'zhihu';
export const PEOPLE_URL = 'https://www.zhihu.com/people/%s';
export const CONTENT_MAX = 16000;
export const EXCERPT_MAX = 200;

const ANSWER_IN_QUESTION = /zhihu\.com\/question\/(\d+)\/answer\/(\d+)/i;
const ANSWER = /(?:zhihu\.com\/answer\/|^answer[:/])(\d+)/i;
const QUESTION = /(?:zhihu\.com\/question\/|^question[:/])(\d+)/i;
const ARTICLE = /(?:zhuanlan\.zhihu\.com\/p\/|zhihu\.com\/p\/|^p[:/]|^article[:/])(\d+)/i;
const PEOPLE = /zhihu\.com\/(?:people|org)\/([\w\-.%]+)/i;
const PEOPLE_PREFIX = /^(?:user|people)[:/](.+)$/i;
const PIN = /(?:zhihu\.com\/pin\/|^pin[:/])(\d+)/i;
const ZVIDEO = /(?:zhihu\.com\/zvideo\/|^zvideo[:/])(\d+)/i;
const DIGITS = /^\d+$/;
const CARD = /^([QPA])_(\d+)$/;

const asDict = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : {});
const asStr = (value) => (typeof value === 'string' ? value : '');
const asInt = (value) => {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) && number > 0 ? number : 0;
};
const isDict = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/** 知乎链接 / 纯 id / 带前缀的 id -> { kind, id, questionId }。 */
export function parseRef(ref) {
  const text = String(ref || '').trim();
  if (!text) {
    throw new CitrusError('bad_request', '没给条目：ref 是空的。', '传知乎链接，或 answer:123 / question:123 / p:456 这种带前缀的 id。');
  }
  let match = ANSWER_IN_QUESTION.exec(text);
  if (match) return { kind: 'answer', id: match[2], questionId: match[1] };
  match = ANSWER.exec(text);
  if (match) return { kind: 'answer', id: match[1], questionId: '' };
  match = QUESTION.exec(text);
  if (match) return { kind: 'question', id: match[1], questionId: match[1] };
  match = ARTICLE.exec(text);
  if (match) return { kind: 'article', id: match[1], questionId: '' };
  match = PEOPLE.exec(text);
  if (match) return { kind: 'user', id: match[1], questionId: '' };
  match = PEOPLE_PREFIX.exec(text);
  if (match) return { kind: 'user', id: match[1], questionId: '' };
  match = PIN.exec(text);
  if (match) return { kind: 'pin', id: match[1], questionId: '' };
  match = ZVIDEO.exec(text);
  if (match) return { kind: 'zvideo', id: match[1], questionId: '' };
  if (DIGITS.test(text)) return { kind: 'unknown', id: text, questionId: '' };
  throw new CitrusError('bad_request', '认不出这个条目：' + text.slice(0, 80), '传知乎的回答/问题/文章链接，或带前缀的 id（answer:123）。');
}

export function webUrl(kind, itemId, questionId = '') {
  if (kind === 'answer') {
    return questionId
      ? 'https://www.zhihu.com/question/' + questionId + '/answer/' + itemId
      : 'https://www.zhihu.com/answer/' + itemId;
  }
  if (kind === 'question') return 'https://www.zhihu.com/question/' + itemId;
  if (kind === 'article') return 'https://zhuanlan.zhihu.com/p/' + itemId;
  if (kind === 'user') return 'https://www.zhihu.com/people/' + itemId;
  if (kind === 'pin') return 'https://www.zhihu.com/pin/' + itemId;
  if (kind === 'zvideo') return 'https://www.zhihu.com/zvideo/' + itemId;
  return 'https://www.zhihu.com/';
}

/** 把「1234 万热度」这种中文计数换成数字。 */
export function parseHeat(text) {
  const raw = String(text || '').replace(/,/g, '').trim();
  const match = /([\d.]+)\s*(亿|万)?/.exec(raw);
  if (!match) return 0;
  const number = Number.parseFloat(match[1]);
  if (!Number.isFinite(number)) return 0;
  const unit = match[2] === '亿' ? 1e8 : match[2] === '万' ? 1e4 : 1;
  return Math.round(number * unit);
}

function clipContent(html, limit) {
  const full = htmlToText(html);
  if (limit > 0 && full.length > limit) {
    return { text: full.slice(0, limit).replace(/\s+$/, '') + '\n…（后面还有，已截断）', truncated: true };
  }
  return { text: full, truncated: false };
}

export function normalizeAuthor(raw) {
  const author = asDict(raw);
  const token = asStr(author.url_token) || asStr(author.id);
  const name = asStr(author.name) || '匿名用户';
  return makeAuthor({
    id: token,
    name,
    url: token ? PEOPLE_URL.replace('%s', token) : '',
    handle: token,
    headline: asStr(author.headline),
    avatar: asStr(author.avatar_url)
  });
}

export function normalizeProfile(raw) {
  const person = asDict(raw);
  const token = asStr(person.url_token) || asStr(person.id);
  return {
    platform: PLATFORM,
    id: token,
    name: asStr(person.name) || token,
    handle: token,
    url: token ? PEOPLE_URL.replace('%s', token) : '',
    headline: asStr(person.headline),
    avatar: asStr(person.avatar_url),
    stats: makeStats(),
    extra: {
      answers: asInt(person.answer_count),
      articles: asInt(person.articles_count),
      followers: asInt(person.follower_count),
      description: asStr(person.description),
      gender: asStr(person.gender)
    }
  };
}

const KIND_WORDS = { answer: '回答', article: '文章', question: '问题', pin: '想法', zvideo: '视频' };

function normalizeWebUrl(url) {
  if (!url) return '';
  if (ANSWER_IN_QUESTION.test(url)) return url.replace('http://', 'https://');
  if (ARTICLE.test(url)) return url.replace('http://', 'https://');
  if (QUESTION.test(url)) return url.replace('http://', 'https://').split('?')[0];
  return '';
}

/** v3/v4 返回的一条（可能是 {target:{...}} 包装）-> 统一 item。 */
export function normalizeItem(raw, options = {}) {
  const source = options.source || '';
  const contentLimit = options.contentLimit || CONTENT_MAX;
  const wrap = asDict(raw);
  const target = asDict(wrap.target) && Object.keys(asDict(wrap.target)).length ? asDict(wrap.target) : wrap;
  const question = isDict(target.question) ? target.question : asDict(wrap.question);

  const rawUrl = asStr(target.url) || asStr(wrap.url);
  let guessed = {};
  if (rawUrl) {
    try {
      guessed = parseRef(rawUrl);
    } catch {
      guessed = {};
    }
  }

  let kind = (asStr(target.type) || asStr(wrap.type)).toLowerCase();
  if (kind === 'feed' || kind === 'feed_item') kind = '';
  if (!['answer', 'article', 'question', 'pin', 'zvideo', 'video'].includes(kind)) {
    const guessKind = guessed.kind || '';
    if (['answer', 'article', 'question', 'pin', 'zvideo'].includes(guessKind)) kind = guessKind;
    else if (question.id) kind = 'answer';
    else kind = 'question';
  }
  if (kind === 'video') kind = 'zvideo';

  let itemId = String(target.id || question.id || guessed.id || '');
  if (question.id && kind === 'answer') itemId = String(target.id || guessed.id || '');
  const questionId = String(question.id || target.question_id || guessed.question_id || '');

  const title = asStr(target.title)
    || asStr(question.title)
    || asStr(target.excerpt).slice(0, 60)
    || '知乎' + (KIND_WORDS[kind] || '内容') + ' ' + itemId;

  const contentHtml = asStr(target.content) || asStr(target.detail);
  const excerpt = asStr(target.excerpt) || plainExcerpt(contentHtml, EXCERPT_MAX);
  const clipped = clipContent(contentHtml, contentLimit);

  const metrics = asDict(target.metrics);
  const tags = Array.isArray(target.tags) ? target.tags : [];
  const stats = makeStats({
    likes: asInt(target.voteup_count || target.vote_count || metrics.voteup_count),
    comments: asInt(target.comment_count || metrics.comment_count),
    shares: asInt(target.reaction_count),
    views: asInt(target.visit_count || metrics.visit_count),
    heat: parseHeat(asStr(metrics.hot) || asStr(target.hot))
  });

  let parent = null;
  if (kind === 'answer' && questionId) {
    parent = makeParent('question', questionId, asStr(question.title), webUrl('question', questionId));
  }

  const extra = {};
  if (asStr(metrics.hot)) extra.hot_text = asStr(metrics.hot);
  if (tags.length) {
    const names = tags.filter(isDict).map((tag) => asStr(tag.name)).filter(Boolean);
    if (names.length) extra.tags = names;
  }

  const url = normalizeWebUrl(rawUrl) || webUrl(kind, itemId, questionId);
  return makeItem(PLATFORM, kind, itemId, {
    title,
    url,
    excerpt,
    content: clipped.text,
    contentTruncated: clipped.truncated,
    author: normalizeAuthor(target.author),
    parent,
    stats,
    createdAt: target.created_time || target.created,
    updatedAt: target.updated_time || target.updated,
    source,
    extra
  });
}

/** 热榜现在是 title_area / excerpt_area / metrics_area + card_id 的结构。 */
export function normalizeHotItem(row) {
  const card = asDict(row);
  if (!Object.keys(card).length) return null;
  const target = isDict(card.target) && Object.keys(card.target).length ? card.target : card;
  const cardId = asStr(card.card_id) || asStr(target.card_id);
  const newShape = isDict(target.title_area)
    || isDict(target.excerpt_area)
    || isDict(target.metrics_area)
    || CARD.test(cardId);

  if (!newShape) {
    const item = normalizeItem(row, { source: 'hot' });
    return item.id ? item : null;
  }

  let kind = 'question';
  let itemId = '';
  const cardMatch = CARD.exec(cardId);
  if (cardMatch) {
    kind = { Q: 'question', P: 'article', A: 'answer' }[cardMatch[1]];
    itemId = cardMatch[2];
  } else {
    itemId = String(target.id || card.id || '');
  }
  if (!itemId) return null;

  const questionId = String(asDict(target.question).id || target.question_id || '');
  const title = asStr(asDict(target.title_area).text)
    || asStr(target.title)
    || asStr(asDict(card.title_area).text);
  const excerpt = asStr(asDict(target.excerpt_area).text)
    || asStr(target.excerpt)
    || asStr(asDict(card.excerpt_area).text);
  const metricsText = asStr(asDict(target.metrics_area).text)
    || asStr(asDict(card.metrics_area).text);

  const extra = {};
  if (metricsText) extra.hot_text = metricsText;
  const answerCount = asInt(asDict(card.feed_specific).answer_count || target.answer_count);
  if (answerCount) extra.answer_count = answerCount;

  return makeItem(PLATFORM, kind, itemId, {
    title: title || '知乎热榜 ' + itemId,
    url: webUrl(kind, itemId, questionId),
    excerpt,
    stats: makeStats({ heat: parseHeat(metricsText) }),
    parent: kind === 'answer' && questionId ? makeParent('question', questionId, title) : null,
    source: 'hot',
    extra
  });
}

export function normalizeSearch(payload) {
  const rows = Array.isArray(asDict(payload).data) ? asDict(payload).data : [];
  const out = [];
  for (const row of rows) {
    const rowDict = asDict(row);
    if (asStr(rowDict.type).toLowerCase() !== 'search_result') continue;
    const obj = asDict(rowDict.object);
    if (!Object.keys(obj).length) continue;
    if (asStr(obj.type).toLowerCase() === 'people') {
      const token = asStr(obj.url_token) || asStr(obj.id);
      if (!token) continue;
      out.push(makeItem(PLATFORM, 'user', token, {
        title: asStr(obj.name) || token,
        url: PEOPLE_URL.replace('%s', token),
        excerpt: asStr(obj.headline),
        author: makeAuthor({
          id: token,
          name: asStr(obj.name),
          url: PEOPLE_URL.replace('%s', token),
          handle: token,
          headline: asStr(obj.headline),
          avatar: asStr(obj.avatar_url)
        }),
        source: 'search',
        extra: { followers: asInt(obj.follower_count) }
      }));
      continue;
    }
    const item = normalizeItem(obj, { source: 'search' });
    if (item.id) out.push(item);
  }
  return out;
}

export function normalizeFeed(payload, source) {
  const rows = Array.isArray(asDict(payload).data) ? asDict(payload).data : [];
  const out = [];
  for (const row of rows) {
    const rowDict = asDict(row);
    if (!Object.keys(rowDict).length) continue;
    if (['ad', 'ad_feed'].includes(asStr(rowDict.type).toLowerCase())) continue;
    const target = isDict(rowDict.target) && Object.keys(rowDict.target).length ? rowDict.target : rowDict;
    if (asStr(target.type).toLowerCase() === 'ad') continue;
    const item = normalizeItem(rowDict, { source });
    if (item.id) out.push(item);
  }
  return out;
}

export function normalizeComment(raw, parentId = '') {
  const row = asDict(raw);
  return makeComment(PLATFORM, String(row.id || ''), {
    author: normalizeAuthor(row.author),
    content: htmlToText(asStr(row.content), { maxChars: 1200 }),
    likes: asInt(row.vote_count || row.like_count),
    replies: asInt(row.reply_count || row.child_comment_count),
    createdAt: row.created_time || row.created,
    parentId
  });
}

export function normalizeComments(payload, parentId = '') {
  const rows = Array.isArray(asDict(payload).data) ? asDict(payload).data : [];
  return rows.filter(isDict).map((row) => normalizeComment(row, parentId));
}
