/**
 * 工具层集成测试：不启动 DeepSeek Harness，只给它需要的 ctx 服务打桩。
 *
 * 验证的是「模型调用工具 -> 适配器 -> 假知乎 -> 结构化结果 + markdown」整条链路。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { MockUpstream } from './mock-upstream.mjs';
import { writeCookieFile } from '../lib/store.js';
import { apply, Config, name as pluginName, inject } from '../lib/index.js';

function defaultConfig(overrides = {}) {
  return {
    cookie: '',
    cookieFile: '',
    hotLimit: 10,
    searchLimit: 8,
    commentLimit: 20,
    contentChars: 1500,
    commentChars: 200,
    excerptChars: 120,
    relatedAnswers: 3,
    gapMs: 0,
    jitterMs: 0,
    timeoutMs: 5000,
    maxRetries: 0,
    promptHint: true,
    ...overrides
  };
}

function fakeContext() {
  const tools = new Map();
  const sections = [];
  const effects = [];
  return {
    tools: {
      register(definition) {
        tools.set(definition.name, definition);
        return () => tools.delete(definition.name);
      },
      get(name) {
        return tools.get(name);
      },
      schemas() {
        return [...tools.values()];
      }
    },
    systemPrompt: {
      section(section) {
        sections.push(section);
        return () => {};
      }
    },
    logger() {
      return { info() {}, warn() {}, debug() {}, error() {} };
    },
    effect(fn) {
      effects.push(fn());
      return () => {};
    },
    _tools: tools,
    _sections: sections,
    _effects: effects
  };
}

async function boot(config) {
  const upstream = new MockUpstream().installDefaults();
  await upstream.start();
  process.env.CITRUS_ZHIHU_BASE_URL = upstream.url;
  const dir = mkdtempSync(join(tmpdir(), 'dsh-citrus-tools-'));
  const cookieFile = join(dir, 'zhihu.cookie');
  writeCookieFile(cookieFile, "curl 'https://www.zhihu.com/' -H 'cookie: z_c0=demo-token; d_c0=demo'");
  const ctx = fakeContext();
  apply(ctx, defaultConfig({ cookieFile, ...config }));
  return {
    upstream,
    ctx,
    dir,
    async stop() {
      delete process.env.CITRUS_ZHIHU_BASE_URL;
      ctx._effects.forEach((dispose) => {
        try {
          dispose();
        } catch {
          /* ignore */
        }
      });
      await upstream.stop();
      rmSync(dir, { recursive: true, force: true });
    }
  };
}

const exec = { signal: AbortSignal.timeout(8000) };

test('插件元信息：名字与依赖服务', () => {
  assert.equal(pluginName, 'dsh-citrus');
  assert.deepEqual(inject, ['tools', 'systemPrompt']);
  assert.ok(Config && typeof Config === 'function');
});

test('注册了 4 个工具和 1 段提示词', async () => {
  const app = await boot({});
  try {
    assert.deepEqual([...app.ctx._tools.keys()].sort(),
      ['zhihu_comments', 'zhihu_hot', 'zhihu_read', 'zhihu_search']);
    assert.equal(app.ctx._sections.length, 1);
    assert.equal(app.ctx._sections[0].name, 'tool:zhihu');
  } finally {
    await app.stop();
  }
});

test('zhihu_hot：返回结构化条目 + markdown', async () => {
  const app = await boot({});
  try {
    const value = await app.ctx._tools.get('zhihu_hot').execute({ limit: 2 }, exec);
    assert.equal(value.platform, 'zhihu');
    assert.equal(value.count, 2);
    assert.equal(value.items[0].title, '如何评价最近的大模型竞赛？');
    assert.ok(value.markdown.includes('知乎热榜'));
    assert.ok(value.markdown.includes('https://www.zhihu.com/question/123456'));
    assert.ok(!JSON.stringify(value).includes('demo-token'));
  } finally {
    await app.stop();
  }
});

test('zhihu_search：关键词与用户结果', async () => {
  const app = await boot({});
  try {
    const value = await app.ctx._tools.get('zhihu_search').execute({ query: '大模型', limit: 5 }, exec);
    assert.equal(value.query, '大模型');
    assert.ok(value.items.some((row) => row.kind === 'user'));
    assert.ok(value.markdown.includes('知乎搜索「大模型」'));
  } finally {
    await app.stop();
  }
});

test('zhihu_read：问题带高赞回答', async () => {
  const app = await boot({});
  try {
    const value = await app.ctx._tools.get('zhihu_read').execute(
      { ref: 'https://www.zhihu.com/question/222', with_answers: true }, exec);
    assert.equal(value.kind, 'question');
    assert.ok(value.content.includes('问题描述'));
    assert.ok(value.related.length >= 1);
    assert.ok(value.markdown.includes('其他高赞回答'));
  } finally {
    await app.stop();
  }
});

test('zhihu_comments：评论列表', async () => {
  const app = await boot({});
  try {
    const value = await app.ctx._tools.get('zhihu_comments').execute({ ref: 'answer:111', limit: 10 }, exec);
    assert.equal(value.count, 1);
    assert.equal(value.items[0].author, '李四');
    assert.ok(value.markdown.includes('说得好。'));
  } finally {
    await app.stop();
  }
});

test('参数校验：query 必填、sort 只认 hot/new', async () => {
  const app = await boot({});
  try {
    await assert.rejects(
      app.ctx._tools.get('zhihu_search').execute({ limit: 3 }, exec),
      /query/
    );
    await assert.rejects(
      app.ctx._tools.get('zhihu_comments').execute({ ref: 'answer:111', sort: 'wild' }, exec),
      /invalid arguments/
    );
  } finally {
    await app.stop();
  }
});

test('没配 Cookie 时给出可行动的错误', async () => {
  const app = await boot({ cookieFile: join(tmpdir(), 'no-such-cookie-file.txt') });
  try {
    await assert.rejects(
      app.ctx._tools.get('zhihu_hot').execute({ limit: 1 }, exec),
      /dsh-citrus auth/
    );
  } finally {
    await app.stop();
  }
});

test('上游 401 时工具抛出人话错误', async () => {
  const app = await boot({});
  try {
    app.upstream.route('/api/v3/feed/topstory/hot-lists/total', { error: 'no' }, 401);
    await assert.rejects(
      app.ctx._tools.get('zhihu_hot').execute({ limit: 1 }, exec),
      /登录态失效/
    );
  } finally {
    await app.stop();
  }
});

test('提示词段落：工具可见时输出指引，关闭开关时为空', async () => {
  const app = await boot({});
  try {
    const section = app.ctx._sections[0];
    const text = section.text({ scope: {} });
    assert.ok(text.includes('zhihu_hot'));
    assert.ok(text.includes('不要凭记忆编造'));
  } finally {
    await app.stop();
  }

  const off = await boot({ promptHint: false });
  try {
    assert.equal(off.ctx._sections.length, 0);
  } finally {
    await off.stop();
  }
});
