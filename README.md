# ComfyUI-DSH-Bridge

把 **DeepSeek Harness（DSH）** 接成 ComfyUI 的推理后端：视频进去，MiniMax H3 提示词出来。

不是又一个 LLM 节点。这里没有本地视觉模型、没有 HTTP API key 输入框、没有 prompt 模板拼接。它做的是：

- **视频 → 帧阵列图**：一段视频均匀抽 16 帧拼成一张图，附带时间轴元数据
- **素材 + 需求 → 结构化提示词**：模型按任务调用对应的 skill，产出六段式 Ref2VA 提示词
- **会话面板**：同一个 harness 会话里追问、改需求，下一轮生成接着上一版改

节点输出只有两个槽：`提示词` 和 `状态`。

---

## 前置要求

| 项 | 要求 |
|---|---|
| ComfyUI | 0.3.x 以上（需要 `comfy_api.latest.io` V3 schema） |
| 操作系统 | **Windows** —— 传输层是命名管道（`PeekNamedPipe`），Linux 跑不了 |
| DSH 桌面版 | 已安装并登录（提供 harness 运行时）—— **<https://www.deepseek.com/harness/>** |
| Python | 3.10+（跑安装脚本用） |

DSH 桌面版是必需项：这个插件不自己实现模型调用，它 spawn 一个 harness 进程，用 JSON-RPC 说话。

安装好之后确认这两条路径存在，安装脚本就靠它们认路：

```
<harness>/resources/app/dsh/node_modules/@deepseek-ai/
<harness>/resources/runtime/primary-runtime/dependencies/node/bin/node.exe
```

---

## 安装

### 1. 放进 custom_nodes

```powershell
cd <ComfyUI>/custom_nodes
git clone https://github.com/sxxzwbl/ComfyUI-DSH-Bridge.git
```

### 2. 跑安装脚本

**先把 ComfyUI 停掉。**

最省事的方式：进插件目录，**双击 `install.bat`**。

它会自己找 ComfyUI 目录、找 Python（优先用整合包自带的）、提示端口是否仍被占用，然后跑安装并停在窗口里让你看结果。

想先预览不改动，双击后在同一个窗口里用命令行带参数跑，或者直接：

```powershell
install.bat --dry-run
```

手动跑安装器也可以：

```powershell
python custom_nodes/ComfyUI-DSH-Bridge/scripts/install.py --dry-run
```

先看它找到了什么：

```
ComfyUI-DSH-Bridge installer
  plugin : I:\ComfyUI\custom_nodes\ComfyUI-DSH-Bridge
  ComfyUI: I:\ComfyUI
  harness: D:\ai\harness
  node   : D:\ai\harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe
  cli    : D:\ai\harness\resources\app\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js
  home   : C:\Users\me\.dsh
```

都对得上就去掉 `--dry-run` 正式装：

```powershell
python custom_nodes/ComfyUI-DSH-Bridge/scripts/install.py
```

找不到 harness 时手动指定：

```powershell
python custom_nodes/ComfyUI-DSH-Bridge/scripts/install.py --harness "D:\tools\harness"
```

脚本做六件事，全部幂等（重复跑只补缺失的）：

1. 探测 harness 安装位置、node 可执行文件、CLI 入口
2. 写 `<ComfyUI>/user/default/dsh_bridge/config.json`
3. 装 `dsh-rpc-pipe` 插件到 `<DSH_HOME>/plugins/`
4. 装 14 个提示词 skill 到 `<DSH_HOME>/skills/`
5. 生成 `comfy` profile 到 `<DSH_HOME>/profiles/comfy/`
6. 种一份 `prompt-inject.md` 模板（已存在则不动）

### 3. 启动 ComfyUI

日志里应该出现：

```
[DSH-Bridge] loaded; profile=comfy model=deepseek-flash transport=pipe frontend=on panel=on nodeUi=on nodes=DSH_ContactSheet,DSH_PromptNode
```

节点菜单里会出现两张脸（分类 `DSH Bridge`）：

- **DSH 帧阵列拼图**
- **DSH 提示词引擎**

---

## 用法

最小可跑的工作流：

```
Load Video ──► DSH 帧阵列拼图 ──┬── 帧阵列 ──► DSH 提示词引擎.sheet_0
                                └── 时间轴 ──► DSH 提示词引擎.帧阵列时间轴

Load Image ─────────────────────── 参考图 ──► DSH 提示词引擎.ref_0
```

然后在**面板**里说一句话（右下角的 `DSH` 按钮），点生成。

需求和槽位说明都在面板的会话框里说，`需求` 和 `槽位说明` 两个输入框是给节点级设定留的，面板会自动把会话内容写进去。

### 两个容易踩的开关

**帧图是否做参考**（默认开）

- 开：帧阵列图作为一个 `ref_image` 输入给 MiniMax，提示词里会用 `<Picture N>` 指认它做动作参考
- 关：帧图只用来读动作，提示词完全不引用它——这时动作全靠文字承载

**参考图数量上限**（默认 0 = 全部）

接了 5 张但只想用前 3 张时填 3。超出的不会解码、不会发送。

### 生成完之后看什么

面板的「会话」标签会推一张映射表：

```
图片输入映射（共 2 张，生成时按此接线）
帧图 → minimax ref_image1 · 动作 / 构图 / 运镜参考
参考图 1 → minimax ref_image2 · 身份 / 服装来源
```

**照着这张表接你下游的 ref_image**。表说帧图是 `ref_image1`，你的 H3 工作流第一个 ref_image 就得接帧图，否则提示词里的 `<Picture 1>` 指向错位。

---

## 配置

`<ComfyUI>/user/default/dsh_bridge/config.json`，由安装脚本生成。常用项：

| 键 | 默认 | 说明 |
|---|---|---|
| `provider` / `model` | `deepseek-official` / `deepseek-flash` | 走哪个模型 |
| `pipe_path` | `\\.\pipe\dsh-comfy` | 命名管道名，多实例并存时改 |
| `profile` | `comfy` | 用哪个 harness profile |
| `attach_only` | `false` | 只连已有 harness，不自己 spawn |
| `max_image_side` | `1568` | 送图前缩到多少 |
| `enable_panel` | `true` | 关掉面板，只留节点 |

环境变量可覆盖同名项：`DSH_BRIDGE_PROVIDER` / `DSH_BRIDGE_MODEL` / `DSH_BRIDGE_PIPE` / `DSH_HOME` 等。

---

## 它到底怎么工作

```
ComfyUI (python)
 ├─ nodes/         两个 V3 节点
 ├─ routes/api.py  /dsh_bridge/{status,chat,last,purge}
 ├─ web/           面板前端
 └─ dsh_bridge/    协议、图像、预设、路径探测
        │  Windows 命名管道 \\.\pipe\dsh-comfy（多客户端，每连接一条 JSON-RPC 流）
        ▼
 node.exe <dsh cli.js> --profile comfy
        ▼
 dsh-base + dsh-sdk-app + dsh-rpc-pipe
        ▼
 deepseek-official / deepseek-flash
```

`dsh-rpc-pipe` 是关键那块：包装好的 harness 只认 stdio，一个进程只能服务一个客户端。这个插件复用它的 `HarnessSdkJsonRpcServer`，**每个管道连接一个 server 实例**，所以节点和面板能共享同一个运行时而不打架。

---

## 提示词 skill

真正决定输出质量的是 `vendor/skills/` 里那套 skill，不是节点的代码。它们会被安装到 `<DSH_HOME>/skills/`：

| 能力层 | 用途 |
|---|---|
| `sequence-sheet-read` | 读帧阵列图：逐格、时间换算、切点判定 |
| `shot-grammar` | 动作/运镜/景别的英文写法 |
| `cast-inventory` | 画面里几个人、谁在左、谁是主体 |
| `character-sheet` | 把一个人写成可跨镜头复用的设定卡 |
| `style-dna` | 抽风格描述卡 |
| `h3-prompt-writing` | H3 六段式结构、`<Picture N>` 编号规则 |
| `ltx提示词skill` | LTX-2.5 提示词 |
| `minimax-h3-limit` | 分辨率/时长预算换算 |

| 任务层 | 触发场景 |
|---|---|
| `video-replica` | 照着这段视频写一版提示词 |
| `person-swap` | 把视频里的人换成参考图那位 |
| `outfit-swap` | 只换衣服，人不动 |
| `action-transfer` | 把这段动作搬到那个人身上 |
| `style-transfer` | 把这份观感套到那个内容上 |
| `image-edit-brief` | 图改图：保留什么、替换什么 |

改 skill 就是改行为。它们只是 markdown，`<DSH_HOME>/skills/<name>/SKILL.md`。

**注意**：skill 文件改动在同一个 harness 会话里不生效——会话上下文已经载入了旧版本。改完在面板点「更新」换一个会话，再生成。

---

## 故障排查

**`DSH_PromptNode` 报 500 / 节点没出现**

看 ComfyUI 启动日志里的 traceback。schema 构造失败会直接打出来。改完 schema 可以先本地验证，不用重启：

```powershell
python -c "import sys,importlib.util; sys.path.insert(0,'<ComfyUI>'); \
spec=importlib.util.spec_from_file_location('b','<ComfyUI>/custom_nodes/ComfyUI-DSH-Bridge/__init__.py', \
submodule_search_locations=['<ComfyUI>/custom_nodes/ComfyUI-DSH-Bridge']); \
m=importlib.util.module_from_spec(spec); sys.modules['b']=m; spec.loader.exec_module(m); \
print(m.NODE_CLASS_MAPPINGS['DSH_PromptNode'].define_schema())"
```

**状态输出 `失败：找不到 harness 程序（missing_cli）`**

安装脚本没跑，或者 DSH 换了安装位置。重跑 `scripts/install.py`——它在 config.json 里写绝对路径，插件运行时不去猜。

**状态输出 `失败：找不到 harness 管道（pipe_unavailable）`**

harness 进程没起来。先手动试一次：

```powershell
node --expose-internals <cli_entry> --profile comfy
```

看它报什么。常见原因是 profile 里的 `harnessRoot` 指向了不存在的目录。

**面板 `ready` 但生成很慢**

冷启动要加载 3–4 个 skill，40 秒左右正常。热会话 10 秒上下。

**改了 skill 没反应**

换会话。见上面那条。

---

## 可选依赖：dsh-purge

面板底部那三个按钮（清洗状态 / 应用清洗 / 回滚清洗）调的是 [dsh-purge](https://github.com/HunYiSage/dsh-purge) 的 CLI。**不装也能正常生成**，只是这三个按钮会提示找不到 CLI。

它不在 npm 上（registry 里那个 `dsh-purge` 是占位空包），只能从 GitHub 装。

### 图形界面里「添加插件」

输入框要求地址**以 `.tar.gz` 或 `.zip` 结尾**，所以要填归档地址，不是 `codeload` 那个：

```
https://github.com/HunYiSage/dsh-purge/archive/refs/heads/master.tar.gz
```

```
https://github.com/HunYiSage/dsh-purge/archive/refs/heads/master.zip
```

填 `https://codeload.github.com/HunYiSage/dsh-purge/tar.gz/refs/heads/master` 会报 `a URL must point at a git repository or a tarball` —— 那个 URL 内容确实是 tar.gz，但结尾是 `/master`，解析器按扩展名判类型，认不出来。

### 命令行

CLI 没有那个扩展名检查，上游文档给的就是 `codeload` 地址：

```bash
dsh plugin --profile desktop add https://codeload.github.com/HunYiSage/dsh-purge/tar.gz/refs/heads/master
```

### 两个已知坑

**别用插件市场。** 上游 README 明确说明：市场一键安装会以 `already queued: dsh-purge` 失败，永远不执行。

**版本要对上。** 插件声明只兼容特定 DSH 版本（`package.json` 里的 `dshTargets`），版本不符时装上了也不会激活。装之前先看那台机器的 DSH 版本。

## 不在仓库里的东西

- `prompt-inject.md`：操作员自己的提示词注入，安装脚本只种模板
- `logs/`、`user/`、`media/`、`config.json`：运行时产物，`.gitignore` 挡掉了
- `dsh-purge`：可选依赖，不随本插件分发，按上一节自行安装

## License

MIT
