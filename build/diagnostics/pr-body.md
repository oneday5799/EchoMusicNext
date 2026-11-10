单一提交，基于 squash-merged 的 #38。

## 背景

库重扫等场景抖动下，页面加载会以相关签名崩溃（Qt6Qml `getterFallback` / sweeper NULL 等）。宿主侧可控的根因有两个：

1. `EchoPixelSnapAttached::refresh()` 同步 emit，触发「绑定 → 写子几何 → 观察者链 → 再入 refresh()」的单栈递归，直至栈溢出；
2. `EchoUiPartRegistration::setResolved()` 同步重算视觉覆盖标志，refresh() 的 detach→attach 使 overrides 穿过空表时反复拆建宿主 Loader。

## 改动

### 1. 像素对齐通知排队合并（EchoPixelSnap）
- 值立即落盘（重求值总能读到新数据），通知走 `Qt::QueuedConnection`，突发合并为每事件循环轮一次 flush；
- 反馈环从单栈嵌套变成有界收敛。仅影响亚像素对齐，一事件循环轮的延迟不可见。

### 2. hasVisualOverrides 迟滞标志（EchoUiPartRegistration）
- 新增只读属性：键中存在非 opacity 覆盖即视为视觉覆盖；
- 排队重算、按稳定值翻转；键/声明变更触发身份重发布的契约不变；
- 四个 QML 使用点全部迁移：`EchoUiPartHost` + Shell 的 `Sidebar`/`PlayerBar`/`TitleBar`，不再逐项扫描 `overrides`。

### 3. 惯用法收敛
- 排队通知样板提取到 `EchoQueuedNotice.h` 的 `queueCoalescedNotice()`；
- `flushNotifications` 转为私有；`setResolved` 的键扫描改用 `std::any_of`。

## 测试适配

- scene-position spy 改用 `QTRY_COMPARE`（通知晚一事件循环轮落定），复位后补一次队列排空断言以保留防重复语义。

## 验证

- 重扫风暴复现场景下对比修复前后二进制：基线每次页面加载必崩（4/4），修复后页面加载与多次重扫存活（0 崩）；
- 相关子集测试（offscreen）：controls-ui（pixelSnap × 3、imageDensity）与 plugin-runtime（uiStyleLayers / uiParts × 3 / temporaryAppearance / appearanceErrors）全部通过，0 失败；
- 实机启动 100s 稳定，无新增 crash dump。
