/**
 * dsh-citrus 的浏览器半侧。
 *
 * 桌面端（0.1.5-rc.2）没有 settings.plugin.item，配置页走的是另一套 slot：
 *   * settings.section —— 设置里新增一个「知乎」分区（最直观）；
 *   * plugins.item     —— 「插件」面板 → 内置插件配置里的卡片。
 *
 * 两边共用 ctx.configForms 的同一个命名空间表单，数据来自 Host 的 settings 服务。
 * 只硬依赖 slots；configForms 用 ctx.inject 延迟挂载，避免启动时被标成等待激活。
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
    const SUMMARY = "配置知乎 Cookie 与返回条数（后续支持更多平台）";

    const NUMERIC_FIELDS = [
      { key: "hotLimit", label: "热榜条数", hint: "1-30；知乎热榜不给翻页，30 就是上限。", min: 1, max: 30 },
      { key: "searchLimit", label: "搜索条数", hint: "1-20。", min: 1, max: 20 },
      { key: "commentLimit", label: "评论条数", hint: "1-100；上游每页只给 10/20 条。", min: 1, max: 100 },
      { key: "contentChars", label: "单条正文字数上限", hint: "200-16000；太长会撑爆上下文。", min: 200, max: 16000 },
      { key: "commentChars", label: "单条评论字数上限", hint: "40-800。", min: 40, max: 800 },
      { key: "excerptChars", label: "列表摘要字数上限", hint: "20-600。", min: 20, max: 600 }
    ];

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

    function valueOf(snapshot, key) {
      const value = snapshot && snapshot.value ? snapshot.value[key] : undefined;
      return value === undefined || value === null ? "" : String(value);
    }

    function NumericField(props) {
      return React.createElement("div", { style: styles.field },
        React.createElement("label", { style: styles.label }, props.label),
        React.createElement("input", {
          style: styles.input,
          type: "number",
          min: props.min,
          max: props.max,
          value: props.value,
          disabled: props.disabled,
          onChange: (event) => props.onEdit(event.target.value)
        }),
        React.createElement("p", { style: styles.hint }, props.hint)
      );
    }

    function SummaryCard(props) {
      const snapshot = React.useSyncExternalStore(
        (listener) => props.form.subscribe(listener),
        () => props.form.getSnapshot(),
        () => props.form.getSnapshot()
      );
      const hot = valueOf(snapshot, "hotLimit");
      return React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: "2px" } },
        React.createElement("span", { style: styles.description }, SUMMARY),
        hot ? React.createElement("span", { style: styles.hint }, "热榜默认 " + hot + " 条") : null
      );
    }

    function CitrusCardView(props) {
      const form = props.form;
      const subscribe = React.useCallback((listener) => form.subscribe(listener), [form]);
      const read = React.useCallback(() => form.getSnapshot(), [form]);
      const snapshot = React.useSyncExternalStore(subscribe, read, read);
      const [draft, setDraft] = React.useState({});
      const [saving, setSaving] = React.useState(false);
      const [message, setMessage] = React.useState(null);

      const disabled = Boolean(snapshot && snapshot.writable === false) || saving || !snapshot || snapshot.status === "unavailable";
      const writable = snapshot && snapshot.writable !== false && snapshot.status === "ready";

      const draftValue = (key) => (Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : valueOf(snapshot, key));
      const edit = (key, text) => setDraft((previous) => ({ ...previous, [key]: text }));

      const run = async (action, okText) => {
        setSaving(true);
        setMessage(null);
        try {
          await action();
          setDraft({});
          setMessage({ kind: "ok", text: okText });
        } catch (error) {
          setMessage({ kind: "error", text: "没有保存成功：" + (error && error.message ? error.message : String(error)) });
        } finally {
          setSaving(false);
        }
      };

      const save = () => {
        if (!writable) return;
        const ops = [];
        for (const field of NUMERIC_FIELDS) {
          if (!Object.prototype.hasOwnProperty.call(draft, field.key)) continue;
          const text = String(draft[field.key]).trim();
          if (text === "") {
            ops.push({ op: "unset", path: [field.key] });
            continue;
          }
          const number = Number(text);
          if (!Number.isInteger(number) || number < field.min || number > field.max) {
            setMessage({ kind: "error", text: "「" + field.label + "」要填 " + field.min + "-" + field.max + " 的整数。" });
            return;
          }
          ops.push({ op: "set", path: [field.key], value: number });
        }
        if (Object.prototype.hasOwnProperty.call(draft, "cookie") && String(draft.cookie).trim() !== "") {
          ops.push({ op: "set", path: ["cookie"], value: String(draft.cookie).trim() });
        }
        if (ops.length === 0) {
          setMessage({ kind: "error", text: "没有改动需要保存。" });
          return;
        }
        run(() => form.mutate(ops, snapshot.revision), "已保存，下一次工具调用立即生效。");
      };

      const clearCookie = () => {
        if (!writable) return;
        run(() => form.unset("cookie"), "已清除保存的 Cookie；会回退到 Cookie 文件或组合配置。");
      };

      const resetAll = () => {
        if (!writable) return;
        const ops = NUMERIC_FIELDS.map((field) => ({ op: "unset", path: [field.key] }));
        ops.push({ op: "unset", path: ["cookie"] });
        run(() => form.mutate(ops, snapshot.revision), "已恢复默认（不会删除本地 Cookie 文件）。");
      };

      if (!snapshot || snapshot.status === "unavailable") {
        return React.createElement("div", { style: styles.root },
          React.createElement("h3", { style: styles.title }, "citrus · 知乎"),
          React.createElement("p", { style: styles.hint }, "当前连接没有开放 dsh-citrus 设置。")
        );
      }

      return React.createElement("div", { style: styles.root },
        React.createElement("div", { style: styles.header },
          React.createElement("h3", { style: styles.title }, "citrus · 知乎"),
          React.createElement("p", { style: styles.description },
            "配置知乎登录态与返回条数。保存后立即生效，无需重启。Cookie 保存后不会回显。")
        ),

        React.createElement("div", { style: styles.field },
          React.createElement("label", { style: styles.label }, "知乎 Cookie"),
          React.createElement("input", {
            style: styles.input,
            type: "password",
            autoComplete: "off",
            placeholder: "粘贴新的 cURL / Cookie（留空表示不修改）",
            value: Object.prototype.hasOwnProperty.call(draft, "cookie") ? draft.cookie : "",
            disabled,
            onChange: (event) => edit("cookie", event.target.value)
          }),
          React.createElement("p", { style: styles.hint },
            "浏览器里 F12 -> Network -> 右键任意知乎请求 -> Copy as cURL，把整段粘进来。面板保存过的 Cookie 优先于本地 Cookie 文件；清除后回退到文件。")
        ),

        NUMERIC_FIELDS.map((field) => React.createElement(NumericField, {
          key: field.key,
          label: field.label,
          hint: field.hint,
          min: field.min,
          max: field.max,
          value: draftValue(field.key),
          disabled,
          onEdit: (text) => edit(field.key, text)
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
          React.createElement("button", {
            type: "button",
            style: styles.danger,
            disabled,
            onClick: clearCookie
          }, "清除保存的 Cookie")
        )
      );
    }

    /** 与官方设置页一致：硬依赖 slots + configForms。 */
    const inject = ["slots", "configForms"];

    /**
     * 注册两处配置入口：
     *   * settings.section —— 设置里的「知乎」分区；
     *   * plugins.item     —— 「插件」面板里的「知乎内容」卡片。
     * 两个 slot 都只在 Host 服务 dsh-citrus 命名空间期间注册。
     */
    function apply(ctx) {
      const form = ctx.configForms.get(NAMESPACE);
      const Page = (props) => React.createElement(CitrusCardView, { form, close: props ? props.close : undefined });
      const Summary = () => React.createElement(SummaryCard, { form });

      ctx.effect(() => ctx.configForms.whileServed([NAMESPACE], () => {
        const disposers = [];
        disposers.push(ctx.slots.inject("settings.section", () => ctx.slots.register({
          name: "settings.section",
          id: SECTION_ID,
          order: 18,
          label: () => TITLE
        }, Page)));
        disposers.push(ctx.slots.inject("plugins.item", () => ctx.slots.register({
          name: "plugins.item",
          id: SECTION_ID,
          order: 50,
          label: () => TITLE
        }, (props) => (props && props.view === "summary"
          ? React.createElement(Summary, null)
          : React.createElement(Page, props)))));
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