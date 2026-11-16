# Stereo 3D (side by side)

Part of **mkw-recomp-stereo**, a fork of [adriadam10/mkw-recomp](https://github.com/adriadam10/mkw-recomp) (MIT,
Copyright (c) 2026 Adrià) at v0.1.11. Only the stereo mode described here is this fork's work; see
[NOTICE.md](NOTICE.md) for the split.

This fork adds a left/right side-by-side (SBS) stereo 3D mode to the runtime, so the game can
be played on SBS-capable glasses (Xreal and similar) instead of a flat screen.

It is built on top of v0.1.11 and targets game version 1.0.0. Nothing in the game itself is
changed: the runtime renders each eye and composes the two into one presented image.

**Status: works, but the current default has no depth.** Read
[Where this stands](#where-this-stands-read-this-before-tuning) before changing `SEP`/`CONV`.

## How it works

1. **Per-eye geometry offset, applied in the vertex/mesh shader.**
   One pipeline is built per eye; the eye and the stereo parameters reach the shader as
   specialization constants. The injected arithmetic is

   ```
   ok  = (w > 1.25) && (w < 500)          // perspective world geometry only
   x  += eye * SEP * (1 - w / CONV) * (ok ? 1 : 0)
   ```

   In NDC this is a shift of `SEP * (1/w - 1/CONV)`: inversely proportional to depth and
   bounded, which is what a lateral camera translation actually produces.

   * `SEP` — eye separation. In clip units, it is the maximum shift (the one reached at
     `w -> 0`); in NDC it is what an object at infinity gets.
   * `CONV` — the `w` where the two eyes agree exactly: the zero-parallax plane. Everything
     nearer comes forward, everything farther sinks back. **If the subject sits at `CONV`
     there is no depth at all** — that is the current default's behaviour, see below.
   * The `w` guard matters in both directions. Post-process and composition passes use
     `w == 1` and the HUD uses a very large `w`; shifting those slides the whole picture
     inside its texture (black band on one side, stretched smear on the other).
   * Orthographic geometry is excluded: the shadow map is rendered orthographically from the
     light, where a clip-space offset is metres of shadow displacement — leave it in and each
     eye gets shadows cast from its own direction.
   * Whole passes are forced mono as well: no colour attachment (depth-only), a square target
     (a shadow map: 1024/2048/4096, never 16:9), or a full-screen draw (few vertices, scissor
     covering the pass). The pass size is recorded when a pass begins
     (`vk_stereo_pass()` in `runtime/gfx/vk/exec/vk_exec.c`); if it is not recorded, every
     rule that depends on it silently does nothing.
   * Mesh shaders are injected too — the position store to
     `gl_MeshVerticesEXT[i].gl_Position` is rewritten the same way. MKW draws characters,
     karts and most objects with them: leave them out and the objects stay at zero parallax
     while the shadows they cast move with the eye.

2. **Both eyes are composed in the presenter.** Each frame draws one eye (left first, then
   right, alternating), and the presenter blits that eye's picture into its half of the
   swapchain, full frame, split exactly in the middle. Frame generation is bypassed while
   stereo is on: its generated frames are mono and would take an eye's place.

3. **Shaders are injected at the SPIR-V level, not in GLSL.** The runtime also builds shader
   programs at run time from templates, so translating only the shipped shaders is not enough
   and the draw that matters may be one of the generated ones. Instead,
   `tools/stereo-inject/inject_stereo_spv.py` walks the official `.spv` cache, disassembles,
   inserts the arithmetic above in front of each vertex entry point's `OpReturn` (and in front
   of the mesh position store), and reassembles. This also sidesteps glslc folding the
   arithmetic away when the constants default to zero.

   ```bash
   # spirv-tools (spirv-dis/spirv-as/spirv-val) must be on PATH
   python3 tools/stereo-inject/inject_stereo_spv.py <official-spv-dir> <out-dir>
   python3 tools/stereo-inject/inject_par.py <official-spv-dir> <out-dir> 8   # 8 workers
   ```

   The result is a directory that starts as a copy of the official shader cache with the
   injected programs on top, pointed at with `MKW_SPIRV`.

   `tools/stereo-inject/inject_stereo_spv_unbounded.py` is the previous variant
   (`x += eye * SEP * (w - CONV)`). It is kept because it explains a bug: its shift grows
   linearly with depth and is unbounded, which shears near geometry hard enough that shadows
   and shading appear to come from the wrong side, mirrored between the two eyes. Do not ship
   it; the reciprocal form above replaced it.

## Where this stands (tuning)

The shipped defaults (`SEP 0.015`, `CONV 20`) give a real stereo pair. From
`parallax = 2 · SEP · (1/w − 1/CONV) · W/2` at `W = 3840` (half width 1920 px):

| distance `w` | `0.015/20` (shipped) | `0.056/40` | `0.30/5` | a real 65 mm pair (f≈1000 px) |
|---|---|---|---|---|
| 1.5 m | 36 px | 138 px | 538 px | — |
| 2 m | **26 px** | 102 px | 346 px | ≈32 px |
| 3 m | 16 px | 66 px | 154 px | ≈20 px |
| 5 m | 8.6 px | 38 px | 0 px | ≈13 px |
| 20 m | 0 px | 5 px | −173 px | ≈3 px |

So the shipped separation is within ~20% of a real eye pair at typical subject distances, and
the extreme settings in the right-hand columns are 4x and 13x too much. Past roughly 0.025 the
near geometry is sheared along x hard enough that its surface orientation reads wrong, and the
shading looks like it comes from the opposite side in each eye (the "two lights" artefact,
observed at 0.056 and at 0.30 but not at 0.015). The usable window is about
`SEP 0.010 – 0.025`; its ceiling is where the shading starts to look wrong, and that is
per-scene.

Two knobs, both baked at pipeline build time (restart required):

* `SEP` — separation. Larger means more depth and more shear distortion.
* `CONV` — the zero-parallax plane. Put it at the main subject's distance so the subject sits
  on the screen plane and everything nearer comes forward. Moving it *away* from the subject
  scales the whole depth range up, which is another way to overflow into the artefact.

**Measurement trap.** Aligning the two halves over a whole window and minimising mean absolute
difference reports 0 px even when the subject is 20-30 px apart: everything around `CONV`
(background, floor, far scenery) really is at 0 px and holds most of the pixels. Measure on the
subject. This fork's own author got this wrong once and briefly documented the mode as
"no depth"; it is not.

## Using it

```
set MKW_STEREO=1
set MKW_SPIRV=<path to the injected shader directory>
set MKW_STEREO_SEP=0.015
set MKW_STEREO_CONV=20
start mkw.exe
```

`MKW_STEREO_SEP` and `MKW_STEREO_CONV` override the values from `mkw.ini`; the same three are
rows in the in-game menu (**Experiments** / 实验 page) and are marked "takes effect after a
restart", because the values are baked into the shader modules when the pipelines are built.

Diagnostics:

* `MKW_STEREO_DBG=1` — logs every render pass that is actually being sheared, as
  `stereo-dbg: pass WxH colour N fmt F depth fmt D eye E`. Use it to see which passes exist
  and which of them the rules let through.
* `MKW_STEREO_SKIP=480x270,960x540` — never shear passes of those sizes. A crude A/B knob for
  finding the pass responsible for an artefact.
* `MKW_SHOTS=<lo>-<hi>:<step>` + `MKW_SHOTS_FULL=1` + `MKW_SHOTS_DIR=<dir>` — dumps presented
  frames (single eye, not the SBS composite).

On the glasses, switch to SBS (hold `+` for two seconds on an Xreal).

## Measured on RTX 3070 Ti, 3840x2160 output

| | |
|---|---|
| Frame rate (stereo) | 45-60 fps (`speed 0.74x - 1.00x` over 5 s windows) |
| Divider | exactly at `W/2 - 1` |
| Cross-half correlation | 0.88 (block matching, static scene) |
| Parallax at `SEP 0.015 / CONV 20` | 26 px at 2 m, 16 px at 3 m, 0 px at 20 m (computed from the formula; the whole-frame matcher used earlier reports 0 px — see the measurement trap above) |
| Parallax with the unbounded variant at `0.015 / 20` | 56 px on a character-select portrait (≈2.9% of the half width) |
| Sheared passes at character select | `1920x1080` and `960x540` (colour+depth), `480x270` ×2, `1920x1080` colour-only |

## Known limitations

* **One frame per eye.** The eyes are one frame apart (16.7 ms at 60 fps), so a fast-moving
  scene shows a slight ghost. Fixing it means rendering both eyes from the same recorded
  frame, which needs a command recorder the runtime does not have yet.
* **The separation ceiling is per-scene.** The mirrored-shading artefact appears when the shear
  is large enough to distort near geometry visibly (roughly `SEP > 0.025` at the settings
  tried), and it was seen at 0.056 and 0.30 but not at 0.015. There is no single value known to
  be safe everywhere.
* About 5% of the vertex shaders cannot be injected (unusual module structure); those keep the
  official mono version, which costs a little depth in the few effects they draw.
* Intermittent `vkQueueSubmit2 ... failed (-4)` (device lost) on the world map, with private
  memory around 10-13 GB of 16 GB. Reproduced twice, not reproduced in four 4-minute bisect
  runs; still open.
* The shear cannot fix screen-space effects: anything the game derives from a screen position
  (rather than from world space) is sampled at the unshifted location while the geometry has
  moved. A real fix is a per-eye projection matrix, which needs the game's camera matrices —
  not something this runtime exposes.
