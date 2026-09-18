# Open WebUI Handoff

## Objective

裁剪为轻量的 OpenAI-compatible 聊天应用，同时保留：

- 认证、会话、用户角色和用户管理
- 核心聊天、流式响应和多模型选择
- 模型配置、系统提示词和聊天历史
- OpenAI-compatible 图片生成和图片编辑
- 本地图片上传
- SQLite 默认数据库以及 PostgreSQL 支持

## Constraints

- 只能使用 `podman` 和 `podman compose`，不能使用 Docker 命令。
- 不能删除数据库、持久化 volume、上传目录或历史 migration。
- 不能保留已删除功能的兼容层、空实现 store、旧 dead code 或旧配置入口。
- 必须保留 Open WebUI 品牌、LICENSE 及相关标识。
- 没有创建 commit。

## Round 3 — 2026-09-18: SSRF 加固 / SQLite 调参 / 镜像 331 MB / 纯 pure 命名

> 命名：Round 2 的镜像标签 `lite` 从本轮起统一为 **`pure`**（compose 默认
> `localhost/open-webui:pure`，README 已同步；下方 Round 2 表格仍保留历史标签名）。

### Results（同一台机器，rootless podman）

| 指标 | Round 2（r2c） | Round 3（pure，`fec50870`） | 说明 |
| --- | --- | --- | --- |
| image | 420 MB | **331 MB** | site-packages 184.4 → 99.1 MB |
| fresh idle（cgroup） | 127.9 MB | **104.8 MB** | cgroup 差额 ~23 MB 来自 zstandard 的 file cache |
| fresh idle（anon） | 98.7 MB | **97.0 MB** | asgiref 不再常驻 |
| fresh idle（RSS / PSS） | 120.5 / 106.4 MB | **120.3 / 108.4 MB** | RSS 含共享库映射，非私有内存 |
| fresh idle（Private_Dirty） | 93.9 MB | **93.8 MB** | 真实私有内存 |
| startup → /health | 1.5~1.7 s | **1.57 s** | 空配置 |
| 120 chats + 图片 + idle 5 min（同协议） | RSS 123.2 | RSS **123.4** | 两者都稳定，不增长 |
| 400 chats×20 msgs（78 MB 库）浏览后 | RSS 209.1 / PD 120.7 | RSS **202.8 / PD 116.0** | 重复浏览与 5 min 空闲均无增长 |
| 回归（fresh volume + mock OpenAI） | 16/16 | **20/20** | 另加用户隔离、OAuth 404、可选依赖 501 |
| SSRF 集成（HTTP 级） | — | **8/8** | 见下 |

真实 volume 兼容性：把 `open-webui_open-webui` volume 复制一份，用 pure 镜像启动，
数据 **users 1 / chats 3 / chat_message 33 / alembic `d4c1a8e37b62`** 与线上完全一致，
`.webui_secret_key` 保留，`/static/logo.png` 200。未改动线上容器。

### 1. SSRF（优先级 1）— 新增 `backend/open_webui/utils/ssrf.py`

- `validate_url()`：http/https、禁止 userinfo、host 为字面量或 DNS 解析后**所有**地址逐个校验；
  拦截 loopback、RFC1918、link-local、CGNAT 100.64/10、0.0.0.0/8、198.18/15、240/4、
  multicast、reserved、`169.254.169.254`/`fd00:ec2::254`、IPv4-mapped、6to4、Teredo、
  NAT64 `64:ff9b::/96`、IPv6 site-local `fec0::/10` 等。
- `SSRFResolver`：包装 `aiohttp` connector 的 resolver，**每次建连时**重新校验解析出的 IP
  （DNS rebinding 窗口内也拦得住）；可信源的主机名允许解析到内网（管理员显式配置的后端）。
- `ssrf_safe_get()`：手动跟随 3xx，**每一跳都重新 validate**，跨源自动剥离
  Authorization/Cookie；`allow_redirects=False` 时直接返回 3xx 响应。
- 可信例外：`is_trusted_origin()` 结构化比较 `scheme + hostname + port`，绝不用
  `startswith`；仅管理员配置的 base URL 精确 origin 生效（images 生成用
  `IMAGES_OPENAI_API_BASE_URL`，编辑用 `IMAGES_EDIT_OPENAI_API_BASE_URL`）。
- 统一接入：`routers/images.py`（`get_image_data` / `load_url_image`）、
  `utils/files.py`（`get_image_base64_from_url`）、`utils/oauth.py`（头像抓取）。
- 测试：`backend/open_webui/test/test_ssrf.py` **59 项**（含 redirect 每跳重校验、
  connect-time resolver、userinfo/suffix 混淆、DNS 失败拒绝等）；HTTP 级集成 **8/8**
  （loopback/metadata/私网/私网 redirect 全部 400，可信 origin 与同源 redirect 200）。

### 2. SQLite RAM 参数（默认值已调整）

- `DATABASE_SQLITE_PRAGMA_CACHE_SIZE` `-65536` → **`-16384`（16 MiB）**；
  `DATABASE_SQLITE_PRAGMA_MMAP_SIZE` `268435456` → **`67108864`（64 MiB）**。
- 微基准（274 MB 库、全表扫描型负载，16 组组合）：mmap 64 + cache 16 时 RSS 102 MB /
  读 47 ms；原 256 + 64 时 RSS 284 MB / 读 9 ms；mmap 0 时读 48~57 ms。
- 小库（10 MB）与真实应用负载（400 chats、78 MB 库、索引查询）无感知差异；
  浏览后 PD 差 <1 MB。大库若要更快的全表扫描可显式调回 256/64（env 覆盖即可）。
- 结论：默认 16/64 是家庭/个人场景的合理下限；写入延迟与 busy 在全部组合中均为 0 错误。

### 3. 默认依赖与镜像（详见 `requirements-*.txt` / `Dockerfile`）

- **构建期生成 `backend/open_webui/latest-changelog.json`**（`utils/changelog.py`，纯 stdlib，
  Docker `changelog` stage 跑 `python changelog.py CHANGELOG.md 5`）；运行时只读 JSON，
  彻底移除 **beautifulsoup4 + Markdown**（约 1.8 MB，且不再有解析开销）。
- **zstandard 移除**（starlette-compress 的硬依赖）：`main.py` 改
  `CompressMiddleware(app, zstd=False)`，保留 brotli+gzip；容器 file cache 24.7 → 3.2 MB。
- **asgiref 移除**：`utils/audit.py` 的类型导入改 `TYPE_CHECKING` + `from __future__ import annotations`。
- **PDF / black / Pillow 改 optional**：新增 `requirements-pdf.txt`、`-code-format.txt`、
  `-pillow.txt` 与 `ENABLE_PDF` / `ENABLE_CODE_FORMAT` / `ENABLE_PILLOW` build args
  （compose 由 `WEBUI_ENABLE_*` 透传）。缺失时分别返回 501 或优雅跳过，行为已实测。
- **httpx 保留（教训）**：httpx 在 open_webui 代码里无直接 import，但 **authlib 的
  starlette_client 集成会 import httpx**；删除它导致 OAuth 500（集成测试抓到）。已恢复
  `httpx==0.28.1`（不带 http2/socks/zstd extras）。
- **ensurepip 内嵌 pip 删除**（~2 MB）。
- 未动原版 UI / emoji / 实际使用的字体与国际化；CJK 字体（24 MB）仍随镜像发布，
  仅供后端 PDF 使用（在后续 layer 里删除不会缩小镜像，故不做假动作）。

### 4. Socket.IO / Engine.IO 定量（未改默认行为）

- 同进程增量实测：`requests` **+5.1 MB**（engineio client 强依赖）、
  `socketio+engineio` **+6.8 MB**，合计 **+11.9 MB** anon、约 +330 个模块、启动 +0.06 s。
- 方案 A（默认）：保留 Socket.IO，接受 fresh idle cgroup ~105 MB / anon ~97 MB。
- 方案 B（未实施）：SSE/HTTP polling 可省掉上述 ~12 MB，但需要重做
  streaming / stop generation / chat active / 多标签页 / 多用户状态同步，
  属于功能层取舍；按要求不作为默认，仅记录为后续可选项。

### 5. 长期 RSS 增长定位（结论：不是泄漏）

- 方法：容器内采样 RSS/PSS/Private_Dirty/SQLite maps/cgroup；120 chats+图片+5 min idle；
  另 400 chats×20 msgs（78 MB DB）浏览 60 条 + 重复浏览。
- 浏览大历史后增长主要来自 **SQLite mmap/WAL 文件页**（可回收，计入 RSS 不计入 PD）
  与 **Python allocator high-water**；PD 首次使用后 +20~33 MB 后不再上升。
- 重复浏览 -0.3 MB、空闲 5 分钟 0 增长；未发现任务/连接泄漏（线程数全程 6~9）。
- `tracemalloc` 对 `import open_webui.main` 的快照：纯 Python 分配 ~50 MB，
  其余为 C 扩展（pydantic_core / cryptography / SQLAlchemy C ext 等），无常驻大数据结构。

### 6. 镜像审计（pure，最大项）

- 文件：`cryptography/_rust.abi3.so` 13.8 MB、`uvloop .so` 13.1 MB、CJK 字体 22.4 MB、
  `libpython` 5.4 MB、`_brotli` 5.2 MB、`pydantic_core` 4.7 MB、Swagger UI 2.4 MB、
  `welcome.mp4` 1.9 MB、`CHANGELOG.md` 1.2 MB。
- Python 包：SQLAlchemy 21.8、cryptography 14.3、uvloop 13.0、aiohttp 7.3、pydantic_core 5.0、
  brotli 5.0（此前 27.7 fonttools / 23.0 zstandard / 20.0 Pillow / 6.1 black 已移出默认）。
- 逐项决策：zstandard（移）、httpx（保留，authlib 依赖）、asgiref（移）、
  bs4+Markdown（移）、fpdf2+fonttools（optional）、Pillow（optional）、black（optional）、
  authlib+joserfc（保留，2.3 MB 且懒加载）、i18n（不动）。

### 7. 验收命令与结果

- `WEBUI_SECRET_KEY=... uv run --frozen pytest backend/open_webui/test -q` → 64 passed。
- fresh volume 容器 + `owui-mock`：20/20 功能回归、8/8 SSRF 集成、startup 1.57 s。
- 真实 volume 复制升级：数据零变化、迁移版本一致、密钥保留。
- 全程未使用 `podman compose down -v`，未删除线上 volume；容器/测试 volume 已清理。

### Remaining（后续可做，不建议本轮做）

- Socket.IO ultra-lite（SSE）≈ 12 MB；若必须 <100 MiB cgroup 才值得动。
- PDF 字体 24 MB：需要把字体移出 `backend/` 上下文（或独立 tar 保存）才能在禁用 PDF 时
  真正不进镜像；仅为 24 MB，暂不做。
- Swagger UI 2.4 MB、CHANGELOG.md 1.2 MB（fallback 用）、i18n 死 key 清理（需上游文案对比）。
- Alembic 启动期 import（迁移后不释放）；可评估迁移子进程化。

## Round 2 — 2026-09-18: default SQLite / lean image / optional features

### Results

| 指标 | Round 1 | Round 2 | 说明 |
| --- | --- | --- | --- |
| image | 750 MB | **420 MB** | `localhost/open-webui:lite`（r2c，`b59536c4`） |
| fresh idle（cgroup） | ~207 MB | **103 MB** | podman stats 102.7MB |
| fresh idle（RSS） | ~207 MB | **124 MB** | PSS_Anon 96 MB |
| 真实部署 idle | 207~225 MB | 161 MB stats / 183 MB RSS | 含 `models.base_models_cache` 启动预取 + 用户浏览 |
| startup → /health | — | **1.5~1.7 s** | 空配置；真实配置因模型预取 ~10s（原有行为） |

功能回归 **16/16 通过**（fresh volume + mock OpenAI）：注册/登录、`/api/config`、模型列表、流式+非流式聊天、文件上传/下载、图片生成、图片编辑、图片配置、`/api/changelog`（懒解析）、`code/format`（懒 black）、PDF（懒 fpdf）、LDAP 未装降级 400、OAuth 路由懒加载 404。

真实 compose 升级验证：原 `open-webui_open-webui` volume 数据零变化（users 1 / chats 1 / chat_message 4 / alembic `d4c1a8e37b62`），`.webui_secret_key` 保留，`/static/*` 品牌资源 200。

### 镜像瘦身来源

- **`chown -R /app` 重复层（155 MB）** → 只 `chown app:app /app/backend/data`（COPY 已带 `--chown`），最大单项。
- `vite.config.ts` `sourcemap: false`：build 83 MB → 45 MB（其中 map 37 MB）。
- 可选依赖剥离进独立 requirements：psycopg2-binary+psycopg(≈35MB)、redis+hiredis(≈7MB)、azure-identity(≈8MB)、ldap3(≈5MB)、openai SDK(≈14MB，实测完全未被 import)、typer/rich/pygments(≈14MB，CLI 改可选)、brotlicffi、python-mimeparse、pytz、pyyaml/watchfiles/python-dotenv（uvicorn[standard]/httpx[cli] 拆掉）。
- pip/setuptools/wheel 在安装后卸载（≈18 MB）。
- `.dockerignore` 排除 `backend/open_webui/static/fonts/*-Variable.ttf`（≈38 MB）：PDF 只 `add_font` Regular/Bold/Italic，`pdf-style.css` 的 @font-face 不会被 fpdf 读取（已核对 fpdf 源码无 font-face 处理）。

### 依赖拆分 / 可选功能

- `backend/requirements-min.txt`：默认（SQLite）；`requirements-postgres.txt`（仅 Psycopg 3）/`-redis.txt`/`-azure.txt`/`-ldap.txt`/`-optional.txt`/`-cli.txt`；`requirements.txt` 保留为 compat（= min）。
- `pyproject.toml` extras：`postgres`/`redis`/`azure`/`ldap`/`cli`/`all`；`uv.lock` 已更新。
- Dockerfile build args：`ENABLE_POSTGRES/ENABLE_REDIS/ENABLE_AZURE/ENABLE_LDAP`（compose 由 `WEBUI_ENABLE_*` 传递，默认 false）。
- PG 只用 Psycopg 3：sync/async/Alembic URL 统一改写 `postgresql+psycopg://`（`internal/db.make_sync_url`，`migrations/env.py` 复用）；未装驱动时启动即报带安装指引的 RuntimeError（已实测）。

### 懒加载 / 常驻内存

- CHANGELOG：导入时 0.57s + 约 36 MB（soup 被模块级变量滞留）→ `env.get_changelog()` 按需解析、缓存结果、释放中间对象。
- 按需导入（功能保留）：`fpdf`/PDFGenerator、`PIL`（图片编辑归一化失败时优雅跳过）、`black`、`azure.identity`、`ldap3`。
- Redis：`utils/redis.py`、`tasks.py`、`main.py` 的 `RedisStore` 全部去掉顶层 import；未配置 `REDIS_URL` 时既不 import 也不启动 listener；requirements 默认不含 redis/hiredis。配置了 Redis 但没装包时日志给出明确指引。
- OAuth：`utils/oauth.py`（authlib/joserfc）懒加载；`config.py` 的 `OAuth` 改 `TYPE_CHECKING`；新增 `utils/oauth_manager.py:get_oauth_manager()` 首次使用时创建并缓存到 `app.state`。
- CLI：`open_webui/__init__.py` 用 `__getattr__` 懒加载 typer（实现移到 `cli.py`），`typer` 改为 optional extra；避免 typer→rich→pygments 常驻，也让 `httpx._main` 不再加载 rich/pygments。
- 移除未使用的 `openai` SDK；`pytz` → `datetime.timezone.utc`。

### 前端 / 静态资源

- `package.json` 删除确认未引用：`@sveltejs/adapter-auto`、`@sveltejs/adapter-node`、`sass-embedded`、`tslib`、`xlsx`、`prosemirror-keymap`；lock 已重生成，`vitest` 8/8 通过。
- 保留原版 UI 与 emojis（18 MB）/welcome 视频等实际使用的素材；未重写界面。

### 本轮踩坑（勿重蹈）

1. **`static/static/` 不是冗余目录**：`config.py` 启动时会**清空 `backend/open_webui/static` 顶层文件**，再从 `FRONTEND_BUILD_DIR/static`（由仓库 `static/static/` 经 SvelteKit 产出）拷回。删除它会导致 `/static/logo.png`、favicon、splash 等全部 404（本次已踩，已恢复）。
2. **本地（非容器）跑 `open_webui.main` 会改动宿主仓库**：同样的同步逻辑会把宿主 `backend/open_webui/static` 顶层文件删除并从本机 `build/static` 重拷。若未先 `npm run build`，这些文件会直接消失（本次根因）。在仓库里跑本地 app 前先构建前端，或接受这些文件被重建。
3. 图片生成/编辑的 base URL 是 `IMAGES_OPENAI_API_BASE_URL`；而 `config.py` 末尾会把 `OPENAI_API_BASE_URL` 强制为 `https://api.openai.com/v1`。只配置外部 OpenAI-compatible 连接时，必须显式设置 `IMAGES_OPENAI_API_BASE_URL`/`IMAGES_OPENAI_API_KEY`（或在管理设置里配置图片引擎），否则图片请求会走公网。
4. 跨容器访问宿主端口受本机 firewalld 策略影响（默认 `podman` bridge → 宿主 LAN IP:19000 被拒；compose 网络正常）。测试 mock 时用宿主 LAN IP 并放在 compose 网络对应的路径更真实；不能依赖容器内 `127.0.0.1`。

### 安全未动

多用户隔离、Auth、SSRF 防护、文件访问权限、数据库迁移均未削弱；本轮只调整依赖可选性与导入时机，migration 历史与 SQLite 数据未删除、未改动。

## Current State

### Completed

- 前端：
  - 聊天消息 tool-call/actions/审批 UI 全部删除；`structuredOutput.ts` 仅保留 message + reasoning。
  - 权限体系前后端同步收缩；删除已移除功能的管理界面、`shortcuts.ts`、`stores/index.ts`、`utils/index.ts`（2120→约 890 行）、`apis/index.ts` 的大批死代码。
  - `AdvancedParams.svelte` 重写为 OpenAI-only（删除 mirostat/tfs_z/num_*/keep_alive/think/format/use_mmap/function_calling/top_k 等）。
  - `admin/Settings/Images.svelte` 重写为 OpenAI-only（删除 A1111/ComfyUI/Gemini 引擎、workflow 编辑器、URL 校验）；`apis/images/index.ts` 删除 `verifyConfigUrl`、`getImageGenerationConfig`、`updateImageGenerationConfig` 三个死 API。
  - **2026-09-17 修复（这些是"打不开/卡logo/页面空白/CSS 丢失/无侧栏"的根因）**：
    - `+layout.svelte` 补 `getContext` 导入（缺失导致启动即 `ReferenceError`，splash 永不消失）。
    - `+layout.svelte` 补回主样式导入 `../tailwind.css`、`../app.css`、`tippy.js/dist/tippy.css`（此前整站无 Tailwind 样式）。
    - `+layout.svelte` 用 `$i18n` 替换无效的 `getContext('i18n')`（组件内 setContext 只对子组件生效，自身取到 undefined）。
    - `+layout.svelte` 登录恢复后调用 `refreshChatList()` 载入侧栏历史。
    - `(app)/+layout.svelte` 恢复未登录跳转 `/auth?redirect=`（新增 `sessionReady` store 避免刷新误跳），并改为 `flex` 布局（侧栏 245px + 主区），桌面默认展开侧栏。
    - `Navbar.svelte` 侧栏开关不再只限移动端（桌面关闭后也能重新打开）。
    - `Chat.svelte`、`admin/+layout.svelte` 移除已失效的 `--sidebar-width` max-width 逻辑。
    - `utils/index.ts` 恢复被误删的 `removeFormattings/removeEmojis/removeDetails/getFormattedDate/getFormattedTime/getCurrentDateTime/getWeekday/MONTH_NAMES`。
    - `ChatItem.svelte` `draggable` 改为 `itemElement.draggable`；`MessageInput.svelte` `class:rounded-full` 改为普通 class；`CodeBlock.svelte` 补回 highlight.js 主题 CSS。
    - 删除死组件 `Selector.svelte`（未导入且 `$i18n` 无效）。
    - `Sidebar.svelte` 重写回官方样式：logo + 名称 + 折叠按钮、New Chat / Search 图标按钮、置顶模型、历史列表、底部 **用户菜单触发器**（头像 + 用户名）——此前触发器缺失，导致 **Admin Panel / Settings / Workspace / Playground / Sign Out 全部无法打开**；用户菜单组件本身一直存在（`Sidebar/UserMenu.svelte`）。
    - 布局为侧栏定义 `--sidebar-width`，与官方用户菜单宽度一致。
    - `SettingsModal.svelte` 补回设置导航：常规（General/Interface/Account/Connections/Keyboard/Data Controls/About）+ 管理设置（General/Authentication/Connections/Models/**Images**/Database），并接上此前未挂载的 `admin/Settings/Images.svelte`。
    - 根布局处理 `?settings=` 深链（`/admin/settings/<tab>` 会打开对应设置页）。
    - **2026-09-18 还原原版 UI**（用户反馈"跟原版不一样/外部链接改炸了"）：
      - `Sidebar.svelte` 直接移植上游 1771 行版本（只剔除 notes/channels），恢复 Folders/Chats 分组、时间分组（Yesterday 等）、快捷键提示、置顶菜单项（Workspace/Playground）、拖拽排序、侧栏宽度拖拽、折叠等原版结构。
      - `(app)/+layout.svelte` 改回上游结构（`flex flex-row justify-end` + `<main class="contents">`），`Chat.svelte` 与管理后台恢复 `md:max-w-[calc(100%-var(--sidebar-width))]` 逻辑；`--sidebar-width` 由 Sidebar 组件写入。
      - `admin/Settings/Connections.svelte` 还原上游"外部连接"管理页（OpenAI API 开关、连接列表 + 编辑/启停、+ 添加、User Connections: Direct Connections / Cache Base Model List、Save）。
      - `AddConnectionModal.svelte` 还原上游 800 行版本（URL/Key/Auth/Session/OAuth/API Type/Provider/Passthrough/Headers/Model IDs/Tags/Prefix、验证连接等），仅剔除 Ollama。
      - `apis/configs` 补回 `getConnectionsConfig`/`setConnectionsConfig`。
    - **2026-09-18 修复会话丢失（"崩溃/401/外部连接加载不出来"的根因）**：
      - `podman-compose.yaml` 增加 `WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key`：此前 `start.sh` 把密钥写在容器工作目录（`/app/backend/.webui_secret_key`），每次重建容器都会重新生成 → 所有 JWT 失效 → 前端全部 401。
      - `src/app.html` 增加 `vite:preloadError` 自动刷新：容器重建后旧页面引用已删除的 chunk 时自动 reload，避免"打不开/白屏"。
    - **2026-09-18 全量还原（用户要求：保留功能必须和原版一致，"只做减法不做重写"）**：
      - 方法：以 `git show HEAD:<file>`（上游 v0.11.3）为基准，逐个文件比对；凡是"重写"的保留功能文件全部回炉为"上游 − 已删功能"，不再手写简化实现。
      - 前端还原：`MessageInput`(2733→1861，含 RichTextInput/tiptap、附件菜单、@/斜杠命令、自动补全、消息队列)、`ModelSelector/Selector` + `ModelItem`/`ModelItemMenu`、`SettingsModal`(1325)、`Chat.svelte`(含消息队列/上下文压缩/chatTasks/命令)、`ResponseMessage`、`Placeholder`、`ChatControls`、`CodeBlock`（mermaid/vega 预览）、`HTMLToken`（视频/音频/YouTube/iframe 渲染）、`Citations`（引用渲染）、`CodeEditor`（后台格式化 API）、根布局/应用布局/各分组布局、`ModelEditor`(1074)、管理端 `Images`/`Models`/`AdminTabIcon`/`ManageModelsModal`、`Permissions`、`FileItem`/`FileItemModal`、`apis/configs` 等。
      - 依赖：重新加入 tiptap/prosemirror/turndown/lowlight、heic2any、mermaid、vega、vega-lite、idb 等 27 个包。
      - 后端还原：`config.py`(3244→1285，142 个保留配置键 + `Config.configure`)、`oauth.py`(完整 SSO：Google/Microsoft/GitHub/OIDC/Feishu)、`routers/tasks.py`(自动补全接口)、`utils/middleware.py`/`payload.py`/`models.py`/`response.py`、`utils/access_control/files.py`（文件/文件夹访问控制）、`socket/*`（Redis 多进程、事件）、`events.py`、`main.py`（`/api/config` 完整保留项、PWA manifest）、`routers/configs.py`（导入/导出/连接/模型/建议/横幅）、`storage/provider.py`（本地存储语义）、`routers/utils.py`（`/code/format` + black 依赖）。
      - 已删功能残留清理：arena/evaluation、`chat.tool_permissions`、空 stub（SkillsModal/ToolServersModal/ValvesModal）、空目录、前端 stores 中 9 个已删功能 config 字段。
      - 验证：`npm run build` 通过；本地 venv + mock OpenAI：注册/登录、`/api/config`、模型列表、聊天（流式/非流式）、图片生成/编辑、文件夹/文件上传全部通过；无头 Firefox 截图核对聊天页/设置/管理端 Connections/用户管理/工作区/管理端 Images 与原版一致，无页面 JS 错误。
    - **已知有意差异（与上游）**：
      - 已删功能模块整体删除（Ollama、RAG/知识库/网页搜索、工具/MCP/Functions/Skills、频道、笔记、日历、自动化、音频、评测/反馈、记忆、通知、Pipelines/SCIM/子代理/遥测、云存储、ComfyUI/A1111/Gemini 图片、Google Drive/OneDrive）。
      - 构建/依赖清单为精简版：`Dockerfile` 只装 `requirements-min.txt`；`requirements.txt` 指向它并补 `psycopg2-binary`；新增 `black==26.5.1`（代码格式化接口需要）。
      - `routers/images.py` / `utils/files.py` 的 `validate_url`/`get_ssrf_safe_session` 为精简实现（上游在已删的 `retrieval/web/utils.py` 中有更强的 SSRF 防护）。
      - README/Makefile 等文档/构建文件为 lite 版本。
      - 生产镜像不含测试用 debug hook（已核对）。
  - `package.json` 删除 58+ 个未引用依赖；恢复 `alpinejs`；lock 已重新生成。
  - `vite.config.ts`：删除 onnxruntime 静态拷贝插件与 `/ollama` 代理。
  - `npm run build` 通过；`npx vitest run` 8 tests 通过；`svelte-check` 仅剩 `APP_VERSION`/`APP_BUILD_HASH` 两个已知误报（Vite define）。
- 后端：
  - `utils/middleware.py` 从 6363 行重写为 2785 行：只保留认证后聊天处理、系统提示词、上下文压缩、图片生成、reasoning/output 流式和后台任务。
  - `main.py` 从 2150 行收缩到 1744 行：删除 webhook 事件端点、SCIM、OpenTelemetry、`config-legacy`、外部 manifest 路径、notifications 路由；补 `has_folder_write_access` 导入。
  - 删除 `routers/notifications.py`、`routers/scim.py`、`utils/notifications.py`、`utils/webhook.py`、`utils/telemetry/`、`utils/mcp/` 相关、`utils/images/comfyui.py`。
  - `events.py`：删除 webhook/notification sink 与旧功能事件目录，仅保留仍被调用的 80 个事件定义。
  - `utils/misc.py`、`utils/task.py`：删除 Ollama/code-interpreter/tool/RAG 残留；`convert_output_to_messages` 仅保留 message/reasoning。
  - `routers/tasks.py`：删除 `/queries`、`/auto`、`/emoji` 端点及相关配置/表单字段。
  - `routers/openai.py`：删除 pipeline payload 与 tool_calls/tool 消息转换分支。
  - `routers/images.py`：重写为 OpenAI-only（IMAGE_CONFIG_KEYS / ImagesConfig / get_models / image_generations / image_edits 只保留 OpenAI 分支；删除 `/config/url/verify`、A1111 auth、ComfyUI workflow）。
  - `config.py`：恢复 `run_migrations()`（API 启动时建表/升级）、`STATIC_DIR` 与前端静态资源拷贝；`DEFAULT_CONFIG` 补齐 `ui.default_user_role`、`ui.watermark`、`task.*`、`image_generation.openai.*`、`images.edit.openai.*` 等；删除 SCIM/OTEL/工具服务器/retrieval/A1111/ComfyUI/Gemini 配置。
  - `env.py`：删除 SCIM、OTEL、MCP/tool-server、retrieval access 配置；补 `ENABLE_ADMIN_EXPORT`、`IFRAME_CSP`；删除遗留 `_cuda_error` 引用。
  - `models/users.py`：删除 SCIM 查询方法（保留 DB 列与 migration）。
  - `backend/requirements-min.txt` + `pyproject.toml` + `uv.lock`：补 `Markdown==3.10.3`（env.py/pdf_generator 需要）。
  - `Dockerfile`：补 `requirements-min.txt`、`CHANGELOG.md` 拷贝。
  - `python -m compileall` 通过；AST 未定义名检查与跨模块导入检查通过。
- 验证（本地 venv + mock OpenAI 服务，`/tmp/opencode/mock_openai.py`）：
  - `/health` 200；`/api/config` 返回裁剪后的配置。
  - 首个用户注册成为 admin；登录、`/api/models`（外部 OpenAI-compatible 模型）、`/api/v1/auths/` 正常。
  - 流式聊天：`POST /api/chat/completions`（chat_id + message_ids）→ mock SSE 正常消费，助手消息落库（content + output + done=true），标题生成成功。
  - 非流式聊天：返回完整 JSON。
  - 文件上传：`POST /api/v1/files/` 落盘 + DB 记录。
  - 图片生成：`POST /api/v1/images/generations` → mock `/v1/images/generations` → 保存为文件记录。
  - 图片编辑：`POST /api/v1/images/edit`（本地文件 URL）→ mock `/v1/images/edits`（multipart）→ 保存为文件记录。
  - 图片配置：`GET/POST /api/v1/images/config(/update)` 正常（此前 500 已修复）。

### Active

- `npm run check` 未与本裁剪基线对比（上游类型噪声约 3600 条）。

### Blocked

- 无。

## Verification History

- Node v24.18.0（engine 要求 <=22），命令均带 `npm_config_engine_strict=false`。
- `npm install --package-lock-only --ignore-scripts`：成功（清理依赖后）。
- `npm run build`：成功（含 Images.svelte / AdvancedParams.svelte 重写后）。
- `npx vitest run --passWithNoTests`：8 tests passed。
- `python -m compileall -q backend/open_webui`：成功。
- `uv sync` + `uv run python -m uvicorn open_webui.main:app`：应用可启动，迁移执行，配置种子写入，API 全链路通过（见上）。
- 2026-09-17 浏览器级验证（无头 Firefox + 页面内错误上报 + 慢加载图片控制截图时机）：
  - 容器：`/` 正确跳转 `/auth?redirect=%2F`，登录页正常渲染，无 JS 错误。
  - 本地 venv + mock OpenAI（已登录 admin）：主界面完整渲染（侧栏 + 历史记录 + 输入框），无 JS 错误。
- 容器（2026-09-17 深夜，修复后重建）：`podman build` 成功；`podman compose -f podman-compose.yaml down`（不带 `-v`）+ `up -d` 重建；`curl --fail http://localhost:3000/health` → `{"status":true}`。
- 镜像命名：`podman-compose.yaml` 现使用 `localhost/open-webui:pure`（纯本地标签，Round 3 由 `lite` 改名）；此前 `ghcr.io/open-webui/open-webui:main` 只是本地 build 标签，从未推送/覆盖官方镜像，现已删除本地该标签以免混淆。
- 未执行系统级 sudo 命令；历史 migration 与数据库文件未删除；未使用 `podman compose down -v`。

## Next Move

1. Round 3 已完成并验证（见顶部 Round 3 章节）。可选后续：
   - Socket.IO ultra-lite（SSE）≈ 12 MB；只有必须 <100 MiB cgroup idle 时才建议评估。
   - PDF 字体 24 MB 需移动字体在上下文中的位置才能真省；Swagger 2.4 MB / CHANGELOG 1.2 MB 可按需删。
   - `npm run check` 与基线对比（上游类型噪声仍在）；i18n 死 key 清理。
2. 停止容器时只用 `podman compose stop` 或 `podman compose down`（不带 `-v`），不得删除 `open-webui` volume。
3. 本地跑 `open_webui.main` 前先 `npm run build`，否则 `backend/open_webui/static` 顶层文件会被启动流程清掉（见 Round 2 踩坑）。
4. 当前线上容器仍是旧的 `lite` 镜像；下次 `podman-up.sh` / `podman compose up -d` 会因 tag 变化自动重建为 `pure`（volume 不变，已验证迁移兼容）。

## Relevant Files

- `HANDOFF.md`: 本交接文档。
- `backend/requirements-min.txt`：默认依赖（唯一装入默认镜像的清单）；
  `requirements-postgres/redis/azure/ldap/pdf/code-format/pillow/optional/cli.txt` 为可选功能依赖。
- `Dockerfile`：多阶段构建（frontend / changelog / runtime）；`ENABLE_*` build args；只 chown data 目录；安装后卸载 pip/setuptools/wheel/zstandard 与 ensurepip。
- `backend/open_webui/utils/ssrf.py`：SSRF 防护（validate_url / SSRFResolver / ssrf_safe_get / is_trusted_origin）。
- `backend/open_webui/test/test_ssrf.py`、`test_changelog.py`：SSRF 与 changelog 解析回归测试（`uv run --frozen pytest backend/open_webui/test -q`）。
- `backend/open_webui/utils/changelog.py`：stdlib changelog 解析器，兼构建期 CLI（生成 `latest-changelog.json`）。
- `podman-compose.yaml`：默认 tag `pure`；`WEBUI_ENABLE_*` build args 透传；`WEBUI_SECRET_KEY_FILE` 持久化 JWT 密钥。
- `backend/open_webui/cli.py`：typer CLI；`__init__.py` 仅 `__getattr__` 懒加载，保持包导入轻量。
- `backend/open_webui/env.py`：`get_changelog()` 懒解析（原模块级 soup 占 ~36MB）。
- `backend/open_webui/utils/oauth_manager.py`：OAuth manager 懒创建入口（authlib 不常驻）。
- `backend/open_webui/internal/db.py`：`make_sync_url()` 将 PG 统一为 `postgresql+psycopg://`；未装 psycopg 时报可操作错误。
- `backend/open_webui/main.py`: FastAPI 装配（1744 行）。
- `backend/open_webui/config.py`: 配置默认值与种子、迁移入口、静态资源拷贝。
- `backend/open_webui/env.py`: 环境配置。
- `backend/open_webui/events.py`: 事件定义与发布。
- `backend/open_webui/utils/middleware.py`: 精简后的聊天中间件（2785 行）。
- `backend/open_webui/utils/misc.py`、`utils/task.py`: 通用工具与任务模板（已收缩）。
- `backend/open_webui/routers/images.py`: OpenAI-only 图片生成/编辑。
- `backend/open_webui/routers/openai.py`: OpenAI-compatible 聊天/模型。
- `backend/open_webui/routers/files.py`: 本地文件 API。
- `backend/open_webui/migrations/`: 历史 migration，禁止修改。
- `src/lib/components/chat/*`: 精简后的聊天 UI。
- `src/lib/components/admin/Settings/Images.svelte`: OpenAI-only 图片设置。
- `src/lib/components/chat/Settings/Advanced/AdvancedParams.svelte`: OpenAI-only 高级参数。
- `src/lib/stores/index.ts`、`src/lib/utils/index.ts`、`src/lib/apis/index.ts`: 前端核心（已收缩）。
- `package.json` / `package-lock.json`、`vite.config.ts`、`Dockerfile`、`podman-compose.yaml`。
