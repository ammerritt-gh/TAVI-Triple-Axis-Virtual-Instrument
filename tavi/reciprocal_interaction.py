"""Qt-free geometry and constraints for the reciprocal-space dock."""
from __future__ import annotations
from dataclasses import dataclass
import math
from tavi.neutron_conversions import k2energy, energy2k

EPSILON = 1e-9


def triangle_can_close(ki: float, kf: float, q: float,
                       tolerance: float = EPSILON) -> bool:
    """Return whether three non-negative side lengths form a TAS triangle."""
    if not all(math.isfinite(value) for value in (ki, kf, q)):
        return False
    if ki <= 0.0 or kf <= 0.0 or q < 0.0:
        return False
    scale = max(1.0, ki, kf, q)
    margin = tolerance * scale
    return abs(ki - kf) - margin <= q <= ki + kf + margin

def tiny_zero(value: float, tolerance: float = 1.0e-10) -> float:
    """Canonicalise numerical noise for labels and Miller-like coefficients."""
    return 0.0 if abs(value) < tolerance else value

def format_small(value: float, precision: int = 6,
                 tolerance: float = 1.0e-10) -> str:
    """Stable compact UI formatting without scientific-notation noise."""
    value = float(value)
    if not math.isfinite(value):
        return str(value)
    value = tiny_zero(value, tolerance)
    nearest = round(value)
    if abs(value - nearest) <= tolerance * max(1.0, abs(value)):
        value = float(nearest)
    return f"{value:.{precision}g}"

@dataclass(frozen=True)
class HandleAffordance:
    handle: str
    movable: bool
    reason: str | None = None
    radial: bool = True
    tangential: bool = True
    pivot: tuple[float, float] | None = None
    mode_kind: str = ""
    line_direction: tuple[float, float] | None = None


@dataclass(frozen=True)
class GestureMode:
    """The one lock-mask interpretation shared by drawing and solving."""
    handle: str
    kind: str
    pivot: tuple[float, float]
    preserves_handedness: bool
    radial: bool
    tangential: bool
    line_direction: tuple[float, float] | None = None


@dataclass(frozen=True)
class ReachOverlay:
    """Descriptor-derived reciprocal reach radii; ``None`` means no axis limit."""
    mono_hard_radius: float
    ana_hard_radius: float
    mono_mechanical_radius: float | None = None
    ana_mechanical_radius: float | None = None

def _unit(point, fallback=(1., 0.)):
    length = math.hypot(*point)
    if length >= EPSILON:
        return point[0]/length, point[1]/length
    fallback_length = math.hypot(*fallback)
    return (1., 0.) if fallback_length < EPSILON else (
        fallback[0]/fallback_length, fallback[1]/fallback_length,
    )

def _intersections(c0, r0, c1, r1):
    dx, dy = c1[0]-c0[0], c1[1]-c0[1]; d = math.hypot(dx, dy)
    if d < EPSILON or d > r0+r1+EPSILON or d < abs(r0-r1)-EPSILON: return ()
    a = (r0*r0-r1*r1+d*d)/(2*d); h = math.sqrt(max(0., r0*r0-a*a))
    x, y = c0[0]+a*dx/d, c0[1]+a*dy/d
    return ((x-h*dy/d, y+h*dx/d), (x+h*dy/d, y-h*dx/d))

@dataclass(frozen=True)
class ReciprocalState:
    ki: float; kf: float; qx: float; qy: float; qz: float = 0.
    p2x: float | None = None; p2y: float | None = None
    basis_u: tuple[float, float] = (1., 0.)
    basis_v: tuple[float, float] = (0., 1.)
    sense: int = 1
    def __post_init__(self):
        invalid = (self.p2x is None or self.p2y is None or
                   abs(math.hypot(self.p2x, self.p2y)-self.ki) > 1e-6 or
                   abs(math.hypot(self.p2x-self.qx, self.p2y-self.qy)-self.kf) > 1e-6)
        if invalid:
            choices = _intersections((0., 0.), self.ki, (self.qx, self.qy), self.kf)
            preferred = (self.p2x, self.p2y) if self.p2x is not None and self.p2y is not None else (self.ki, 0.)
            signed = [point for point in choices if (point[0]*self.qy-point[1]*self.qx) * self.sense >= 0]
            p2 = min(signed or choices, key=lambda point: math.dist(point, preferred)) if choices else (self.ki, 0.)
            object.__setattr__(self, "p2x", p2[0]); object.__setattr__(self, "p2y", p2[1])
    @property
    def q(self): return math.hypot(self.qx, self.qy)
    @property
    def actual_ki(self): return math.hypot(self.p2x, self.p2y)
    @property
    def actual_kf(self): return math.hypot(self.p2x-self.qx, self.p2y-self.qy)
    @property
    def delta_e(self): return k2energy(self.actual_ki)-k2energy(self.actual_kf)

@dataclass
class LockState:
    ki: bool = False; kf: bool = False; q: bool = False; delta_e: bool = False

@dataclass(frozen=True)
class DragResult:
    state: ReciprocalState; valid: bool; reason: str | None = None
    snapped: tuple[float, float] | None = None; unsnapped: tuple[float, float] | None = None


@dataclass(frozen=True)
class LiveReciprocalResult:
    """Qt-free acknowledgement of an authoritative reciprocal live update.

    ``feasible`` is advisory: ``False`` retains the requested point but marks
    its angle solution stale, while ``None`` means the instrument could not
    determine feasibility.  Only an exception during preparation rolls back.
    """
    state: ReciprocalState
    feasible: bool | None
    reason: str | None = None
    applied: bool = True

class ReciprocalInteractionModel:
    def __init__(self, state, locks=None):
        self.committed = self.preview = state; self.locks = locks or LockState(); self._drag_start = state; self._gesture = None
        self._last_nonzero_sense = self._sense_of(state)
        self.scale = 80.; self.offset = (0., 0.)
    def begin_drag(self, handle=None):
        self._drag_start=self.committed; self.preview=self.committed
        self._gesture = self.gesture_mode(handle) if handle else None
        self._last_nonzero_sense = self._sense_of(self._drag_start) or self._last_nonzero_sense
    def cancel(self): self.preview=self.committed; self._gesture = None
    def commit(self): self.committed=self.preview; return self.committed
    def set_state(self, state): self.committed=self.preview=state
    def cancel_external_update(self, state):
        """An authoritative controller snapshot always wins over a preview."""
        self._drag_start = state
        self.committed = self.preview = state
        self._gesture = None
        self._last_nonzero_sense = self._sense_of(state) or self._last_nonzero_sense
    def accept_live_update(self, state):
        """Record a controller acknowledgement without disturbing a drag pivot."""
        self.committed = state
        if self._gesture is None:
            self.preview = state

    def end_drag(self):
        self._gesture = None

    def _mask(self):
        return "".join("1" if value else "0" for value in (
            self.locks.ki, self.locks.kf, self.locks.q, self.locks.delta_e,
        ))

    def gesture_mode(self, handle: str | None) -> GestureMode:
        """Return the approved vTAS single-analyser lock-mask gesture mode."""
        handle = handle or "p1"
        mask = self._mask()
        start = self._drag_start
        if handle == "p1":
            if mask in {"0000", "1000"}:
                kind = "free_q"
            elif mask in {"0010", "1010"}:
                kind = "q_circle"
            elif mask in {"0001", "0101", "1001"}:
                kind = "delta_e_annulus"
            elif mask in {"0100", "1100", "1101"}:
                kind = "kf_circle"
            else:
                kind = "rigid_rotation"
            pivot = (start.p2x, start.p2y) if kind == "kf_circle" else (0., 0.)
        elif handle == "p2":
            if mask in {"0000", "0010"}:
                kind = "free_p2"
            elif mask in {"1000", "1010"}:
                kind = "ki_circle"
            elif mask in {"0100", "0110"}:
                kind = "kf_circle"
            elif mask in {"0001", "0011"}:
                kind = "delta_e_line"
            else:
                kind = "rigid_rotation"
            pivot = (start.qx, start.qy) if kind == "kf_circle" else (0., 0.)
        else:
            return GestureMode(str(handle), "disabled", (0., 0.), False, False, False)
        radial = kind not in {"q_circle", "ki_circle", "kf_circle", "rigid_rotation"}
        line_direction = None
        if kind == "delta_e_line":
            line_direction = _unit((-start.qy, start.qx))
        return GestureMode(handle, kind, pivot,
                           kind in {"delta_e_annulus", "rigid_rotation"},
                           radial, True, line_direction)
    def _to_plane(self, point):
        u,v=self.preview.basis_u,self.preview.basis_v; det=u[0]*v[1]-u[1]*v[0]
        if abs(det)<EPSILON: return point
        return ((point[0]*v[1]-point[1]*v[0])/det, (u[0]*point[1]-u[1]*point[0])/det)
    def _from_plane(self, point):
        u,v=self.preview.basis_u,self.preview.basis_v
        return (u[0]*point[0]+v[0]*point[1], u[1]*point[0]+v[1]*point[1])
    def _camera_axes(self):
        """Orthonormal display camera; U/V remain the full coefficient basis."""
        u = _unit(self.preview.basis_u)
        v = (-u[1], u[0])
        if v[0]*self.preview.basis_v[0] + v[1]*self.preview.basis_v[1] < 0:
            v = (-v[0], -v[1])
        return u, v
    def screen_to_world(self, point, centre):
        plane=((point[0]-centre[0]-self.offset[0])/self.scale, -(point[1]-centre[1]-self.offset[1])/self.scale)
        u,v=self._camera_axes(); return (u[0]*plane[0]+v[0]*plane[1], u[1]*plane[0]+v[1]*plane[1])
    def world_to_screen(self, point, centre):
        u,v=self._camera_axes(); plane=(point[0]*u[0]+point[1]*u[1], point[0]*v[0]+point[1]*v[1]); return (centre[0]+self.offset[0]+plane[0]*self.scale, centre[1]+self.offset[1]-plane[1]*self.scale)

    def handle_affordance(self, handle: str) -> HandleAffordance:
        if handle not in {"p1", "p2"}: return HandleAffordance(handle, False, "unknown handle")
        mode = self.gesture_mode(handle)
        labels = {
            "free_q": "free Q", "free_p2": "free ki endpoint",
            "q_circle": "|Q| locked", "ki_circle": "ki locked",
            "kf_circle": "kf locked", "delta_e_annulus": "ΔE annulus",
            "delta_e_line": "ΔE line", "rigid_rotation": "rigid rotation",
        }
        return HandleAffordance(handle, True, labels[mode.kind], mode.radial,
                                mode.tangential, mode.pivot, mode.kind,
                                mode.line_direction)
    def zoom_at(self, factor, cursor, centre):
        old=self.screen_to_world(cursor,centre); self.scale=max(10.,min(1000.,self.scale*factor)); new=self.world_to_screen(old,centre); self.offset=(self.offset[0]+cursor[0]-new[0],self.offset[1]+cursor[1]-new[1])
    def pan(self, delta): self.offset=(self.offset[0]+delta[0],self.offset[1]+delta[1])
    def fit(self, extent,size): self.scale=max(10.,min(size)/max(2*extent,EPSILON)); self.offset=(0.,0.)
    def _state(self,q,p2):
        start=self._drag_start
        area = p2[0]*q[1]-p2[1]*q[0]
        sense = (1 if area > 1e-9 else -1 if area < -1e-9 else start.sense)
        if self._gesture is not None and self._gesture.preserves_handedness:
            sense = start.sense
        return ReciprocalState(math.hypot(*p2),math.dist(p2,q),q[0],q[1],start.qz,p2[0],p2[1],start.basis_u,start.basis_v,sense)
    def _choose(self, choices, preferred): return min(choices,key=lambda p:math.dist(p,preferred)) if choices else None
    @staticmethod
    def _sense_of(state):
        area = state.p2x * state.qy - state.p2y * state.qx
        return 1 if area > 1e-9 else -1 if area < -1e-9 else 0
    def _choose_branch(self, choices, preferred, q):
        """Use the captured scattering branch for every constrained rebuild."""
        desired = self._last_nonzero_sense
        if desired:
            matching = [point for point in choices if (1 if point[0]*q[1]-point[1]*q[0] > 0 else -1) == desired]
            if matching:
                choices = matching
        return self._choose(choices, preferred)
    def _update_free_sense(self, state):
        sense = self._sense_of(state)
        if sense:
            self._last_nonzero_sense = sense
    @staticmethod
    def _rotate(point, angle):
        c, s = math.cos(angle), math.sin(angle)
        return point[0]*c-point[1]*s, point[0]*s+point[1]*c
    def _rigid(self, candidate, handle):
        start = self._drag_start
        source = (start.qx, start.qy) if handle == "p1" else (start.p2x, start.p2y)
        if math.hypot(*source) < EPSILON or math.hypot(*candidate) < EPSILON:
            return DragResult(self.preview, False, "rigid rotation needs a non-zero handle")
        angle = math.atan2(candidate[1], candidate[0]) - math.atan2(source[1], source[0])
        q, p2 = self._rotate((start.qx, start.qy), angle), self._rotate((start.p2x, start.p2y), angle)
        state = self._state(q, p2); self.preview = state
        return DragResult(state, True)
    def drag_p1(self,candidate,*,snap_grid=None,reflections=(),capture=None):
        start=self._drag_start; unsnapped=candidate; snapped=None; mode = self._gesture or self.gesture_mode("p1")
        # inputs are physical Q, but grid coordinates are U/V r.l.u.
        if capture is not None:
            hits=[r for r in reflections if math.dist(candidate,r)<=capture]
            if hits: candidate=min(hits,key=lambda r:math.dist(candidate,r)); snapped=candidate
        if snapped is None and snap_grid:
            plane=self._to_plane(candidate); candidate=self._from_plane((round(plane[0]/snap_grid)*snap_grid,round(plane[1]/snap_grid)*snap_grid)); snapped=candidate
        if mode.kind == "rigid_rotation":
            return self._rigid(candidate, "p1")
        p2=(start.p2x,start.p2y); ki0,kf0=start.actual_ki,start.actual_kf
        if mode.kind == "free_q":
            q = candidate
        elif mode.kind == "q_circle":
            q = tuple(value*start.q for value in _unit(candidate, (start.qx, start.qy)))
        elif mode.kind == "kf_circle":
            direction = _unit((candidate[0]-p2[0], candidate[1]-p2[1]), _unit((start.qx-p2[0], start.qy-p2[1])))
            q = (p2[0] + direction[0]*kf0, p2[1] + direction[1]*kf0)
        elif mode.kind == "delta_e_annulus":
            direction = _unit(candidate, (start.qx, start.qy))
            # Keep both captured arm lengths.  The triangle inequality gives
            # the annulus; inset its edges slightly to avoid numerical tangency.
            margin = 1e-7 * max(1., ki0, kf0)
            lower, upper = abs(ki0-kf0) + margin, ki0+kf0-margin
            if lower > upper:
                lower, upper = abs(ki0-kf0), ki0+kf0
            qmag = min(max(math.hypot(*candidate), lower), upper)
            q = direction[0]*qmag, direction[1]*qmag
            choices=_intersections((0.,0.),ki0,q,kf0); p2=self._choose_branch(choices,p2,q)
            if p2 is None:return DragResult(self.preview,False,"locked deltaE cannot close the triangle",snapped,unsnapped)
        result=self._state(q,p2); self.preview=result
        if not mode.preserves_handedness:
            self._update_free_sense(result)
        # A snap marker promises the displayed Q target, not merely an input
        # candidate that a later circle/annulus projection had to move away.
        honest_snap = snapped if snapped is not None and math.dist((result.qx, result.qy), snapped) < 1e-8 else None
        return DragResult(result, True, snapped=honest_snap, unsnapped=unsnapped)
    def drag_p2(self,candidate):
        start=self._drag_start; q=(start.qx,start.qy); p2=candidate; ki0,kf0=start.actual_ki,start.actual_kf; mode = self._gesture or self.gesture_mode("p2")
        if mode.kind == "rigid_rotation":
            return self._rigid(candidate, "p2")
        if mode.kind == "ki_circle":
            p2=tuple(value*ki0 for value in _unit(p2,(start.p2x,start.p2y)))
        elif mode.kind == "kf_circle":
            direction = _unit((p2[0]-q[0], p2[1]-q[1]), _unit((start.p2x-q[0], start.p2y-q[1])))
            p2 = (q[0] + direction[0]*kf0, q[1] + direction[1]*kf0)
        elif mode.kind == "delta_e_line":
            q2 = q[0]*q[0] + q[1]*q[1]
            if q2 < EPSILON:
                return DragResult(self.preview, False, "ΔE line needs non-zero Q")
            target = start.p2x*q[0] + start.p2y*q[1]
            correction = (target - (p2[0]*q[0] + p2[1]*q[1])) / q2
            p2 = (p2[0] + correction*q[0], p2[1] + correction*q[1])
        result=self._state(q,p2); self.preview=result
        if not mode.preserves_handedness:
            self._update_free_sense(result)
        return DragResult(result,True)
