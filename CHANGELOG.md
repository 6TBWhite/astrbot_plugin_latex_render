# 开发变更记录

> 时间倒序（最新在最前）。

---

## 2026-07-10：v1.0.1 体积优化与元数据补全

### 摘要

插件体积从 18.30 MB 降至 2.18 MB（-88%），主要来自移除从未被加载的内置字体文件；同时对齐 AstrBot 插件开发指南，补全 `metadata.yaml` 可选字段；优化 Playwright 启动流程。

### 改动

**1. 移除 fonts/ 目录（-15.9 MB）**

- 删除 8 套 Google Fonts woff2 字体文件、`fonts_local.css`、`manifest.json`（共 409 个文件）
- 原因：内置模板 `classic` / `novel` 只用系统字体名（思源黑体、苹方、微软雅黑等），从不请求 `fonts.gstatic.com` URL，`renderer.py` 的字体路由拦截逻辑不会触发，这些字体从未被加载
- `renderer.py` 的路由拦截逻辑保留，`manifest.json` 不存在时优雅降级（输出 debug 日志 + abort 请求），无需改代码

**2. README 新增两节**

- 「字体说明」：解释内置模板依赖系统字体、自定义模板的回退行为、如何恢复内置字体
- 「Linux 服务器字体要求」：裸 Linux 默认不装 CJK 字体会导致中文渲染成豆腐块，给出 apt/yum 安装命令和 `fc-list :lang=zh` 验证方式

**3. metadata.yaml 补全（对齐开发指南）**

| 字段 | 值 |
|------|-----|
| `display_name` | LaTeX/Markdown 图片渲染器 |
| `short_desc` | LLM 调用本地工具，把文本/Markdown/LaTeX 渲染成图片。 |
| `repo` | https://github.com/6TBWhite/astrbot_plugin_latex_render |
| `astrbot_version` | `>=4.26.3`（PEP 440 格式） |
| `version` | 1.0.0 → 1.0.1 |

**4. Playwright 启动优化**

- `_ensure_playwright()` 增加 Chromium 已存在检测：扫描 `PLAYWRIGHT_BROWSERS_PATH` 目录下是否有 `chromium*` 子目录，已存在则跳过 `playwright install chromium` subprocess 调用
- 效果：后续启动不再每次 spawn subprocess，初始化更快

**5. 其他**

- `main.py` `@register` 版本号同步至 1.0.1
- `logo.png` 纳入版本控制（之前未被 git 跟踪）
- `CHANGELOG_DEV.md` 重命名为 `CHANGELOG.md`（去掉 `_DEV` 后缀，符合命名规范）

### 对用户的影响

- 内置 `classic` / `novel` 模板：无影响，渲染效果取决于宿主系统是否装了中文字体
- 自定义模板用 `@font-face` 指 Google Fonts：Playwright 路由拦截会 abort 请求，回退到 `font-family` 后备系统字体
- 想恢复内置字体：重新放回 `fonts/` 目录 + `manifest.json` 即可，`renderer.py` 字体路由会自动识别

---

## 2026-07-05：Playwright 浏览器二进制路径修复

### 问题

AstrBot 更新/降级后，插件依赖的 Chromium 浏览器实例会消失，导致渲染失败。排查发现 AstrBot 的自动备份/恢复机制只覆盖 `data/` 和 `venv/`，而 Playwright 浏览器二进制默认安装到系统缓存目录 `%LOCALAPPDATA%\ms-playwright\`，不在备份范围内。

### 修复

在 `initialize()` 中设置环境变量 `PLAYWRIGHT_BROWSERS_PATH`，将 Chromium 浏览器安装到插件数据目录 `data/plugin_data/astrbot_plugin_latex_render/playwright_browsers/` 下，确保随 AstrBot 备份/恢复一起保留。

**修改文件**：`main.py`（`initialize` 方法中 `_ensure_playwright` 调用前）

```python
plugin_data_dir = os.path.normpath(StarTools.get_data_dir("astrbot_plugin_latex_render"))
playwright_browsers_dir = os.path.join(plugin_data_dir, "playwright_browsers")
os.makedirs(playwright_browsers_dir, exist_ok=True)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = playwright_browsers_dir
```

### 效果

- 浏览器二进制从系统缓存移入 AstrBot 管理的 `data/` 目录（headless shell ~273MB）
- 首次启动自动安装，后续启动检测已存在则跳过
- AstrBot 更新/降级时浏览器二进制随 `data/` 备份恢复，不再丢失

---

## 待办

- [ ] 手动触发渲染以验证日志输出格式（当前测试卡在第 4 张图，溢出分支未覆盖）

## 2026-07-01：修复 LLM 工具参数 schema 静默丢失

### 摘要

`render_to_image` 工具注册给框架后，生成的 JSON Schema 中 `parameters.properties` 为空 `{}`，导致 LLM 调用时无法识别 `content` 和 `template` 两个参数。定位到 docstring 缩进不一致导致 `docstring_parser` 跳过 `Args:` 段，修复对齐后以脚本验证通过。

### 根因

AstrBot 框架 `@filter.llm_tool` 内部通过 `docstring_parser` 解析函数 docstring 来生成参数 schema（**不是**直接读函数签名）。`docstring_parser` 靠缩进识别 section 边界——要求描述文本与 `Args:` 行必须在同一缩进层级。

原 docstring 中描述文本顶格（0 缩进），`Args:` 行缩进 4 个空格，parser 把 `Args:` 及其下方参数列表全部当作普通长描述文字跳过后，输出的 `params` 为空列表。框架拿到空列表后静默生成 `{"type": "object", "properties": {}}`，不报错、不提示。

### 修改

- **`main.py`** `render_to_image_tool` docstring：将 `Args:` 行及其下方参数描述统一为顶格 0 缩进，与描述文本同级

### 验证

用 `docstring_parser.parse()` 解析修复后的 docstring，确认提取出 2 个参数（`content: string`、`template: string`），PASS。

```text
=== params (len=2) ===
  content (string): 必填，不可为空。将要渲染成图片的完整文本内容。
  template (string): 可选。classic（讲题排版，默认）或 novel（小说风格）。

PASS: both params extracted
```

### 经验

- `@filter.llm_tool` 的参数 docstring 必须保证 `Args:` 与描述文本缩进一致
- Schema 静默丢失不抛异常，发现问题靠对比"函数签名有参数但 schema 没有"才倒推回来
- 验证方式：直接在 Python 里 import `docstring_parser` 跑一下最快

---

## 2026-07-01：版本号修正 & 重发布准备

### 摘要

将插件从 `html_render` 修改版正式独立为 `astrbot_plugin_latex_render` v1.0.0，修正所有遗留版本号引用，更新元数据。

### 修改

- **`@register` 装饰器**（`main.py`）：版本改为 `"1.0.0"`
- **插件描述**：更新为「LLM能够主动调用的图片渲染工具，可支持文本、LaTeX/Markdown 内容，支持本地字体与自定义模板。」
- **`metadata.yaml`**：同步确认 `version: 1.0.0`、`author: 6TBWhite & Para`、description 一致
- **`CHANGELOG_DEV.md`**：历史章节标题中版本号统一改为 `v1.0`
- **`enable_hidden_ctx_buffer` 默认值**：`True` → `False`（实验性功能保持关闭，用户按需开启）

---

## 2026-07-01：独立上下文缓冲区 & 废弃项清理

### 摘要

隐藏上下文缓冲区（hidden context buffer）完成完整交付：新增独立开关、废弃旧配置项、补全可观测性日志。

### 新增

**1. 独立上下文缓冲区开关 `enable_hidden_ctx_buffer`**

- 配置项迁移至 `_conf_schema.json` 顶部层级
- `label: "图片原始文本独立缓存区"`
- `description` 和 `hint` 经过 UI 适配（避免旧文案在窄屏被截断）
- 默认开启，布尔类型，与渲染管线解耦

**2. 三条控制台日志**

| 日志 | 触发时机 | 输出内容 |
|------|----------|----------|
| 暂存 | `_push_hidden_ctx` | 字符数 + 缓冲区深度（如 `1/3`） |
| 溢出 | 缓冲区满 | 被淘汰条目的大小 |
| 注入 | `_inject_hidden_ctx` | 实际注入的伪造消息条数 |

- 静默机制：`enable_hidden_ctx_buffer=False` 时，以上日志全部被守卫语句短路，无输出

### 移除

**`preserve_text_for_context` 配置项完全移除**

- `_conf_schema.json`：字段删除
- `main.py`：两处逻辑合并至 `enable_hidden_ctx_buffer` 单一路径，移除内部双重守卫
- 原因：旧开关被新开关完全覆盖，新开关开则旧开关无效，新开关关则旧开关被短路，无独立作用

---

## 2026-06-30：hidden context buffer 机制

### 改动内容

渲染产物（Markdown 原文）不再直接发送给用户，转入内部缓冲，LLM 后续请求时以伪造 assistant 消息形式注入上下文。

**新增**：

| 项目 | 位置 | 作用 |
|------|------|------|
| `_push_hidden_ctx` | 私有方法 | 把渲染原文压入缓冲 |
| `_inject_hidden_ctx` | 私有方法 | LLM 请求前从缓冲取出并注入 |
| `_hidden_ctx_buffer` | 实例字段 | 存储 buffer（普通 list，遵循 FIFO 淘汰） |

**修改**：

| 方法 | 行为变化 |
|------|----------|
| `render_to_image_tool` | 发图只发图 → 原文进缓冲 |
| `cmd_test_render` | 同上 |
| `cmd_preview_template` | 同上 |
| `on_llm_req` | 每次 LLM 请求前调用 `_inject_hidden_ctx` 将缓冲内容作为 assistant 消息注入 `req.contexts` |

### 设计思路

- 渲染过的讲义/公式原文不展示给用户（用户只收图），但 LLM 仍然需要在后续对话中引用或解释这些内容
- 缓冲内容作为普通上下文参与压缩/丢弃/reset——不赋予特权，寿命与常规对话一致
- 注入形式是伪造 assistant 消息 → 让 LLM 认为这些内容是自己之前"说过"的

### 预期流程

```
1. 用户: "(做这道题)"
2. LLM: 调用 render_to_image_tool(高斯积分原文)
3. 系统: 发图给用户 + 原文进 buffer
4. 用户: "下一步怎么算?"
5. 系统: LLM 请求前注入 buffer 内容作为 assistant 消息
6. LLM: 看到自己之前"输出"过高斯积分 → 回答下一步
```

---

## 2026-06-30：classic 模板视觉参数调整

### 改动内容

针对手机阅读场景优化 classic 模板的版心与字号：

| 项目 | 旧值 | 新值 |
|------|------|------|
| body 外圈边距 | 较大 | `18px` |
| page 内边距 | 较大 | `32px 28px` |
| 正文字号 | `16px` | `21px` |
| h1 字号 | `22px` | `29px` |
| h2 字号 | `19px` | `24px` |
| h3 字号 | `17px` | `22px` |
| 行高 | `1.8` | 保持 `1.8` |

### 设计思路

- 收窄外圈绿色边框与米色画布之间的空白，让手机一屏能容纳更多有效内容
- 放大正文字号，提升长文阅读舒适度
- 标题字号按正文比例同步放大，保持层级对比
- 行高保持不变，避免字大后显得拥挤

### 当前状态

classic 模板已按 `21px` 正文字号定稿，并在 `_conf_schema.json` 中新增了 `classic_` 开头的配置项（外圈边距、画布内边距、正文/标题字号、行高）。

- `main.py` 在 `_apply_template` 时为 classic 模板注入 CSS 变量，覆盖默认值
- `templates/classic.html` 使用 `var(--classic-xxx, default)`，即使未注入也能保持可用
- 用户可在 WebUI 配置面板中搜索 `classic_` 开头的选项进行调节

---

## v1.0 架构重构：`<render>` 标签 → LLM 工具

### 概述

旧管线被动拦截 `<render>` 标签（`on_decorating_result` / `on_llm_response`），AI 得先学会造标签才能用，且标签外纯文本会被错误吞入图片。全面重构为 Agent 工具调用模式。

### 改动清单

| 变更 | 旧行为 | 新行为 |
|------|--------|--------|
| 渲染入口 | AI 写 `<render>` 让插件拦截 | AI 直接调用 `render_to_image` 工具 |
| 生命周期组件 | 多个被动拦截钩子 | 仅保留 LLM 工具 + 4 条调试命令 |
| 图片发送 | `yield event.chain_result()`（图片会丢失） | `await event.send()` 直接发送 |
| 自动检测配置 | ~10 个相关配置项 | 全部废弃，仅保留 `preserve_text_for_context` |
| 提示词策略 | 长"功能说明书" + 示例 | 精简为决策卡片（何时用 + 用什么） |

### 设计思路

1. 标签模式让用户和 AI 都得猜——不确定哪些被截获、哪些被自动改
2. 工具模式让 AI 自己决策出图时机、选择模板，语义更明确
3. 借此重构契机，顺手清掉长期没用的配置项和 CDN 依赖

### 三个子项的详细记录见下方

---

## v1.0 子项：废弃配置清理

### 背景

架构重构后，原自动检测管线已删除，但相关配置项残留在 `_conf_schema.json` 里，用户看到会困惑"这是什么"。

### 清理清单（共 10 项）

- `enable_auto_detect` — 是否启用自动检测
- `auto_dialogue_detection` — 对话场景自动检测
- `dialogue_quote_threshold` — 对话引用阈值
- `auto_render_all` — 是否全部自动渲染
- `auto_render_min_length` — 自动渲染最小长度
- `auto_render_template` — 自动渲染默认模板
- `auto_merge_renders` — 是否合并相邻 render
- `inject_prompt` — 是否注入旧版提示词
- `example_template` — 提示词中的示例模板变量
- `preserve_text_for_context` — **保留**（接入新发送点，仍然生效）

### 保留项说明

`preserve_text_for_context` 功能在新架构下继续生效：发图时是否在对话历史中保留文本摘要，让后续聊天能引用图内细节。接入点从旧管线移到 `render_to_image_tool` 和各调试命令。

---

## v1.0 子项：MathJax 修复 + 本地化

### 背景

架构重构过程中，顺手排查了存在的两个公式渲染 bug，并把 MathJax 资源本地化。

### Bug 修复

**Bug 1 — 行内公式左右残留 `$` 符号**

- 现象：`$a^2$` 渲染后图片上显示 `$$a^2$$`
- 根因：正则匹配边界处理不当，清理不干净
- 改后：改用更精确的边界正则，确保 `$` 被完全剥离

**Bug 2 — 矩阵 `&` 转义为 `amp;`**

- 现象：LaTeX 矩阵 `&` 在 HTML 阶段被误转义，MathJax 接收不到正确语法
- 根因：HTML 转义顺序不当，先转义后传给 MathJax
- 改后：调整转义顺序，仅对非公式区块做 HTML 转义

### 资源本地化

- 原：运行时从 CDN 加载 `mathjax-tex-svg.js`（~2MB），弱网环境不可用
- 现：将 JS 文件下载到插件根目录，优先加载本地副本，不存在时回退 CDN
- 文件：`mathjax-tex-svg.js`（2MB）

---

## 2026-06-29：修复 `<render>` 标签外文本被吞入图片

### 补充说明：旧问题到底是什么

旧逻辑中 `<render>` 标签被当作分割符，分割后每一段文本都会被渲染成图片，不区分标签内外。例如 `你好<render>正文</render>再见` 会出三张图：`Image("你好")`、`Image("正文")`、`Image("再见")`，标签外的纯文本也变成了图。

共改动三处：

### 1. `_process_text` 核心逻辑（`main.py` ~L680）

- **改之后**：只有 `<render>` 到 `</render>` 之间的内容渲染成图片，标签外文本全部作为纯文本发送
- 用 `text.split(full_match, 1)` 逐个切出标签前后文本
- 标签前文本 → `Plain()`，标签内内容 → `Image()`
- 最后一段剩余文本 → `Plain()` 兜底
- 空文本不产生空 `Plain`

### 2. inject_prompt 规则 1（给 AI 的提示词）

- **旧**："所有内容必须在标签内部，标签外不要遗留任何内容"
- **新**："标签内的渲染成图片，标签外的以纯文本发送，灵活组合"

### 3. inject_prompt 规则 3（给 AI 的提示词）

- **旧**："你的所有回复内容都会被渲染成图片"
- **新**："日常对话直接纯文本回复，需要渲染的才套 render 标签"

核心思路：让 AI 自由决定哪些内容用图、哪些用纯文本，而不是一股脑全渲染成图。

### auto_merge_renders

- 配置在 `_conf_schema.json` L50，默认 `True`
- 开：多个 render 合一张图；关：每个 render 各一张图
- 两条路径标签外文本都是纯文本，不受影响

### 预期输出

```
输入: 你好！<render>正文1</render> 再见 <render>正文2</render> 拜拜

auto_merge=True:  Plain("你好！") → Image(正文1+正文2) → Plain("再见") → Plain("拜拜")
auto_merge=False: Plain("你好！") → Image(正文1) → Plain("再见") → Image(正文2) → Plain("拜拜")
```

---

## 2026-06-28：注入提示词大幅精简重写

### 背景

旧提示词是"功能说明书"式写法，按功能罗列模式 A/B、GIF、语义标签、规则、示例等，AI 看完知道"有这些工具"但不知道"什么时候该用"。用户实际场景只有讲题、表格、公式矩阵，用不到模式 B 和 GIF，大量内容是噪音。

### 砍掉的内容

- 整个"背景说明"段落（渲染原理对 AI 无意义）
- 模式 A / 模式 B 的概念区分
- GIF 动图模式全部内容（语法表两行 + 整个章节 + 示例结构）
- 两个大示例（模式 A 小说示例 + 模式 B 自定义 HTML 示例）
- 四条"重要规则"段落
- `example_template` 变量（已无引用）

### 保留的内容

- render 标签语法（`<render>` 和 `<render template="...">` 两种写法）
- 语义标签五条（`<q>` `<inner>` `<act>` `<scene>` `<aside>`）
- 两条注意事项（禁止代码块包裹、日常对话不需要 render）

### 新增的关键引导

> 当你需要讲题、列表格、写公式或矩阵时，用 `<render>` 标签从开头到结尾包裹你这次回复的全部内容。在 render 内部正常写 markdown（表格、列表等）和 LaTeX 公式即可，系统会自动转换并渲染成图片。

核心思路：从"功能说明书"改为"决策卡片"——AI 不需要理解渲染原理，只需要知道什么时候用 render、里面写什么。

---

## 项目渊源

本插件并非从零开发，早期代码（2026-06-28 及之前的变更记录）继承自原项目 **lumingya/astrbot_plugin_html_render**。

我们从该仓库 fork 后进行了深度改造：将渲染管线从被动拦截 `<render>` 标签改为 Agent 工具调用模式，本地化 MathJax 资源，增加隐藏上下文缓冲区机制，并重写提示词策略。至 2026-07-01 正式更名为 `astrbot_plugin_latex_render`，以 v1.0.0 独立发布。

- 原项目仓库：https://github.com/lumingya/astrbot_plugin_html_render