# 更新记录

> 时间倒序（最新在最前）。

---

## 2026-08-08：v1.3.2 单次字号调整与 MathJax 质量门禁

### 新增

- `latex_render_to_image` 新增可选 `font_scale` 参数：相对当前模板基础字号按 `0.75–1.5` 缩放，仅对本次渲染生效
- Classic、Aurora、Novel 与 Paper 统一支持正文、标题和表格字号缩放；Custom 不做破坏用户 CSS 的强制覆盖
- 截图前新增 MathJax 硬门禁：公式必须完成 SVG 排版，且不存在语法错误、未知命令、零尺寸或可见区域溢出

### 行为修复

- MathJax 加载失败或 15 秒超时不再被视为排版完成，也不会继续生成图片
- 去除 `noerrors` / `noundefined` 错误掩盖，使无效公式返回可定位的公式序号与错误类别
- 浏览器池和独立回退渲染共用同一公式门禁；公式内容错误不触发浏览器重建重试
- Classic 移除纸面径向渐变并改用干净的暖白底色，消除 JPEG 成图中容易出现的圆环色带
- Aurora 移除画布左上与右下的径向光斑，改用均匀深蓝底色，保留卡片内部的渐变层级与强调色

### 兼容性

- 旧工具调用不传 `font_scale` 时保持 `1.0`；现有模板、布局与持久化偏好不变
- 工具成功结果回传实际字号倍率，便于 Agent 连续执行“再大一点 / 再小一点”
- 隐藏上下文功能保持默认关闭，本次不调整

### 渲染器分层

- 将原先集中在 `renderer.py` 的页面准备、截图采集和图片后处理拆为独立模块；总入口只保留浏览器池、错误归类与阶段编排
- `RenderOptions` 下沉为共享模型，三个阶段只依赖共同参数契约，避免模块间反向引用
- 暂时保留 `renderer.py` 的既有内部函数导出，运行入口和现有调用方无需迁移

### 验证

- 普通测试 146 项通过、7 项按环境跳过；真实 Chromium 集成测试 6 项通过
- Maxwell 长文以四个内置模板分别执行 `font_scale=0.8/1.25`：98 个公式全部通过门禁，大小图与分页数量均发生预期变化
- Custom 非默认倍率和第 99 个未知命令场景均明确拒绝，未生成图片

---

## 2026-08-04：v1.3.1 模板体系调整（Aurora 内置化与 Custom 解绑）

### 摘要

Aurora 灵感卡从 `custom` 槽位转正为内置模板，承接原有的深色渐变卡片样式并继承 8 条排版滑条；`custom` 槽位重做为由报纸社论风起始稿构成的自由编辑模板，不再继承基础模板的 CSS variables。模板目录改为内置优先排序，未配置默认模板时保持 `classic` 不变。同时调整 WebUI 工作台交互与布局：移除冗余预览按钮、Custom 一键恢复默认、统一画布尺寸并修复 Aurora 滑条。

### 模板变更

- 新增内置模板 `aurora`：深色渐变灵感卡片，场景标记为“灵感记录”，继承 classic 的边距、字号、行高与标题字号共 8 条滑条
- `custom` 槽位写入空 `css_variables`：画廊不再显示滑条，渲染时也不注入样式变量；HTML/CSS 自由编辑不受影响
- `custom` 起始稿改为报纸社论风（米黄纸底、衬线字体、双线分隔标题），与 `classic`、`novel`、`paper`、`aurora` 在视觉上相互区分
- 内置模板目录顺序改为按 `manifest.json` 声明排列、自定义模板排在最后；新增内置模板不会改变默认模板

### 界面变更

- Gallery 页删除“立即预览”按钮：滑条、内容与布局变化均已自动刷新预览，按钮已冗余
- Custom 页“立即预览”改为“恢复默认”：确认后直接覆盖保存并刷新预览
- 画廊布局：左侧模板选择器固定 290px，滑条栏固定 340px，预览画布占据剩余宽度；画布高度统一为 `clamp(700px, calc(100vh - 160px), 920px)`，Gallery 与 Custom 等高

### 行为修复

- 修复 WebUI 中 custom 模板滑条无效：此前 custom 继承 classic 的 `css_variables`，画廊显示滑条，但模板 CSS 未引用对应变量，拖动无视觉效果；现 custom 不显示滑条，aurora 等使用变量的模板滑条正常生效
- 修复 Aurora 灵感卡滑条不生效：`manifest.json` 中 aurora 条目补充 `base_template: classic`，classic 系列 CSS 变量正确注入模板

### 内部调整

- WebUI `bootstrap` 响应新增 `default_custom_html`，以 `templates/_starters/custom.default.html` 作为恢复默认的唯一内容源
- 删除前端过期的硬编码 `starterTemplate()`，消除默认模板的第三份副本

### 兼容性

- 模板调用名、配置项、聊天命令与 LLM 工具保持不变；已保存的 `custom` 编辑不会被升级覆盖
- 原 custom 内容由内置 `aurora` 模板承接，样式与调用方式一致

### 验证

- 普通测试：127 passed，5 skipped（浏览器集成与真实 Chromium 用例按环境跳过）
- WebUI、模板管理与代码高亮回归测试全部通过；`bootstrap` 返回的 `default_custom_html` 与磁盘默认文件一致；aurora 样式覆盖注入 `--classic-font-size: 30px` 生效

---

## 2026-08-04：v1.3.0 模块化重构与渲染修复

### 摘要

本版本将插件的单入口与扁平模块重组为分层架构：渲染管线、模板系统与业务动作各自独立成包，入口文件收敛为组合根。对外行为（聊天命令、LLM 工具、配置项、内置模板与工作台页面）保持不变，同时修复 Playwright 浏览器版本误判与 MathJax 分隔符转义回归。

### 架构调整

- `core/` 按职责拆分为 `rendering/`（浏览器渲染、文档组装、资源注入、安全清洗与文本处理）、`template_system/`（模板发现、校验、选择与指南）和 `application/`（命令与工具业务、诊断、隐藏上下文缓冲、工作台控制器）三个包
- 新增 `config.py`（类型化配置读取与限幅）与 `preferences.py`（会话渲染偏好原子持久化）
- `main.py` 精简为组合根与装饰器薄适配层，业务逻辑下沉到 `application/actions.py`
- 渲染流程收敛到 `rendering/pipeline.py`（队列、超时、重试、冷却与结果规范化），浏览器生命周期由 `rendering/browser_runtime.py` 统一管理

### 行为修复

- 修复 Playwright 浏览器版本误判：此前只检查数据目录下是否存在任意 `chromium_headless_shell*` 目录，Playwright 升级导致浏览器 revision 变化时会误跳过安装；现改为读取 Playwright `browsers.json` 清单，按精确 revision 校验对应目录及其中的 `chrome-headless-shell` 可执行文件，不匹配时重新安装
- 修复 MathJax `inlineMath` / `displayMath` 分隔符转义回归：注入页面的 `\(...\)` 与 `\[...\]` 配置丢失一层反斜杠，导致行内与块级公式均停留在原始 LaTeX 文本
- 新增回归测试，覆盖浏览器版本判断与 MathJax 转义，防止再次回归

### 兼容性

- 聊天命令、LLM 工具（`latex_render_to_image` / `latex_render_template_guide`）、配置项与 `_conf_schema.json`、内置模板与 WebUI 工作台均与 v1.2.3 保持一致
- 用户持久化偏好、缓存与浏览器目录结构不变，升级无需迁移

### 验证

- 普通测试：127 passed，5 skipped（含 Playwright 版本判断与 MathJax 转义回归测试）
- 真实 Chromium 端到端：修复前 `mjx-container` 为 0，修复后行内与块级公式均正常渲染

---

## 2026-08-02：v1.2.3 代码高亮与语言标识开关

### 摘要

本版本将代码语法高亮与右上角语言标识统一为一项可配置功能。新增开关默认开启，关闭后保留普通 Markdown 代码块与模板基础样式，同时完整跳过 Highlight.js 资源、语言角标和布局等待。

### 配置与行为

- 新增 `enable_code_highlight` 配置，并在 AstrBot 配置页和渲染工作台中显示为“代码高亮与语言标识”
- 开启时继续按模板加载本地 Highlight.js 主题，归一化常见语言别名，并在分页测量前等待高亮完成
- 关闭时不加载脚本与主题 CSS，不创建语言角标或 ready 标记，也不进入最长 3 秒的高亮等待
- 显式声明但 Highlight.js 不支持的语言继续显示声明名称，例如 `foo` 显示为 `FOO`，但不着色、不自动猜测
- 普通代码框、代码正文与合法 `language-*` class 不受开关影响；Inline code 与可信原始 HTML 仍不参与高亮

### 兼容性

- 开关默认值为 `true`；旧配置文件缺少该键时仍按开启处理，无需迁移
- LLM 工具、模板、分页模式、输出尺寸和用户持久化偏好保持不变

### 验证

- 普通测试：106 passed，5 skipped
- 真实 Chromium 渲染：4 passed，覆盖开关两种状态、已知与未知语言、四模板主题及输出图片
- WebUI 真实浏览器交互：1 passed，确认新开关进入功能设置区
- Ruff 静态检查、差异检查与代码质量复核通过

---

## 2026-08-02：v1.2.2 Agent 工具命名空间与模板指南

### 摘要

本版本为 Agent 工具增加稳定的 `latex_render_` 命名空间，并新增按需查询模板与写作规范的只读工具。渲染工具描述聚焦排版图片交付并明确排除文生图；模板详情不再依赖每轮注入的硬编码长提示。

### 工具与提示词

- `render_to_image` 重命名为 `latex_render_to_image`，处理函数同步更名；旧工具名不再注册，避免与其他渲染插件的同名工具按加载顺序互相覆盖
- 新增 `latex_render_template_guide`：留空参数返回当前模板及实时可用目录，指定模板名返回用途、标签、内置内容规范和调用参数
- 两个工具共享 `latex_render_` 前缀；渲染工具声明“会直接发图”，模板指南声明属于 LaTeX Render 插件且“只返回说明”
- 渲染工具仅在用户明确要求图片或任务需要以排版图片交付时使用，工具描述明确排除文生图
- `template` 参数默认留空沿用当前偏好，仅在用户明确指定或已经选定模板时填写
- 可选 `inject_template_prompts` 继续默认关闭；启用时复用实时模板目录，不再维护硬编码模板清单

### 模板目录与安全边界

- 模板概览与详情统一读取 `TemplateManager` 的实际可用模板、manifest 元数据和内置 `BUILTIN_PROMPT`
- 内置模板可返回受长度限制的内容规范；Custom 只公开名称、描述和标签，不读取或返回 HTML、CSS 与模板源码
- 未知模板、空模板目录和异常元数据均返回受控文本；显示名称、描述、标签数量、标签长度和内容规范分别设定输出上限
- 模板指南独立为 `core/template_guidance.py`，渲染入口只保留工具适配和会话模板解析

### 兼容性

- 这是一次公开工具名的破坏性变更：旧 Persona、Agent 配置或工具白名单需将 `render_to_image` 替换为 `latex_render_to_image`
- 命令、配置键、模板结构、分页流程、输出尺寸和用户持久化偏好保持不变

### 验证

- 普通测试：101 passed，5 skipped
- 真实 Chromium 渲染：4 passed，覆盖 Agent 工具、用户命令、固定 A4、四模板代码高亮与输出尺寸
- Ruff 静态检查与差异检查通过；契约测试确认两个公开工具均使用 `latex_render_` 命名空间且旧名未注册

---

## 2026-08-01：v1.2.1 代码高亮与页码优化

### 摘要

本版本为显式标注语言的 Markdown 围栏代码块增加离线语法高亮，并重新设计多页输出的页码。高亮、字体与主题资源全部随插件本地提供，分页继续在 Chromium 完成布局稳定后执行；既有模板、配置结构、输出尺寸和可信 HTML 行为保持兼容。

### 新特性

- 引入固定版本 Highlight.js 11.11.2 common 浏览器构建及许可证，离线提供 Python、JavaScript、JSON、Bash、C++ 等常用语言高亮
- 仅处理带合法 `language-*` class 的 Markdown 围栏代码块；未知语言和未标注语言保持原代码，不启用自动识别
- 按模板场景选择主题：Classic 使用 `github-dark`、Novel 使用 `docco`、Paper 使用 `github`、Custom 使用 `night-owl`
- 为显式语言代码块增加右对齐语言标题，并统一 `js`、`ts`、`py`、`sh` 等常见别名的展示名称
- 多页页码改为底部居中的 `— 当前页 / 总页数 —`，根据页脚亮度自动选择深色或浅色文字，并按渲染缩放加载跨平台字体
- Classic、Novel、Paper 与 Custom 使用各自的页脚偏移，避免页码压线或脱离模板底部视觉区域

### 安全与稳定性

- HTML 清洗器仅允许长度受限、字符合法的 `language-*` class，继续移除事件属性、普通 class 与主动内容
- 语言标题通过 DOM `textContent` 创建，语言名不能注入 HTML；高亮脚本只读取固定本地资源
- Chromium 在测量高度和分页前等待高亮完成，最长等待 3 秒；资源缺失或执行失败时退化为原有纯色代码块
- 拆分渲染准备、浏览器执行、静态分页与 GIF 处理职责，降低主渲染流程的参数数量和单函数体积，不改变外部调用接口

### 验证

- 普通测试：95 passed，5 skipped
- 真实 Chromium 渲染：4 passed，覆盖四种模板、高亮后分页、代码与公式混排及输出尺寸
- Maxwell 多页样例完成逐页视觉检查，确认页码清晰、代码块和公式无裁切、模板底部无重叠

---

## 2026-08-01：v1.2.0 固定页高装箱分页

### 摘要

本版本将普通模板（`classic` / `novel` / `custom`）的分页改为固定页高容器加块装箱：内容按顶层语义块收集后按页高预算装箱，注入等高页面容器后逐页截图。每张图片尺寸一致、上下边框完整，不再出现公式贴底、边框被截断的问题。`paper` 模板继续按固定 A4 语义切片分页，不受影响。

### 改动

- 新增块收集与装箱：`_collect_pagination_blocks` 收集顶层语义块并记录高度，`_pack_into_pages` 按页高预算装箱（预算计入卡片 padding 与边框，并预留 24px MathJax 字体加载余量）
- 新增页面容器注入：`_inject_page_containers` 克隆页容器、搬移内容块并清除 box-shadow，避免投影在 `overflow: hidden` 下被裁进盒内产生底部渐变
- 分页截图改为元素级 `element.screenshot`：`page.screenshot(clip=)` 存在 4px 偏移和邻近内容污染问题
- 模板边框方案：`classic` / `novel` / `custom` 改为卡片自带实色边框（绿 18px / 灰 40px / 深色 24px），`overflow: hidden` 下不再裁掉边框，body padding 归零
- 超高单块保留硬切加续页标记兜底；配置与 WebUI 文案同步更新
- 模板定位文案：`classic` 描述与标签改为突出"手机阅读讲题"场景（长文按页分屏、一页一屏），同步 README 与 WebUI 模板画廊

---

## 2026-08-01：v1.1.0 渲染参数收敛与分页缓冲移除

### 摘要

本版本将 `html_to_image_playwright` 的 14 个平铺参数收敛为 `RenderOptions` 数据类，并移除了 1.0.8 引入的分页底部缓冲补丁。该补丁在正文紧贴切片底边时通过复制边缘像素扩展图片，会产生拖影；移除后分页输出不再附加底部扩展。

### 改动

- 渲染入口 `html_to_image_playwright` 的 14 个位置参数收敛为 `RenderOptions` dataclass，调用方与测试同步更新，渲染行为不变
- 移除 `_append_bottom_buffer` 分页底部缓冲：内容贴底时不再复制边缘像素补高，消除拖影；分页图片高度恢复为与切片高度一致，正文紧贴图片下沿为原始分页行为
- README 门面整理：版本发布徽章改为动态读取、移除版本更新段落与迁移细节（收归 CHANGELOG）、术语统一、补充导航章节，并同步更新测试契约

---

## 2026-07-29：v1.0.9 文档表述与发布信息修订

### 摘要

本版本统一 README、CHANGELOG、版本元数据与发布徽章的表述，不改变渲染行为、配置接口和模板格式。

### 改动

- README 顶部说明缩减为“支持自动分页与 A4 版式”
- README 的 WebUI、配置和模板说明改为直接陈述实现与边界
- CHANGELOG 标题改为“更新记录”，并统一旧版本记录中的口语化表述
- 版本元数据、发布徽章和测试契约更新至 v1.0.9

---

## 2026-07-29：v1.0.8 安全分页与可视化渲染工作台

### 摘要

本版本新增安全隔离、资源预算、语义分页、固定 A4 输出和独立 WebUI 渲染工作台。管理员可以在 AstrBot 插件页面中调整常用设置、查看运行状态、预览真实分页结果，并维护唯一的 `custom` 模板槽。

### 新特性

- 首次提供独立 WebUI 渲染工作台，包含“基础设置 / 模板画廊 / Custom 编辑”三个区域
- WebUI preview API 复用正式渲染的模板解析、分页与 Chromium 截图组件；消息平台发送仍由 AstrBot 消息链负责
- 基础设置按参数、功能和安全选项分区展示，完整配置仍由 AstrBot 配置页提供
- 运行诊断按状态区分正常与异常项
- 模板画廊可切换布局、实时拖动字号/行高/页边距，使用缩放、抓手和适应页面工具观察真实多页预览；抓手默认关闭
- 语义分页将标题和短引导段与紧随的公式、表格、代码或列表组成分页原子组，避免引导语与内容跨页分离
- 普通模板分页在页高预算内预留底部缓冲，降低正文紧贴图片下沿的情况；固定 A4 输出不受影响
- 基础设置新增自动分页高度，可在 1200–6000 CSS px 范围内调整；默认 3200，普通聊天建议 2400–4000
- 画廊标签改为模板的具体场景与排版特性，不再重复展示所有模板共有的 Markdown / LaTeX 能力
- Gallery 与 Custom 的 Markdown 样例统一为可展示、可编辑的内容卡片；默认测试文本完整展开，超长文本达到保护高度后再内部滚动
- Custom 简化为唯一固定槽：编辑 HTML/CSS 时自动预览、保存后直接调用，并保留 JSON 导入导出备份
- Custom 默认使用独立的深色 `Aurora 灵感卡`；仅自动升级从未编辑过的旧 Classic 克隆稿，用户已有修改不会被覆盖
- Aurora 简介明确提供 Custom 编辑入口，标签展示自由改版、HTML/CSS 和实时预览能力
- Custom 画布与左侧编辑区等高伸展；桌面双列同步滚动，窄屏按编辑区、画布、Markdown 顺序单列排列
- 工作台提供 Chromium、MathJax、中文字体、队列、耗时和最后错误诊断
- 新增 `paper` 模板：794×1123 CSS 像素纯白 A4 画布，默认约 25.4mm 页边距、小四级正文和固定同尺寸分页输出
- `render_to_image` 新增可选 `layout=auto|single`，长内容按 Markdown 顶层语义块拆成多图并逐页发送；旧值 `paged` 作为 `auto` 的兼容别名保留
- 可选的 LLM 模板提示改为精简说明，仅概述 classic、paper 与 custom，避免向每轮请求注入全部模板长提示
- 精简 `render_to_image` 的工具描述，保留输入格式、模板选择与分页参数，移除重复的调用警告
- 用户模板与布局偏好按会话和用户原子持久化，插件重载后仍保留

### 安全与稳定性

- 默认清洗脚本、样式、事件属性和嵌入页面；Playwright 默认阻断 HTTP、HTTPS 与 file 请求
- 自定义模板拒绝脚本、事件属性、iframe/object/embed、远程 URL、file URL 与 CSS `@import`
- 增加输入长度、超时、并发、队列、页高、页数和单图体积预算；浏览器失败只重试一次并进入冷却
- 背景素材只从管理员维护的 `assets/backgrounds/` 发现，`paper` 始终保持纯白
- 移除旧 `/模板画廊`、`/templategallery`、`/gallery` 聊天入口，画廊统一由插件页面承载

### 验证

- 单元测试覆盖命令、Agent 工具、配置、模板、安全、分页、偏好持久化和 WebUI API
- 真实 Chromium 覆盖用户命令、Agent 发图、GIF 探针、固定 A4 分页和 WebUI 主要交互
- `python -m pytest -q`
- `ASTRBOT_LATEX_RENDER_INTEGRATION=1 python -m pytest -q`
- `python -m ruff check .`
- `python -m ruff format --check .`

---

## 2026-07-29：v1.0.4 功能审计与端到端测试

### 摘要

逐项核对 README 中声明的 Markdown、LaTeX、模板选择、本地渲染、用户命令和 Agent 工具功能，并为用户入口与 Agent 调用补充行为测试及真实 Chromium 集成测试。运行代码和静态资源重新归档，根目录仅保留 AstrBot 入口、配置、元数据与项目文档。

### 改动

- 新增 `/测试`、`/切换`、`/查看`、`/预览模板` 的命令调用测试
- 新增 `render_to_image` 的成功、空内容、未知模板和发送失败路径测试
- 新增完整渲染管线测试，覆盖 Markdown 表格、LaTeX、内置 MathJax、模板应用和 JPEG 输出参数
- 新增真实 Chromium 集成测试，从用户命令和 Agent 工具入口生成图片，并验证 GIF 探针三帧输出
- 隐藏原文只在图片成功生成并发送后写入缓冲，渲染失败不再留下无效上下文
- 模板发现阶段忽略缺少 `{{content}}` 占位符或无法读取的 HTML 文件
- 修复 GIF 探针仍查询旧 `.danmu-line` 选择器的问题，改为检测实际使用的 `.track` 动画元素
- 移除 AstrBot 已弃用的 `@register` 装饰器，插件信息统一由 `metadata.yaml` 提供
- 将渲染、文本和模板模块整理至 `core/`，将离线 MathJax 归档至 `assets/`

### 验证

- `python -m pytest -q`
- `ASTRBOT_LATEX_RENDER_INTEGRATION=1 python -m pytest -q`
- `python -m ruff check .`
- `python -m ruff format --check .`
- `python -m compileall -q .`

---

## 2026-07-29：v1.0.3 指南合规与发布信息整理

### 摘要

按 AstrBot 插件开发指南复核代码、依赖、元数据和用户文档，修复英文命令别名未注册、动态上下文注入位置不当及 Playwright 初始化失败后仍继续加载等问题；README 按当前产品定位重新组织。

### 改动

- 命令装饰器由无效的 `aliases` 参数改为 AstrBot 支持的 `alias`，恢复 `/test`、`/switch`、`/templates`、`/previewtpl`、`/tplpreview` 和 `/probegif`
- LLM 工具参数文档改为指南要求的 `参数名(类型): 描述` 格式
- 模板提示和实验性图片原文改用 `extra_user_content_parts` 临时动态上下文，不再改写每轮系统提示词或伪造历史消息
- 隐藏原文缓冲按完整会话 UMO 隔离，且所有运行时默认值与配置 Schema 的默认关闭保持一致
- Playwright 浏览器下载或启动失败时明确中止插件初始化，避免插件显示成功却无法渲染
- 修复浏览器实例断开后的重建流程，并延迟清理 GIF 探针截图
- 移除未使用的 `aiohttp` 直接依赖，为 `mistune` 增加兼容上限
- 补全 `metadata.yaml` 的市场字段，分类设为“工具”，增加中文检索标签并统一短描述和长描述
- 重构 README，明确区分 Python 自动依赖、Chromium 下载、Linux 系统库和 CJK 字体的安装责任
- 新增文本处理、模板管理、命令契约和元数据回归测试

---

## 2026-07-10：v1.0.2 Chromium 安装与磁盘占用优化

### 摘要

插件渲染只用 headless 模式，但 `playwright install chromium` 会同时下载完整 Chromium（~415MB）和 headless shell（~270MB），完整版从未被使用。改为只安装 `chromium-headless-shell`，新用户磁盘占用从 ~688MB 降至 ~273MB。

### 改动

- `_ensure_playwright()` 安装命令从 `playwright install chromium` 改为 `playwright install chromium-headless-shell`，只下载 headless shell 变体
- 已存在检测从匹配 `chromium*` 改为精确匹配 `chromium_headless_shell*`，避免误判完整版存在而跳过 headless shell 安装
- README 问题排查章节同步更新（提及 headless shell、~270MB）
- 版本号 1.0.1 → 1.0.2

### 背景

Playwright 1.40+ 的 `playwright install chromium` 会同时下载两个变体：
- `chromium-XXXX`（~415MB）— 完整版浏览器，供 `headless=False` 使用
- `chromium_headless_shell-XXXX`（~270MB）— 精简版，供 `headless=True` 使用

`renderer.py` 的 `chromium.launch()` 未传 `headless` 参数，Playwright 默认 `headless=True`，因此完整版 Chromium 不会被加载，只会增加磁盘占用。

### 对现有用户的影响

升级后不会自动删除旧的 `chromium-XXXX` 目录。如需回收 ~415MB 磁盘空间，手动删除 `playwright_browsers/chromium-*`（保留 `chromium_headless_shell-*`）即可。

---

## 2026-07-10：v1.0.1 体积优化与元数据补全

### 摘要

插件体积从 18.30 MB 降至 2.18 MB（-88%），主要来自移除从未被加载的内置字体文件；同时对齐 AstrBot 插件开发指南，补全 `metadata.yaml` 可选字段；优化 Playwright 启动流程。

### 改动

**1. 移除 fonts/ 目录（-15.9 MB）**

- 删除 8 套 Google Fonts woff2 字体文件、`fonts_local.css`、`manifest.json`（共 409 个文件）
- 原因：内置模板 `classic` / `novel` 只用系统字体名（思源黑体、苹方、微软雅黑等），从不请求 `fonts.gstatic.com` URL，`renderer.py` 的字体路由拦截逻辑不会触发，这些字体从未被加载
- `renderer.py` 保留路由拦截；`manifest.json` 不存在时记录 debug 日志并中止对应请求

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
| 提示词策略 | 完整格式说明与示例 | 调用条件与输入格式 |

### 设计思路

1. 标签模式的触发边界不明确，难以判断内容是否会被自动处理
2. 工具模式由 Agent 显式调用并指定模板
3. 同时移除不再使用的配置项和 CDN 依赖

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

### 补充说明：旧问题

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

输出方式改为由 Agent 选择，文本回复与图片渲染不再强制绑定。

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

旧提示词按功能罗列模式 A/B、GIF、语义标签、规则和示例，但缺少明确的使用时机说明。主要使用场景集中在讲题、表格和公式矩阵，模式 B 与 GIF 说明在默认提示词中占用较多上下文。

### 移除的内容

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

提示词缩减为调用条件和输入格式，不再包含渲染实现说明。

---

## 项目渊源

本插件并非从零开发，早期代码（2026-06-28 及之前的变更记录）继承自原项目 **lumingya/astrbot_plugin_html_render**。

我们从该仓库 fork 后进行了深度改造：将渲染管线从被动拦截 `<render>` 标签改为 Agent 工具调用模式，本地化 MathJax 资源，增加隐藏上下文缓冲区机制，并重写提示词策略。至 2026-07-01 正式更名为 `astrbot_plugin_latex_render`，以 v1.0.0 独立发布。

- 原项目仓库：https://github.com/lumingya/astrbot_plugin_html_render
