/**
 * 四个模型可见的工具。
 *
 * 每个工具都：
 *   * 用中文写清楚「什么时候该调用」；
 *   * 参数有上下界，模型写错也不会把上游打疼；
 *   * 返回结构化数据 + 一段 markdown（PTC 模式模型直接读 JSON，Native 模式读 markdown）；
 *   * 失败时抛出一句带「下一步」的中文，交给工具流水线转成 Error: ...
 *
 * 条数/字数等上限每次调用时从 getConfig() 取：面板里改完设置立即生效。
 */

import { writeFileSync } from 'node:fs';
import { friendlyMessage } from './core/errors.js';
import { PAGE_MAX, PLATFORM_BOUNDS, PLATFORM_DEFAULTS, platformConfig } from './platforms/registry.js';
import { dataDir } from './store.js';
import {
  renderComments, renderHot, renderItem, renderSearch, summarizeItem
} from './render.js';

const INT = (description) => ({ type: 'integer', description });
const STR = (description) => ({ type: 'string', description });
const BOOL = (description) => ({ type: 'boolean', description });

/** 条数/字数的兜底值与上下界，和 schema 同一份（registry.js）。 */
const DEFAULTS = PLATFORM_DEFAULTS.zhihu;
const BOUNDS = PLATFORM_BOUNDS.zhihu;
/** 给参数说明用的「a-b」区间文本。 */
const range = (key) => BOUNDS[key][0] + '-' + BOUNDS[key][1];

function toolFailure(error) {
  return new Error(friendlyMessage(error));
}

function clampInt(value, fallback, low, high) {
  const number = Number.parseInt(value, 10);
  const base = Number.isFinite(number) ? number : fallback;
  return Math.max(low, Math.min(high, base));
}

/**
 * 收敛成「无损 JSON」：宿主对 type: 'json' 的工具输出做 JSON 往返比对，
 * 任何一个 undefined（对象里或数组里）或带原型的实例都会让整次调用被判非法。
 * 这一层是兜底，字段自己该给 null 的还是要给。
 * @param {unknown} value 工具要返回的原始值
 * @returns {unknown} 能安全穿过 wire 的同一份数据
 */
function jsonSafe(value) {
  return JSON.parse(JSON.stringify(value));
}

/** 收集 Host 侧的加载/配置诊断（不输出 Cookie 值）。 */
function collectDiagnostics(ctx, current) {
  const report = {
    host: {
      settingsService: false,
      namespaces: [],
      namespaceRegistered: false,
      values: {
        // 取不到的字段给 null：工具输出必须是可 JSON 序列化的，undefined 会让宿主直接判非法。
        hotLimit: current.hotLimit ?? null,
        searchLimit: current.searchLimit ?? null,
        commentLimit: current.commentLimit ?? null,
        // 面板里存的优先，否则看 auth 写进本地文件的那份。
        cookieConfigured: Boolean(String(current.cookie || '').trim())
      }
    },
    clientModules: { available: false }
  };
  try {
    const settings = ctx.get('settings');
    if (settings) {
      report.host.settingsService = true;
      const described = settings.describe({ redactSecrets: true });
      report.host.namespaces = described.map((row) => row.ns);
      report.host.namespaceRegistered = report.host.namespaces.includes('dsh-citrus');
    }
  } catch (error) {
    report.host.error = String(error && error.message ? error.message : error);
  }
  try {
    const modules = ctx.get('clientModules');
    if (modules) {
      const graph = modules.graph();
      const ids = graph.entries.map((row) => row.id);
      report.clientModules = {
        available: true,
        hasCitrus: ids.includes('dsh-citrus'),
        entries: ids.filter((id) => id === 'dsh-citrus' || id.includes('settings')),
        clientPath: modules.clientPath('dsh-citrus') ?? null
      };
    }
  } catch (error) {
    report.clientModules.error = String(error && error.message ? error.message : error);
  }
  return report;
}

/**
 * @param {object} ctx
 * @param {() => object} getConfig
 * @param {import('./runtime.js').CitrusRuntime} runtime
 * @param {typeof import('@deepseek-ai/dsh-tools').defineTool} defineTool 宿主提供的工具定义器
 */
export function registerTools(ctx, getConfig, runtime, defineTool) {
  if (typeof defineTool !== 'function') {
    throw new TypeError('registerTools 需要宿主提供的 defineTool');
  }
  const config = () => (typeof getConfig === 'function' ? getConfig() : getConfig) || {};
  /** 知乎那一段配置：所有条数/字数都从这里取，平台字段的层级只在 registry.js 出现一次。 */
  const platform = () => platformConfig(config(), 'zhihu');
  /** 取某个配置字段，按 registry 的上下界夹紧。 */
  const limit = (key) => clampInt(platform()[key], DEFAULTS[key], BOUNDS[key][0], BOUNDS[key][1]);

  ctx.tools.register(defineTool({
    name: 'zhihu_hot',
    description: '获取知乎实时热榜。当用户问「知乎热榜」「今天知乎在讨论什么」「最近有什么热门话题」时调用。返回标题、热度、摘要和链接。',
    parameters: {
      limit: INT('返回条数，' + range('hotLimit') + '。知乎热榜不给翻页，' + BOUNDS.hotLimit[1] + ' 就是上限。')
    },
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: value.markdown }]
    },
    timeoutMs: 60000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      try {
        if (Number(args.limit) === 0) {
          const report = jsonSafe(collectDiagnostics(ctx, platform()));
          return { ...report, markdown: JSON.stringify(report, null, 2) };
        }
        const count = clampInt(args.limit, limit('hotLimit'), ...BOUNDS.hotLimit);
        const page = await runtime.adapter().hot(count, { signal: exec.signal });
        return {
          platform: 'zhihu',
          source: 'hot',
          count: page.count,
          items: page.items.map(summarizeItem),
          markdown: renderHot(page, {
            maxItems: count,
            excerptChars: limit('excerptChars')
          })
        };
      } catch (error) {
        throw toolFailure(error);
      }
    }
  }));

  ctx.tools.register(defineTool({
    name: 'zhihu_search',
    description: '在知乎里搜索问题、回答、文章和用户。当用户对某个话题不熟悉、想找特定讨论、或需要多个来源时调用。返回标题、摘要和链接。',
    parameters: {
      query: { ...STR('搜索关键词，例如「大模型」或「AI 取代程序员」'), required: true },
      limit: INT('返回条数，' + range('searchLimit')),
      kind: STR('可选：只保留某一类结果（answer / article / question / user）')
    },
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: value.markdown }]
    },
    timeoutMs: 120000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      try {
        const query = String(args.query || '').trim();
        if (!query) throw new Error('没有给搜索关键词。');
        const count = clampInt(args.limit, limit('searchLimit'), ...BOUNDS.searchLimit);
        const page = await runtime.adapter().search(query, count, {
          kind: String(args.kind || ''),
          signal: exec.signal
        });
        return {
          platform: 'zhihu',
          source: 'search',
          query,
          count: page.count,
          items: page.items.map(summarizeItem),
          ...(page.errors ? { errors: page.errors } : {}),
          markdown: renderSearch({ ...page, query }, {
            maxItems: count,
            excerptChars: limit('excerptChars')
          })
        };
      } catch (error) {
        throw toolFailure(error);
      }
    }
  }));

  ctx.tools.register(defineTool({
    name: 'zhihu_read',
    description: '读取一条知乎内容的正文：可以传问题链接、回答链接、文章链接，或 answer:123 / question:123 这样的 id。读问题时默认带上同问题下的高赞回答，适合回答「这个问题大家怎么看」。',
    parameters: {
      ref: { ...STR('知乎链接（question/answer/article）或带前缀的 id（answer:123）'), required: true },
      with_answers: BOOL('读问题时是否附带同问题下的高赞回答，默认 true'),
      content_chars: INT('正文截断字数，' + range('contentChars'))
    },
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: value.markdown }]
    },
    timeoutMs: 120000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      try {
        const ref = String(args.ref || '').trim();
        if (!ref) throw new Error('没有给知乎链接或 id。');
        const chars = clampInt(args.content_chars, limit('contentChars'), ...BOUNDS.contentChars);
        const withAnswers = args.with_answers === undefined ? true : Boolean(args.with_answers);
        const item = await runtime.adapter().item(ref, {
          related: withAnswers,
          contentLimit: chars,
          signal: exec.signal
        });
        const related = limit('relatedAnswers');
        return {
          platform: 'zhihu',
          kind: item.kind,
          id: item.id,
          title: item.title,
          url: item.url,
          author: item.author,
          parent: item.parent,
          stats: item.stats,
          content: item.content,
          content_truncated: item.content_truncated,
          excerpt: item.excerpt,
          related: (item.related || []).slice(0, related).map(summarizeItem),
          extra: item.extra,
          markdown: renderItem(item, {
            contentChars: chars,
            related,
            relatedChars: 600
          })
        };
      } catch (error) {
        throw toolFailure(error);
      }
    }
  }));

  ctx.tools.register(defineTool({
    name: 'zhihu_status',
    description: '检查 dsh-citrus 的加载与配置状态（排查配置页不显示、Cookie 是否就绪时使用）。',
    parameters: {},
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: value.markdown }]
    },
    timeoutMs: 15000,
    isConcurrencySafe: () => true,
    async execute() {
      const report = jsonSafe(collectDiagnostics(ctx, platform()));
      // 落一份快照：工具本身返回失败时，还能从文件里看真实内容。
      try {
        writeFileSync(dataDir() + '/status.json', JSON.stringify(report, null, 2), 'utf8');
      } catch {
        /* 只读环境里写不了就算了 */
      }
      return { ...report, markdown: JSON.stringify(report, null, 2) };
    }
  }));

  ctx.tools.register(defineTool({
    name: 'zhihu_comments',
    description: '读取某条知乎回答下面的评论。当用户想知道「评论区怎么看」「大家有什么不同意见」「有哪些反对声音」时调用。注意：知乎的问题级评论需要浏览器签名，插件读不到；要读评论请用具体回答的 id（zhihu_read 的输出里，每条高赞回答后面带 answer:<id>）。',
    parameters: {
      ref: { ...STR('知乎回答链接或 answer:123 这样的 id（zhihu_read 的输出里带这个 id）'), required: true },
      limit: INT('返回评论条数，' + range('commentLimit')),
      page: INT('第几页，1 起（配合 limit 翻页；返回里的 has_more 表示还有没有下一页）'),
      sort: {
        type: 'string',
        enum: ['hot', 'new'],
        description: 'hot 按热度（默认），new 按时间倒序'
      }
    },
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: value.markdown }]
    },
    timeoutMs: 180000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      try {
        const ref = String(args.ref || '').trim();
        if (!ref) throw new Error('没有给知乎链接或 id。');
        const count = clampInt(args.limit, limit('commentLimit'), ...BOUNDS.commentLimit);
        const sort = String(args.sort || 'hot').toLowerCase() === 'new' ? 'new' : 'hot';
        const page = await runtime.adapter().comments(ref, {
          limit: count,
          page: clampInt(args.page, 1, 1, PAGE_MAX),
          sort,
          signal: exec.signal
        });
        return {
          platform: 'zhihu',
          target: ref,
          count: page.count,
          ...(page.total !== undefined ? { total: page.total } : {}),
          has_more: page.has_more,
          items: page.items.map((row) => ({
            id: row.id,
            author: row.author && row.author.name ? row.author.name : '匿名用户',
            content: row.content,
            likes: row.likes,
            replies: row.replies,
            created_at: row.created_at
          })),
          ...(page.errors ? { errors: page.errors } : {}),
          markdown: renderComments(page, {
            maxItems: count,
            contentChars: limit('commentChars', 40, 800)
          })
        };
      } catch (error) {
        throw toolFailure(error);
      }
    }
  }));
}