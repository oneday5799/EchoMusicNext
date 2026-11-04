# 全屏白条 - 根因与修复（2026-11-05）

## 最终结论（已验证）

**根因**：窗口保留 GDI 重定向面（无 WS_EX_NOREDIRECTIONBITMAP），DWM 合成顺序为
[DirectComposition 交换链 alpha] → [GDI 重定向面] → [Accent 材质] → [桌面]。
全屏转场重分配重定向面时，新增行未初始化（白色），GDI 与场景都从不绘制它们；
半透明皮肤（wash 0.44）之下透出的就是这些白行。白条顶边 = 任务栏顶 = 工作
区底 = 转场前几何的底边（用户观察完全吻合）。

**修复**：全屏几何稳定后 `PatBlt(hdc, 0, 0, clientW, clientH, BLACKNESS)` 清零
整个重定向面。该窗口为纯 D3D 呈现，重定向面本就应为全空，置零永远正确；
行合成回透明后材质（毛玻璃）正常透出。

**位置**：`WindowsWindowBackdrop::applyFullscreenGeometryNow` 尾部。

## 验证（全 band=0）
- 循环 1：最大化 → 全屏 ✓
- 循环 2：退出 → 再全屏 ✓
- 循环 3：还原 → 最大化 → 全屏 ✓
- 退出全屏回最大化：无回归，毛玻璃视觉正常 ✓

## 置顶透明条带（任务栏被盖）- 根因与修复（2026-11-05，第三版方案）

**现象**：窗口置顶时，最小化→还原→最大化后，窗口底边与任务栏之间出现
一条透明条带，壁纸从条带透出，任务栏顶部被盖住约 9 物理像素。

**根因**：带 CAPTION 的最大化被 user32 强制落到"工作区 + 不可见
resize-border 环"矩形（消息层之下，ptMaxSize 无法覆盖）。无边框窗口的
环区无人绘制 = 全透明。非置顶时任务栏 z 序在窗口之上，环被盖住不可见；
**置顶时环在任务栏之上，9px 透明环直接盖住任务栏顶部**。

**环强制实测矩阵（最小窗口 + 应用双验证，决定性）**：
1. 环不派生自 WS_THICKFRAME（CAPTION 无 THICKFRAME 同样落环）；
2. 带 CAPTION 的最大化无视改写的 ptMaxSize（两种提案均落同一环）；
3. 环持续强制：带 CAPTION 时最大化后 SetWindowPos(工作区) 被拉回环
   （ret=1 但矩形不变）；
4. **摘除 CAPTION（保持 WS_MAXIMIZE）后即可自由缩放**：缩到裸工作区
   精确停止、IsZoomed 保持——整个方案的基石；
5. Qt 6.12.0 无 handleResized 最大化纠偏（6.12 分支较新提交才有）；
6. QTBUG-117704 守卫：客户区尺寸==窗口尺寸时边距缓存冻结（不写入）。

**最终方案「动画先行、落地收缩」**：最大化转场照常加临时 CAPTION
（DWM 动画照播、引擎落环）；移除 WM_NCCALCSIZE 钳制（客户区恒等于
窗口矩形 → QTBUG-117704 守卫使边距缓存永不写入、恒 0，配对问题彻底
消失）；**settle 在首次 queued repair（约 10-30ms，变形动画刚开始）**：
摘 CAPTION + SetWindowPos 缩到裸工作区——跳变被变形动画完全遮盖
（settle 在 350ms 计时器时机时，动画结束后环→工作区的收缩可见跳变，
用户实测否决）。材质重放的 CAPTION 回加按 IsZoomed 抑制，防止 repair
把 CAPTION 加回已最大化的窗口复活环强制。`maximizeInfoToWork`
（MINMAXINFO 改写裸工作区）保留作无 CAPTION 最大化路径（aero snap
等）的兜底。

**历史方案（被取代，保留教训）**：
- v1 环矩形 + NCCALCSIZE 钳制 + 缓存配对：场景正确但置顶环条带
  （本 bug）。
- v2 无 CAPTION 最大化落裸工作区：条带根治但最大化动画丢失（CAPTION
  门控），且当时以为互斥不可两全——v2 的错误在于只测了"带 CAPTION
  时缩矩形被强制"，没测"摘 CAPTION 后再缩"（第 4 条）。

**验证**（置顶位贯穿全程，物理行 1380=工作区底）：早期 settle 后
SC_MAXIMIZE t+0.06s 即 = 裸工作区 (0,0,2048,1104) 且 CAPTION 已摘
（settle 先于变形动画可见期，无跳变）；SC_RESTORE(WPF_RESTORETOMAXIMIZED)
同样；像素 1381+ 行 = 任务栏原色；还原几何 (400,150,1680,950) 不受
settle 缩放影响；全屏进出回归通过。（350ms 计时器版本的中间验证：
t+0.25s = 环 (-7,-7,2055,1111)、t+0.85s = 工作区——两段行为成立但
收缩可见，被早期 settle 取代。）

**探针教训（重要）**：python ctypes 调 `SetWindowPos(hwnd, -1, ...)` 必须
先设 `argtypes`（HWND=64 位指针）。未声明 argtypes 时 -1 按 32 位 int
传参，高位截断后变成非法句柄 → 调用静默失败（ret=0, err=1400）。此前
多轮"置顶复现"实际从未置顶成功，导致长期无法复现用户现象。

## 诊断中被证伪的假说（保留教训）
1. 材质（Accent）层白条 — accent(0→4) 切换无效（白在材质之前）
2. DWM_BB / 扩展边框 / 边框色 / cloak 脉冲 — 全部无效
3. ThemeBackground 的 layer 纹理陈旧 — 关闭 layer 期间白条依旧
4. 场景脏区未刷新 — 全窗口元素几何脉冲（±0.001px）无效
5. 交换链未写入行 — 与最终结论等价但定位在了错误的层（是 GDI 面，
   不是 DComp 缓冲）

## 探针注意事项
- python 探针为 DPI-unaware：GetWindowRect/MoveWindow 坐标 = DIP（×1.25 = 物理）；
  BitBlt 截图恒为物理像素。两套坐标混用曾造成大量误判。
- band 检测阈值 min(r,g,b)>245 在低透明度下会误报（皮肤本身接近白色）。
- 诊断脚本启动器：build/diagnostics/launch-app.py（默认 1280×800 @ (400,150)，
  处理持久化最大化状态的还原）。
