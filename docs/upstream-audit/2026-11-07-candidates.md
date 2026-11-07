# Open WebUI Pure 上游候选修复清单（v0.12.5 → v0.13.0，2026-11-07）

- 审计范围：`f7ac7ee10..c38885a1a`（v0.12.5 → v0.13.0），共 194 个提交、551 个文件。
- 记录基线：本地 `cf38af786`（审计上下文冻结值）；上游 `c38885a1a`；merge-base `f7ac7ee10`。
- 判定口径：`建议取用`、`仅取部分/适配`、`翻译按现有键筛选`、`不涉及/不导入`、`暂不引入`、`Pure 已覆盖`、`中间版本/被替代`、`合并节点`。
- 优先级结果：**P1 = 0 项，P2 = 4 项，P3 = 28 项**。完整 194 条判定见同目录的 `2026-11-07-commits.json` / `2026-11-07-commits.csv`。
- 预算漂移提示：`context.md` 冻结的本地基线是 `cf38af786`，但部分批次判定时读取的本地分支已前进到 `cc50498ce`、`2fdb0f2bf`、`0393a28ce`、`9ddae7f4`（均为审计期间/之后在本地落地的移植提交）。本清单不改动批次实质判定，只按任务要求重排编号；涉及“Pure 已覆盖”或“审计后似已移植”的条目已在文中标注，取用前必须按当前 HEAD 复核。

## P1：安全、鉴权、隐私与数据完整性候选

本范围内**没有**优先级为 P1 的保留功能候选（0 项）。

| 编号 | 上游提交 + 原始标题 | 判定 + 文本检查 | 取用理由及边界 | 本地定位 |
| --- | --- | --- | --- | --- |
| — | （无 P1 候选） | — | 见下方说明 | — |

说明：

1. 临时聊天会话绑定 `321701c1af09`（refac，临时聊天按创建者 user/session 绑定、聊天补全/resume 鉴权、socket 定向发送、断线续传）原为 P1 重点候选；判定时核查到本地分支已有 `cc50498ce fix(security): bind temporary chats to their creating session`，安全子集已完整覆盖，其余为已删除的 Side Chat/ChatTabs/终端功能，故判 `Pure 已覆盖`，未重开为 P1。注意 `cc50498ce` 不在冻结基线 `cf38af786` 上，属审计期间前进的本地提交。
2. 删除功能的安全修复 `4adf3083f3`（RAG 压缩包解压炸弹）、`b4b6cc936d`（knowledge 轮询鉴权）、`1d5373066d`（OTel 指标序列膨胀）、`47934d1cc2`（终端策略设置被覆盖）均按产品边界判 `不涉及/不导入` 并标 `security_skip`，不因安全属性导入已删功能。
3. Responses API 流转换/usage、非 ASCII 停止序列属于保留的 OpenAI 兼容链路数据正确性修复，按影响面降为 P2，列入下表。

## P2/P3：其余保留功能候选

> 为便于阅读，P3 表格中部分本地路径省略了公共前缀 `src/lib/components/`（后端路径除外）；完整路径以 `2026-11-07-commits.csv` 的 `local_targets` 列为准。

### P2（4 项）

| 编号 | 上游提交 + 原始标题 | 判定 + 文本检查 | 取用理由及边界 | 本地定位 |
| --- | --- | --- | --- | --- |
| 69 | `96c1cfca6e25` fix: Temporary Chat toggle on a folder page drops the folder (#33456) | 建议取用 · 通过（仅文本检查） | 在 `/folders/` 页用顶栏按钮或 `/temporary` 切换临时聊天时不再强制 `goto('/')`，避免丢失文件夹、系统提示词和默认模型；两处路径条件加 `!startsWith('/folders/')`，本地上下文完全一致。 | `src/lib/components/chat/MessageInput.svelte`；`src/lib/components/chat/Navbar.svelte` |
| 175 | `e789513ea62e` refac（实际主体为 Responses API 流转换） | 仅取部分/适配 · 冲突/路径变化/前置差异 | 只取 `openai.py`、`middleware.py` 的 Responses SSE→Chat Completions 转换，以及 `response.py`/`openai.py` 的 `created`/`refusal`/`finish_reason`/usage 字段映射；按 Pure 的 92 行 `response.py` 重写。排除 Ollama 转换器、Anthropic 适配器、functions/MCP 全部 hunk；须与 193 一起实现。 | `backend/open_webui/routers/openai.py`；`backend/open_webui/utils/middleware.py`；`backend/open_webui/utils/response.py` |
| 189 | `dd6720c528f8` fix: non-ASCII stop sequences on a model reach the provider corrupted (#33614) | 仅取部分/适配 · 冲突/路径变化/前置差异 | 只取 `apply_model_params_to_body_openai` 的一行：`bytes(...).decode('unicode_escape')` 改为 `latin-1 + backslashreplace` 后再解转义，避免 `終`/`café` 被破坏；上游第二处 Ollama 分支不取。审计后本地 `2fdb0f2bf` 已出现同名修复，取用前先复核当前 HEAD。 | `backend/open_webui/utils/payload.py` |
| 193 | `aa1326eaeaee` fix: replies cut off at the token limit on a Responses API connection lose their token usage (#33619) | 仅取部分/适配 · 冲突/路径变化/前置差异 | 把 `response.completed` 分支扩展为同时接受 `response.incomplete`，使达到 token 上限或被内容过滤而提前结束的回复仍返回 usage；Pure 等价函数在 `middleware.py` 第 509 行。须与 175 配套，否则 `/openai/chat/completions` 流式输出仍不是标准 chunk。 | `backend/open_webui/utils/middleware.py`；`backend/open_webui/routers/openai.py` |

### P3（28 项）

| 编号 | 上游提交 + 原始标题 | 判定 + 文本检查 | 取用理由及边界 | 本地定位 |
| --- | --- | --- | --- | --- |
| 30 | `13bede8ba6` fix(a11y): Enter and Space on a notification's Dismiss button dismiss it instead of opening the chat (#33406) | 建议取用 · 通过 | NotificationToast 外层 keydown 增加 `e.target !== e.currentTarget` 保护，避免在 Dismiss 上按 Enter/Space 同时打开聊天；仅取这一行。 | `src/lib/components/NotificationToast.svelte` |
| 34 | `15d98d4610` fix(a11y): a filter's clear button has a name and isn't inside the filter's button (#33416) | 建议取用 · 通过 | 把 TagSelector 清除按钮移出 Select 触发按钮并加 `aria-label='Clear filters'`；本地 en-US 缺该键，移植时补键。 | `src/lib/components/workspace/common/TagSelector.svelte` |
| 35 | `d89699992a` fix(a11y): a group's checkbox in the member picker has a name and isn't inside the group's button (#33418) | 建议取用 · 冲突 | 分组行由外层 `<button>` 包 Checkbox 改为 `div + 独立按钮`，Checkbox 加 `ariaLabel` 与 `on:change`；本地结构有漂移，需手工适配，本地 Checkbox 已支持 `ariaLabel`。 | `src/lib/components/workspace/common/MemberSelector.svelte` |
| 37 | `476b6f49e4` fix(a11y): fields on Workspace, Notes, Playground and chat pages have names (#33422) | 仅取部分/适配 · 冲突 | 只取保留部分：Controls 系统提示文本域、CodeBlock、EmojiPicker、Tags、Playground Chat/Message/Completions/Images、ModelEditor 的 Model Name/ID、AccessControl 写权限开关。Functions/Channel/FileNav/Notes/Knowledge 属已删功能不取；CodeBlock 需先给本地 CodeEditor 加 `ariaLabel` prop，TTS Voice 跳过。 | `Controls.svelte`；`CodeBlock.svelte`；`CodeEditor.svelte`；`EmojiPicker.svelte`；`Tags.svelte`；`playground/Chat.svelte`；`playground/Chat/Message.svelte`；`playground/Completions.svelte`；`playground/Images.svelte`；`Models/ModelEditor.svelte`；`common/AccessControl.svelte` |
| 38 | `24c891fabe` fix(a11y): fields in windows and the Settings window have names (#33424) | 仅取部分/适配 · 冲突 | 只取 Groups/General 的 Name 标签与分享范围 select、ArchivedChats/ChatsModal 的 `Search Chats` aria-label、FolderModal 的 Folder Name 与背景图 `aria-labelledby`；InterfaceSettings 本地已有 label 关联可略，Terminal/Tool/Automation/Calendar/Channel/Notifications/Memory 等不取。 | `admin/Users/Groups/General.svelte`；`chat/Settings/ArchivedChats.svelte`；`layout/ChatsModal.svelte`；`layout/Sidebar/Folders/FolderModal.svelte` |
| 39 | `0ea4591258` fix(a11y): Admin Settings fields are named by their visible labels (#33426) | 仅取部分/适配 · 冲突 | 只取 Authentication 的 `AdminSettingField forId/id`、OpenAIConnection 的 `API Base URL`、General 的 Folder Max File Count/WebUI URL、Images 的模型/尺寸、Interface 的上下文压缩/自动补全、Models 的 `Search Models`。Audio/CodeExecution/Documents/WebSearch/Ollama 不取；多数字段需按本地 `AdminSettingField` 手工加 `forId/id`。 | `admin/Settings/Authentication.svelte`；`Connections/OpenAIConnection.svelte`；`General.svelte`；`Images.svelte`；`Interface.svelte`；`Models.svelte` |
| 44 | `d11a5f0f03` fix(a11y): the sidebar can be resized from the keyboard (#33440) | 建议取用 · 通过 | 侧栏拖拽分隔条增加 ArrowLeft/ArrowRight 每次 ±10px、写 localStorage、`tabindex=0`、`aria-label='Resize panel'`、`aria-orientation` 与 `aria-valuenow/min/max`；单文件通过，需补 `Resize panel` 键。 | `src/lib/components/layout/Sidebar.svelte` |
| 46 | `afcd1cd7ee` fix(a11y): Analytics and group member tables can be sorted from the keyboard (#33432) | 仅取部分/适配 · 通过 | Analytics 属已删功能不取；仅取 Groups/Users 表格：`th` 内改 `button`、加 `aria-sort` 与 `sortState`，排序可键盘触发，本地父版本一致。 | `src/lib/components/admin/Users/Groups/Users.svelte` |
| 48 | `487a193d69` fix(a11y): the emoji button in Set your status can be reached with the keyboard (#33436) | 建议取用 · 通过 | UserStatusModal 的 emoji 入口由不可聚焦 `div` 改为 `button` 并加 `aria-label='Emoji'`；单文件通过。 | `src/lib/components/layout/Sidebar/UserStatusModal.svelte` |
| 50 | `3d0de7ed86` fix(a11y): the full-size image viewer is a dialog that keeps focus inside it and returns it on close (#33443) | 建议取用 · 通过 | ImagePreview 全屏查看器加 focus-trap、`role=dialog`/`aria-modal`/`aria-label`、`tabindex=-1`，关闭或销毁时 deactivate；本地已有 focus-trap 依赖，文件与上游父版本一致。 | `src/lib/components/common/ImagePreview.svelte` |
| 55 | `3bb962f2bb` refac | 仅取部分/适配 · 通过 | 新增的 `BlockHandle.svelte` 构件拖拽属新功能不取；仅取 `listDragHandlePlugin.js` 的健壮性修复（update/destroy、Escape/blur 清理 ghost 与监听、非 editable 禁用、docChanged 清状态）。不要带入依赖 `y-prosemirror/prosemirror-history` 的 `moveBlock`。 | `src/lib/components/common/RichTextInput/listDragHandlePlugin.js` |
| 58 | `a988369a8e` fix(a11y): tag and voice suggestions can be chosen with the arrow keys and Enter (#33452) | 仅取部分/适配 · 冲突 | TTSVoiceInput 属已删音频功能不取；仅取 Tags 的 `role=listbox/option`、ArrowUp/Down、Enter 选中与 `aria-activedescendant/id` 关联。前置是 37 在 Tags 补的 `aria-label='Add a tag'`，需先做 37。 | `src/lib/components/common/Tags.svelte` |
| 60 | `c4daef0c94` fix(a11y): icon buttons named only by a tooltip have names (#33454) | 仅取部分/适配 · 冲突 | 只取保留文件的图标按钮 aria-label：admin Models、ChatsModal、ChatItem、PinnedModelItem、UserMenu、UserStatusModal、playground Images、AccessControl、SVGPanZoom、FileItemModal、ManageProviderModels、FormattingButtons。排除 Terminal/Evaluations/Events/Integrations/channel/Tools/Knowledge 等；UserMenu 的 notes/calendar/automations 固定项跳过。 | `admin/Settings/Models.svelte`；`ManageProviderModels.svelte`；`common/FileItemModal.svelte`；`RichTextInput/FormattingButtons.svelte`；`common/SVGPanZoom.svelte`；`layout/ChatsModal.svelte`；`Sidebar/ChatItem.svelte`；`Sidebar/PinnedModelItem.svelte`；`Sidebar/UserMenu.svelte`；`Sidebar/UserStatusModal.svelte`；`playground/Images.svelte`；`common/AccessControl.svelte` |
| 65 | `6a789c1199` fix(a11y): 8 fields named "Password", by a placeholder, or not at all have names (#33477) | 仅取部分/适配 · 冲突 | ScheduleDropdown/SqliteView 属已删功能不取，EditUserModal 的 rotatedAPIKey 本地不存在；仅取 ResponseMessage/UserMessage 的 `aria-label='Message number'` 与 Account 的 JWT/API Key placeholder。en-US 新增 4 键中仅 `Message number` 属保留功能，需补。 | `chat/Messages/ResponseMessage.svelte`；`chat/Messages/UserMessage.svelte`；`chat/Settings/Account.svelte` |
| 66 | `27eb2d2eff` fix(a11y): the page buttons' Previous and Next have names, and the current page is marked (#33475) | 建议取用 · 通过 | Pagination 的上一页/下一页加 `aria-label`，当前页加 `aria-current='page'`，引入 `getContext('i18n')`；两个键本地 en-US 已有。 | `src/lib/components/common/Pagination.svelte` |
| 71 | `a3801c4bd5` fix(a11y): 25 fields, switches and buttons with no name, or only a placeholder, have names (#33471) | 仅取部分/适配 · 冲突 | 仅取保留功能：消息编辑 textarea、文件夹删除复选框/重命名、连接开关 `ariaLabel`、侧栏聊天项/用户状态输入。排除 Pipelines/Automations/Channel/AskUserCard/FileNav/Notebook/Port/Knowledge；OutputEditView 的 `Text` 本地缺键，应改用现有等价文案。 | `Messages/OutputEditView.svelte`；`Messages/ResponseMessage.svelte`；`Messages/UserMessage.svelte`；`Placeholder/FolderTitle.svelte`；`Settings/Connections/Connection.svelte`；`Sidebar/ChatItem.svelte`；`Sidebar/RecursiveFolder.svelte`；`Sidebar/UserMenu.svelte`；`Sidebar/UserStatusModal.svelte`；`workspace/Models/ModelEditor.svelte` |
| 72 | `3361943104` refac | 仅取部分/适配 · 冲突 | 实为保留功能弹层小修复：app.css 清 transparent tippy 内容内边距、DropdownSub 的 max-width 改 rem、suggestions.ts 关闭默认 maxWidth、Tags 用 `popupElement.offsetWidth` 计算左边界避免窄屏越界；排除 Channel/CommentFilePreview/TTSVoiceInput。app.css 需手工插入现有规则后。 | `src/app.css`；`common/DropdownSub.svelte`；`RichTextInput/suggestions.ts`；`common/Tags.svelte` |
| 82 | `1dd3793d4e` fix(a11y): drawers keep keyboard focus inside and are announced as dialogs (#33547) | 仅取部分/适配 · 冲突 | 给通用 Drawer 加 `role=dialog`、`aria-modal`、`ariaLabel`、`tabindex` 与 focus-trap，仅适配 Pure 的 ChatControls、InputModal 两个调用点；排除 Channel/Comments/CodeEditorModal/Notes/Knowledge/SkillFiles；focus-trap 依赖已存在。 | `chat/ChatControls.svelte`；`common/Drawer.svelte`；`common/InputModal.svelte` |
| 114 | `a06aa230f7` refac | 仅取部分/适配 · 冲突 | 主体是 ChatControls→ChatTabs、Browser/终端/FileNav 改造，必须排除；唯一可取的是 `Drawer.svelte` 把无条件 `document.body.appendChild(modalElement)` 改为仅当父节点不是 body 时追加，避免响应式更新反复搬移 DOM、破坏焦点/滚动状态；需手工适配一行。 | `src/lib/components/common/Drawer.svelte` |
| 123 | `295b077893` refac | 仅取部分/适配 · 通过 | 只取 `codemirror.ts` 的语言描述表：`.svelte` 用 HTML 模式、Shell 增加 zsh/bash 别名、Dockerfile/Containerfile 匹配；Git diff/FileNav 属已删 Desktop/Git 功能，不取，不新增依赖。 | `src/lib/utils/codemirror.ts` |
| 165 | `f773e057e2` fix(a11y): three buttons' names include the text they show (#33593) | 仅取部分/适配 · 通过 | 只取 UserList：把 `Change User Role` 的 aria-label 改为 `sr-only` span，使按钮名包含当前角色文本；UsageChart/NoteEditor 属已删功能不取，复用现有翻译键。 | `src/lib/components/admin/Users/UserList.svelte` |
| 166 | `51cef9e26f` fix(a11y): task list checkboxes are named by their item's text (#33589) | 建议取用 · 冲突 | 为 Markdown 任务列表 checkbox 加唯一 id 与 `aria-labelledby`，让读屏器以列表项文字命名；本地是 disabled 简化版，需保留现有 `onTaskClick` 与样式差异。 | `src/lib/components/chat/Messages/Markdown/MarkdownTokens.svelte` |
| 168 | `aec5796a53` fix: Preview opens a code block nested in a list, quote or details block (#33586) | 建议取用 · 冲突 | 给列表/引用/details 内的 `svelte:self` 递归调用补传 `onPreview`，修复嵌套代码块点 Preview 无反应；本地六个递归点均缺失，按本地行号适配，不引入上游 doc/chat tabs 属性。 | `src/lib/components/chat/Messages/Markdown/MarkdownTokens.svelte` |
| 169 | `4ea29c0d61` refac | 建议取用 · 冲突 | 实为草稿恢复修复：`initNewChat` 中 `restoreChatInput` 恢复草稿后，挂载编辑器会清空 prompt，故保存到 `chatInputPrompt` 并在 `tick` 后重设；只取该两处逻辑，不取桌面/终端事件代码。审计后本地 `9ddae7f4` 已出现“restore drafts”提交，取用前复核。 | `src/lib/components/chat/Chat.svelte` |
| 173 | `0171427a10` fix(a11y): Tab cancels shortcut recording instead of binding Tab, and focus stays on the shortcut (#33597) | 仅取部分/适配 · 冲突 | 把 Tab 与 Escape 同列为取消，绑定按钮加 id，取消/绑定后 `tick` 再聚焦；本地无上游 XMark 删除按钮，相关 hunk 不取，不新增键位。 | `src/lib/components/chat/Settings/Shortcuts.svelte` |
| 174 | `a671146b91` fix(a11y): windows opened from a menu return focus to the menu button when they close (#33601) | 仅取部分/适配 · 冲突 | 给 Modal/ConfirmDialog 的 focus-trap 加 `setReturnFocus`，capture 阶段记录弹窗外焦点目标，使菜单按钮被卸载后关闭窗口仍能归还焦点；需适配本地 `allowOutsideClick`/暂停陷阱与 confirm/cancel 清理。 | `src/lib/components/common/Modal.svelte`；`src/lib/components/common/ConfirmDialog.svelte` |
| 177 | `563d621854` refac | 仅取部分/适配 · 冲突 | 新增 `normalizeImageFile`：对 MIME 为空或 `application/octet-stream` 的拖放文件按 JPEG/PNG/GIF/WEBP/AVIF/HEIC 文件头识别并重建 File，修复 macOS Photos 拖入图片被当作普通文件；只取 `utils/index.ts` 与 chat/MessageInput 调用点，channels 不取。 | `src/lib/utils/index.ts`；`src/lib/components/chat/MessageInput.svelte` |
| 180 | `8e61cc0210` refac | 仅取部分/适配 · 冲突 | 抽出并修正上下文 token 估算的两处数据问题：结构化 output 已含正文时不再重复计 content/tool_calls；用 usage 检查点估算最新消息在报告 usage 之后的增量。只取估算逻辑就地改，不取上游纯函数化签名与阈值参数化。审计后本地 `9ddae7f4` 已出现“refine context usage estimates”，取用前复核。 | `src/lib/components/chat/Chat.svelte`；`src/lib/components/chat/MessageInput.svelte` |

## 暂不引入（与保留功能相关，需记录）

以下条目触及保留路径，但因新功能、视觉重排、大重构、依赖冻结迁移或本地结构不存在而不取；完整列表见 CSV。纯 README/版本号/格式化/仅已删功能的 `暂不引入` 不再重复列出。

| 编号 | 上游提交 + 原始标题 | 判定 + 文本检查 | 不取理由及边界 | 本地定位 |
| --- | --- | --- | --- | --- |
| 3 | `c5981aaea6` refac | 暂不引入 · 冲突 | Channel/TerminalMenu 断点、ChatControls/Controls/SearchModal/Sidebar 布局重构；本地结构差异大，全部冲突，属新版布局而非明确缺陷修复。 | — |
| 6 | `8650cd2dd5` feat: generate a title when renaming a chat from the top bar (#33382) | 暂不引入 · n/a | 顶栏重命名聊天时调用模型生成标题，显式新功能；本地 Navbar 无顶栏标题编辑。 | — |
| 16 | `b29f7781aa` refac | 暂不引入 · n/a | showControls 布尔改字符串以承载 Comments 页签 + 加载骨架屏重排；本地缺 startChatLoad 前置。RichTextInput 的销毁空指针保护可独立适配，但不在本批导入。 | — |
| 21 | `f62bd78fa0` refac | 暂不引入 · n/a | Workspace 列表空状态文案/列宽调整，同时含 Knowledge/Skills/Tools 与评论按钮；视觉/文案调整，非缺陷修复。 | — |
| 27 | `f2a990f6da` fix(a11y): every window has a name for screen readers (#33412) | 暂不引入 · 冲突 | 56 个 Modal 调用点补 ariaLabel；其中 23 个路径本地存在，但依赖上游 Modal.svelte 新增 `ariaLabel` prop，Pure 的 Modal 仍只有 `role/aria-modal` 且本提交未改组件，逐文件冲突，需专门适配。 | — |
| 32 | `be1a36376a` refac | 暂不引入 · n/a | Workspace Models/Prompts 无编辑权限时显示只读 Switch，依赖本范围新增 `is_active` 字段与迁移 `6f8c2a91d4e7`；迁移冻结且本地列表无该字段。 | — |
| 33 | `5acb235c82` fix(a11y): the model picker's active option stays rendered and announced after scrolling the list (#33414) | 暂不引入 · 冲突 | 依赖上游 combobox、`aria-activedescendant`、visibleStart/visibleEnd 与 ITEM_HEIGHT 虚拟化；本地 ModelSelector 无该结构，直接移植会破坏现有选择器。 | — |
| 43 | `c9ee89467e` feat: {{USER_ROLE}} prompt variable for the signed-in user's role (#33441) | 暂不引入 · n/a | 新增提示变量与新功能；本地 task.py/MessageInput 存在但不取。 | — |
| 49 | `fe0d22cc24` refac | 暂不引入 · n/a | 新增 ModelPreview/Overview 弹窗并将 Overview 从侧栏标签改为 Modal，属新功能；Comments 并入 chat controls 属已删功能。 | — |
| 52 | `3814b7b2f1` refac | 暂不引入 · n/a | 新增 notification inbox 模型/路由/迁移与 utils/inbox，重写 events sink；保留文件改动普遍 import 已删 notifications/comments 模块，新增迁移 `e42c8f710a36` 禁止导入。 | — |
| 54 | `5f45546809` refac | 暂不引入 · n/a | RecursiveFolder 行容器 pr-6 内边距移位，纯样式整理；本地结构不同。 | — |
| 59 | `68df5123ff` fix(a11y): opening a Search menu moves focus to its options, and Escape returns focus to its button (#33450) | 暂不引入 · n/a | 本地 SearchModal 是不同版本，完全没有 panel/data-search-panel/togglePanel 结构，修复对象不存在。 | — |
| 79 | `9959fc95a2` refac | 暂不引入 · n/a | @/Emoji/斜杠/Prompts/Skills 建议列表视觉重排，非缺陷修复，并夹带已删 Channel/Knowledge/Skills 命令组件。 | — |
| 80 | `5bd49c38e9` refac | 暂不引入 · n/a | 删除 Desktop AppSidebar/isApp 外壳并重排 OnBoarding/Sidebar 视觉；Desktop 已按边界移除，非保留功能修复。 | — |
| 81 | `3cda94d403` refac | 暂不引入 · n/a | 移动端侧栏宽度改为按 window.innerWidth 计算；本地无 MOBILE_WIDTH/对应 Drawer width 参数，属布局重构。 | — |
| 102 | `ab71357980` refac | 暂不引入 · 冲突 | RichTextInput 新增 CopyableCodeBlock 节点视图、Copy 按钮/toast/剪贴板，显式新功能。 | — |
| 104 | `ee8b69e718` refac | 暂不引入 · 冲突 | TipTap 代码块配色改 highlight.js 主题样式，视觉改造且与新增 CopyableCodeBlock 耦合。 | — |
| 106 | `2d7cf5ec99` refac | 暂不引入 · 冲突 | 大型聊天 UI 重构：showControls→showTabs、Controls 标签移除、参数/模型控件迁移，依赖已删 ModelControls/TerminalMenu/Comments/语音组件；属 Tabbed Workspace 式重设计。 | — |
| 107 | `d38d0031b3` refac | 暂不引入 · 通过 | Controls Files 折叠区样式类与间距微调，视觉微调，不孤立引入上游新布局。 | — |
| 128 | `a46ad149bf` refac | 暂不引入 · 冲突 | Navbar/Sidebar 图标尺寸像素级调整，Tabs 按钮属已删功能，非缺陷修复。 | — |
| 135 | `00ce7003ad` refac | 暂不引入 · n/a | 导航栏/侧栏 padding、移动侧栏最大宽度与预格式化排版，视觉重排；本地结构差异大。 | — |
| 137 | `b96993c9b7` refac | 暂不引入 · n/a | channel/admin/automations/calendar 属已删功能；保留路径仅 padding/对齐/响应式间距视觉调整。 | — |
| 140 | `5140da6eb9` refac | 暂不引入 · n/a | Sidebar 聊天列表顶部内边距 `pt-2.5→pt-1.5`，纯视觉微调。 | — |
| 141 | `d99ec1c02c` refac | 暂不引入 · n/a | 135 文件、净删 1261 行纯注释/分隔线清理，改到 6 个 migrations；迁移冻结，行为保持型大重构不引入，也不是 access_grants 安全修复。 | — |
| 154 | `c4eb444a04` refac | 暂不引入 · n/a | 浮动选区工具栏改 selectionchange + selectionToolbar.ts + `@floating-ui/dom`，同批大改 CommentsHost/anchors/FileNav；本地仍为旧 mouseup 实现，属大重构。 | — |
| 156 | `042ac65628` refac | 暂不引入 · n/a | app.html UA 检测 + webkit 滚动条 native-scrollbars 全局视觉重设计，另改 Pure 不存在的 PdfPagesPreview/PptxPreview。 | — |
| 159 | `ddb43c83ba` refac | 暂不引入 · 冲突 | 新增 pending_approval 贯穿 chat_messages/chats/folders/socket/middleware 与侧栏黄点，围绕已删除 tools/MCP 的工具审批新 UI；本地无 session_records/pause_for_tool_approval。 | — |
| 176 | `bab66b2c2f` refac（OAuth 配置） | 暂不引入 · n/a | OAuth provider 配置从环境变量改数据库 Config、异步 load + lifespan 初始化；当前部署不使用 SSO/OAuth，属认证架构重构，按边界延后，不加新配置项与 i18n 键。 | — |
| 181 | `a8b478ed7b` refac | 暂不引入 · n/a | 上下文压缩大改（返回压缩列表、apply_summary_checkpoint、复用消息前缀命中 prompt cache、按 filter/pipeline/tool 分支）；性能/缓存行为与大规模重构，非缺陷修复。 | — |

## 修复族索引

- **临时聊天与文件夹导航**：`321701c1af09`（Pure 已覆盖），`96c1cfca6e25`（P2，建议取用）。
- **OpenAI Responses API / token usage**：`e789513ea62e`（P2）、`aa1326eaeaee`（P2）；审计后本地移植提交 `0393a28ce`。
- **非 ASCII 停止序列**：`dd6720c528f8`（P2）；审计后本地移植提交 `2fdb0f2bf`。
- **聊天草稿与新聊天初始化**：`4ea29c0d61`（P3）、`d58af14c0ce5`（中间版本/被替代）、`082df44d9217`（不涉及，本地已用不同结构实现）；审计后本地移植提交 `9ddae7f4`。
- **上下文用量估算**：`8e61cc02106e`（P3）；审计后本地移植提交 `9ddae7f4`。
- **聊天 Markdown / 代码预览**：`aec5796a535b`（P3），`51cef9e26f`（P3）（编号 166/168）；与 `3bb962f2bb`、`295b077893` 的编辑器健壮性/语言支持相关。
- **聊天输入、图片与临时聊天**：`563d621854e7`（P3，图片 MIME 识别）、`3d0de7ed86`（P3，图片查看器焦点）、`96c1cfca6e25`（P2）。
- **抽屉/弹窗/焦点管理**：`1dd3793d4e`（P3）、`a06aa230f7`（P3）、`a671146b91`（P3）、`3d0de7ed86`（P3）；批量 Modal 命名 `f2a990f6da` 暂不引入。
- **表单/控件可访问名**：`13bede8ba6`、`15d98d4610`、`d89699992a`、`476b6f49e4`、`24c891fabe`、`0ea4591258`、`d11a5f0f03`、`afcd1cd7ee`、`487a193d69`、`a988369a8e`、`c4daef0c94`、`6a789c1199`、`27eb2d2eff`、`a3801c4bd5`、`f773e057e2`、`51cef9e26f`。
- **富文本/代码编辑器**：`3bb962f2bb`、`295b077893`、`ab71357980`（新功能，不取）、`ee8b69e718`（视觉改造，不取）。
- **布局与视觉重排（不导入）**：`c5981aaea6`、`2d7cf5ec99`、`d38d0031b3`、`a46ad149bf`、`00ce7003ad`、`b96993c9b7`、`5140da6eb9`、`5bd49c38e9`、`3cda94d403`、`042ac65628`、`9959fc95a2` 以及 README/品牌/版本系列。
- **i18n**：`93f4440a38`、`64796faceb`、`bd6277ec5c`、`4a0e63e886`、`34be5d8f67`、`e9faf7509c`；代码提交附带键：`6a789c1199`（`Message number`）、`15d98d4610`/`d11a5f0f03`（需补 `Clear filters`/`Resize panel`）。
- **删除功能的安全修复（security_skip）**：`4adf3083f3`、`b4b6cc936d`、`1d5373066d`、`47934d1cc2`。
- **迁移/大重构**：`9d1b4ef362`（新增迁移，不涉及）、`3814b7b2f1`（通知收件箱迁移，暂不引入）、`d99ec1c02c`（注释清理改动迁移，暂不引入）、`a8b478ed7b`（上下文压缩重构，暂不引入）。
- **发布/合并**：`c38885a1a7`（0.13.0 合并节点，组合 diff 为空，不单独取用）。