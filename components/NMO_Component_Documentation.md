# FlatEllipse_finite_mirror - Optimized NMO Component

## Overview

This is an optimized McStas component for simulating Nested Mirror Optics (NMO) 
based on flat elliptical mirrors for neutron focusing. The implementation follows
the design described in:

> Herb et al., "Nested mirror optics for neutron extraction, transport, and focusing"
> Nuclear Inst. and Methods in Physics Research A 1040 (2022) 167154

## Key Optimizations

### 1. Binary Search for Mirror Location (O(log n) vs O(n))
For ~80 mirrors, this reduces comparisons from 80 to ~7 per neutron:
```
Linear search:  80 comparisons × 10^9 neutrons = 8×10^10 operations
Binary search:   7 comparisons × 10^9 neutrons = 7×10^9 operations
```
**Expected speedup: ~10x for mirror location logic**

### 2. Pre-computed Boundary Arrays
Absolute values and outer boundaries are computed once at initialization:
- `rfront_inner_abs[i] = fabs(rfront_inner[i])`
- `rfront_outer_abs[i] = rfront_inner_abs[i] + mirror_width`

This eliminates repeated `fabs()` calls in the hot TRACE loop.

### 3. Silicon Refraction Toggle
New parameter `enable_silicon_refraction` (default=1):
- Set to 0 to skip refraction calculations for faster runs
- Geometry tracking still works; only the refraction math is skipped
- Useful for quick test runs or when refraction effects are negligible

### 4. Memory Management
- All allocated arrays are properly freed in FINALLY block
- Table structures are freed to prevent memory leaks
- NULL checks prevent double-free errors

### 5. Reduced Hot-Path Operations
- Removed debug printf from TRACE (use `-DDEBUG_NMO` to enable)
- Eliminated redundant particle recreation
- Streamlined conditional logic

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sourceDist` | double | 0 | Distance for mirror spacing calculation [m] |
| `LStart` | double | 0.6 | First focal point z-coordinate [m] |
| `LEnd` | double | 0.6 | Second focal point z-coordinate [m] |
| `lStart` | double | 0 | Mirror assembly start z-coordinate [m] |
| `lEnd` | double | 0 | Mirror assembly end z-coordinate [m] |
| `r_0` | double | 0.02076 | Outermost mirror distance at lStart [m] |
| `nummirror` | int | 9 | Number of mirrors (overridden by file) |
| `mf` | double | 4 | Front coating m-value (uniform) |
| `mb` | double | 0 | Back coating m-value (uniform) |
| `mirror_width` | double | 0.003 | Substrate thickness [m] |
| `mirror_sidelength` | double | 1 | Mirror height in y [m] |
| `doubleReflections` | int | 0 | Allow backside reflections |
| `enable_silicon_refraction` | int | 1 | Model Si refraction (0=off) |
| `rfront_inner_file` | string | "NULL" | B-values input file |
| `mirror_mvalue_file` | string | "NULL" | Per-mirror m-values file |

## Input File Formats

### B-values File (`rfront_inner_file`)
Tab-separated, two columns:
```
# index    b_value [m]
0          0.01700
1          0.01520
2          0.01360
...
```

### M-values File (`mirror_mvalue_file`)
Tab-separated, three columns:
```
# index    mf_front    mb_back
0          4.5         0.0
1          4.0         0.0
...
```

## Usage Examples

### Basic usage with automatic mirror calculation:
```c
COMPONENT nmo = FlatEllipse_finite_mirror(
    LStart = 6.0, LEnd = 6.0,
    lStart = -0.5, lEnd = 0.5,
    r_0 = 0.05, nummirror = 20,
    mf = 4, mirror_width = 0.0003
)
AT (0, 0, 6) RELATIVE source
```

### Using B-values from file:
```c
COMPONENT nmo = FlatEllipse_finite_mirror(
    LStart = 6.0, LEnd = 6.0,
    lStart = -0.5, lEnd = 0.5,
    mf = 4, mirror_width = 0.0003,
    rfront_inner_file = "my_bvalues.txt"
)
AT (0, 0, 6) RELATIVE source
```

### Full configuration with per-mirror m-values:
```c
COMPONENT nmo = FlatEllipse_finite_mirror(
    LStart = 6.0, LEnd = 6.0,
    lStart = -0.5, lEnd = 0.5,
    mirror_width = 0.0003,
    mirror_sidelength = 0.045,
    enable_silicon_refraction = 1,
    rfront_inner_file = "bvalues.txt",
    mirror_mvalue_file = "mvalues.txt"
)
AT (0, 0, 6) RELATIVE source
```

### Fast test run (no refraction):
```c
COMPONENT nmo = FlatEllipse_finite_mirror(
    LStart = 6.0, LEnd = 6.0,
    lStart = -0.5, lEnd = 0.5,
    mf = 4, mirror_width = 0.0003,
    enable_silicon_refraction = 0,  // Skip refraction for speed
    rfront_inner_file = "bvalues.txt"
)
AT (0, 0, 6) RELATIVE source
```

## Debugging

To enable debug output, compile with:
```bash
mcrun -DDEBUG_NMO my_instrument.instr
```

This enables verbose warnings for edge cases like negative propagation times.

## Dependencies

Required header files (must be in McStas component path):
- `conic_finite_mirror.h`
- `calciterativemirrors.h`
- `read_table-lib` (standard McStas library)

## Performance Notes

For best performance:
1. Use `enable_silicon_refraction = 0` for initial testing
2. Minimize `mirror_width` if substrate effects aren't critical
3. The binary search provides significant speedup for nummirror > 20
4. Memory usage scales as O(n) with number of mirrors

## Changes from Original

| Feature | Original | Optimized |
|---------|----------|-----------|
| Mirror search | O(n) linear | O(log n) binary |
| fabs() calls | Per neutron | Pre-computed |
| Silicon refraction | Always on | Toggle parameter |
| Memory cleanup | Partial | Complete |
| Debug output | Always | Compile flag |
| Per-mirror m-values | Supported | Supported + validated |
| Documentation | Minimal | Comprehensive |
