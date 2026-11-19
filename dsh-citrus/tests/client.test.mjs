/**
 * 浏览器半侧的契约：注册到哪些 slot、平台 tab 怎么渲染、写回失败了怎么办。
 *
 * 不需要真 React：这里只求把 factory 里的组件函数跑起来，
 * 断言 surface 注册、嵌套写入路径，以及「Host 拒绝写入」不会被当成保存成功。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PLATFORM_BOUNDS, PLATFORM_DEFAULTS } from '../lib/platforms/registry.js';

/** 极简 hook 运行时：state 在多次 render 之间保留，其余 hook 每次重置。 */
function createReact() {
  let hooks = [];
  let index = 0;

  const React = {
    createElement(type, props, ...children) {
      return { type, props: { ...(props ?? {}), children } };
    },
    useState(initial) {
      const slot = index++;
      if (!(slot in hooks)) hooks[slot] = initial;
      const set = (next) => {
        hooks[slot] = typeof next === 'function' ? next(hooks[slot]) : next;
      };
      return [hooks[slot], set];
    },
    useCallback(fn) {
      index++;
      return fn;
    },
    useSyncExternalStore(_subscribe, getSnapshot) {
      return getSnapshot();
    }
  };

  return {
    React,
    /** 每次渲染前调用：保留 state，重置 hook 游标。 */
    begin() { index = 0; }
  };
}

/** 挂一个假 window.__ModuleLoader__ 并执行 client.js（模块只执行一次）。 */
let definitionPromise;
function getDefinition() {
  if (definitionPromise === undefined) {
    definitionPromise = (async () => {
      let definition;
      globalThis.window = {
        __ModuleLoader__: {
          load(value) { definition = value; }
        }
      };
      await import('../lib/client.js');
      return definition;
    })();
  }
  return definitionPromise;
}

/** 取出 factory 并用给定的 react 物化导出。 */
async function loadClient(react) {
  const definition = await getDefinition();
  assert.ok(definition, 'client.js 必须调用 window.__ModuleLoader__.load');
  assert.equal(definition.id, 'dsh-citrus');
  return definition.factory((name) => {
    if (name === 'react') return react.React;
    throw new Error('未预期的模块请求：' + name);
  });
}

/** 记录注册结果的假 slots / configForms。 */
function createContext(form) {
  const registrations = [];
  let servedCallback = null;

  const ctx = {
    configForms: {
      get(namespace) {
        ctx.requestedNamespace = namespace;
        return form;
      },
      whileServed(namespaces, register) {
        ctx.watchedNamespaces = namespaces;
        servedCallback = register;
        return () => { servedCallback = null; };
      }
    },
    slots: {
      inject(name, callback) {
        ctx.injected = ctx.injected ?? [];
        ctx.injected.push(name);
        return callback();
      },
      register(options, Component) {
        registrations.push({ options, Component });
        return () => {};
      }
    },
    effect(callback) {
      return callback();
    }
  };

  return { ctx, registrations, serve: (served) => servedCallback?.(served) };
}

/** 深度遍历元素树。 */
function walk(node, visit) {
  if (node === null || node === undefined) return;
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit);
    return;
  }
  if (typeof node !== 'object') {
    visit(node);
    return;
  }
  visit(node);
  walk(node.props?.children, visit);
}

function textOf(node) {
  let text = '';
  walk(node, (element) => {
    if (typeof element === 'string') text += element;
  });
  return text;
}

/** 展开函数组件，得到纯 DOM 形态的元素树。 */
function expand(node) {
  if (Array.isArray(node)) return node.map(expand);
  if (node === null || node === undefined || typeof node !== 'object') return node;
  if (typeof node.type === 'function') return expand(node.type(node.props));
  return { ...node, props: { ...node.props, children: expand(node.props?.children) } };
}

/** 渲染一次组件并返回元素树。 */
function render(react, Component, props) {
  react.begin();
  return expand(Component(props));
}

function findAll(tree, predicate) {
  const found = [];
  walk(tree, (element) => {
    if (element && typeof element === 'object' && predicate(element)) found.push(element);
  });
  return found;
}

/** 统一准备：起 ctx、注册、拿到 Page。 */
async function mount(form) {
  const react = createReact();
  const client = await loadClient(react);
  const { ctx, registrations, serve } = createContext(form);
  client.apply(ctx);
  serve(new Set(['dsh-citrus']));
  const Page = registrations.find((entry) => entry.options.name === 'settings.section').Component;
  return { react, client, ctx, registrations, serve, Page };
}

test('client 只硬依赖 slots 与 configForms', async () => {
  const react = createReact();
  const client = await loadClient(react);
  assert.deepEqual(client.inject, ['slots', 'configForms']);
});

test('Host serve 命名空间后，注册 settings.section 与 plugins.row.config', async () => {
  const form = { subscribe: () => () => {}, getSnapshot: () => ({ status: 'loading' }) };
  const { ctx, registrations, serve } = createContext(form);
  const react = createReact();
  const client = await loadClient(react);

  client.apply(ctx);
  assert.equal(ctx.requestedNamespace, 'dsh-citrus');
  assert.deepEqual(ctx.watchedNamespaces, ['dsh-citrus']);
  assert.equal(registrations.length, 0, '命名空间没被 serve 之前不该注册任何入口');

  serve(new Set(['dsh-citrus']));

  const section = registrations.find((entry) => entry.options.name === 'settings.section');
  assert.ok(section, '缺少 settings.section 注册');
  assert.equal(section.options.id, 'dsh-citrus');

  const rowConfig = registrations.find((entry) => entry.options.name === 'plugins.row.config');
  assert.ok(rowConfig, '缺少 plugins.row.config 注册');
  // keyed slot 的 key 必须是 <包名>#<行 id>
  assert.equal(rowConfig.options.key, 'dsh-citrus#dsh-citrus');

  assert.ok(
    !registrations.some((entry) => entry.options.name === 'plugins.item'),
    'plugins.item 是官方插件分组，第三方 bundle 不该占用'
  );
});

test('面板的字段与上下界和 registry 一致（面板加载不到宿主模块，只能靠这条守住）', () => {
  const source = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8');
  const panel = new Map();
  const re = /\{\s*kind:\s*"number",\s*key:\s*"(\w+)"[^}]*?min:\s*(-?\d+),\s*max:\s*(-?\d+)/g;
  let match;
  while ((match = re.exec(source))) panel.set(match[1], [Number(match[2]), Number(match[3])]);

  assert.deepEqual(
    [...panel.keys()].sort(),
    Object.keys(PLATFORM_BOUNDS.zhihu).sort(),
    '面板的数字字段列表要和 PLATFORM_BOUNDS 完全对应'
  );
  for (const [key, bounds] of Object.entries(PLATFORM_BOUNDS.zhihu)) {
    assert.deepEqual(panel.get(key), bounds, `字段 ${key} 的 min/max 和 registry 不一致`);
  }
});

test('面板每个字段在 schema 默认值里都有一份', async () => {
  const source = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8');
  const keys = new Set();
  const re = /key:\s*"(\w+)"/g;
  let match;
  while ((match = re.exec(source))) keys.add(match[1]);

  for (const key of keys) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(PLATFORM_DEFAULTS.zhihu, key),
      `面板字段 ${key} 在 PLATFORM_DEFAULTS 里没有默认值`
    );
  }
});

test('平台以 tab 呈现：一个平台一个页签', async () => {
  const { Page, react } = await mount({
    subscribe: () => () => {},
    getSnapshot: () => ({ status: 'ready', writable: true, revision: 1, value: { platforms: { zhihu: {} } } })
  });

  const tree = render(react, Page, {});
  const tablists = findAll(tree, (element) => element.props?.role === 'tablist');
  assert.equal(tablists.length, 1, '应该有且只有一个 tab 栏');

  const tabs = findAll(tree, (element) => element.props?.role === 'tab');
  assert.equal(tabs.length, 1, '目前只有知乎一个平台');
  assert.equal(textOf(tabs[0]), '知乎');
  assert.equal(tabs[0].props['aria-selected'], true, '默认选中第一个平台');
});

test('面板覆盖全部配置字段（数字 / 密码 / 开关）', async () => {
  const { Page, react } = await mount({
    subscribe: () => () => {},
    getSnapshot: () => ({ status: 'ready', writable: true, revision: 1, value: { platforms: { zhihu: {} } } })
  });

  const tree = render(react, Page, {});
  const inputs = findAll(tree, (element) => element.type === 'input');
  const countOf = (type) => inputs.filter((element) => element.props.type === type).length;

  // schema 里一共 13 个字段（cookie 不给自定义路径），面板不该漏掉任何一个。
  assert.equal(inputs.length, 13);
  assert.equal(countOf('number'), 11);
  assert.equal(countOf('password'), 1);
  assert.equal(countOf('checkbox'), 1);
});

test('密码框留空表示不修改，开关写布尔值', async () => {
  const calls = [];
  const form = {
    subscribe: () => () => {},
    getSnapshot: () => ({
      status: 'ready',
      writable: true,
      revision: 2,
      value: { platforms: { zhihu: { promptHint: true } } }
    }),
    mutate: async (ops, revision) => {
      calls.push({ ops, revision });
      return true;
    },
    unset: async () => true
  };
  const { Page, react } = await mount(form);

  let tree = render(react, Page, {});
  // 密码框改成空：读不回原值，所以只能表示「不动它」，不能当成清空。
  findAll(tree, (element) => element.props?.type === 'password')[0]
    .props.onChange({ target: { value: '   ' } });
  findAll(tree, (element) => element.props?.type === 'checkbox')[0]
    .props.onChange({ target: { checked: false } });

  tree = render(react, Page, {});
  const saveButton = findAll(tree, (element) => element.type === 'button' && textOf(element) === '保存设置');
  await saveButton[0].props.onClick();

  assert.deepEqual(calls, [{
    ops: [{ op: 'set', path: ['platforms', 'zhihu', 'promptHint'], value: false }],
    revision: 2
  }]);
});

test('保存只提交改过的字段，并带上读到的 revision', async () => {
  const calls = [];
  const form = {
    subscribe: () => () => {},
    getSnapshot: () => ({
      status: 'ready',
      writable: true,
      revision: 7,
      value: { platforms: { zhihu: { hotLimit: 10, searchLimit: 8 } } }
    }),
    mutate: async (ops, revision) => {
      calls.push({ ops, revision });
      return true;
    },
    unset: async () => true
  };
  const { Page, react } = await mount(form);

  // 改「热榜条数」，不动其它字段。
  let tree = render(react, Page, {});
  const hotInput = findAll(tree, (element) => element.props?.type === 'number' && element.props.min === 1 && element.props.max === 30);
  assert.equal(hotInput.length, 1);
  hotInput[0].props.onChange({ target: { value: '12' } });

  tree = render(react, Page, {});
  const saveButton = findAll(tree, (element) => element.type === 'button' && textOf(element) === '保存设置');
  assert.equal(saveButton.length, 1);
  await saveButton[0].props.onClick();

  assert.deepEqual(calls, [{
    ops: [{ op: 'set', path: ['platforms', 'zhihu', 'hotLimit'], value: 12 }],
    revision: 7
  }]);
});

test('清除 Cookie 写的是嵌套路径，不是顶层 cookie', async () => {
  const calls = [];
  const form = {
    subscribe: () => () => {},
    getSnapshot: () => ({ status: 'ready', writable: true, revision: 4, value: { platforms: { zhihu: {} } } }),
    mutate: async (ops, revision) => {
      calls.push({ ops, revision });
      return true;
    },
    unset: async () => true
  };
  const { Page, react } = await mount(form);

  const tree = render(react, Page, {});
  const clear = findAll(tree, (element) => element.type === 'button' && textOf(element).includes('清除'));
  assert.equal(clear.length, 1);
  await clear[0].props.onClick();

  assert.deepEqual(calls, [{
    ops: [{ op: 'unset', path: ['platforms', 'zhihu', 'cookie'] }],
    revision: 4
  }]);
});

test('Host 拒绝写入（mutate 返回 false）时不能报成功', async () => {
  const form = {
    subscribe: () => () => {},
    getSnapshot: () => ({ status: 'ready', writable: true, revision: 3, value: { platforms: { zhihu: { hotLimit: 10 } } } }),
    mutate: async () => false,
    unset: async () => false
  };
  const { Page, react } = await mount(form);

  let tree = render(react, Page, {});
  findAll(tree, (element) => element.props?.type === 'number' && element.props.min === 1 && element.props.max === 30)
    .forEach((element) => element.props.onChange({ target: { value: '11' } }));

  tree = render(react, Page, {});
  const saveButton = findAll(tree, (element) => element.type === 'button' && textOf(element) === '保存设置');
  await saveButton[0].props.onClick();

  tree = render(react, Page, {});
  const text = textOf(tree);
  assert.ok(!text.includes('已保存'), '被拒绝的写入不能显示成功提示');
  assert.ok(text.includes('Host 没有接受'), '要说明这次写入没被接受，实际文案：' + text);
});

test('Host 只读时不提交写入', async () => {
  let calls = 0;
  const form = {
    subscribe: () => () => {},
    getSnapshot: () => ({ status: 'ready', writable: false, revision: 1, value: { platforms: { zhihu: { hotLimit: 10 } } } }),
    mutate: async () => { calls += 1; return true; },
    unset: async () => { calls += 1; return true; }
  };
  const { Page, react } = await mount(form);

  const tree = render(react, Page, {});
  findAll(tree, (element) => element.type === 'button').forEach((element) => element.props.onClick?.());

  assert.equal(calls, 0, '只读部署里点按钮不该发出写入');
});
