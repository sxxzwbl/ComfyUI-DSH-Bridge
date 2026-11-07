// ComfyUI-DSH-Bridge — prompt workbench panel driven by the DSH prompt nodes.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { FLAGS } from "./_flags.js";

const API = "/dsh_bridge";
const STORE = "dsh_bridge.panel";
const SIZE_KEY = "dsh_bridge.panel.size";

function css() {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./dsh_bridge.css", import.meta.url).href;
  document.head.appendChild(link);
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent(event, JSON.parse(data));
    }
  }
}

class DshPanel {
  constructor() {
    const saved = JSON.parse(localStorage.getItem(STORE) || "{}");
    this.session = saved.session || `panel-${Date.now().toString(36)}`;
    this.messages = saved.messages || [];
    this.busy = false;
    this.tab = "prompt";
    this.carry = null;
    this.lastMapTs = 0;
    css();
    this.build();
    this.render();
    this.refreshStatus();
  }

  build() {
    const statusDot = el("span", { className: "dsh-dot" });
    const statusText = el("span", { className: "dsh-status-text" }, "off");
    const title = el("div", { className: "dsh-title" }, "DSH 提示词助手");
    const closeBtn = el("button", { className: "dsh-icon", title: "收起" }, "×");
    closeBtn.onclick = () => this.toggle(false);

    const header = el(
      "div",
      { className: "dsh-header" },
      title,
      el("div", { className: "dsh-head-right" }, statusDot, statusText, closeBtn),
    );

    const input = el("textarea", {
      className: "dsh-prompt",
      placeholder: "说清要做什么，或继续追问…（讨论内容会随生成一起交给模型）",
    });
    input.onkeydown = (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        this.send(input);
      }
    };

    const sendBtn = el("button", { className: "dsh-btn primary" }, "发送");
    sendBtn.onclick = () => this.send(input);

    // "更新" resets the discussion: new session name plus a cleared log, and it
    // lives in the operations row so the reading area stays clean.
    const newBtn = el("button", { className: "dsh-btn small", title: "换一个新会话并清空讨论" }, "更新");
    newBtn.onclick = () => {
      this.session = `panel-${Date.now().toString(36)}`;
      this.messages = [];
      this.carry = null;
      this.render();
      this.persist();
      this.toast("已开新会话");
    };
    const cleanBtn = el("button", { className: "dsh-btn small", title: "清空讨论记录" }, "清空");
    cleanBtn.onclick = () => {
      this.messages = [];
      this.carry = null;
      this.render();
      this.persist();
    };

    // Operations row: dsh-purge cleanse + manual reconnect after the harness host
    // went away (desktop restart, crash, or a purge run that rewrites files).
    const purgeStatusBtn = el("button", { className: "dsh-btn small", title: "读取 dsh-purge 清洗进度" }, "清洗状态");
    purgeStatusBtn.onclick = () => this.purge("status", purgeStatusBtn);
    const purgeApplyBtn = el("button", { className: "dsh-btn small", title: "应用 86 项清洗（改写磁盘文件，需重启 harness 生效）" }, "应用清洗");
    purgeApplyBtn.onclick = () => this.purge("apply", purgeApplyBtn);
    const purgeRevertBtn = el("button", { className: "dsh-btn small", title: "回滚清洗到备份原件（保留 prompt-inject.md）" }, "回滚清洗");
    purgeRevertBtn.onclick = () => this.purge("revert", purgeRevertBtn);
    const reconnectBtn = el("button", { className: "dsh-btn small", title: "断开并重新连接 harness（attach / spawn 由配置决定）" }, "重连");
    reconnectBtn.onclick = () => this.reconnect(reconnectBtn);

    const ops = el(
      "div",
      { className: "dsh-ops" },
      purgeStatusBtn,
      purgeApplyBtn,
      purgeRevertBtn,
      reconnectBtn,
      el("span", { className: "dsh-ops-gap" }),
      newBtn,
      cleanBtn,
    );

    // One reading area, three views of it: the prompt, the reasoning behind it,
    // and the discussion that produced it. Tabs keep the panel short without
    // hiding anything, and the composer stays put so a question is always one
    // keystroke away.
    const panel = el(
      "div",
      { className: "dsh-panel" },
      header,
      el(
        "div",
        { className: "dsh-scroll" },
        this.buildTask(),
      ),
      el("div", { className: "dsh-ask" }, input, sendBtn),
      ops,
    );
    // Visibility is driven by inline style, not by the stylesheet: if the CSS asset
    // ever fails to load, the panel must still never cover the canvas.
    panel.style.display = "none";

    const launcher = el("button", { className: "dsh-launcher", title: "DSH 提示词助手" }, "DSH");
    launcher.onclick = () => this.toggle();

    document.body.append(launcher, panel);
    this.dom = {
      panel,
      input,
      statusDot,
      statusText,
      sendBtn,
      cleanBtn,
      ops: [purgeStatusBtn, purgeApplyBtn, purgeRevertBtn, reconnectBtn],
    };
    Object.assign(this.dom, this.taskDom || {});
    this.showTab(this.tab || "prompt");
    this.restoreSize(panel);
  }

  // The panel is resizable; remember what the user dragged it to. The reading
  // area is the whole point, so its height is a preference worth keeping.
  restoreSize(panel) {
    try {
      const saved = JSON.parse(localStorage.getItem(SIZE_KEY) || "{}");
      if (saved.h >= 420) panel.style.height = `${saved.h}px`;
      if (saved.w >= 380) panel.style.width = `${saved.w}px`;
    } catch {
      /* a corrupt entry just means the default size */
    }
    if (typeof ResizeObserver === "undefined") return;
    let timer = 0;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        try {
          localStorage.setItem(
            SIZE_KEY,
            JSON.stringify({ w: panel.offsetWidth, h: panel.offsetHeight }),
          );
        } catch {
          /* storage disabled — the panel still resizes, it just forgets */
        }
      }, 400);
    });
    observer.observe(panel);
  }

  // ------------------------------------------------------------- workbench view
  taskNodes() {
    return (app.graph?._nodes || []).filter((node) => node?.type === "DSH_PromptNode");
  }

  boundNode() {
    const id = this.dom.bindSel?.value;
    if (id) {
      const found = this.taskNodes().find((node) => String(node.id) === String(id));
      if (found) return found;
    }
    return this.taskNodes()[0] || null;
  }

  buildTask() {
    const bindSel = el("select", { className: "dsh-select" });
    bindSel.onchange = () => this.syncFromNode();
    const connInfo = el("span", { className: "dsh-conn" }, "");
    // Task and target are not mirrored here: they live on the node itself and the
    // run reads them straight from the graph. A second copy would only be a way
    // to drift out of sync with what the node is actually going to execute.
    const baseChk = el("input", { type: "checkbox" });
    const baseLabel = el("label", { className: "dsh-base" }, baseChk, "在上一版基础上修改");
    const genBtn = el("button", { className: "dsh-btn primary" }, "生成");
    genBtn.onclick = () => this.generate();
    const copyBtn = el("button", { className: "dsh-btn small", title: "复制当前提示词" }, "复制");
    copyBtn.onclick = () => {
      const text = this.dom.promptPre?.textContent || "";
      if (!text.trim()) return this.toast("还没有提示词");
      navigator.clipboard?.writeText(text).then(
        () => this.toast("已复制"),
        () => this.toast("复制失败"),
      );
    };
    // "同步" pulls: whatever the node produced last — prompt, analysis, task,
    // media counts — is read back into the panel. Pressing it is the manual
    // fallback for the automatic pull that runs whenever a prompt finishes.
    const syncBtn = el(
      "button",
      { className: "dsh-btn small", title: "把节点最新一次生成的提示词与参数拉回面板" },
      "同步",
    );
    syncBtn.onclick = async () => {
      const ok = await this.pullResults(null, true);
      this.toast(ok ? "已同步节点最新结果" : "节点还没有生成过");
    };
    // "带入" pushes: the prompt rides along with the next message so it can be
    // discussed, without ever being written into the log.
    const carryBtn = el(
      "button",
      { className: "dsh-btn small", title: "把当前提示词带进下一句话，作为上下文发给模型" },
      "带入",
    );
    carryBtn.onclick = () => this.carryPrompt();

    const promptPre = el("pre", { className: "dsh-pre" }, "");
    const analysisPre = el("pre", { className: "dsh-pre" }, "");
    const log = el("div", { className: "dsh-log" });

    const panes = { prompt: promptPre, analysis: analysisPre, chat: log };
    const tabBtns = {};
    const tabBar = el("div", { className: "dsh-tabs" });
    for (const [key, label] of [
      ["prompt", "提示词"],
      ["analysis", "分析"],
      ["chat", "会话"],
    ]) {
      const btn = el("button", { className: "dsh-tab", type: "button" }, label);
      btn.onclick = () => this.showTab(key);
      tabBtns[key] = btn;
      tabBar.append(btn);
    }
    // Both actions sit next to the views they act on: 同步 refreshes the panel
    // from the node, 带入 pushes the prompt into the discussion.
    tabBar.append(syncBtn, carryBtn, el("span", { className: "dsh-tab-gap" }), copyBtn);

    const view = el(
      "div",
      { className: "dsh-task" },
      el("div", { className: "dsh-row" }, el("label", {}, "绑定"), bindSel, connInfo),
      el("div", { className: "dsh-row" }, genBtn, baseLabel),
      tabBar,
      el("div", { className: "dsh-panes" }, promptPre, analysisPre, log),
    );

    // buildTask() runs before this.dom exists, so keep its controls aside and merge
    // them once the main dom map is in place.
    this.taskDom = {
      bindSel,
      connInfo,
      baseChk,
      genBtn,
      promptPre,
      analysisPre,
      log,
    };
    this.panes = panes;
    this.tabBtns = tabBtns;
    return view;
  }

  // Only one pane is ever in the layout: the panel is a reading surface, and
  // three stacked blocks would push the composer off the bottom.
  showTab(key) {
    this.tab = key;
    for (const [name, btn] of Object.entries(this.tabBtns || {})) {
      btn.classList.toggle("active", name === key);
    }
    for (const [name, pane] of Object.entries(this.panes || {})) {
      pane.hidden = name !== key;
    }
    if (key === "chat") this.scrollLog();
  }

  scrollLog() {
    const log = this.dom?.log;
    if (log) log.scrollTop = log.scrollHeight;
  }

  refreshNodeList() {
    const select = this.dom?.bindSel;
    if (!select) return;
    const nodes = this.taskNodes();
    const previous = select.value;
    select.textContent = "";
    if (!nodes.length) {
      select.append(el("option", { value: "" }, "（画布上没有 DSH 提示词节点）"));
      this.dom.connInfo.textContent = "";
      return;
    }
    for (const node of nodes) {
      select.append(el("option", { value: String(node.id) }, `#${node.id} ${node.title || ""}`.trim()));
    }
    if (previous && nodes.some((node) => String(node.id) === previous)) select.value = previous;
    this.syncFromNode();
  }

  widgetOf(node, name) {
    return node?.widgets?.find((widget) => widget.name === name) || null;
  }

  syncFromNode() {
    const node = this.boundNode();
    if (!node) return;

    // Connection state is readable from the front end, so warn before a slow run.
    const inputs = node.inputs || [];
    const count = (prefix) => inputs.filter((input) => input.name?.startsWith(prefix) && input.link != null).length;
    const sheets = count("sheets.");
    const refs = count("refs.");
    const meta = inputs.find((input) => input.name === "sheet_meta");
    // The task selector lives on the node now, so surface what it is set to here
    // rather than making the user leave the panel to find out.
    const task = String(this.widgetOf(node, "task")?.value || "").trim();
    const parts = [task, `sheets ${sheets}`, `refs ${refs}`, `meta ${meta?.link != null ? "✓" : "缺"}`];
    this.dom.connInfo.textContent = parts.filter(Boolean).join(" · ");
    this.dom.connInfo.dataset.warn = meta?.link == null ? "1" : "0";

    const saved = this.loadTaskState(node.id);
    if (saved.prompt) this.renderResult(saved);
    this.dom.baseChk.checked = Boolean(saved.baseEnabled);
  }

  // The discussion below the prompt is the only place a requirement is written:
  // there is no separate text box to keep in sync. Everything the user said is
  // folded into one brief, newest last, so the model reads the current intent.
  requirementFromChat() {
    const turns = this.messages
      .filter((message) => message.role === "user")
      .map((message) => (message.text || "").trim())
      .filter(Boolean)
      .slice(-6);
    if (!turns.length) return "";
    if (turns.length === 1) return turns[0];
    const lines = turns.map((text, index) => `${index + 1}. ${text}`).join("\n");
    return `需求讨论记录（按时间顺序，最后一条是当前要求）：\n${lines}`;
  }

  applyToNode(node) {
    const write = (name, value) => {
      const widget = this.widgetOf(node, name);
      if (!widget) return;
      widget.value = value;
      try {
        widget.callback?.(value);
      } catch (error) {
        console.warn("[DSH] widget callback failed", error);
      }
    };
    // The task and target are read straight off the node by the run itself, so
    // there is nothing to push back for them here.
    // A requirement typed on the node itself still wins when nothing was said
    // in the discussion; otherwise the discussion supplies it.
    const said = this.requirementFromChat();
    if (said) write("requirement", said);
    // Share one session with the discussion so the model keeps the thread it
    // was just talking in — the run is a continuation, not a cold start.
    write("session", this.session);
    app.graph.setDirtyCanvas(true, true);
  }

  // What the node will actually run, for labels in the discussion.
  nodeTaskLabel(node) {
    const widget = this.widgetOf(node || this.boundNode(), "task");
    return String(widget?.value || "").trim();
  }

  taskStateKey(nodeId) {
    return `dsh_bridge.task.${nodeId}`;
  }

  loadTaskState(nodeId) {
    try {
      return JSON.parse(localStorage.getItem(this.taskStateKey(nodeId)) || "{}");
    } catch {
      return {};
    }
  }

  saveTaskState(nodeId, payload) {
    try {
      localStorage.setItem(this.taskStateKey(nodeId), JSON.stringify(payload));
    } catch {
      /* storage full or disabled — the panel still works, iteration just resets */
    }
  }

  setGenBusy(busy) {
    if (!this.dom.genBtn) return;
    this.dom.genBtn.disabled = busy;
    this.dom.genBtn.textContent = busy ? "生成中…" : "生成";
  }

  async generate() {
    const node = this.boundNode();
    if (!node) return this.toast("画布上没有 DSH 提示词节点");
    // The requirement now lives in the discussion; without one this run would
    // fall back to whatever stale text sits on the node.
    const said = this.requirementFromChat();
    const onNode = String(this.widgetOf(node, "requirement")?.value || "").trim();
    if (!said && !onNode) return this.toast("先在下面的讨论里说要做什么");

    const state = this.loadTaskState(node.id);
    const baseWidget = this.widgetOf(node, "base_prompt");
    const useBase = this.dom.baseChk.checked && (state.prompt || "").trim();
    if (baseWidget) {
      baseWidget.value = useBase ? state.prompt : "";
      try {
        baseWidget.callback?.(baseWidget.value);
      } catch {
        /* noop */
      }
    }

    this.applyToNode(node);
    this.setGenBusy(true);
    const before = state.ts || 0;
    try {
      await app.queuePrompt(0, 1);
    } catch (error) {
      this.setGenBusy(false);
      return this.toast(`提交失败：${error}`);
    }
    this.pollResult(node.id, before);
  }

  pollResult(nodeId, beforeTs, attempt = 0) {
    if (attempt > 200) {
      this.setGenBusy(false);
      return this.toast("等待结果超时");
    }
    setTimeout(async () => {
      try {
        const response = await fetch(`${API}/last?node_id=${encodeURIComponent(nodeId)}`);
        const data = await response.json();
        const result = data.result || {};
        if (result.ts && result.ts !== beforeTs) {
          this.renderResult(result, true);
          this.setGenBusy(false);
          this.saveTaskState(nodeId, {
            ...result,
            prompt: result.prompt || "",
            baseEnabled: this.dom.baseChk.checked,
          });
          return;
        }
      } catch (error) {
        console.warn("[DSH] poll failed", error);
      }
      this.pollResult(nodeId, beforeTs, attempt + 1);
    }, 1500);
  }

  renderResult(result, focus = false) {
    if (!this.dom.promptPre) return;
    this.dom.promptPre.textContent = result.prompt || "";
    this.dom.analysisPre.textContent = result.analysis || "";
    if (result.status && result.status !== "ok") {
      this.dom.promptPre.textContent = `[${result.status}] ${result.analysis || ""}`;
    }
    // Only an explicit pull or a run started here steals the view; a background
    // sync must not yank the user out of the discussion mid-sentence.
    if (focus && (result.prompt || result.analysis)) this.showTab("prompt");
    this.pushMap(result);
  }

  // The node decided which image occupies which generator slot; print that table
  // into the discussion so the wiring can be checked without opening the analysis.
  pushMap(result) {
    const rows = result?.picture_map || [];
    if (!rows.length || result.ts === this.lastMapTs) return;
    this.lastMapTs = result.ts;
    const lines = [`图片输入映射（共 ${rows.length} 张，生成时按此接线）`];
    for (const row of rows) {
      lines.push(`${row.label} → minimax ${row.slot} · ${row.role}`);
    }
    for (const kind of result.picture_unused || []) {
      lines.push(`${kind === "sheet" ? "帧图" : "参考图"} 未输入 · 仅用于读动作，提示词不引用`);
    }
    this.note(lines.join("\n"));
  }

  // "带入" hands the finished prompt to the next message only: the log must
  // keep showing the real conversation, never a pasted copy of the prompt.
  carryPrompt() {
    const prompt = (this.dom.promptPre?.textContent || "").trim();
    if (!prompt) return this.toast("还没有提示词");
    this.carry = { prompt, node: this.boundNode()?.id ?? null };
    this.markCarry(true);
    this.showTab("chat");
    this.dom.input?.focus();
    this.toast("已带入，下一句话会附上这段提示词");
  }

  // The node records every run in the bridge, so the panel can read back a run
  // it did not start. This is what keeps the panel from showing version one
  // forever when the graph is queued from the canvas instead.
  async pullResults(nodeId = null, force = false) {
    const node = nodeId
      ? this.taskNodes().find((item) => String(item.id) === String(nodeId))
      : this.boundNode();
    if (!node) return false;
    const state = this.loadTaskState(node.id);
    try {
      const response = await fetch(`${API}/last?node_id=${encodeURIComponent(node.id)}`);
      const payload = await response.json();
      const result = payload.result || {};
      if (!result.ts) return false;
      // Without force, only a genuinely newer record replaces what is on screen.
      if (!force && result.ts <= (state.ts || 0)) return false;
      // Persist before refreshing the controls: syncFromNode() re-renders from
      // stored state, so an older entry would otherwise undo this render.
      this.saveTaskState(node.id, {
        ...result,
        prompt: result.prompt || "",
        baseEnabled: this.dom.baseChk?.checked ?? false,
      });
      this.renderResult(result, force);
      this.syncFromNode();
      return true;
    } catch (error) {
      console.warn("[DSH] pull failed", error);
      return false;
    }
  }

  markCarry(on) {
    const input = this.dom?.input;
    if (!input) return;
    input.classList.toggle("carry", on);
    input.placeholder = on
      ? "已带入提示词，接着说你的改动…"
      : "说清要做什么，或继续追问…（讨论内容会随生成一起交给模型）";
  }

  toggle(force) {
    const visible = this.dom.panel.style.display !== "none";
    const show = force ?? !visible;
    this.dom.panel.style.display = show ? "flex" : "none";
    // The node list is built from the live graph, so it must be rebuilt every
    // time the panel opens: nodes get added, deleted and reloaded in between.
    if (show) {
      this.refreshNodeList();
      this.dom.input.focus();
    }
  }

  persist() {
    localStorage.setItem(STORE, JSON.stringify({ session: this.session, messages: this.messages.slice(-80) }));
  }

  render() {
    const log = this.dom.log;
    log.textContent = "";
    for (const message of this.messages) {
      const roleName = message.role === "user" ? "你" : message.role === "system" ? "系统" : "harness";
      log.append(
        el(
          "div",
          { className: `dsh-msg ${message.role}` },
          el("div", { className: "dsh-role" }, roleName),
          el("div", { className: "dsh-body" }, message.text),
          message.note ? el("div", { className: "dsh-note" }, message.note) : null,
        ),
      );
    }
    log.scrollTop = log.scrollHeight;
  }

  note(text) {
    this.messages.push({ role: "system", text });
    if (this.messages.length > 120) this.messages.splice(0, this.messages.length - 120);
    this.render();
    this.persist();
  }

  setOpsBusy(busy) {
    for (const button of this.dom.ops || []) button.disabled = busy;
  }

  async purge(op, button) {
    const label = op === "status" ? "清洗状态" : op === "apply" ? "应用清洗" : "回滚清洗";
    this.setOpsBusy(true);
    this.setStatus("purge");
    button.disabled = true;
    button.textContent = `${label}…`;
    try {
      const response =
        op === "status"
          ? await fetch(`${API}/purge/status`)
          : await fetch(`${API}/purge/${op}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: "{}",
            });
      const data = await response.json();
      if (data.error) {
        this.note(`[${label}] 失败：${data.error}`);
        this.setStatus("error");
        return;
      }
      const lines = [data.output || "(无输出)"];
      if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
      if (data.partial) lines.push("→ 有补丁没匹配上，但已落盘的部分都已生效，harness 已按新文件重启。");
      if (data.restart_required) lines.push("→ 当前是 attach 模式：需要重启 DSH 桌面，清洗才会生效。");
      if (data.reconnect) {
        lines.push(
          data.reconnect.ok
            ? `→ 已重连：${(data.reconnect.ready || []).join(", ")}`
            : `→ 重连失败：${(data.reconnect.errors || []).join("; ")}`,
        );
      }
      this.note(`[${label}]\n${lines.join("\n")}`);
    } catch (err) {
      this.note(`[${label}] 请求失败：${err.message || err}`);
      this.setStatus("error");
    } finally {
      button.textContent = label;
      this.setOpsBusy(false);
      this.refreshStatus();
    }
  }

  async reconnect(button) {
    this.setOpsBusy(true);
    this.setStatus("starting");
    button.disabled = true;
    button.textContent = "重连中…";
    try {
      const response = await fetch(`${API}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await response.json();
      const reconnected = data.reconnect || {};
      const status = data.status || {};
      const head = reconnected.ok ? "已连上" : "未连上";
      const detail = `mode=${status.mode || "?"} pid=${status.pid ?? "-"} 通道=[${(reconnected.ready || []).join(", ")}]`;
      const errors = (reconnected.errors || []).length ? `\n${reconnected.errors.join("\n")}` : "";
      this.note(`[重连] ${head} · ${detail}${errors}`);
    } catch (err) {
      this.note(`[重连] 请求失败：${err.message || err}`);
      this.setStatus("error");
    } finally {
      button.textContent = "重连";
      this.setOpsBusy(false);
      this.refreshStatus();
    }
  }

  toast(text) {
    const tip = el("div", { className: "dsh-toast" }, text);
    document.body.append(tip);
    setTimeout(() => tip.remove(), 1600);
  }

  setStatus(value) {
    this.dom.statusDot.dataset.state = value;
    this.dom.statusText.textContent = value;
  }

  async refreshStatus() {
    try {
      const response = await fetch(`${API}/status`);
      const payload = await response.json();
      const status = payload.status || {};
      this.setStatus(status.alive ? (status.ready?.length ? "ready" : "starting") : "off");
      if (payload.config?.model) {
        const label = `${payload.config.provider} / ${payload.config.model}`;
        this.dom.statusText.title = label;
        this.dom.statusDot.title = label;
      }
    } catch {
      this.setStatus("off");
    }
  }

  async send(input) {
    if (this.busy) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    this.messages.push({ role: "user", text });
    const reply = { role: "assistant", text: "" };
    this.messages.push(reply);
    this.showTab("chat");
    this.render();
    this.busy = true;
    this.dom.sendBtn.disabled = true;
    this.setStatus("running");

    try {
      // A carried prompt rides along once, unseen in the log.
      const prefix = this.carry ? `【当前提示词】\n${this.carry.prompt}\n\n` : "";
      this.carry = null;
      const response = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: `${prefix}${text}`,
          session: this.session,
          // Ask the bridge for the bound node's payloads so the model sees the
          // same frames here that it would see during a generation run.
          node_id: this.boundNode()?.id ?? null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      await readSse(response, (event, data) => {
        if (event === "status") {
          this.setStatus(data.stage || "running");
        } else if (event === "done") {
          reply.text = data.text || "(空回复)";
          // Tell the user when the turn rode on pictures the model already had.
          reply.note = data.reused ? "复用上文图片，本轮未重复上传" : "";
          this.setStatus("ready");
          this.render();
          this.persist();
        } else if (event === "error") {
          reply.text = `[${data.code}] ${data.message}`;
          this.setStatus("error");
          this.render();
        }
      });
    } catch (err) {
      reply.text = `[请求失败] ${err.message || err}`;
      this.setStatus("error");
      this.render();
    } finally {
      this.busy = false;
      this.dom.sendBtn.disabled = false;
      this.markCarry(false);
      this.persist();
      this.refreshStatus();
    }
  }
}

// The task list is built from the live graph, so it has to follow node churn
// even while the panel sits open.
function watchGraph() {
  setInterval(() => {
    const panel = window.__dshBridgePanel;
    if (!panel || panel.dom.panel.style.display === "none") return;
    const nodes = panel.taskNodes().length;
    const known = panel.dom.bindSel?.options.length || 0;
    const isPlaceholder = panel.dom.bindSel?.options[0]?.value === "";
    if (nodes !== known || (nodes > 0 && isPlaceholder)) panel.refreshNodeList();
  }, 1200);
}

// A run queued from the canvas never passes through the panel, yet it is the
// normal way to iterate. Watch for it and pull the result back, otherwise the
// panel keeps showing the first version forever.
function watchRuns() {
  if (!api?.addEventListener) return;
  const pull = (event) => {
    const node = event?.detail?.node;
    const panel = window.__dshBridgePanel;
    if (!panel) return;
    // Only react to our own nodes; anything else is another extension's run.
    if (node && node.type !== "DSH_PromptNode") return;
    setTimeout(() => panel.pullResults(node?.id ?? null), 300);
  };
  try {
    // `executed` fires per node, `execution_success` once per queue entry: the
    // pair covers both a cached partial run and a full pass.
    api.addEventListener("executed", pull);
    api.addEventListener("execution_success", () => pull({}));
  } catch (error) {
    console.warn("[DSH] run watcher unavailable", error);
  }
}

app.registerExtension({
  name: "DSH.Bridge.Panel",
  async setup() {
    if (!FLAGS.panel) return;
    try {
      window.__dshBridgePanel = new DshPanel();
      // The graph may still be loading when the panel mounts, so try again after
      // the workflow settles, then watch for node count changes while visible.
      setTimeout(() => window.__dshBridgePanel?.refreshNodeList(), 1200);
      watchGraph();
      watchRuns();
    } catch (err) {
      console.error("[DSH] panel failed to mount", err);
    }
  },
});
