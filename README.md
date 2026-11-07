# ComfyUI-DSH-Bridge

把 **DeepSeek Harness（DSH）** 接成 ComfyUI 的提示词推理后端：视频和参考图进去，MiniMax H3 提示词出来。

它做三件事：

- **视频 → 帧阵列图**：均匀抽帧拼成一张图，附时间轴
- **素材 + 需求 → 结构化提示词**：模型按任务自己调用对应的 skill
- **会话面板**：同一个会话里追问、改需求，下一轮接着上一版改

节点输出只有两个槽：`提示词` 和 `状态`。

---

## 安装

### 1. 安装 DeepSeek Harness

<https://www.deepseek.com/harness/>

装完打开并登录一次，插件要用它的运行时。

**然后必须另外申请一个 API key**，第 3 步要填：

<https://platform.deepseek.com> → `API keys` → 创建 → 复制保存（只显示一次）

注意：桌面版登录之后，凭据只落在本机文件里，**没有可复制的 key**，也没法拿来填 `--api-key`。所以这个 key 只能自己到开放平台申请。

### 2. 安装 dsh-purge（可选）

面板底部那三个按钮（清洗状态 / 应用清洗 / 回滚清洗）会用到它。**不装也能正常生成**，只是这三个按钮会提示找不到 CLI。

<https://github.com/HunYiSage/dsh-purge>

在 DSH 的插件界面「添加插件」里填**归档地址**（解析器按扩展名判类型，必须以 `.tar.gz` 或 `.zip` 结尾）：

```
https://github.com/HunYiSage/dsh-purge/archive/refs/heads/master.tar.gz
```

三点注意：

- **别用插件市场**，会以 `already queued` 失败，永远不执行
- 装之前对一下 DSH 版本：插件声明了兼容范围，版本不符时装上了也不会激活
- **合规使用**：dsh-purge 会改写 DSH 的指令层、审批与沙箱默认行为，并改动磁盘上的文件。只在你自己的机器、或你有明确授权的环境里使用；先用「清洗状态」看清它要改什么，再决定是否应用，出问题用「回滚清洗」还原

### 3. 安装插件

把仓库放进 `custom_nodes`（下载 zip 解压，或直接 clone）：

```powershell
cd <ComfyUI>\custom_nodes
git clone https://github.com/sxxzwbl/ComfyUI-DSH-Bridge.git
```

**先停掉 ComfyUI。** 然后在 `ComfyUI-DSH-Bridge` 这个文件夹的**地址栏里输入 `cmd` 回车**，弹出的黑框里执行：

```powershell
install.bat --api-key sk-你的真实key
```

把 `sk-你的真实key` 换成第 1 步申请到的 DeepSeek API key。安装器会自己找 ComfyUI、找 Python（优先用整合包自带的）、写配置、装 skill，然后停在窗口里等你看结果。

装完启动 ComfyUI，日志里出现这行就成了：

```
[DSH-Bridge] loaded; ... nodes=DSH_ContactSheet,DSH_PromptNode
```

节点菜单里会有两张脸（分类 `DSH Bridge`）：**DSH 帧阵列拼图**、**DSH 提示词引擎**。

重装或升级：双击 `uninstall.bat`（先列清单、问你一句、答 Y 才删），再把新版放进来重新跑一次 `install.bat`。

---

## 用法

最小可跑的工作流：

```
Load Video ──► DSH 帧阵列拼图 ──┬── 帧阵列 ──► DSH 提示词引擎.sheet_0
                                └── 时间轴 ──► DSH 提示词引擎.帧阵列时间轴

Load Image ─────────────────────── 参考图 ──► DSH 提示词引擎.ref_0
```

然后在**面板**里用自己的话说需求（右下角 `DSH` 按钮），点生成。

生成完面板的「会话」标签会推一张映射表：

```
帧图   → minimax ref_image1 · 动作 / 构图 / 运镜参考
参考图1 → minimax ref_image2 · 身份 / 服装来源
```

**照着这张表接下游的 ref_image**。表说帧图是 `ref_image1`，你的 H3 工作流第一个 ref_image 就得接帧图，否则提示词里的 `<Picture 1>` 指错位。

两个容易弄错的开关：

- **帧图是否做参考**（默认开）：开=提示词里用 `<Picture N>` 指认帧图做动作参考；关=帧图只用来读动作，提示词完全不引用它
- **参考图数量上限**（默认 0=全部）：接了 5 张只用前 3 张就填 3，超出的不解码不发送

---

## 配置

`<ComfyUI>/user/default/dsh_bridge/config.json`，安装器生成。常用项：

| 键 | 默认 | 说明 |
|---|---|---|
| `provider` / `model` | `deepseek-official` / `deepseek-flash` | 走哪个模型 |
| `pipe_path` | `\\.\pipe\dsh-comfy` | 命名管道名，多实例并存时改 |
| `profile` | `comfy` | 用哪个 harness profile |
| `attach_only` | `false` | 只连已有 harness，不自己 spawn |
| `max_image_side` | `1568` | 送图前缩到多少 |
| `enable_panel` | `true` | 关掉面板，只留节点 |

环境变量可覆盖同名项：`DSH_BRIDGE_PROVIDER` / `DSH_BRIDGE_MODEL` / `DSH_BRIDGE_PIPE` / `DSH_HOME`。

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

`dsh-rpc-pipe` 是关键那块：harness 原本只认 stdio，一个进程只能服务一个客户端。这个插件复用它的 `HarnessSdkJsonRpcServer`，**每个管道连接一个 server 实例**，所以节点和面板能共享同一个运行时而不打架。

---

## 它能做什么

真正决定输出质量的是随插件安装的提示词 skill，不是节点代码。装上之后在面板里用自己的话说就行，模型自己挑 skill：

| 你说 | 它会做什么 |
|---|---|
| 照着这个视频写一版提示词 | 读帧阵列图，按时间推算动作与切点，写成能复刻同款的提示词 |
| 把视频里的人换成参考图这位 | 动作、构图、运镜一律不动，只替换身份与服装 |
| 只换衣服，人别动 | 人和场景保持不变，整套服装替换 |
| 把这个人的动作搬到那个人身上 | 从动作源只取动作与节奏，剥离原人物、原服装、原场景 |
| 把这份观感套到那个内容上 | 抽出可复用的风格描述，再套到新内容 |
| 这张图改成那样 | 拆成「保留清单 / 替换清单」逐项写死 |
| 算一下这个分辨率会不会出黄噪 | 按行数预算和 32 倍数约束给出安全分辨率 |

为什么值得这么绕：视频里的**人、衣服、动作、镜头是四件独立的事**，放在一句话里描述就会互相污染——模型看到人变了就把整段重画。所以每类任务先把不该动的部分剥离成明确声明，再只描述要变的那一层。这也是「一次只改一件事」总比「全部重说一遍」效果好的原因。

**先把边界说清楚**：上面这些事想靠提示词「完美做到」是不可能的。插件产出的是描述文字——它把该交代的交代清楚：谁在哪、做什么动作、镜头怎么走、哪些不许变。但最终像不像、对不对，取决于你的工作流怎么用它：模型选择、采样参数、参考图怎么接线、下游怎么放大。提示词是工作流里的一环，不是工作流的替代品。

所以更实际的问法是「我要让提示词这一步解决什么」。把你工作流的接法说清楚——帧图在第几路 ref_image、要不要保留原服装、出图是 720p 还是放大后——它就会按那个接法写。这比要求它一次写对有用得多。

改行为就是改这些 skill，它们只是 markdown。**改完要换一个会话**（面板点更新），旧会话已经载入了旧版本。

---

## 注意：代理

如果 ComfyUI 是启动器拉起来的，启动器可能给它注入了 `HTTP_PROXY` / `HTTPS_PROXY`。桥接 spawn 的 harness 会继承这两个变量，之后**每个模型请求都走那个代理**；代理不通时请求根本出不了机器，节点表现为**空回复**，日志里只有一句 `DeepSeek Messages transport failed`。

安装器会自动测：先试直连，不通再试继承到的代理，把结论写进 config。也可以手动指定：

```json
{ "strip_proxy_env": false, "proxy_url": "http://127.0.0.1:7890" }
```

`proxy_url` 非空时优先，会覆盖所有代理变量。
