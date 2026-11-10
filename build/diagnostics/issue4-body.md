## 现象

主窗口为 `Qt.FramelessWindowHint` 无边框窗口，边缘用 `startSystemResize` 的 8 方向 MouseArea 驱动系统缩放（进入 Windows 模态缩放循环 `WM_SIZING`）。在 Windows 上拖拽任意边/角时，**内容边缘明显抖动**：窗口边框本身跟随光标平滑移动（DWM 按实时 rect 绘制），但内容边缘——最明显的是播放栏中的矩形正在播放封面和私人 FM 页的圆形封面——会冻结一到数个合成拍，然后一次性跳 20–30 px，偶尔向回弹一下。拖动移动（`startSystemMove`）不受影响，仅缩放触发。

经逐帧自动化测量（工具见文末），抖动最终定性为**两类独立机制**，一类已修复，一类是呈现路径的结构性问题。

## 环境

- Windows 11 x64（24H2 → 26H2 build 26300 均复测，结论不变），显示缩放 125%（DPR = 1.25，per-monitor aware），2560×1440
- Qt 6.12.0 官方 SDK，MSVC 2022，Qt Quick 渲染后端 D3D11（`QSG_INFO` 确认）
- GPU：AMD Radeon RX 7700 XT / Intel iGPU（多后端复测，结论一致）
- 窗口创建路径：`QQuickWindow::setDefaultAlphaBuffer(true)`（`app/main.cpp`）+ `color: "transparent"` + `startSystemResize`

## 两类抖动

1. **几何量化抖动（已修复）** — 场景位置随窗口宽度变化的图像以 0.8 logical px 步进移动，可能落在取整/遮罩阈值附近，来回翻转整个像素。私有 FM 封面边缘的翻转即此类，机制与修复见下文“已修复部分”。
2. **DWM 旧帧拉伸（结构性问题，待上游/架构解决）** — 每个 `WM_SIZING` 步进中，从 `SetWindowPos` 到同步 paint 完成之间，DWM 把**上一帧**交换链内容**拉伸到新窗口尺寸**再合成。所有内容——包括像素级静态的虚线加卡、+ 按钮字形、chips——被重采样约 0.1–0.5 px 一至两个合成拍，然后弹回。此类无法逐元素修复，是下文 freeze-then-jump 的同一个传输节拍。

用 `jitter_pause_probe.py`（拖拽/停止分段）可把两类干净分离：受测裁剪框只在生长帧变化（54–55 / 696 帧），**每个停止段全部位稳定**；`ECHO_PIXEL_SNAP_TRACE=sidebar` 的穷举日志证明拖拽期间侧栏无场景几何变化；`WindowResizeSync` 报告 `incomplete-frames=0`（每个 WM_SIZE 都有匹配新尺寸的帧被提交）。**Qt 提交了每一帧 ≠ DWM 显示了每一帧。**

## 已修复部分：几何量化（EchoPixelSnap）

**FM 封面边缘翻转的机制。** Qt 按窗口 *logical* 尺寸渲染场景（`QWindow` 尺寸是整 DIP），而原生客户区 rect 以单个物理像素步进，有效场景缩放为 `W / round(W / 1.25)`，随宽度走动最多摆动 ~0.04%——足以让 400 px 外的内容边缘在每步间移动零点几像素。EchoCover 的遮罩管线（`MultiEffect`，`maskThresholdMin: 0.5, maskSpreadAtMin: 1`）对覆盖率做硬阈值，感知边缘位置被量化到整像素；落在半像素边界附近的边缘，亚像素摆动一过阈值就翻转整个可见像素。

**修复与推广。** 先在 FM 封面单点修复，后推广为共享原语 `EchoPixelSnap.{h,cpp}` 附加属性（跟踪整个祖先链的 x/y/scale/parent 变化和窗口 DPR，因为 Qt 6.12 QML 没有可跟踪的 `scenePosition` 等价物）——`EchoCover.qml` / `EchoIcon.qml` 内部绑定对齐的 `alignedSurface`，应用里所有封面与图标（歌曲封面、歌单封面、插件图标、按钮字形）经共享组件一次全部吸附到整设备像素，无需逐资源修改。`ECHO_PIXEL_SNAP=0` 全部置零可 A/B，`ECHO_PIXEL_SNAP_TRACE=<substring>` 记录匹配项的场景/DPR 变化。

**验证（2026-11-03）**：修复后三次启动渲染同一边界列，经 3×231 步 1 px/步的 1600→1831 px 拖拽，原始边缘边界列一次未动（`fm-edge-moves = 0`），底边保持 213.000 ± 0.055 px。被吸附的静态图像块在拖拽中位稳定。其余文本/圆形边缘的“抖动”实测同样只在生长帧发生、停止段位稳定、首末变化帧像素相同且零净位移——纯亚像素重采样，静止即复原；字形笔画与细曲线弧是屏上最高频内容，0.1–0.5 px 旧帧重采样在它们上面最可见（照片封面掩盖同样重采样）。这些元素已无几何可修。

## 结构性问题：呈现路径新旧帧竞速（逐帧实测，150 fps 采样）

**同一页面的 Electron 参照证明这不是“Windows 下限”。** 旧版 EchoMusic（Electron 43.7.2）在同等测量下：8 个受测框中 **7 个经全部拖拽帧位稳定**，唯一变化框（拉伸位移最大）最多变化 **1 个灰度级**。Chromium 的区别：它在 `WS_EX_NOREDIRECTIONBITMAP` 窗口上经 DirectComposition visual tree 自己提交内容——**DWM 从不持有需要重缩放的旧尺寸 surface**。

| 配置（同一 harness，FM 页） | 66 个生长帧中有内容变化帧 / 最大偏差 |
| --- | --- |
| GPU flip + alpha（DComp `SCALING_STRETCH`，透明窗口默认路径） | 59–63 / 139–255 |
| 无 alpha + 不透明（flip `SCALING_NONE`） | 57–62 / 139–255 |
| `QT_D3D_NO_FLIP=1`（legacy DISCARD） | 33–65 / 44–255 |
| `QT_QUICK_BACKEND=software`（GDI BitBlt） | **0（全部框）** / 0 |
| Electron 参照（独立探针） | **0 / 135 px 生长** |
| `DwmLockScreenUpdates` 冻结 | n/a — Win11 26300 的 dwmapi.dll 中不存在该 API |

Qt 6.12 源码核实（`qtbase/src/gui/rhi/qrhid3d11.cpp`）：alpha 窗口走 `CreateSwapChainForComposition`，源码注释明言 DComp *"cannot use SCALING_NONE … forced to SCALING_STRETCH"*；无 alpha 则 `CreateSwapChainForHwnd`、`FLIP_DISCARD` + `SCALING_NONE`。

**判别式**：不是 flip 与 bitblt 之别，也不是 alpha 与不透明之别，而是**新尺寸内容能否与尺寸变化原子地同时变为 DWM 可见**。GDI BitBlt 在 `WM_PAINT` 内同步更新重定向面，赢下竞速；Qt Quick 的 D3D 路径在尺寸落地后 ~7–10 ms 才提交帧，合成拍按 165 Hz 计，合成器其间拉伸旧帧——**降低 paint 延迟不可靠地赢回竞速**（FM 页 paint 已 6.5–10 ms，仍输 ~90% 的步进）。

**软件后端排除为产品路径**：实测确认 `QT_QUICK_BACKEND=software` 消除冻结/跳变（竞速物理性消失），但封面占位符顶替真实封面、逐像素圆角丢失、GPU 模糊/效果全灭——本应用视觉大量依赖 `MultiEffect` 与内联 `fragmentShader`，任何以关闭 GPU 视觉换顺滑的方案不可接受。

**三配置同 harness 量化（3 组对角拖拽，150 fps 采样）**：

| 指标（3 会话合计） | baseline（GPU） | software | basic |
|---|---|---|---|
| 有旧内容的生长帧 | 30 / 34（88%） | 22 / 32（69%） | 10 / 13（77%） |
| 冻结帧（封面静止而窗口生长） | 9（26%） | 4（12%） | 5（33%） |
| freeze-jump 事件（可见节拍） | 6 | 3 | 2 |
| 最坏单帧内容跳变 | 29.6 px | 30 px | 20 px |
| 封面边缘最大滞后 | 39.6 px | 40 px | 30 px |

- **绝对滞后主要是传输而非 GPU**：该拖速下（0.77 px/ms）software 后端也有 30–40 px 合成滞后 ≈ 39–52 ms 流水线延迟；恒定延迟平滑移动，不被感知为抖动。
- **GPU 路径与众不同的是 freeze-then-jump 结构**：内容静止一至数拍（旧尺寸帧）再跳 20–30 px 追平——冻结帧比同口径 software 多 ~2.2×。软件后端“消除抖动”的实感，实际是消除了停顿而非滞后。
- `QSG_RENDER_LOOP=basic` 作为应用侧过渡止血（无视觉牺牲），但未达零抖动，且实测有确定性 ~1005 ms 的 GUI 线程同步停顿。

## 业界参照

- **Chromium**（crrev 07e75413）承认 Windows 不允许把「窗口尺寸 / DComp 裁剪 / surface 重绘」原子化，采用 `WM_SIZING` 内按提议尺寸预渲染 + 自管 DComp 提交；其 NOREDIRECTIONBITMAP + 自管 visual tree 架构正是 DWM 无旧尺寸帧可拉的原因。
- **Avalonia** #9103：`WS_EX_NOREDIRECTIONBITMAP` + DComp 的 resize 闪烁同类未解。
- **noflicker_directx_window** POC：根治形态存在但需引擎层编排——在 WM_NCCALCSIZE（尺寸落地前）`ResizeBuffers` 并渲染新尺寸帧 + present + Commit；前提（以未来尺寸渲染）在 Qt 的 QPA/RHI 几何与交换链管理下不可达（`QWindowsWindow::handleGeometryChange()` 实时 `GetWindowRect`，不读 WM_SIZE lParam）。
- **QTBUG-88659**（open, P2）：同类 Quick resize 拉伸闪烁。

## 期望的上游 / 架构方向（按成本递增）

1. **降低场景 paint 成本**：缩减每步被拉伸的合成拍数（主页现 24–44 ms ≈ 3–6 拍；仍不归零）。
2. **Qt 上游**：在 `WM_SIZING` 内按提议尺寸渲染帧后再使尺寸落地（Chromium 的 resize 同步），或显式管理 DComp visual 尺寸提交而非依赖 STRETCH 默认。对预编译 Qt 6.12 不可达。
3. **接管整个呈现**：`QQuickRenderControl` + 自管 DComp visual tree 于 `WS_EX_NOREDIRECTIONBITMAP` 窗口——即 Chromium 架构，属应用架构重写而非补丁。

A/B 开关：`ECHO_WINDOW_ALPHA=0`（present-path 探测）、`ECHO_PIXEL_SNAP=0`、`ECHO_RESIZE_*` 系列（`WindowResizeSync`：fence/preview/native）与 `ECHO_RENDER_DIAGNOSTICS=1`。

## 诊断资产（tools/diagnostics/resize-jitter/，本仓库）

| 工具 | 用途 |
|---|---|
| `resize_jitter.py` | 自动复现：真实鼠标拖拽（231 步 × 1 px/13 ms × 3 会话）+ 150 fps 位级采集，跟踪右/下内容边界与播放栏封面边缘 |
| `jitter_census.py` / `jitter_oscillation.py` | 全帧 diff 热点普查 / 逐框梯度轨迹与翻转分类 |
| `jitter_pause_probe.py` / `jitter_fm_probe.py` | 拖拽/停止分段刀切（区分类 1 与类 2）；FM 页面逐框判定 |
| `jitter_electron_probe.py` | 同探针对运行中的旧 Electron 应用，建立“非 Windows 下限”的对照证据 |

结果输出到 `build/diagnostics/resize-jitter/<config>/`（`summary.json`、逐帧 `trace.csv`、证据 PNG）。使用方式见该目录 `README.md`。

## 复现条件

1. Windows 10/11 + `Qt.FramelessWindowHint` + 边缘 `startSystemResize`（GPU 路径）
2. 默认 threaded 循环（或 basic，程度轻）
3. 拖拽任意边缘/角缩放，观察内容边缘（播放栏封面 / 圆形封面最明显）

