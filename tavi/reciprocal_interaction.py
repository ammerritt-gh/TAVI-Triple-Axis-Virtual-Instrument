"""Qt-free geometry and constraints for the reciprocal-space dock."""
from __future__ import annotations
from dataclasses import dataclass
import math
from tavi.neutron_conversions import k2energy, energy2k

EPSILON = 1e-9

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

def _unit(point, fallback=(1., 0.)):
    length = math.hypot(*point)
    return fallback if length < EPSILON else (point[0]/length, point[1]/length)

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
    def __post_init__(self):
        invalid = (self.p2x is None or self.p2y is None or
                   abs(math.hypot(self.p2x, self.p2y)-self.ki) > 1e-6 or
                   abs(math.hypot(self.p2x-self.qx, self.p2y-self.qy)-self.kf) > 1e-6)
        if invalid:
            choices = _intersections((0., 0.), self.ki, (self.qx, self.qy), self.kf)
            preferred = (self.p2x, self.p2y) if self.p2x is not None and self.p2y is not None else (self.ki, 0.)
            p2 = min(choices, key=lambda point: math.dist(point, preferred)) if choices else (self.ki, 0.)
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
        self.committed = self.preview = state; self.locks = locks or LockState(); self._drag_start = state
        self.scale = 80.; self.offset = (0., 0.)
    def begin_drag(self): self._drag_start=self.committed; self.preview=self.committed
    def cancel(self): self.preview=self.committed
    def commit(self): self.committed=self.preview; return self.committed
    def set_state(self, state): self.committed=self.preview=state
    def cancel_external_update(self, state):
        """An authoritative controller snapshot always wins over a preview."""
        self._drag_start = state
        self.committed = self.preview = state
    def accept_live_update(self, state):
        """Record a controller acknowledgement without disturbing a drag pivot."""
        self.committed = state
        self.preview = state
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
        if self.locks.ki and self.locks.kf and self.locks.q and self.locks.delta_e:
            return HandleAffordance(handle, True, "orientation-only: ki, kf, |Q|, ΔE locked", False, True, (0., 0.))
        if handle == "p1" and self.locks.q:
            return HandleAffordance(handle, True, "|Q| locked", False, True, (0., 0.))
        if handle == "p2" and self.locks.ki:
            return HandleAffordance(handle, True, "ki locked", False, True, (0., 0.))
        if self.locks.kf:
            pivot = (self._drag_start.p2x, self._drag_start.p2y) if handle == "p1" else (self._drag_start.qx, self._drag_start.qy)
            return HandleAffordance(handle, True, "kf locked", False, True, pivot)
        # A delta-E-only P2 move is projected onto a line perpendicular to Q.
        # Both screen-space components can respond locally, so show both cues;
        # the solver remains authoritative about the exact coupled path.
        if handle == "p2" and self.locks.delta_e:
            return HandleAffordance(handle, True, "ΔE-coupled motion", True, True)
        return HandleAffordance(handle, True)
    def zoom_at(self, factor, cursor, centre):
        old=self.screen_to_world(cursor,centre); self.scale=max(10.,min(1000.,self.scale*factor)); new=self.world_to_screen(old,centre); self.offset=(self.offset[0]+cursor[0]-new[0],self.offset[1]+cursor[1]-new[1])
    def pan(self, delta): self.offset=(self.offset[0]+delta[0],self.offset[1]+delta[1])
    def fit(self, extent,size): self.scale=max(10.,min(size)/max(2*extent,EPSILON)); self.offset=(0.,0.)
    def _state(self,q,p2):
        start=self._drag_start
        return ReciprocalState(math.hypot(*p2),math.dist(p2,q),q[0],q[1],start.qz,p2[0],p2[1],start.basis_u,start.basis_v)
    def _choose(self, choices, preferred): return min(choices,key=lambda p:math.dist(p,preferred)) if choices else None
    def drag_p1(self,candidate,*,snap_grid=None,reflections=(),capture=None):
        start=self._drag_start; unsnapped=candidate; snapped=None
        # inputs are physical Q, but grid coordinates are U/V r.l.u.
        if capture is not None:
            hits=[r for r in reflections if math.dist(candidate,r)<=capture]
            if hits: candidate=min(hits,key=lambda r:math.dist(candidate,r)); snapped=candidate
        if snapped is None and snap_grid:
            plane=self._to_plane(candidate); candidate=self._from_plane((round(plane[0]/snap_grid)*snap_grid,round(plane[1]/snap_grid)*snap_grid)); snapped=candidate
        direction=_unit(candidate,_unit((start.qx,start.qy))); qmag=start.q if self.locks.q else math.hypot(*candidate); q=(direction[0]*qmag,direction[1]*qmag)
        ki0,kf0=start.actual_ki,start.actual_kf; p2=(start.p2x,start.p2y)
        # deltaE couples magnitudes: choose a fixed side if locked, otherwise
        # retain ki and derive kf from the locked energy transfer.
        if self.locks.delta_e:
            ki=ki0
            if self.locks.kf: kf=kf0; ki=energy2k(k2energy(kf)+start.delta_e)
            else: kf=energy2k(k2energy(ki)-start.delta_e)
            choices=_intersections((0.,0.),ki,q,kf); p2=self._choose(choices,p2)
            if p2 is None:return DragResult(self.preview,False,"locked deltaE cannot close the triangle",snapped,unsnapped)
        elif self.locks.ki and self.locks.kf:
            p2=self._choose(_intersections((0.,0.),ki0,q,kf0),p2)
            if p2 is None:return DragResult(self.preview,False,"locked ki/kf cannot reach this Q",snapped,unsnapped)
        elif self.locks.kf:
            # vTAS Kf-only P1 projection: preserve incident endpoint and
            # project the dragged Q endpoint onto its fixed-Kf circle.
            direction = _unit((candidate[0]-p2[0], candidate[1]-p2[1]), _unit((start.qx-p2[0], start.qy-p2[1])))
            if self.locks.q:
                # Q radius wins; project P2 around the fixed Q instead.
                p2 = (q[0] + direction[0]*kf0, q[1] + direction[1]*kf0)
            else:
                q = (p2[0] + direction[0]*kf0, p2[1] + direction[1]*kf0)
        # ki lock or fully free keep the incident endpoint continuous.
        result=self._state(q,p2); self.preview=result; return DragResult(result,True,snapped=snapped,unsnapped=unsnapped)
    def drag_p2(self,candidate):
        start=self._drag_start; q=(start.qx,start.qy); p2=candidate; ki0,kf0=start.actual_ki,start.actual_kf
        if self.locks.ki: p2=tuple(value*ki0 for value in _unit(p2,(start.p2x,start.p2y)))
        if self.locks.delta_e:
            # A locked final arm wins over a free candidate magnitude; delta-E
            # then derives ki.  With neither side fixed, candidate ki drives
            # the coupled final magnitude.
            if self.locks.kf:
                kf = kf0; ki = energy2k(k2energy(kf)+start.delta_e)
            else:
                ki=math.hypot(*p2)
                if self.locks.ki: ki=ki0
                kf=energy2k(k2energy(ki)-start.delta_e)
            p2=self._choose(_intersections((0.,0.),ki,q,kf),p2)
            if p2 is None:return DragResult(self.preview,False,"locked deltaE cannot close the triangle")
        elif self.locks.ki and self.locks.kf:
            p2 = self._choose(_intersections((0., 0.), ki0, q, kf0), p2)
            if p2 is None:return DragResult(self.preview,False,"locked ki/kf cannot close the triangle")
        elif self.locks.kf:
            # vTAS Kf-only P2 projection: candidate lies on circle about Q.
            direction = _unit((p2[0]-q[0], p2[1]-q[1]), _unit((start.p2x-q[0], start.p2y-q[1])))
            p2 = (q[0] + direction[0]*kf0, q[1] + direction[1]*kf0)
        result=self._state(q,p2); self.preview=result; return DragResult(result,True)
