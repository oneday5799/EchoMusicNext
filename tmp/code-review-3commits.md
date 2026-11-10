# 三提交审查报告

- 审查范围：`origin/main..HEAD`（3 个未推送提交）
- 审查方式：两轴并行（规范符合性 + 正确性/质量）；三个提交均无 issue 引用、无书面 spec，因此 Spec 轴以"提交声明逐条核验"替代
- 日期：2026-11-10

## 提交清单

| 提交 | 主题 |
| --- | --- |
| 5a0ea01 | feat: keep window chrome operable under modal popups and menus |
| d1c7817 | feat: add song info offset setting to taskbar lyric preferences |
| 08b6471 | fix: measure more menu width and harden offscreen test rendering |

## 发现清单（按严重度）

### P1 — EchoDialog 的 Escape 兜底是死代码【已确认，修复已实施】

`modules/EchoMusic/Controls/EchoDialog.qml:65`（修复前）：

```qml
enabled: dialog.enabled && dialog.visible && dialog.managedDismiss && dialog.closable
         && (dialog.activeFocus
             || (dialog.overlay ? EchoWindowChrome.coversFocus(dialog.overlay.Window.window) : false))
```

- **根因**：`Popup` 没有 `overlay` 这个普通属性。attached 属性必须写成 `dialog.Overlay.overlay`（QQuickOverlayAttached，`qquickoverlay_p.h:90`）。QV4 对 QObject 未知的小写属性名静默返回 undefined，于是 `dialog.overlay ? A : false` 永远走 `false`，`coversFocus` 分支永不执行。
- **佐证**：全仓库 QML 中这是唯一一处小写 `.overlay` 访问；同文件第 48 行自己都在用 `parent: Overlay.overlay`；仓库内其余 8+ 处均为 `Overlay.overlay`；Qt 源码 dump（qquickpopup.cpp）中不存在 `QQuickPopup::overlay()` 访问器。
- **影响场景**：弹窗打开时点击标题栏可聚焦控件（搜索框等）使其持有 activeFocus，之后按 Escape 无法弹出 dismiss 流程——5a0ea01 提交声明"dialog Escape stays armed while chrome holds the focus"实际未落地。
- **修复**：`dialog.overlay` → `dialog.Overlay.overlay`（两处），并为 Shortcut 加 `objectName: "echoDialogEscapeShortcut"` 供测试定位。

### P2 — Escape 键盘路径测试零覆盖【已确认，测试已补】

`tests/qt/controls/ControlsUiPopups.cpp:983-991` 只直接调 `chromeCoversFocus` 验证注册表，注释自认"keyboard path is covered by manual verification"——正是这个缺口让 P1 静默存活。

- **处置**：offscreen 上 QQuickShortcut 分发需要 native active window（原注释属实），完整键盘路径不可测；改为断言 Shortcut 的 `enabled` 绑定值本身：chrome 持焦 → enabled=true（P1 回归用例），弹窗持焦 → true，中性位置（contentItem）持焦 → false。为此给 `ChromePassthroughHarness.qml` 加 `focusNeutral()`。
- 之前"manual verification"注释随本修复更新。

### P2 — modal 期间 wheel/hover 仍穿透 chrome【接受的取舍，建议注释明示】

`EchoModalDimmer.qml` 的 containmentMask 对所有事件类型生效：弹窗打开时在 40px 标题栏上滚动会滚动弹窗底下的页面、tooltip 会触发。功能上属接受的取舍（与"chrome 可操作"的设计一致），建议在 dimmer 或 chrome 注册处加一句注释明示该边界。【未实施，纯注释级】

### P3 — 提交消息类名不准确【已修正】

08b6471 消息写 "ShellActionModel exposes per-row title and badge visibility"，实际新增的 `titleAt`/`badgeVisibleAt` 位于同头文件中的 `ShellActionProjection`（`ShellActionModel.h:132`）。提交未推送，消息已修正。

## 已核验但否决的发现

| 发现 | 否决理由 |
| --- | --- |
| TaskbarLyricSettingsSection "0 - 6 像素"应为 DIP | 同节三处文案（160-800 像素 / 0-6 像素 / 11-22 像素）一致使用"像素"，是既定用户文案约定，单独改一处反而破坏一致性 |
| EchoWindowChrome.covers 两角判定对旋转/负缩放会误判 | chrome（标题栏/拖拽条）无旋转、无负缩放，uiScale 为均匀正向缩放，两角判定在该场景恒正确；为此引入四角判定属 Speculative Generality |
| ShellTest.cpp 两处重复 `resize(1150, 750)` | 分别是拖拽压力段前与取消段前，两段独立需要基线几何，各有注释说明，非 Duplicated Code |
| frostedSupported 门控复制 EchoFloatingSurface 内部逻辑 | 注释已声明"mirror the gate here"是有意镜像（测试不能 import 私有门控），属测试的固有代价 |

## Standards 轴（规范符合性）

对照 docs/build.md、docs/formatting.md（工具链强制部分跳过）、docs/windows-window-pipeline.md：**无硬违规**。5a0ea01 全部在 QML 层，未触碰文档管辖的原生窗口管线，与 §3 无边框呈现现状一致；d1c7817 的键值/钳制分层符合 SettingsKeys.def 既有约定（与 maxWidth 先例同构）。

判断项（judgement calls，供后续收敛，本次不动）：

1. `Component.onCompleted: EchoWindowChrome.register(...)` / `onDestruction: unregister(...)` 成对写法在 Main.qml（sidebarDragArea）、TitleBar.qml（bar）、ChromePassthroughHarness.qml（chromeStrip）三处重复——收敛候选：attached property / 专用 Behavior。
2. `QGuiApplication::platformName() == "offscreen"` 分支在 DesktopPagesPlayback3.cpp 与 DesktopPagesSettings2.cpp 重复——候选提取 `Test::` helper。
3. TitleBarMorePopup.qml 的 `Connections` 五个 handler 同调 `remeasureRowWidth()`——QML API 所限，一次模型批量变更会触发多次 O(rows) 重测（开销小，可接受）。
4. `titleAt`/`badgeVisibleAt` 在头文件内联，而同类 `beginReorder` 等为声明式——风格小分歧。
5. EchoWindowChrome.qml 的 `entries = entries.concat([{ item, window }])`——item+window 数据团，QML 下可用对象列表承载（现状可读）。

## 提交声明核验

| 提交 | 声明 | 结果 |
| --- | --- | --- |
| 5a0ea01 | EchoWindowChrome 注册表 + dimmer containment mask | ✅ 落地 |
| 5a0ea01 | 六处弹窗/抽屉/面板共享 dimmer | ✅ 落地 |
| 5a0ea01 | caption 按钮停止抢焦点 | ✅ 落地 |
| 5a0ea01 | **dialog Escape 在 chrome 持焦时保持可用** | ❌ **未落地（P1）** |
| d1c7817 | 存储 clamp `qBound(0, value, 6)` | ✅ 落地 |
| d1c7817 | 设置区 spin box 紧随宽度 | ✅ 落地 |
| d1c7817 | `Math.min(infoOffset, seekArea.height / 2)` 实时封顶 | ✅ 落地（默认 6 与旧行为一致） |
| 08b6471 | 更菜单按最宽标题增长（280-420 DIP）+ 命令式测量 | ✅ 落地 |
| 08b6471 | styledUiFont 非正 probe 回退 | ✅ 落地 |
| 08b6471 | 测试侧 update()/invokeMethod/attemptClose/重试等加固 | ✅ 落地 |

## 后续建议（本次未实施）

1. EchoModalDimmer 补一句"wheel/hover 同样穿透 chrome"的取舍注释（P2，纯注释）。
2. offscreen 平台分支提取 `Test::` helper（跨两个 desktop 测试文件）。
3. chrome register/unregister 收敛为 attached property（跨三处生产 QML，收益中等，改动面大）。

## 附录：上游合并状态（2026-11-10 晚查证）

本地三个提交已被上游吸收，但内容与 sha 不再对应：

| 本地提交 | 上游去向 |
| --- | --- |
| d1c7817 歌词信息偏移 | PR #42 第 1 个提交 `1834f38`（feat: 新增任务栏歌词信息偏移设置）✅ 已合并 |
| 08b6471 更多菜单测量 + offscreen 加固 | PR #42 第 2 个提交 `73adf20`（fix: 修复更多菜单测量并硬化 offscreen 测试）✅ 已合并 |
| 5a0ea01 window chrome operable | **未进主干**：PR #42 共 18 个文件，无任何 Chrome/ModalDimmer/Main.qml/TitleBar.qml；上游无 EchoWindowChrome.qml |

上游最新提交（截至 14:27 UTC）：`73f0c58` "fix: 统一任务栏歌词偏移上限并优化更多菜单测量"——正是本报告"判断项"里偏移上限魔法数与 more 菜单测量两项的收敛实现。另：PR #44（MOldtime，open）待审。

结论：

1. 本地 main 的 d1c7817/08b6471 已无推送价值（等价内容在主干、sha 不同），同步时直接以 origin/main 为基。
2. chrome 工作（5a0ea01）连同本报告 P1 修复（EchoDialog attached overlay，未推送）是一体的，应作为下一个 PR 的内容——上游当前不存在该缺陷（代码未合入），但合入 chrome 时必须带上此修复。
3. 本会话的审查修复（EchoDialog.qml / ChromePassthroughHarness.qml / ControlsUiPopups.cpp）在工作区未提交，构建验证被打断，回归状态未知。
