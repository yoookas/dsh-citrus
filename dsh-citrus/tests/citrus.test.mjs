/**
 * 离线测试：起一个假知乎，把所有能力与工具跑一遍。
 *
 *   node --test tests/
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { MockUpstream } from './mock-upstream.mjs';
import { parseCookieInput, maskCookie } from '../lib/core/cookies.js';
import { htmlToText } from '../lib/core/html.js';
import { CitrusError, friendlyMessage } from '../lib/core/errors.js';
import { ZhihuAdapter } from '../lib/platforms/zhihu/adapter.js';
import { renderComments, renderHot, renderItem, renderSearch } from '../lib/render.js';
import { resolveCookie } from '../lib/store.js';

const CURL = "curl 'https://www.zhihu.com/api/v4/me' -H 'cookie: z_c0=demo-token; d_c0=demo' -H 'user-agent: TestAgent/1.0'";

async function withUpstream(fn) {
  const upstream = new MockUpstream().installDefaults();
  await upstream.start();
  try {
    return await fn(upstream);
  } finally {
    await upstream.stop();
  }
}

function adapterFor(upstream, options = {}) {
  return new ZhihuAdapter({
    cookie: 'z_c0=demo; d_c0=demo',
    baseUrl: upstream.url,
    gapMs: 0,
    jitterMs: 0,
    maxRetries: 0,
    ...options
  });
}

// ---- Cookie ---------------------------------------------------------

test('Cookie：认 cURL、请求头、裸串、JSON', () => {
  const curl = parseCookieInput(CURL, { authCookieNames: ['z_c0'] });
  assert.equal(curl.cookie, 'z_c0=demo-token; d_c0=demo');
  assert.equal(curl.userAgent, 'TestAgent/1.0');
  assert.equal(curl.source, 'curl');
  assert.equal(curl.hasLogin, true);

  const header = parseCookieInput('Cookie: z_c0=abc; d_c0=def\nUser-Agent: UA/2', { authCookieNames: ['z_c0'] });
  assert.equal(header.cookie, 'z_c0=abc; d_c0=def');
  assert.equal(header.source, 'header');

  const raw = parseCookieInput('z_c0=raw; q_c1=x', { authCookieNames: ['z_c0'] });
  assert.equal(raw.source, 'raw');
  assert.equal(raw.hasLogin, true);

  const json = parseCookieInput('{"z_c0":"j1","d_c0":"j2"}', { authCookieNames: ['z_c0'] });
  assert.equal(json.cookie, 'z_c0=j1; d_c0=j2');
  assert.equal(json.source, 'json');
});

test('Cookie：没登录态时 hasLogin=false', () => {
  const parsed = parseCookieInput('d_c0=x', { authCookieNames: ['z_c0'] });
  assert.equal(parsed.hasLogin, false);
});

test('Cookie：错误输入给出可行动的错误', () => {
  assert.throws(() => parseCookieInput('', {}), CitrusError);
  assert.throws(() => parseCookieInput('https://www.zhihu.com/', {}), /网址/);
  assert.throws(() => parseCookieInput('not-a-cookie', {}), /name=value/);
});

test('Cookie：指纹不泄漏原文', () => {
  const masked = maskCookie('z_c0=SECRET; d_c0=x');
  assert.ok(masked.includes('z_c0'));
  assert.ok(!masked.includes('SECRET'));
  assert.match(masked, /#[0-9a-f]{8}/);
});

// ---- HTML -----------------------------------------------------------

test('HTML：标签、图片、实体、段落', () => {
  const text = htmlToText('<p>第一段 &amp; 第二行</p><p><strong>粗体</strong></p><img src="x"><script>bad()</script>');
  assert.ok(text.includes('第一段 & 第二行'));
  assert.ok(text.includes('粗体'));
  assert.ok(text.includes('[图]'));
  assert.ok(!text.includes('bad()'));
  assert.ok(!text.includes('<'));
});

// ---- HOT / SEARCH ---------------------------------------------------

test('热榜：解析 card_id、热度、链接', async () => {
  await withUpstream(async (upstream) => {
    const page = await adapterFor(upstream).hot(2);
    assert.equal(page.count, 2);
    const first = page.items[0];
    assert.equal(first.kind, 'question');
    assert.equal(first.id, '123456');
    assert.equal(first.title, '如何评价最近的大模型竞赛？');
    assert.equal(first.stats.heat, 12340000);
    assert.equal(first.extra.hot_text, '1234 万热度');
    assert.equal(first.url, 'https://www.zhihu.com/question/123456');
    assert.equal(page.items[1].kind, 'article');
  });
});

test('搜索：混合结果 + 用户条目', async () => {
  await withUpstream(async (upstream) => {
    const page = await adapterFor(upstream).search('大模型', 5);
    assert.equal(page.source, 'search');
    assert.ok(page.items.some((row) => row.kind === 'answer' && row.id === '111'));
    assert.ok(page.items.some((row) => row.kind === 'user' && row.id === 'zhangsan'));
  });
});

// ---- ITEM -----------------------------------------------------------

test('正文：回答', async () => {
  await withUpstream(async (upstream) => {
    const item = await adapterFor(upstream).item('answer:111', { contentLimit: 500 });
    assert.equal(item.kind, 'answer');
    assert.equal(item.id, '111');
    assert.ok(item.content.includes('这是正文第一段'));
    assert.equal(item.author.name, '张三');
    assert.equal(item.stats.likes, 1234);
    assert.equal(item.parent.id, '222');
    assert.equal(item.url, 'https://www.zhihu.com/question/222/answer/111');
  });
});

test('正文：问题带高赞回答', async () => {
  await withUpstream(async (upstream) => {
    const item = await adapterFor(upstream).item('question:222', { related: true });
    assert.equal(item.kind, 'question');
    assert.equal(item.title, '这个问题值得读吗？');
    assert.equal(item.extra.answer_count, 42);
    assert.ok(item.related.length >= 1);
  });
});

test('正文：纯数字 id 会依次尝试', async () => {
  await withUpstream(async (upstream) => {
    const item = await adapterFor(upstream).item('111');
    assert.equal(item.kind, 'answer');
  });
});

// ---- COMMENTS -------------------------------------------------------

test('评论：回答优先走旧接口，拿得到内容', async () => {
  await withUpstream(async (upstream) => {
    const page = await adapterFor(upstream).comments('answer:111', { limit: 10 });
    assert.equal(page.count, 1);
    assert.equal(page.items[0].content, '说得好。');
    assert.equal(page.total, 1);
    assert.deepEqual(upstream.calls.map((call) => call.path), ['/api/v4/answers/111/comments']);
  });
});

test('评论：排序参数会翻译成上游取值', async () => {
  await withUpstream(async (upstream) => {
    await adapterFor(upstream).comments('answer:111', { limit: 10, sort: 'new' });
    assert.ok(upstream.calls[0].query.includes('order=score'));
    await assert.rejects(adapterFor(upstream).comments('answer:111', { sort: 'weird' }), /评论排序/);
  });
});

test('评论：上游只报总数不给正文时，把原因写清楚', async () => {
  await withUpstream(async (upstream) => {
    upstream.route('/api/v4/answers/111/comments', { data: [], paging: { totals: 1 } });
    const page = await adapterFor(upstream).comments('answer:111', { limit: 10 });
    assert.equal(page.count, 0);
    assert.equal(page.total, 1);
    assert.match(page.errors[0].message, /没返回正文/);
  });
});

test('评论：翻页不受「这一页不满」影响，直到上游 is_end', async () => {
  await withUpstream(async (upstream) => {
    // 知乎会折叠/删除部分评论：每页实际返回值不定长，第二页只有 19 条也不能当成结尾。
    const pages = { 0: [20, false], 20: [19, false], 40: [13, true] };
    upstream.route('/api/v4/answers/111/comments', (url) => {
      const offset = Number(url.searchParams.get('offset') || 0);
      const [count, isEnd] = pages[offset] || [0, true];
      const data = Array.from({ length: count }, (_, index) => ({
        id: String(10000 + offset + index),
        content: '<p>评论 ' + (offset + index) + '</p>',
        author: { name: '路人' },
        vote_count: 1,
        reply_count: 0,
        created_time: 1700000000
      }));
      return { data, paging: { is_end: isEnd, totals: 52 } };
    });

    const page = await adapterFor(upstream).comments('answer:111', { limit: 100 });
    assert.equal(page.count, 52, '三页要全部拿到');
    assert.equal(page.total, 52);
    assert.equal(page.has_more, false, '上游 is_end 之后不该再说有下一页');
  });
});

test('评论：非回答类内容读不到正文时，说明原因并指向 answer:<id>', async () => {
  await withUpstream(async (upstream) => {
    upstream.route('/api/v4/questions/222/comments', { data: [], paging: { totals: 18 } });
    const page = await adapterFor(upstream).comments('question:222', { limit: 5 });
    assert.equal(page.count, 0);
    assert.match(page.errors[0].message, /签名/);
    assert.match(page.errors[0].message, /answer:/);
  });
});

// ---- 错误翻译 --------------------------------------------------------

test('错误：401 -> not_logged_in', async () => {
  await withUpstream(async (upstream) => {
    upstream.route('/api/v3/feed/topstory/hot-lists/total', { error: 'unauthorized' }, 401);
    await assert.rejects(adapterFor(upstream).hot(3), (error) => error instanceof CitrusError && error.code === 'not_logged_in');
  });
});

test('错误：403 验证页 -> challenge', async () => {
  await withUpstream(async (upstream) => {
    upstream.route('/api/v3/feed/topstory/hot-lists/total',
      '<html><body>安全验证</body></html>', 403, 'text/html; charset=utf-8');
    await assert.rejects(adapterFor(upstream).hot(3), (error) => error instanceof CitrusError && error.code === 'challenge');
  });
});

test('错误：429 重试后仍失败 -> rate_limited', async () => {
  await withUpstream(async (upstream) => {
    upstream.route('/api/v3/feed/topstory/hot-lists/total', { error: 'slow down' }, 429);
    const adapter = adapterFor(upstream, { maxRetries: 1 });
    await assert.rejects(adapter.hot(3), (error) => error instanceof CitrusError && error.code === 'rate_limited');
    assert.equal(upstream.calls.length, 2);
  });
});

test('错误：friendlyMessage 带下一步', () => {
  const message = friendlyMessage(new CitrusError('challenge', '风控'));
  assert.ok(message.includes('验证'));
  assert.ok(message.includes('不要连续重试'));
});

// ---- 渲染 -----------------------------------------------------------

test('渲染：热榜/搜索/正文/评论都带链接且不含 cookie', async () => {
  await withUpstream(async (upstream) => {
    const adapter = adapterFor(upstream);
    const hot = renderHot(await adapter.hot(2));
    assert.ok(hot.includes('知乎热榜'));
    assert.ok(hot.includes('https://www.zhihu.com/question/123456'));
    assert.ok(!hot.includes('demo-token'));

    const search = renderSearch({ ...(await adapter.search('大模型', 3)), query: '大模型' });
    assert.ok(search.includes('知乎搜索「大模型」'));

    const item = renderItem(await adapter.item('question:222', { related: true }));
    assert.ok(item.includes('【问题】'));
    assert.ok(item.includes('其他高赞回答'));
    // 高赞回答要带 answer:<id>，否则追问「这条回答的评论」时没有可用的 ref。
    assert.ok(/answer:\d+/.test(item), '渲染里应带可引用的 answer id');

    const comments = renderComments(await adapter.comments('answer:111', { limit: 5 }));
    assert.ok(comments.includes('评论'));
    assert.ok(comments.includes('说得好。'));
  });
});

// ---- Cookie 只有一个来源：配置里的 platforms.<平台>.cookie ------------------

test('Cookie：从配置里解析，带登录态且指纹不泄漏原文', () => {
  const resolved = resolveCookie({ cookie: CURL });
  assert.equal(resolved.hasLogin, true);
  assert.equal(resolved.cookie, 'z_c0=demo-token; d_c0=demo');
  assert.ok(!resolved.fingerprint.includes('demo-token'));
});

test('Cookie：配置里为空时给出 no_credential', () => {
  for (const config of [{}, { cookie: '' }, { cookie: '   ' }]) {
    assert.throws(
      () => resolveCookie(config),
      (error) => error instanceof CitrusError && error.code === 'no_credential'
    );
  }
});
