# PANDA Model Status

- Model version: **0.1.0**
- Model date: **2026-07-18**
- Runtime status: **research**
- Last evidence review: **2026-07-18**

| Area | Available information | Status | Required action |
|---|---|---|---|
| Beam transport | Papers describe supermirror-guide and virtual-source concepts | provisional | Extract present-day geometry and apertures. |
| McStas tree | Historical `vpanda.instr` snapshot | provisional | Compare component by component with current hardware. |
| Mono/sample/analyser geometry | Partial information in papers and historical model | missing | Establish current distances, senses, limits, and crystals. |
| Collimation, slits, filters | Not yet curated | missing | Obtain an instrument configuration table or drawing. |
| Detector and output contract | Not selected for TAVI | missing | Define the initial single-detector scope. |
| Runtime implementation | No descriptor, plugin, model, or verification points | missing | Complete scientist review before implementation. |
| Historical `vpanda.instr` quality | `atx` is unused; defaulted `kf` shadows explicit `ki`; parameter descriptions contain placeholder units; scattering-sense inputs are unused; fallback ΔE uses the wrong momentum relationship | conflicting | Preserve the immutable snapshot, treat it as comparison-only, and resolve each issue from authoritative evidence before implementing PANDA. |

No value in the historical McStas file is accepted as current merely because
it is executable.
