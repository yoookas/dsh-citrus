/**
 * dsh-citrus 的浏览器半侧。
 *
 * 注册两处入口，都只在 Host 正在 serve `dsh-citrus` 这个 settings 命名空间时存在：
 *   * settings.section     —— 「设置」里的独立分区；
 *   * plugins.row.config   —— 「插件」页里本 bundle 的 dsh-citrus 行，多一个「配置」按钮，
 *                             key 是 <包名>#<行 id>。
 *
 * 表单数据来自 Host 的 settings 服务：ctx.configForms.get(条目 id) 给出一个共享表单，
 * 读快照、订阅变化、mutate/unset 写回，写回带 revision 防并发覆盖。
 *
 * 注意：plugins.item 是「官方插件」分组，第三方 bundle 不该占用；本包走 row.config。
 */
window.__ModuleLoader__.load({
  id: "dsh-citrus",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const React = require("react");

    const NAMESPACE = "dsh-citrus";
    const SECTION_ID = "dsh-citrus";
    const TITLE = "citrus";
    /** 「插件」页里本 bundle 那一行的配置 key：<包名>#<行 id>。 */
    const ROW_CONFIG_KEY = "dsh-citrus#dsh-citrus";

    /**
     * 配置页的 tab：一个平台一项，顺序就是 tab 顺序。
     *
     * 每个字段的 kind 决定控件和写回语义：
     *   number —— 数字框；留空 = 取消覆盖（unset）
     *   text   —— 文本框；留空 = 取消覆盖
     *   secret —— 密码框；留空 = 不修改（值读不回来，不能误清）
     *   toggle —— 开关；总是写布尔值，要回默认用「恢复默认」
     *
     * 字段路径一律是 ["platforms", <平台 id>, <key>]。
     *
     * 注意：这里是浏览器 bundle，加载不到 lib/platforms/registry.js，
     * 所以 min/max 只能写字面量。改上下界时两份都要改——
     * tests/client.test.mjs 会把它和 registry 的 PLATFORM_BOUNDS 逐项比对。
     */
    const PLATFORMS = [
      {
        id: "zhihu",
        label: "知乎",
        fields: [
          {
            kind: "secret",
            key: "cookie",
            label: "知乎 Cookie",
            placeholder: "粘贴新的 cURL / Cookie（留空表示不修改）",
            hint: "浏览器里 F12 -> Network -> 右键任意知乎请求 -> Copy as cURL，把整段粘进来即可。这里保存的 Cookie 存在当前 profile 的配置里；留空保存表示不修改，要清空请用下面的「清除」。"
          },
          { kind: "number", key: "hotLimit", label: "热榜条数", hint: "1-30；知乎热榜不给翻页，30 就是上限。", min: 1, max: 30 },
          { kind: "number", key: "searchLimit", label: "搜索条数", hint: "1-20。", min: 1, max: 20 },
          { kind: "number", key: "commentLimit", label: "评论条数", hint: "1-100；上游每页最多 20 条，插件会自动翻页。", min: 1, max: 100 },
          { kind: "number", key: "contentChars", label: "单条正文字数上限", hint: "200-16000；太长会撑爆上下文。", min: 200, max: 16000 },
          { kind: "number", key: "commentChars", label: "单条评论字数上限", hint: "40-800。", min: 40, max: 800 },
          { kind: "number", key: "excerptChars", label: "列表摘要字数上限", hint: "20-600。", min: 20, max: 600 },
          { kind: "number", key: "relatedAnswers", label: "附带高赞回答数", hint: "读问题时默认带几条（0-5）。", min: 0, max: 5 },
          {
            kind: "toggle",
            key: "promptHint",
            label: "系统提示词指引",
            hint: "消息提到知乎时，提醒模型用 zhihu_* 工具现场抓，别凭记忆编。"
          },
          { kind: "number", key: "gapMs", label: "请求最小间隔（ms）", hint: "0-10000。别长期设 0，那是给自己找风控。", min: 0, max: 10000 },
          { kind: "number", key: "jitterMs", label: "随机抖动（ms）", hint: "0-10000，加在最小间隔之上。", min: 0, max: 10000 },
          { kind: "number", key: "timeoutMs", label: "单次超时（ms）", hint: "1000-120000。", min: 1000, max: 120000 },
          { kind: "number", key: "maxRetries", label: "重试次数", hint: "0-5；只对 429/5xx/网络错误重试。", min: 0, max: 5 }
        ]
      }
    ];

    /** 平台字段在配置里的位置。 */
    function pathOf(platformId, key) {
      return ["platforms", platformId, key];
    }

    /** 按路径读嵌套值；路径断了就 undefined。 */
    function valueAt(value, path) {
      let current = value;
      for (const key of path) {
        if (current === null || typeof current !== "object") return undefined;
        current = current[key];
      }
      return current;
    }

    const styles = {
      root: {
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        padding: "16px",
        border: "0.5px solid var(--dsw-alias-border-l2, #e5e7eb)",
        borderRadius: "12px",
        background: "var(--dsw-alias-bg-layer-3, #ffffff)"
      },
      header: { display: "flex", flexDirection: "column", gap: "4px" },
      title: { margin: 0, fontSize: "15px", fontWeight: 600, color: "var(--dsw-alias-label-primary, #111827)" },
      description: { margin: 0, fontSize: "12px", lineHeight: 1.6, color: "var(--dsw-alias-label-tertiary, #6b7280)" },
      field: { display: "flex", flexDirection: "column", gap: "6px" },
      toggle: { display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" },
      label: { fontSize: "13px", fontWeight: 500, color: "var(--dsw-alias-label-primary, #111827)" },
      input: {
        boxSizing: "border-box",
        width: "100%",
        height: "34px",
        padding: "0 12px",
        border: "0.5px solid var(--dsw-alias-border-l4, #d1d5db)",
        borderRadius: "8px",
        background: "var(--dsw-alias-bg-layer-3, #ffffff)",
        color: "var(--dsw-alias-label-primary, #111827)",
        fontSize: "13px",
        fontFamily: "inherit"
      },
      hint: { margin: 0, fontSize: "12px", lineHeight: 1.5, color: "var(--dsw-alias-label-tertiary, #6b7280)" },
      error: { margin: 0, fontSize: "12px", color: "var(--dsw-alias-label-error, #dc2626)" },
      ok: { margin: 0, fontSize: "12px", color: "var(--dsw-alias-state-business-primary, #2563eb)" },
      tabs: {
        display: "flex",
        alignItems: "center",
        gap: "2px",
        padding: "3px",
        borderRadius: "9px",
        background: "var(--dsw-alias-bg-layer-1, #f3f4f6)",
        alignSelf: "flex-start",
        maxWidth: "100%",
        overflowX: "auto"
      },
      tab: {
        height: "26px",
        padding: "0 12px",
        border: "none",
        borderRadius: "7px",
        background: "transparent",
        color: "var(--dsw-alias-label-tertiary, #6b7280)",
        fontSize: "12px",
        fontWeight: 500,
        fontFamily: "inherit",
        cursor: "pointer",
        whiteSpace: "nowrap"
      },
      tabActive: {
        height: "26px",
        padding: "0 12px",
        border: "none",
        borderRadius: "7px",
        background: "var(--dsw-alias-bg-layer-3, #ffffff)",
        color: "var(--dsw-alias-label-primary, #111827)",
        fontSize: "12px",
        fontWeight: 600,
        fontFamily: "inherit",
        cursor: "pointer",
        whiteSpace: "nowrap",
        boxShadow: "0 1px 2px rgba(0, 0, 0, 0.08)"
      },
      actions: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" },
      primary: {
        height: "32px",
        padding: "0 16px",
        border: "none",
        borderRadius: "8px",
        background: "var(--dsw-alias-brand-primary, #2563eb)",
        color: "#ffffff",
        fontSize: "13px",
        fontWeight: 500,
        cursor: "pointer"
      },
      secondary: {
        height: "32px",
        padding: "0 14px",
        border: "0.5px solid var(--dsw-alias-border-l4, #d1d5db)",
        borderRadius: "8px",
        background: "transparent",
        color: "var(--dsw-alias-label-primary, #111827)",
        fontSize: "13px",
        cursor: "pointer"
      },
      danger: {
        height: "32px",
        padding: "0 14px",
        border: "0.5px solid var(--dsw-alias-border-l4, #d1d5db)",
        borderRadius: "8px",
        background: "transparent",
        color: "var(--dsw-alias-label-error, #dc2626)",
        fontSize: "13px",
        cursor: "pointer"
      }
    };

    /** 按 kind 渲染一个字段：数字框 / 文本框 / 密码框 / 开关。 */
    function Field(props) {
      const field = props.field;

      if (field.kind === "toggle") {
        return React.createElement("div", { style: styles.field },
          React.createElement("label", { style: styles.toggle },
            React.createElement("input", {
              type: "checkbox",
              checked: Boolean(props.value),
              disabled: props.disabled,
              onChange: (event) => props.onEdit(event.target.checked)
            }),
            React.createElement("span", { style: styles.label }, field.label)),
          React.createElement("p", { style: styles.hint }, field.hint)
        );
      }

      const type = field.kind === "secret" ? "password" : field.kind === "number" ? "number" : "text";
      return React.createElement("div", { style: styles.field },
        React.createElement("label", { style: styles.label }, field.label),
        React.createElement("input", {
          style: styles.input,
          type,
          min: field.min,
          max: field.max,
          autoComplete: field.kind === "secret" ? "off" : undefined,
          placeholder: field.placeholder,
          value: props.value,
          disabled: props.disabled,
          onChange: (event) => props.onEdit(event.target.value)
        }),
        React.createElement("p", { style: styles.hint }, field.hint)
      );
    }

    function CitrusCardView(props) {
      const form = props.form;
      const subscribe = React.useCallback((listener) => form.subscribe(listener), [form]);
      const read = React.useCallback(() => form.getSnapshot(), [form]);
      const snapshot = React.useSyncExternalStore(subscribe, read, read);
      const [draft, setDraft] = React.useState({});
      const [active, setActive] = React.useState(PLATFORMS[0].id);
      const [saving, setSaving] = React.useState(false);
      const [message, setMessage] = React.useState(null);

      const disabled = Boolean(snapshot && snapshot.writable === false) || saving || !snapshot || snapshot.status === "unavailable";
      const writable = snapshot && snapshot.writable !== false && snapshot.status === "ready";

      const platform = PLATFORMS.find((item) => item.id === active) || PLATFORMS[0];
      const keyOf = (path) => path.join(".");
      const edited = (path) => Object.prototype.hasOwnProperty.call(draft, keyOf(path));
      const draftValue = (path, field) => {
        if (edited(path)) return draft[keyOf(path)];
        const current = valueAt(snapshot && snapshot.value, path);
        if (field.kind === "toggle") return Boolean(current);
        return current === undefined || current === null ? "" : String(current);
      };
      const edit = (path, next) => setDraft((previous) => ({ ...previous, [keyOf(path)]: next }));

      // mutate/unset 返回布尔值：false 表示 Host 拒绝了这次写入（并发冲突或校验不过），
      // 不会抛异常。所以这里必须看返回值，不能写成「await 完就当成功」。
      const run = async (action, okText) => {
        setSaving(true);
        setMessage(null);
        try {
          const accepted = await action();
          if (!accepted) {
            setMessage({ kind: "error", text: "Host 没有接受这次修改（可能刚被别处改过，或字段没通过校验）。草稿还在，请再试一次。" });
            return;
          }
          setDraft({});
          setMessage({ kind: "ok", text: okText });
        } catch (error) {
          setMessage({ kind: "error", text: "没有保存成功：" + (error && error.message ? error.message : String(error)) });
        } finally {
          setSaving(false);
        }
      };

      // 草稿按路径存，所以切 tab 不会丢掉另一个平台已经改了一半的输入。
      const save = () => {
        if (!writable) return;
        const ops = [];
        for (const item of PLATFORMS) {
          for (const field of item.fields) {
            const path = pathOf(item.id, field.key);
            if (!edited(path)) continue;
            const raw = draft[keyOf(path)];

            if (field.kind === "toggle") {
              ops.push({ op: "set", path, value: Boolean(raw) });
              continue;
            }

            const text = String(raw ?? "").trim();
            if (field.kind === "secret") {
              // 密码框读不回原值：留空只表示「不修改」，绝不能当成清空。
              if (text === "") continue;
              ops.push({ op: "set", path, value: text });
              continue;
            }
            if (text === "") {
              ops.push({ op: "unset", path });
              continue;
            }
            if (field.kind === "number") {
              const number = Number(text);
              if (!Number.isInteger(number) || number < field.min || number > field.max) {
                setMessage({ kind: "error", text: "「" + item.label + " · " + field.label + "」要填 " + field.min + "-" + field.max + " 的整数。" });
                return;
              }
              ops.push({ op: "set", path, value: number });
              continue;
            }
            ops.push({ op: "set", path, value: text });
          }
        }
        if (ops.length === 0) {
          setMessage({ kind: "error", text: "没有改动需要保存。" });
          return;
        }
        run(() => form.mutate(ops, snapshot.revision), "已保存，下一次工具调用立即生效。");
      };

      // 「清除 Cookie」只清当前 tab 这个平台：form.unset(key) 只认顶层字段名，
      // 嵌套路径必须走 mutate，否则会写到 ["cookie"] 而不是 ["platforms", id, "cookie"]。
      const secretField = platform.fields.find((field) => field.kind === "secret");
      const clearCookie = () => {
        if (!writable || secretField === undefined) return;
        const path = pathOf(platform.id, secretField.key);
        run(
          () => form.mutate([{ op: "unset", path }], snapshot.revision),
          "已清除「" + platform.label + "」保存的 Cookie；会回退到 Cookie 文件或组合配置。"
        );
      };

      const resetAll = () => {
        if (!writable) return;
        const ops = [];
        for (const item of PLATFORMS) {
          for (const field of item.fields) ops.push({ op: "unset", path: pathOf(item.id, field.key) });
        }
        run(() => form.mutate(ops, snapshot.revision), "已恢复默认（不会删除本地 Cookie 文件）。");
      };

      if (!snapshot || snapshot.status === "unavailable") {
        return React.createElement("div", { style: styles.root },
          React.createElement("h3", { style: styles.title }, TITLE),
          React.createElement("p", { style: styles.hint }, "当前连接没有开放 dsh-citrus 设置。")
        );
      }

      return React.createElement("div", { style: styles.root },
        React.createElement("div", { style: styles.header },
          React.createElement("h3", { style: styles.title }, TITLE),
          React.createElement("p", { style: styles.description },
            "按平台配置登录态与返回条数。保存后立即生效，无需重启；Cookie 保存后不会回显。")
        ),

        // 平台 tab：PLATFORMS 里加一项，这里就自动多一个页签。
        React.createElement("div", { style: styles.tabs, role: "tablist", "aria-label": "平台" },
          PLATFORMS.map((item) => React.createElement("button", {
            key: item.id,
            type: "button",
            role: "tab",
            "aria-selected": item.id === active,
            style: item.id === active ? styles.tabActive : styles.tab,
            onClick: () => setActive(item.id)
          }, item.label))),

        platform.fields.map((field) => React.createElement(Field, {
          key: platform.id + "." + field.key,
          field,
          value: draftValue(pathOf(platform.id, field.key), field),
          disabled,
          onEdit: (next) => edit(pathOf(platform.id, field.key), next)
        })),

        message === null ? null : React.createElement("p", {
          style: message.kind === "ok" ? styles.ok : styles.error
        }, message.text),

        React.createElement("div", { style: styles.actions },
          React.createElement("button", {
            type: "button",
            style: styles.primary,
            disabled,
            onClick: save
          }, saving ? "保存中…" : "保存设置"),
          React.createElement("button", {
            type: "button",
            style: styles.secondary,
            disabled,
            onClick: resetAll
          }, "恢复默认"),
          secretField === undefined ? null : React.createElement("button", {
            type: "button",
            style: styles.danger,
            disabled,
            onClick: clearCookie
          }, "清除「" + platform.label + "」Cookie")
        )
      );
    }

    /** 与官方设置页一致：硬依赖 slots + configForms。 */
    const inject = ["slots", "configForms"];

    /**
     * 注册两处配置入口：
     *   * settings.section   —— 设置里的独立分区；
     *   * plugins.row.config —— 「插件」页里本 bundle 的 dsh-citrus 行 →「配置」页。
     * 两个 slot 都只在 Host serve `dsh-citrus` 命名空间期间注册，
     * 所以没装/没启用的部署里不会留下任何入口。
     */
    function apply(ctx) {
      const form = ctx.configForms.get(NAMESPACE);
      const Page = () => React.createElement(CitrusCardView, { form });

      ctx.effect(() => ctx.configForms.whileServed([NAMESPACE], () => {
        const disposers = [];
        disposers.push(ctx.slots.inject("settings.section", () => ctx.slots.register({
          name: "settings.section",
          id: SECTION_ID,
          // 排在各内置分区之后：General 0 / Models 10 / 插件 15 / Agent 预设 20。
          order: 25,
          label: () => TITLE
        }, Page)));
        // keyed slot：key 必须是 <包名>#<行 id>，行 id 跟 bundle patch 里的 id 一致。
        disposers.push(ctx.slots.inject("plugins.row.config", () => ctx.slots.register({
          name: "plugins.row.config",
          key: ROW_CONFIG_KEY
        }, Page)));
        return () => {
          for (const dispose of disposers) {
            try {
              dispose();
            } catch {
              /* 已释放 */
            }
          }
        };
      }), "dsh-citrus: config surfaces");
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  }
});