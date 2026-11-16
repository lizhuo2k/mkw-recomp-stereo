# NOTICE

This repository is a derivative work. This file records what comes from where, so the upstream attribution
required by the MIT license is unambiguous.

## Upstream

* **Project:** mkw-recomp — https://github.com/adriadam10/mkw-recomp
* **Author / copyright holder:** Adrià, Copyright (c) 2026
* **License:** MIT (see [`LICENSE`](LICENSE), kept unmodified)
* **Base taken:** release v0.1.11

Everything that makes the game run is upstream work:

* the static recompiler and the generated C (`recomp/`, the game's translated code),
* the NVN2 reimplementation on top of Vulkan (`runtime/gfx/nvn/`, `runtime/gfx/vk/`),
* the SM86-to-SPIR-V shader translator (`sm86/`),
* the launcher, the menu framework, the settings system, the i18n catalogues, the build system, the documentation.

## Changes in this fork

Published by the authors of this fork under the same MIT terms as upstream:

| Path | Change |
|---|---|
| `runtime/gfx/vk/pipe/vk_stereo.{c,h}` | new: eye state, the stereo settings, the full-screen pass mark |
| `runtime/gfx/vk/pipe/vk_pipeline.c`, `vk_pipe_keys.c`, `vk_pipe_internal.h`, `vk_pipe_gpl.c` | the eye as part of the pipeline key; mono for depth-only and full-screen draws |
| `runtime/gfx/vk/device/vk_backend.c`, `vk.h` | one eye per submission, the eye handed to the presenter |
| `runtime/gfx/vk/pipe/vk_spirv_patch.{c,h}` | the eye's specialization constants written into the shader module |
| `runtime/gfx/vk/exec/vk_exec_draw.c` | marks a full-screen draw before its pipeline is asked for |
| `runtime/gfx/nvn/host/gfx_present.c` | the side-by-side composition: each eye over half the frame, split in the middle |
| `runtime/core/base/cfg.c` | `STEREO`, `STEREO_SEP`, `STEREO_CONV` |
| `runtime/ui/menu/settings_tabs.cpp`, `runtime/gfx/nvn/host/ui_text.h`, `i18n/*.pot`, `i18n/zh-Hans.po` | three menu rows on the Experiments page |
| `tools/stereo-inject/` | new: the SPIR-V injection that gives the shipped shaders their parallax |
| `STEREO-3D.md`, this file, the fork notice in `README.md` | documentation |

## Game content

No part of *Mario Kart World* is in this repository or in anything published from it: no executables, no RomFS, no
keys. As upstream requires, the game has to be dumped from your own console.

## Trademarks

*Mario Kart World* and Nintendo Switch 2 are trademarks of Nintendo. This project is not affiliated with, endorsed
by, or sponsored by Nintendo, nor by the upstream project's authors.
