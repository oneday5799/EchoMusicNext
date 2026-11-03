# Resize jitter reproduction harness (issue #4)

Automated reproduction and quantification of the frameless-window resize
jitter reported in
[hoowhoami/EchoMusicNext#4](https://github.com/hoowhoami/EchoMusicNext/issues/4).

## The phenomenon

The app resizes via 8-direction `MouseAreas` calling `startSystemResize()`,
which enters the modal `WM_SIZING` loop on Windows. While dragging, the
window border itself follows the cursor smoothly (DWM draws it at the live
rect), but **content edges** — most visibly the rectangular now-playing cover
in the player bar, and the hero circle covers — freeze for one to several
composition beats and then jump 20–30 px at once, occasionally bouncing
backward. That freeze-then-jump at content edges is the jitter users report.

## Method

`resize_jitter.py`:

1. Launches the app at a fixed rect (400,150 1600×1000 physical px) and puts
   a solid-black backdrop window directly beneath it (the wallpaper has
   bright regions within a few gray levels of the app background, which
   blinds edge detection; the backdrop also hides neighbouring windows).
2. Drives a real mouse drag on the bottom-right resize handle
   (`SetCursorPos` + `mouse_event` → `startSystemResize` → `WM_SIZING`):
   231 diagonal 1 px steps at 13 ms (~3.3 s per session — real mouse drag
   granularity; coarser steps skip over the widths where the cover edge
   quantization flips), three sessions per run, re-centered before each.
3. Samples the true rect every ~2 ms (`GetWindowRect` follows the modal loop
   synchronously — ground truth) and BitBlt-captures the composed desktop at
   150 fps with per-frame monotonic timestamps from the same clock the drag
   thread uses, so alignment holds by construction. (ffmpeg `gdigrab` was
   tried first: its `-framerate` pacing does not hold on this machine — it
   delivered all 1500 frames ungated before the first drag — hence the
   in-process grabber.)
4. Tracks per frame:
   - **right / bottom** — composed window content boundary against the black
     backdrop, anchored to the true rect (`light_edge`);
   - **cover-top** — the now-playing bar cover's edge via 1D gradient-profile
     correlation. The bar is bottom-anchored, so a fresh frame keeps the
     cover 1:1 with the live bottom border; a stale frame leaves it behind.
     The pulsing gap between cover edge and window border is exactly what a
     user sees at content edges;
   - **circle-x** — left tangent structure of the hero circle row
     (width-responsive layout);
   - two strong static interior layout edges.
5. Classifies every growth frame (detector bias = median idle lag, subtracted):
   **stale** (edge ≥ 18 px behind truth while the window grew), **bounce**
   (backward jump while the window did not shrink), **freeze** (cover edge
   stood still while the window grew), **freeze-jump** (a catch-up jump
   > 8 px within 3 frames after a freeze — the visible jitter event),
   **clean**, plus maxima and percentiles. Evidence frames (worst lag, worst
   cover deviation, bounces) are saved as PNGs.

## The FM-cover edge flip (root cause and fix)

The Private FM hero cover is layout-static (identical bbox at window widths
800–1600 physical px and during every drag), yet users see its edge jitter.

**Mechanism.** Qt serves the scene at the window's *logical* size, which is
integral (`QWindow` sizes are whole DIPs), while the native client rect moves
in single physical pixels. The effective scene scale is therefore
`W / round(W / 1.25)`, which wobbles by up to ~0.04 % as the width walks —
enough to move a 400 px-distant content edge by tenths of a pixel per
`WM_SIZING` step. EchoCover's mask pipeline (`MultiEffect` with
`maskThresholdMin: 0.5, maskSpreadAtMin: 1`) hard-thresholds coverage, so the
perceived edge position is quantized to whole pixels. An edge whose true
physical position sits near a half-pixel boundary therefore flips a full
visible pixel whenever its sub-pixel excursion crosses the threshold.

**Why it is launch-dependent.** Pre-fix, the cover's fractional position was
whatever the unsnapped layout produced: the manual run measured the boundary
at 563|564 (with real ±1 flips — see below), a synthetic launch put it at
564|565 with no flips. Only launches whose fraction sits near .5 jitter;
that is why automated drags kept missing what hands see.

**Why hand drags flip but early synthetic drags did not.** The first harness
stepped 10 px per event; those widths kept the excursion inside one
quantization cell. 1 px/step drags (the current default) walk every integer
width like a real mouse.

**The fix** (`modules/EchoMusic/Music/SongDetailHeader.qml`, later superseded
by the shared EchoCover integration — see the next section): the cover
Loader's scene rect is snapped to whole device pixels — x/y compensate the
fractional scene position of the slot (`round(scenePos * dpr) / dpr -
scenePos`) and width/height are snapped to integer physical px (150 → 150.4
logical = 188 physical at 125 %). The edge's fraction becomes exactly 0, so
the flip threshold sits 0.5 px away; the residual per-step excursion measured
0.07 px (worst-case scale wobble ~0.4 px) cannot reach it.

**Verification (2026-11-03).** Post-fix, three launches all render the edge
at the same boundary (565|566 capture columns), crisp with no AA ramp;
through three 231-step 1600→1831 px drags the raw edge boundary column never
moved once (`fm-edge-moves` = 0 in all sessions; idle and drag frames are
bit-identical at the boundary) and the bottom edge holds 213.000 ± 0.055 px.

**Metric caveat (read before trusting `fm-flips`).** `fm-wobble`/`fm-flips`
read the NCC tracker. Its parabolic subpixel estimate quantizes the edge's
0.07 px excursion into ±1 readings and flips direction whenever a faint
secondary gradient one column beside the edge (~7 % intensity, ~5 % of
frames, present pre- AND post-fix — cover shadow/AA) appears or disappears.
Every saved "flip" frame is bit-identical at the boundary in both the pre-fix
and post-fix captures, and the pre-fix manual session's flips were
accompanied by real flips of two *independent* interior-edge trackers
(lockstep, 352 co-timed events) — so trust the manual session's flips as
real, treat synthetic-run `fm-flips` counts as tracker wobble, and use
`fm-edge-moves` (raw gradient argmax around the rest position, proven to
detect ±1 px shifts) as the ground-truth edge metric. The reference frame is
frozen only after warmup layout settles (`warmup_edge_stable`); freezing
earlier anchors a constant +2 px bias and manufactures phantom flips.

## Generalization: device-pixel snapping for all imagery, and the two jitter classes

The FM fix removed one instance. The follow-up request was to fix every
jittering element (song covers, sidebar add-card, plugin icons, …) in one
shot instead of patching static resources one by one.

**The shared primitive** (`modules/EchoMusic/Controls/EchoPixelSnap.{h,cpp}`):
an attached property that exposes the attached item's tracked scene position
and device pixel ratio. Qt 6.12 QML has no tracked equivalent (qmltypes list
`scenePosition` only on `QQuickEventPoint`, and `mapToItem` bindings are not
notified), which is what forced the per-element patch before. The attachment
watches x/y/scale/parent changes along the whole ancestor chain, so scroll
views, anchors and responsive reflows all arrive. `ECHO_PIXEL_SNAP=0` parks
every compensation at zero (A/B runs); `ECHO_PIXEL_SNAP_TRACE=<substring>`
logs every scene/dpr change of matching items — the trace that proved the
residual class below is *not* geometry.

**The application**: `EchoCover.qml` and `EchoIcon.qml` each bind an inner
`alignedSurface` Item from the attached values (position compensated,
width/height rounded to whole device px) and render placeholder, image, mask
and effects inside it. Every cover and every icon in the app — song covers,
playlist covers, plugin icons, button glyphs — is snapped through its shared
component, with no per-resource edits. Static imagery then renders
bit-identically through drags (probe below: left grid-column covers, chips at
stable phases and most sidebar covers never change a single pixel).

**The two classes.** Census tooling: `jitter_census.py` (full-frame diff
hotspots, idle subtracted), `jitter_oscillation.py` (per-box gradient-argmax
trajectory; direction reversals during a grow-only drag = flips),
`jitter_pause_probe.py` (alternating 45 px drag bursts and 1.4 s holds, with
per-frame `GetWindowRect` and per-box crop hashes).

1. **Geometry quantization** — imagery whose scene position depends on window
   width moves in 0.8 px logical steps and can sit near a rounding or mask
   threshold, flipping a whole pixel back and forth. This is what the FM fix
   addressed. The snap removes it wherever it is applied; static snapped
   imagery was already bit-stable.
2. **DWM stale-frame stretch** — during each `WM_SIZING` step, between
   `SetWindowPos` and the synchronous paint completing, DWM re-composites the
   *previous* swapchain frame stretched to the new window size. Every frame
   of content — including pixel-perfect static chrome such as the dashed
   add-card, the + button glyph, chips — is resampled by ~0.1–0.5 px for one
   or two composition beats, then snaps back. Pause-probe evidence (final
   binary): all watched crops change only during growth frames (54–55 of 696,
   maxdiff 28–168 gray levels) and are **bit-identical through every hold**;
   the exhaustive `ECHO_PIXEL_SNAP_TRACE=sidebar` log shows *no* sidebar scene
   change during drags (only the bottom-anchored `sidebarLayoutTrigger`
   follows the height, monotonically); `WindowResizeSync` reports
   `incomplete-frames=0` (every WM_SIZE got a matching new-size frame). This
   class is not fixable per element — it is the same transport beat that
   causes the freeze-then-jump below, already minimized by the sync protocol.
   The remaining lever is paint latency: a synchronous paint faster than one
   composition beat (~17 ms at 60 Hz; current max 24–44 ms) would close most
   of the remaining window.

**Metric caveat for the census:** argmax "flips" on static boxes include
class-2 tipping, so a nonzero count is not a geometry regression. The tipping
is a per-element phase lottery (same component, same row: `chip-1` never
flips while `chip-2` ping-pongs 553↔574; `side-cover-2/7` never flip while
`side-cover-1` ping-pongs 102↔112), which is why single-box A/B counts moved
in both directions when the snap shifted fractional phases (add-dashed
0 → 36, row-cover-2 32 → 24). Trust the pause probe's move/hold split and the
geometry trace over per-box flip counts.

**Why text and the FM circle edges read as jitter while playlist covers look
clean (FM-page probe, `jitter_fm_probe.py`).** The app restores its last
route, so it opens on the Personal FM page; the probe boxes cover the circle
row edges, the song title/tag text, the square artwork, the dashed add card
and a sidebar playlist cover. Verdict for every box: changes only during
growth frames, bit-identical through every hold, and the first and last
change crops are pixel-identical with zero net displacement — the text and
circle "jitter" is pure sub-pixel resample that fully reverts at rest. The
user-visible asymmetry is perceptual plus positional: glyph strokes and thin
curved arcs are the highest-frequency content on screen, so a 0.1–0.5 px
stale-frame resample is most visible there, while photographic covers hide
the same resample; content far from the stretch origin also shifts more.
There is no geometry left to fix in these elements — the remaining lever is
paint latency (a synchronous paint under one composition beat, ~17 ms;
already met on the FM page at ~6.5 ms, currently 24–44 ms on the heavier
home page).

## The Electron reference: the residual is not a Windows floor (2026-11-03)

The user compared the same page in the old app (`D:\Code\EchoMusic`,
Electron 43.7.2) and saw nothing. Measured objectively with the same
move/hold probe (`jitter_electron_probe.py`, boxes fully inside the window,
3×45 px 1 px-step drags, +135 px total growth): **7 of 8 boxes — text, circle
edges, square cover, sidebar text — were bit-stable through every drag
frame**; the only changing box (the rightmost circle edge, largest stretch
displacement) changed by at most **1 gray level**. The old app is genuinely
clean; the "compositor floor" reading of the earlier sections was wrong.

What Chromium has that the Qt window does not: it presents through a
DirectComposition visual tree on a `WS_EX_NOREDIRECTIONBITMAP` window and
commits the content itself, so DWM never holds a stale-size surface it needs
to rescale. The Qt 6.12 present path (`qtbase/src/gui/rhi/qrhid3d11.cpp`):

- an alpha swapchain (our windows use `color: "transparent"`, so always) takes
  the DirectComposition branch — `CreateSwapChainForComposition` with
  `Scaling = DXGI_SCALING_STRETCH`, the source comments that DComp "cannot
  use SCALING_NONE";
- without alpha it is `CreateSwapChainForHwnd`, `FLIP_DISCARD` +
  `DXGI_SCALING_NONE`;
- `QT_D3D_NO_FLIP=1` selects the legacy `DISCARD` model.

Probed all of them on the FM page (same boxes, same harness):

| configuration | move-chg / 66 grow frames | maxdev |
| --- | --- | --- |
| GPU flip + alpha (DComp STRETCH) | 59–63 | 139–255 |
| no-alpha + opaque color (flip SCALING_NONE) | 57–62 | 139–255 |
| `QT_D3D_NO_FLIP=1` (legacy DISCARD) | 33–65 | 44–255 |
| `QT_QUICK_BACKEND=software` (GDI BitBlt) | **0 on all inside boxes** | 0 |
| Electron reference (separate probe) | **0 of 135 px growth** | 1 |
| `DwmLockScreenUpdates` freeze (ECHO_RESIZE_FREEZE) | n/a — API absent from dwmapi.dll on Win11 26300 (error 127) | |

So the discriminator is neither flip vs bitblt nor alpha vs opaque: it is
whether the new-size content becomes visible to DWM **atomically with the
size change**. GDI BitBlt (software backend) updates the redirection surface
synchronously inside `WM_PAINT`, so it wins the race. Every Qt Quick D3D path
submits its frame ~7–10 ms after the size change lands, and with composition
ticks at the display's 165 Hz the compositor stretches the stale frame in
between — paint latency reduction cannot reliably win that race (the FM page
already paints in 6.5–10 ms and still loses ~90 % of steps). The software
backend is disqualified as a product path anyway (probed visually:
placeholder covers render where artwork should be, per-pixel-alpha rounded
corners are lost, GPU blur/effects are gone).

Structural escapes, in increasing cost:

1. Reduce scene paint cost — shrinks the number of stretched beats per step
   (home page at 24–44 ms is 3–6 beats; still not zero).
2. Upstream Qt work: render the frame at the *proposed* size inside
   `WM_SIZING` before the size lands (Chromium's resize synchronization), or
   manage the DComp visual size commit explicitly instead of relying on the
   STRETCH default. Not reachable from this repo against prebuilt Qt 6.12.
3. Own the whole presentation with `QQuickRenderControl` + a self-managed
   DComp visual tree on a `WS_EX_NOREDIRECTIONBITMAP` window — the exact
   Chromium architecture; an application-architecture rewrite, not a patch.

`ECHO_WINDOW_ALPHA=0` (app) remains as an A/B switch for present-path probing;
it does not change the resize artifact by itself.

## Results (3 corner drags per config, 2026-11-03, 150 fps capture)

| metric (3-session total) | baseline (GPU) | QT_QUICK_BACKEND=software | QSG_RENDER_LOOP=basic |
|---|---|---|---|
| growth frames with stale content | 30 / 34 (88 %) | 22 / 32 (69 %) | 10 / 13 (77 %) ¹ |
| freeze frames (cover still while window grows) | 9 (26 %) | 4 (12 %) | 5 (33 %) ¹ |
| freeze-jump events (the visible beat) | 6 | 3 | 2 ¹ |
| worst single-frame content jump | 29.6 px | 30 px | 20 px |
| max cover-edge deviation from live border | 39.6 px | 40 px | 30 px |
| cover deviation p95 | 34.8 px | 36 px | 30 px |
| max composed lag (right / bottom) | 39 px | 40 px | 30–39 px |
| bounce (backward jump) | 0 (up to 32 px in earlier runs) | 0 | 0 |

¹ basic suffered deterministic ~1005 ms synchronous paint stalls in drag
sessions 2–3 (two consecutive runs), which swallowed most of those drags —
the basic loop blocks the GUI thread; numbers are from its valid session 1
(plus the partial stalled sessions).

Earlier right-edge-only runs (12 px steps) measured baseline max lag
46–59 px and a 32 px single-frame backward bounce of the composed edge.

## Interpretation

- **Absolute lag is mostly transport, not the GPU.** At this drag speed
  (10 px / 13 ms ≈ 0.77 px/ms) even the software backend shows 30–40 px of
  composed lag ≈ a 39–52 ms pipeline delay (modal loop + DWM composition
  beat + capture skew). A constant delay moves content smoothly and is not
  perceived as jitter.
- **What distinguishes the GPU path is the freeze-then-jump structure**: the
  composed content stands still for one or more beats (stale old-size frame)
  and then jumps 20–30 px to catch up — ~2.2× more freeze frames than the
  software backend in the same harness. That matches the user report that
  `QT_QUICK_BACKEND=software` removes the *perceived* jitter: it does not
  remove the lag, it removes the stalls.
- **Content edges are where it is visible.** The composed boundary at the
  window edge and the bar-cover edge lag by identical amounts (same stale
  frame), but the border follows the cursor live, so only the content-edge
  motion — covers — reads as jitter. Hence the harness tracks the cover edge
  explicitly.
- **The app's own diagnostics agree**: with `ECHO_RENDER_DIAGNOSTICS=1` the
  baseline logs `incomplete-frames=0` while the measured composition lags
  30–40 px — Qt submitted every frame, DWM still displayed old ones
  ("submission is not proof of DWM's displayed result", as
  `WindowResizeSync.h` puts it).

## Usage

```bash
python tools/diagnostics/resize-jitter/resize_jitter.py run baseline   # or software | basic | preview | sync
python tools/diagnostics/resize-jitter/resize_jitter.py manual --seconds 75  # capture while YOU drag
python tools/diagnostics/resize-jitter/resize_jitter.py probe          # calibration against a running instance
python tools/diagnostics/resize-jitter/jitter_census.py <out> [secs]   # full-frame diff hotspot census
python tools/diagnostics/resize-jitter/jitter_oscillation.py <out> [secs]  # per-box reflow/jitter classification
python tools/diagnostics/resize-jitter/jitter_pause_probe.py <out>     # move/hold split; class-1 vs class-2
python tools/diagnostics/resize-jitter/jitter_fm_probe.py <out>        # FM page move/hold; ECHO_* env is forwarded
python tools/diagnostics/resize-jitter/jitter_electron_probe.py <out>  # same probe against a running EchoMusic (Electron)
```

Results land in `build/diagnostics/resize-jitter/<config>/`:
`summary.json`, `trace.csv` (per-frame trajectories; `fm_col` is the raw
edge-boundary column behind `fm-edge-moves`), evidence PNGs, and
`build/diagnostics/resize-jitter/app.log` (app diagnostics).

The tables above date from the 10 px-step era and quantify the separate
freeze-then-jump transport artifact; edge-flip verification uses the 1 px
step default and the `fm-edge-moves` metric.

Manual-mode caveat: the capture region is fixed (`CAP_W = WIN_W + 320`,
tuned for the synthetic 231 px drags). Dragging the window far beyond that
envelope saturates the pixel trackers (e.g. true right edge at 2155 vs
capture 1920), inflating lag/stale/bounce numbers with clipping artifacts;
the FM-cover edge metrics stay valid because the cover is left-anchored.

Requirements: Windows 10/11, built `build/release/app/echomusicnext.exe`,
screen ≥ 2560×1440 with the taskbar at the bottom (the drag would otherwise
be clamped by the work area), display scale 125 % (any scale works — the
script is per-monitor DPI aware — but thresholds are tuned for ~125 %).
