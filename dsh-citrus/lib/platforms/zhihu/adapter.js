/**
 * 知乎适配器 —— 把统一能力接到知乎的具体接口上。
 *
 * 编排逻辑全在这里：选接口、限条数、翻页、缓存；字段层面的脏活在 normalize.js。
 */

import { TtlCache } from '../../core/cache.js';
import { CitrusError } from '../../core/errors.js';
import { PacedHttpClient } from '../../core/http.js';
import { makePage, nowIso } from '../../core/model.js';
import * as endpoints from './endpoints.js';
import * as normalize from './normalize.js';

export const PLATFORM = 'zhihu';
export const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

export const BROWSER_HEADERS = {
  referer: 'https://www.zhihu.com/',
  origin: 'https://www.zhihu.com',
  'x-requested-with': 'XMLHttpRequest',
  'x-api-version': '3.0.91'
};

const RAW_TTL = 300000;
const COMMENT_TTL = 120000;

export const MAX_HOT = 30;
export const MAX_SEARCH = 100;
export const MAX_COMMENTS = 100;
const MAX_PAGE = 10;
const SEARCH_PAGE_BUDGET = 6;
const COMMENT_PAGE_BUDGET = 8;

export const COMMENT_SORTS = {
  hot: 'hot', score: 'hot', default: 'hot',
  new: 'new', ts: 'new', time: 'new', latest: 'new'
};

const clamp = (value, low, high, fallback) => {
  const number = Number.parseInt(value, 10);
  const base = Number.isFinite(number) ? number : fallback;
  return Math.max(low, Math.min(high, base));
};

const upstreamTotal = (payload) => {
  const counts = payload && payload.counts;
  if (counts && typeof counts.total_counts === 'number' && counts.total_counts >= 0) return counts.total_counts;
  const paging = payload && payload.paging;
  if (paging && typeof paging.totals === 'number' && paging.totals >= 0) return paging.totals;
  return null;
};

const hasMore = (total, offset, returned, count) => {
  if (returned <= 0) return false;
  if (total !== null) return offset + returned < total;
  return returned >= count;
};

export function normalizeSort(value) {
  const key = String(value || '').trim().toLowerCase();
  if (!key) return 'hot';
  const resolved = COMMENT_SORTS[key];
  if (!resolved) {
    throw new CitrusError('bad_request', '不认识的评论排序：' + value, '支持 sort=hot（默认，按热度）或 sort=new（按时间倒序）。');
  }
  return resolved;
}

export class ZhihuAdapter {
  /**
   * @param {object} options
   * @param {string} options.cookie
   * @param {string} [options.userAgent]
   * @param {string} [options.baseUrl]
   * @param {number} [options.gapMs]
   * @param {number} [options.jitterMs]
   * @param {number} [options.timeoutMs]
   * @param {number} [options.maxRetries]
   * @param {(message: string) => void} [options.logger]
   */
  constructor(options) {
    this.cookie = options.cookie || '';
    this.userAgent = options.userAgent || DEFAULT_UA;
    this.cache = new TtlCache(256);
    this.client = new PacedHttpClient({
      baseUrl: options.baseUrl || endpoints.BASE_URL,
      gapMs: options.gapMs,
      jitterMs: options.jitterMs,
      timeoutMs: options.timeoutMs,
      maxRetries: options.maxRetries,
      headers: {
        ...BROWSER_HEADERS,
        'user-agent': this.userAgent,
        cookie: this.cookie
      },
      logger: options.logger
    });
  }

  get(spec, signal) {
    const [path, params] = spec;
    return this.client.getJson(path, { params, signal });
  }

  cached(key, ttlMs, loader) {
    const hit = this.cache.get(key, MESSAGE_MISS);
    if (hit !== MESSAGE_MISS) return hit;
    return this.cache.set(key, loader(), ttlMs);
  }

  // ---- account ------------------------------------------------------

  async account(signal) {
    const payload = await this.get(endpoints.me(), signal);
    return {
      platform: PLATFORM,
      configured: true,
      cookie_hint: '',
      profile: normalize.normalizeProfile(payload),
      fetched_at: nowIso()
    };
  }

  // ---- hot ----------------------------------------------------------

  async hot(limit = 20, options = {}) {
    const count = clamp(limit, 1, MAX_HOT, 20);
    const payload = await this.get(endpoints.hot(count), options.signal);
    const rows = payload && Array.isArray(payload.data) ? payload.data : [];
    let items = [];
    for (const row of rows) {
      const item = normalize.normalizeHotItem(row);
      if (item) items.push(item);
    }
    if (!items.length) items = normalize.normalizeFeed(payload, 'hot');
    items = items.slice(0, count);
    if (!items.length) {
      throw new CitrusError('bad_upstream_response', '热榜接口通了，但没解析出条目。', '知乎可能改版了。');
    }
    return makePage(items, { page: 1, hasMore: false, source: 'hot' });
  }

  // ---- search -------------------------------------------------------

  async search(query, limit = 20, options = {}) {
    const text = String(query || '').trim();
    if (!text) throw new CitrusError('bad_request', '需要一个查询关键词。', '例如 query="大模型"。');
    const count = clamp(limit, 1, MAX_SEARCH, 20);
    const page = clamp(options.page, 1, MAX_PAGE, 1);
    const wanted = String(options.kind || '').trim().toLowerCase();

    const items = [];
    const seen = new Set();
    let cursor = (page - 1) * count;
    let pages = 0;
    let payload = null;

    while (items.length < count && pages < SEARCH_PAGE_BUDGET) {
      pages += 1;
      payload = await this.get(endpoints.search(text, count - items.length, cursor, wanted), options.signal);
      const chunk = normalize.normalizeSearch(payload);
      for (const row of chunk) {
        if (wanted && row.kind !== wanted) continue;
        const key = row.kind + ':' + row.id;
        if (seen.has(key)) continue;
        seen.add(key);
        items.push(row);
      }
      if (chunk.length < endpoints.SEARCH_PAGE_CAP) break;
      cursor += chunk.length;
    }

    const errors = [];
    if (!items.length && payload && Array.isArray(payload.data) && payload.data.length) {
      errors.push({
        source: 'search',
        code: 'no_usable_results',
        message: '上游这一页只返回了广告/推荐位（' + payload.data.length + ' 行），没有可用条目。'
      });
    }
    return makePage(items.slice(0, count), {
      page,
      hasMore: items.slice(0, count).length >= count,
      source: 'search',
      errors
    });
  }

  // ---- item ---------------------------------------------------------

  async item(ref, options = {}) {
    const resolved = this.resolve(ref, options.kind, options.id);
    const contentLimit = clamp(options.contentLimit, 0, normalize.CONTENT_MAX, normalize.CONTENT_MAX) || normalize.CONTENT_MAX;
    const related = Boolean(options.related);

    if (resolved.kind === 'unknown') {
      const item = await this.itemByTrial(resolved.id, contentLimit);
      if (related) await this.attachRelated(item, resolved);
      return item;
    }
    const item = await this.loadItem(resolved.kind, resolved.id, contentLimit);
    if (related) await this.attachRelated(item, resolved);
    return item;
  }

  resolve(ref, kind, id) {
    if (kind && id) return { kind: String(kind).trim().toLowerCase(), id: String(id), questionId: '' };
    if (ref) {
      const resolved = normalize.parseRef(ref);
      if (kind) resolved.kind = String(kind).trim().toLowerCase();
      return resolved;
    }
    throw new CitrusError('bad_request', '要么给 ref（链接或 id），要么给 kind + id。', '例如 ref=https://www.zhihu.com/question/1/answer/2');
  }

  async itemByTrial(itemId, contentLimit) {
    let lastError = null;
    for (const candidate of ['answer', 'question', 'article']) {
      try {
        return await this.loadItem(candidate, itemId, contentLimit);
      } catch (error) {
        if (!(error instanceof CitrusError) || !['not_found', 'bad_upstream_response'].includes(error.code)) throw error;
        lastError = error;
      }
    }
    throw lastError || new CitrusError('not_found', '找不到 id=' + itemId + ' 的内容。');
  }

  async loadItem(kind, itemId, contentLimit) {
    const key = 'item:' + kind + ':' + itemId + ':' + contentLimit;
    return this.cached(key, RAW_TTL, async () => {
      const raw = await this.fetchRaw(kind, itemId);
      if (kind === 'question') return this.questionItem(raw, itemId, contentLimit);
      if (kind === 'pin') {
        const item = normalize.normalizeItem({ ...raw, type: 'pin', id: itemId }, { source: 'item', contentLimit });
        item.kind = 'pin';
        item.id = String(itemId);
        item.url = normalize.webUrl('pin', itemId);
        return item;
      }
      if (kind === 'zvideo') {
        const item = normalize.normalizeItem({ ...raw, type: 'zvideo', id: itemId }, { source: 'item', contentLimit });
        item.kind = 'zvideo';
        item.id = String(itemId);
        item.url = normalize.webUrl('zvideo', itemId);
        item.content = String(raw.description || '');
        return item;
      }
      if (kind === 'article') {
        const item = normalize.normalizeItem({ ...raw, type: 'article' }, { source: 'item', contentLimit });
        item.kind = 'article';
        item.id = String(item.id || itemId);
        item.url = item.url || normalize.webUrl('article', String(itemId));
        return item;
      }
      const item = normalize.normalizeItem(raw, { source: 'item', contentLimit });
      item.kind = 'answer';
      item.id = String(item.id || itemId);
      const question = raw && raw.question ? raw.question : {};
      const questionId = String(question.id || '');
      if (questionId) {
        item.url = normalize.webUrl('answer', item.id, questionId);
        item.parent = {
          kind: 'question',
          id: questionId,
          title: String(question.title || ''),
          url: normalize.webUrl('question', questionId)
        };
      }
      return item;
    });
  }

  async fetchRaw(kind, itemId) {
    if (kind === 'question') {
      let meta = {};
      try {
        meta = await this.get(endpoints.question(itemId));
      } catch (error) {
        if (!(error instanceof CitrusError) || !['challenge', 'forbidden', 'not_found'].includes(error.code)) throw error;
      }
      let answers = [];
      try {
        const payload = await this.get(endpoints.questionAnswers(itemId, 3, 0));
        answers = payload && Array.isArray(payload.data) ? payload.data : [];
      } catch (error) {
        if (!(error instanceof CitrusError) || !['challenge', 'forbidden'].includes(error.code)) throw error;
      }
      if (!meta.title && !answers.length) {
        throw new CitrusError('not_found', '问题 ' + itemId + ' 拿不到内容。', '可能问题不存在，或这份 Cookie 没权限。');
      }
      return { ...meta, _answers: answers };
    }
    if (kind === 'pin') return this.get(endpoints.pin(itemId));
    if (kind === 'zvideo') return this.get(endpoints.zvideo(itemId));
    if (kind === 'article') return this.get(endpoints.article(itemId));
    return this.get(endpoints.answer(itemId));
  }

  questionItem(raw, itemId, contentLimit) {
    const answersRaw = Array.isArray(raw._answers) ? raw._answers : [];
    const item = normalize.normalizeItem(
      { ...raw, type: 'question', id: itemId, question: { id: itemId, title: raw.title } },
      { source: 'item', contentLimit }
    );
    item.kind = 'question';
    item.id = String(itemId);
    item.title = String(raw.title || item.title || '问题 ' + itemId);
    item.url = normalize.webUrl('question', itemId);
    item.stats.views = Number(raw.visit_count || 0);
    item.extra = {
      ...item.extra,
      answer_count: Number(raw.answer_count || 0),
      follower_count: Number(raw.follower_count || 0),
      top_answers: answersRaw.slice(0, 3).map((answer) => briefAnswer(answer, itemId))
    };
    item.related = answersRaw.slice(0, 3).map((answer) =>
      normalize.normalizeItem({ ...answer, type: 'answer' }, { source: 'item', contentLimit: 3000 })
    );
    return item;
  }

  async attachRelated(item, resolved) {
    const questionId = resolved.questionId || (item.parent && item.parent.id) || '';
    if (!questionId) return;
    try {
      const payload = await this.get(endpoints.questionAnswers(String(questionId), 4, 0));
      const rows = payload && Array.isArray(payload.data) ? payload.data : [];
      item.related = rows
        .map((row) => normalize.normalizeItem({ ...row, type: 'answer' }, { source: 'related', contentLimit: 800 }))
        .filter((other) => other.id && other.id !== item.id)
        .slice(0, 3);
    } catch (error) {
      if (error instanceof CitrusError) item.extra.related_error = error.code;
    }
  }

  // ---- comments -----------------------------------------------------

  async comments(ref, options = {}) {
    const order = normalizeSort(options.sort);
    const resolved = this.resolve(ref, options.kind, options.id);
    let kind = resolved.kind === 'unknown' ? 'answer' : resolved.kind;
    const count = clamp(options.limit, 1, MAX_COMMENTS, 20);
    const page = clamp(options.page, 1, MAX_PAGE, 1);
    const offset = (page - 1) * count;

    return this.cached('comments:' + kind + ':' + resolved.id + ':' + count + ':' + offset + ':' + order, COMMENT_TTL,
      () => this.loadComments(kind, String(resolved.id), count, offset, page, order, options.signal));
  }

  async loadComments(kind, resourceId, count, offset, page, sort, signal) {
    const order = kind === 'answer' ? ['legacy', 'v5'] : ['v5', 'legacy'];
    let total = null;
    let lastError = null;
    // 「200 但没内容」比 404 更有信息量，收尾时要优先报它。
    let emptyButTotal = null;
    let answered = false;
    let chosen = null;
    // 上游明确说过 is_end：之后不会再有内容了。
    let exhausted = false;
    const items = [];
    const seen = new Set();
    let cursor = offset;
    let pages = 0;

    while (items.length < count && pages < COMMENT_PAGE_BUDGET) {
      pages += 1;
      const want = count - items.length;
      let payload = null;
      let chunk = [];
      const variants = chosen ? [chosen] : order;
      for (const variant of variants) {
        try {
          const spec = variant === 'legacy'
            ? endpoints.commentsLegacy(kind, resourceId, want, cursor, sort)
            : endpoints.commentsV5(kind, resourceId, want, cursor, sort);
          const result = await this.get(spec, signal);
          if (!result || typeof result !== 'object') continue;
          const reported = upstreamTotal(result);
          if (reported !== null) total = reported;
          const candidate = normalize.normalizeComments(result, resourceId);
          // 200 但一条都没给、上游又说有评论：这个接口对我们不可用
          //（comment_v5 需要 x-zse 签名，不签名就是空数组），换下一个接口。
          if (!candidate.length && reported) {
            emptyButTotal = new CitrusError(
              'comments_unavailable',
              '上游返回了评论数（' + reported + '）却没给正文：这个评论接口要浏览器签名。',
              kind === 'question'
                ? '问题本身读不到评论；要看评论请指定某条回答，传 answer:<id>（zhihu_read 的输出里带这个 id）。'
                : '换 sort=hot / sort=new 再试，或稍后用 answer:<id> 指定具体回答。',
              { platform: PLATFORM }
            );
            lastError = emptyButTotal;
            continue;
          }
          chosen = variant;
          payload = result;
          chunk = candidate;
          break;
        } catch (error) {
          lastError = error;
        }
      }
      if (!payload) break;

      answered = true;
      const found = upstreamTotal(payload);
      if (found !== null) total = found;
      const fresh = chunk.filter((row) => row.id && !seen.has(row.id));
      for (const row of fresh) {
        seen.add(row.id);
        items.push(row);
      }

      // 一页不满 limit 不代表到头：知乎会折叠/删除部分评论，
      // 上游只回 19 条时后面往往还有几十条。只有 is_end 才算完。
      // 游标按「请求的页大小」前进：被折叠的条目在上游的 offset 空间里仍占位，
      // 按返回行数推进会跳过中间的条目（也会让重复行把游标带偏）。
      const returned = Array.isArray(payload.data) ? payload.data.length : chunk.length;
      const cap = endpoints.COMMENT_PAGE_CAPS[chosen || 'legacy'] || 20;
      const step = Math.min(want, cap);
      const isEnd = Boolean(payload.paging && payload.paging.is_end);
      if (isEnd) exhausted = true;
      if (isEnd || returned === 0) break;
      cursor += step;
    }

    // 有「200 但空」的诊断就报它：比上游 404 更能说明该怎么做。
    if (!answered && (emptyButTotal || lastError)) throw emptyButTotal || lastError;

    const rows = items.slice(0, count);
    const errors = [];
    if (!rows.length && total) {
      // 拿到总数、拿不到正文，基本就是 comment_v5 的签名门槛；问题维度没有 legacy 可退。
      errors.push({
        source: 'comments',
        code: 'comments_unavailable',
        message: kind === 'question'
          ? '问题自身有 ' + total + ' 条评论，但知乎的评论接口需要浏览器签名，插件读不到正文；' +
            '想看评论请指定某条回答：传 answer:<id>（zhihu_read 的输出里带这个 id）。'
          : '上游说有 ' + total + ' 条评论，但两个评论接口都没返回内容（多半被风控或评论已关闭）。'
      });
    }
    return makePage(rows, {
      page,
      // 上游已经 is_end，或者这一页没凑满请求量，就都算到头了：
      // totals 常常大于实际可取条数（折叠/删除的不返回），不能只按总数判断。
      hasMore: !exhausted && rows.length >= count && hasMore(total, offset, rows.length, count),
      source: 'comments',
      total,
      errors
    });
  }
}

const MESSAGE_MISS = Symbol('miss');

function briefAnswer(answer, questionId) {
  const row = answer && typeof answer === 'object' ? answer : {};
  const answerId = String(row.id || '');
  const author = row.author && typeof row.author === 'object' ? row.author : {};
  return {
    id: answerId,
    author: String(author.name || ''),
    votes: Number(row.voteup_count || 0),
    url: answerId ? normalize.webUrl('answer', answerId, questionId) : ''
  };
}
