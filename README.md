# AstrBot_Plugin LaTeX Render 

[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-blue)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.9+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> 本项目为 vibe coding 产物

LLM 主动调用的图片渲染工具，支持文本、Markdown、LaTeX 公式渲染为图片。基于 LLM 工具调用架构，AI 自行决定何时出图、选用何种模板。本项目灵感来源于 [lumingya/astrbot_plugin_html_render](https://github.com/lumingya/astrbot_plugin_html_render)（MIT 协议）。

## 功能一览

- **LLM Agent 工具**：AI 通过 `render_to_image` 工具主动发图，告别标签拦截模式
- **双内置模板**：`classic` 用于讲题排版，`novel` 用于小说叙事
- **Markdown + LaTeX 公式**：支持标准语法，前端 MathJax 离线渲染
- **全局原文本缓冲区**（实验性功能，未充分测试）：可选开启，图片渲染后原文本将会持续注入回上下文。

## 安装

### 1. 获取插件

如果插件已发布到 AstrBot 插件市场，您可以直接从市场安装。

如果从仓库获取，请打开插件 GitHub 仓库页面，点击绿色的 `Code` 按钮，选择 `Download ZIP` 下载源代码压缩包。下载完成后，在 AstrBot 管理面板中前往「插件」→「安装插件」→「从文件安装」，选择该 `.zip` 文件上传即可。

### 2. 依赖项

本插件依赖以下 Python 库：

- `playwright` — 浏览器自动化引擎
- `aiohttp` — 异步 HTTP 客户端
- `mistune` — Markdown 解析器
- `Pillow` — 图像处理库

AstrBot 通常会在插件安装时自动安装以上依赖。如果自动安装失败，请手动运行：

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置文件

插件根目录包含以下配置文件，无需手动创建：

| 文件 | 说明 |
|------|------|
| `_conf_schema.json` | 插件配置定义，用于 WebUI 配置面板 |
| `metadata.yaml` | 插件元数据（名称、作者、版本等） |

### 4. 重载/重启 AstrBot

安装或更新插件后，在 AstrBot WebUI 中找到本插件并点击"重载插件"，或直接重启 AstrBot 服务，即可使更改生效。

插件初始化时会自动创建模板目录和缓存目录。

## 配置

所有配置项均可在 WebUI 插件面板中修改。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| **基础** | | | |
| `default_template` | string | `""` | 默认模板名（留空用第一个可用） |
| `inject_template_prompts` | bool | `false` | 是否在 LLM 请求时注入模板独有指令 |
| **渲染** | | | |
| `render_width` | int | `600` | 画布宽度（px） |
| `render_scale` | int | `2` | 分辨率倍数，越高越清晰 |
| `enable_markdown` | bool | `true` | 启用 Markdown 语法解析 |
| `enable_math` | bool | `true` | 启用 LaTeX 数学公式渲染 |
| **经典模板** | | | |
| `classic_body_padding` | int | `18` | 外圈绿色边距（px） |
| `classic_page_padding_y` | int | `32` | 画布上下内边距（px） |
| `classic_page_padding_x` | int | `28` | 画布左右内边距（px） |
| `classic_font_size` | int | `22` | 正文字号（px） |
| `classic_line_height` | float | `1.8` | 行高 |
| `classic_h1_size` | int | `31` | h1 字号（px） |
| `classic_h2_size` | int | `26` | h2 字号（px） |
| `classic_h3_size` | int | `23` | h3 字号（px） |
| **实验性功能** | | | |
| `enable_hidden_ctx_buffer` | bool | `false` | 独立缓冲区：发图后把原文摘要注入上下文，仅推荐需在对话超过上下文长度设置后仍需引用图片内容的用户开启 |

## 使用方式

### LLM 工具（主路径）

Agent发现用户需要讲解、列公式、画表格或者用户主动要求时，可调用 `render_to_image`工具将整段讲解过程（包含文字与公式）渲染为图片：

```
render_to_image(
  content="## 勾股定理\n设直角三角形两直角边为 $a$、$b$，斜边为 $c$，则\n$$a^2 + b^2 = c^2$$",
  template="classic"
)
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `content` | ✅ | Markdown / LaTeX 内容，不要包裹 `<render>` 标签 |
| `template` | ❌ | `classic` 或 `novel`，留空用默认模板 |

### 用户命令

| 命令 | 别名 | 用法 |
|------|------|------|
| `/测试 <文本>` | `/test` | 测试当前模板渲染效果 |
| `/切换 <名或ID>` | `/switch` | 切换自己的默认模板 |
| `/查看` | `/templates` | 查看可用模板列表 |
| `/预览模板 <名或ID> [文本]` | `/previewtpl` | 临时预览指定模板，不改默认设置 |
| `/探针gif` | `/probegif` | 渲染一张 GIF 测试功能 |

## 模板指南

### classic — 经典讲题排版

结构化知识呈现首选。绿色外框 + 米色画布，版心经过手机端调优，9 项视觉参数全部配置化，可以直接在 WebUI 面板调，不用改代码。

示例渲染内容：多标题层级、行内公式、块级公式、有序列表、代码块。

### novel — 小说风格模板

叙事、故事、对话场景专用，支持 5 个语义标签：

| 标签 | 用途 | 样式 |
|------|------|------|
| `<q>` | 对话台词 | 棕色背景 + 引号 |
| `<inner>` | 内心独白 | 灰色斜体 + 括号 |
| `<act>` | 动作描写 | 灰色斜体 + 虚线下划线 |
| `<scene>` | 场景描写 | 左侧边框 + 淡绿色背景 |
| `<aside>` | 旁白叙述 | 居中灰色小字 |

### 更多模板

如需更多模板，可参考上游项目的 [templates 目录](https://github.com/lumingya/astrbot_plugin_html_render/tree/main/templates)。

## 待开发功能

有原型，本插件暂未开放使用：

- **GIF 录制**（待开发）：通过 Playwright 截图序列合成 CSS 动效 GIF，可在 WebUI 中配置录制时长、帧率和分辨率倍数
- **自定义背景图**（待开发）：支持氛围背景和正文水印两种渲染模式，提供固定、轮询、随机三种切换策略，透明度可调

## 注意事项

- 模板用 UTF-8 编码保存
- MathJax 使用本地副本渲染（`mathjax-tex-svg.js`），无需联网
- `templates` 目录不能为空，否则渲染会直接报错