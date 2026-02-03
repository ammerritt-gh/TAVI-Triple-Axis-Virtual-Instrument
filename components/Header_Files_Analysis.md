# NMO Header Files Analysis

## Overview

The NMO McStas component depends on two header files:

| File | Purpose | Lines | Author |
|------|---------|-------|--------|
| `conic_finite_mirror.h` | Ray-tracing engine for conic surfaces | ~1772 | Giacomo Resta (MIT) + modifications |
| `calciterativemirrors.h` | Mirror position calculator | ~50 | Christoph Herb (TUM) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    McStas Instrument                             │
│                         │                                        │
│                         ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │         FlatEllipse_finite_mirror.comp                   │    │
│  │                                                          │    │
│  │  INITIALIZE:                                             │    │
│  │    - Reads B-values from file OR                        │    │
│  │    - Calls get_r_at_z0() to calculate them              │    │
│  │    - Creates Scene with nested elliptical mirrors       │    │
│  │                                                          │    │
│  │  TRACE:                                                  │    │
│  │    - Propagates neutron to NMO entrance                 │    │
│  │    - Checks if entering through silicon                 │    │
│  │    - Calls traceSingleNeutron() for ray-tracing         │    │
│  │    - Handles exit refraction                            │    │
│  └──────────────────┬──────────────────────────────────────┘    │
│                     │                                            │
│         ┌───────────┴───────────┐                               │
│         ▼                       ▼                               │
│  ┌─────────────────┐    ┌─────────────────────────────────┐    │
│  │calciterative    │    │   conic_finite_mirror.h          │    │
│  │mirrors.h        │    │                                   │    │
│  │                 │    │  Scene: collection of geometry    │    │
│  │ get_r_at_z0()   │    │  - FlatSurf[] (elliptical mirrors)│    │
│  │ Calculates      │    │  - Disk[] (absorbers/propagators) │    │
│  │ mirror positions│    │  - Detector[]                     │    │
│  │ using iterative │    │                                   │    │
│  │ algorithm       │    │  traceSingleNeutron():           │    │
│  │                 │    │  - Finds next collision           │    │
│  │                 │    │  - Handles reflection/refraction  │    │
│  │                 │    │  - Loops until no more collisions │    │
│  └─────────────────┘    └─────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## `calciterativemirrors.h` - Detailed Analysis

### Purpose
Implements the iterative mirror construction algorithm from Zimmer's paper (arXiv:1611.07353).

### Key Function: `get_r_at_z0()`

```c
double* get_r_at_z0(int number, double z_0, double r_0, double z_extract,
                    double LStart, double LEnd, double lStart, double lEnd)
```

**Algorithm:**
1. Start with outermost mirror defined by point (z_0, r_0)
2. Calculate the ellipse passing through this point with foci at LStart and LEnd
3. For each subsequent mirror:
   - Find where current mirror ends at z = lEnd
   - Draw line from F1 through this point
   - Where it intersects z = lStart defines the next mirror's starting point
   - Calculate new ellipse through this point

**Mathematical basis:**
- Ellipse equation: r² = k₁ + k₂z + k₃z²
- Semi-major axis: a = √[(u² + c² + r² + √((u² + c² + r²)² - 4c²u²)) / 2]
- Where c = (LEnd - LStart)/2 and u = z + c - LEnd

### Bugs Found

1. **Wrong type in malloc (line 19):**
   ```c
   // WRONG:
   double *r_zExtracts = malloc(n*sizeof(double_t));
   // CORRECT:
   double *r_zExtracts = malloc(n*sizeof(double));
   ```

2. **Debug printf left in production code (lines 26, 40):**
   These slow down initialization and clutter output.

3. **No NULL check after malloc:**
   Should verify allocation succeeded.

4. **Encoding corruption in comment:**
   `Ã¼berlegungen` should be `überlegungen`

---

## `conic_finite_mirror.h` - Detailed Analysis

### Purpose
Complete ray-tracing framework for conic section geometries (ellipses, parabolas, hyperboloids).

### Key Data Structures

```c
// A neutron particle
typedef struct {
    double _x, _y, _z;      // Position
    double _vx, _vy, _vz;   // Velocity
    double _sx, _sy, _sz;   // Spin
    double w;               // Statistical weight
    int silicon;            // +1: in silicon, -1: in air, 0: no tracking
    int absorb;             // Absorption flag
    double _t;              // Time of flight
} Particle;

// A flat elliptical mirror surface
typedef struct {
    double k1, k2, k3;      // Conic coefficients: x² = k1 + k2*z + k3*z²
    double zs, ze;          // Start and end z-coordinates
    double ll, rl;          // Left and right limits (y direction)
    double m;               // Supermirror m-value
    double f1, f2;          // Focal points
    double a, c;            // Ellipse parameters
    int doubleReflections;  // Allow backside reflections
} FlatSurf;

// Collection of all geometry
typedef struct {
    FlatSurf f[MAX_FLATSURF];   // Up to 200 flat surfaces
    int num_f;
    ConicSurf c[MAX_CONICSURF]; // Up to 100 conic surfaces
    int num_c;
    Disk di[MAX_DISK];          // Up to 100 disks
    int num_di;
    // ... function pointers for tracing
} Scene;
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `makeScene()` | Create empty scene |
| `addFlatEllipse()` | Add elliptical mirror to scene |
| `addDisk()` | Add disk (absorber/propagator) |
| `traceSingleNeutron()` | Main ray-tracing loop |
| `getTimeOfFirstCollisionFlat()` | Find when neutron hits surface |
| `reflectNeutronFlat()` | Handle reflection/refraction |
| `refractNeutronFlat()` | Snell's law for silicon interface |

### Main Tracing Loop (`traceSingleNeutron`)

```c
void traceSingleNeutron(Particle* p, Scene s) {
    int contact = 1;
    do {
        // Find earliest collision among ALL surfaces
        for each FlatSurf: check collision time
        for each ConicSurf: check collision time  
        for each Disk: check collision time
        for each Detector: check collision time
        
        // Handle the earliest collision
        switch (type) {
            case FLAT: traceNeutronFlat(p, surface);
            case DISK: traceNeutronDisk(p, disk);
            // etc.
        }
    } while (contact && !p->absorb);
}
```

### Bugs and Issues Found

#### Critical Bugs

1. **Wrong random function usage (line 66):**
   ```c
   // WRONG - rand01() already returns [0,1], dividing makes it tiny
   double getRandom() {
       return (double)rand01()/RAND_MAX;
   }
   // CORRECT
   double getRandom() {
       return rand01();
   }
   ```

2. **Hardcoded silicon attenuation (line 348):**
   ```c
   p->w *= exp(-t*98900/52.338);  // Only valid for specific velocity!
   ```
   Should be velocity-dependent or parameterized.

3. **Hardcoded supermirror parameters (line 1537):**
   ```c
   weight = calcSupermirrorReflectivity(V2Q_conic*2*vn, s.m, 0.995, 0.0218);
   // R0=0.995 and Qc=0.0218 should be configurable
   ```

#### Performance Issues

1. **O(n) collision search (lines 1686-1732):**
   Every neutron iteration checks ALL surfaces. For 160 surfaces (80 mirrors × 2 sides), this is expensive.
   
   **Potential optimization:** Spatial indexing or bounding box pre-filtering.

2. **No early termination in collision loop:**
   Even after finding a collision, continues checking all remaining surfaces.

3. **Repeated sqrt() and trig calls:**
   Many calculations could be cached.

#### Code Quality Issues

1. **Magic numbers throughout:**
   - `1e-11` cutoff in multiple places
   - `98900/52.338` for silicon attenuation
   - `6.84459399932` in grazing angle calculation

2. **Inconsistent error handling:**
   Some functions call `exit(-1)`, others return `-1`.

3. **Memory management:**
   Detector allocates memory but relies on `finishDetector()` being called.

---

## Recommendations

### Immediate Fixes (High Priority)

1. Fix `double_t` → `double` in calciterativemirrors.h
2. Fix `getRandom()` function
3. Add NULL checks after malloc
4. Remove debug printf statements (or make conditional)

### Performance Improvements (Medium Priority)

1. Add spatial indexing for collision detection
2. Pre-compute constant values during initialization
3. Use early termination when collision is found far from remaining surfaces

### Long-term Improvements (Low Priority)

1. Make hardcoded physics parameters configurable
2. Add proper error handling with return codes
3. Consider using McStas's built-in table interpolation for reflectivity
4. Document the physics assumptions and valid parameter ranges

---

## File Locations

After fixes, the files should be placed in your McStas component search path, typically:
- `$MCSTAS/lib/share/` (system-wide)
- Your instrument directory (local)
- A custom include path specified with `-I` flag

The component finds them via:
```c
%include "conic_finite_mirror.h"
%include "calciterativemirrors.h"
```
