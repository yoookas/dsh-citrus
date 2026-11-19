/**
 * 工具层集成测试：给 ctx 服务打桩，验证「模型调用工具 -> 适配器 -> 假知乎 -> 结果」。
 *
 * 不依赖 DeepSeek Harness 的包，因此 CI 不需要安装宿主依赖。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { MockUpstream } from './mock-upstream.mjs';
import { platformConfig, resolveConfig } from '../lib/platforms/registry.js';
import { CitrusRuntime } from '../lib/runtime.js';
import { registerTools } from '../lib/tools.js';
import { registerPrompt } from '../lib/prompt.js';

/** 演示用 Cookie：只有面板一个来源，所以测试直接把它放进配置。 */
const DEMO_COOKIE = "curl 'https://www.zhihu.com/' -H 'cookie: z_c0=demo-token; d_c0=demo'";

function defaultConfig(overrides = {}) {
  // 配置按平台分组：overrides 直接并进知乎那一段，调用点不用关心层级。
  return {
    platforms: {
      zhihu: {
        cookie: DEMO_COOKIE,
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
      }
    }
  };
}

/** 最小 defineTool 替身：只记录定义，不做 schema 编译（真编译在 DSH 里已验证）。 */
function fakeDefineTool(options) {
  return { ...options };
}

test('Volatile 配置引用：解开之后设置才真的生效', () => {
  const inner = defaultConfig({ hotLimit: 3 });
  const ref = { get: () => inner };

  // Config.meta.volatile 的插件收到的是 { get() }，直接读字段全是 undefined。
  assert.deepEqual(resolveConfig(ref), inner);
  assert.equal(platformConfig(resolveConfig(ref), 'zhihu').hotLimit, 3);

  // 普通对象原样返回
  assert.equal(platformConfig(resolveConfig(inner), 'zhihu').hotLimit, 3);

  // 旧版扁平结构（没有 platforms）仍然可读，升级不炸
  assert.equal(platformConfig({ hotLimit: 7 }, 'zhihu').hotLimit, 7);

  // 缺平台段 / 空配置给空对象，不该抛
  assert.deepEqual(platformConfig({}, 'zhihu'), {});
  assert.deepEqual(resolveConfig(undefined), {});
});

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
  const ctx = fakeContext();
  // Cookie 只有面板一个来源，于是直接放进配置里——和插件真实读到的形状一致。
  const resolved = defaultConfig(config);
  let live = resolved;
  const getConfig = () => live;
  const runtime = new CitrusRuntime(getConfig, () => {});
  registerTools(ctx, getConfig, runtime, fakeDefineTool);
  registerPrompt(ctx, getConfig);
  return {
    upstream,
    ctx,
    runtime,
    setConfig(next) {
      live = next;
    },
    async stop() {
      delete process.env.CITRUS_ZHIHU_BASE_URL;
      runtime.dispose();
      ctx._effects.forEach((dispose) => {
        try {
          dispose();
        } catch {
          /* ignore */
        }
      });
      await upstream.stop();
    }
  };
}

const exec = { signal: AbortSignal.timeout(8000) };

test('注册了 4 个工具和 1 段提示词', async () => {
  const app = await boot({});
  try {
    assert.deepEqual([...app.ctx._tools.keys()].sort(),
      ['zhihu_comments', 'zhihu_hot', 'zhihu_read', 'zhihu_search', 'zhihu_status']);
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

test('设置热更新：条数上限下一次调用立即生效', async () => {
  const app = await boot({ hotLimit: 2 });
  try {
    const tool = app.ctx._tools.get('zhihu_hot');
    const first = await tool.execute({}, exec);
    assert.equal(first.count, 2);

    app.setConfig(defaultConfig({ hotLimit: 1 }));
    const second = await tool.execute({}, exec);
    assert.equal(second.count, 1);
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

test('没配 Cookie 时给出可行动的错误', async () => {
  const app = await boot({ cookie: '' });
  try {
    await assert.rejects(
      app.ctx._tools.get('zhihu_hot').execute({ limit: 1 }, exec),
      /设置 → citrus/
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

test('提示词段落：工具可见时输出指引，关闭开关时不注册', async () => {
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
    assert.equal(off.ctx._sections.length, 1);
    assert.equal(off.ctx._sections[0].text({ scope: {} }), '');
  } finally {
    await off.stop();
  }
});

test('工具输出必须能无损 JSON 序列化（宿主会拒绝 undefined）', async () => {
  // 宿主对声明 type: 'json' 的工具做无损 JSON 校验；任何一个 undefined 字段都会让整次调用失败。
  const app = await boot({});
  try {
    const status = await app.ctx._tools.get('zhihu_status').execute({}, {});
    assert.deepEqual(JSON.parse(JSON.stringify(status)), status);

    const report = await app.ctx._tools.get('zhihu_hot').execute({ limit: 0 }, {});
    assert.deepEqual(JSON.parse(JSON.stringify(report)), report);

    // 真实 Host 里这两个服务都在；clientPath 可能没有值，
    // 这种「可选」字段一旦原样透出 undefined，整次工具调用就会被判非法。
    const services = {
      settings: { describe: () => [{ ns: 'dsh-citrus' }] },
      clientModules: { graph: () => ({ entries: [{ id: 'dsh-citrus' }] }), clientPath: () => undefined }
    };
    app.ctx.get = (name) => services[name];

    const liveStatus = await app.ctx._tools.get('zhihu_status').execute({}, {});
    assert.deepEqual(JSON.parse(JSON.stringify(liveStatus)), liveStatus);

    const liveReport = await app.ctx._tools.get('zhihu_hot').execute({ limit: 0 }, {});
    assert.deepEqual(JSON.parse(JSON.stringify(liveReport)), liveReport);
  } finally {
    await app.stop();
  }
});
