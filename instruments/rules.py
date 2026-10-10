"""The point plan: which calculation a scan runs, what sets each quantity, and its points.

Two scan commands are compiled against a frozen context into one supported
calculation. Rules are plain data plus a function: each declares, for every
output, the inputs that output depends on, and evaluates by calling the
existing solvers in ``instruments.tas_runtime`` (never a re-implementation).
``build_plan`` applies the precedence and refuses a command it cannot honour,
naming what owns the quantity; ``expand`` turns the plan into named points
against a launch snapshot; ``check_point`` judges one point's feasibility.
There is no pair list: two commands are compatible exactly when both survive
as distinct independent inputs of the calculation they select.

Qt-free. Every quantity is named by its canonical ID (``tavi.quantities``).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Callable, Mapping

import numpy as np

from instruments.contract import Capabilities, CurvatureMode
from instruments.descriptor import CurvatureAxis
from instruments.tas_runtime import (
    ATT,
    DE,
    HKL,
    HKL_CALC,
    MOTORS,
    MTT,
    Q,
    Q_CALC,
    SGL,
    SGU,
    STH,
    STT,
    _solve_point_geometry,
    curvature_run_error,
    curvature_scan_error,
    describe_scan_error_flags,
    judge_point_geometry,
    plane_lock_q,
)
from tavi.neutron_conversions import energy2k
from tavi.orientation import locked_plane_text
from tavi.quantities import (
    QuantityRefused, by_id, crystal_theta, resolve, slit_gap_ids, to_internal,
)
from tavi.tas_geometry import component_q_to_instrument_q
from tavi.utilities import parse_scan_steps, scan_range_error

MTH, ATH = "mono_theta_deg", "analyzer_theta_deg"
ARCS = (SGL, SGU)
EI, EF = "incident_energy_mev", "final_energy_mev"
KI, KF = "incident_wavevector_inv_angstrom", "final_wavevector_inv_angstrom"
# Requested radius -> the crystal 2θ its branch and its autofocus follow.
RADIUS_CRYSTAL = {"mono_horizontal_radius_m": MTT, "mono_vertical_radius_m": MTT,
                  "analyzer_horizontal_radius_m": ATT, "analyzer_vertical_radius_m": ATT}

CALCULATION_LABEL = {HKL_CALC: "HKL calculation", Q_CALC: "Q calculation",
                     MOTORS: "direct-motor calculation"}

SCANNED, SET_PER_POINT = "scanned", "set_per_point"
USED_AS_TYPED, NOT_READ = "used_as_typed", "not_read"


CONFLICT_NOTE = "force does not override a command conflict."


class PlanRefused(ValueError):
    """A scan that cannot run as written; str() is the message a physicist reads.

    ``command`` is the box at fault (1 or 2), or None when the pair or the
    launch state is; ``quantity`` the canonical ID the refusal is about.
    ``conflict`` marks a refusal of the pair (or of a command the calculation
    cannot take), which every surface must refuse: its message says so here,
    the one place every surface's text comes from.
    """

    def __init__(self, message, command=None, quantity=None, conflict=False):
        super().__init__(f"{message} {CONFLICT_NOTE}" if conflict else message)
        self.command = command
        self.quantity = quantity


@dataclass(frozen=True)
class AxisPolicy:
    """One requested-radius axis as this launch has it."""

    mode: CurvatureMode           # HELD or AUTOFOCUS: the launch's choice for an unscanned axis
    hardware: CurvatureAxis       # the installed assembly's resolved declaration
    holder: str = ""              # what fixes a driven=False axis, for its refusal


@dataclass(frozen=True)
class PlanContext:
    """The caller's frozen launch context; nothing here is read from live state."""

    engine: str                   # "mcstas" or "deterministic"
    fixed_side: str               # "Ki" or "Kf"
    fixed_energy_mev: float
    monocris: str | None
    anacris: str | None
    plane_lock: dict | None       # the state's plane_lock: {"hkl_u", "hkl_v", "tilts"}, or None
    curvature: Mapping[str, AxisPolicy]   # requested-radius ID -> its policy
    inputs: frozenset             # IDs the instrument takes as independent inputs
    observables: frozenset        # IDs it offers as derived observables
    slit_bindings: frozenset = frozenset()   # slit gap IDs with a per-point binding

    @property
    def fixed_policy(self) -> str:
        return f"fixed {self.fixed_side}"


@dataclass(frozen=True)
class Rule:
    """A named step of a calculation: per output, the IDs it depends on, and its evaluator.

    ``policy`` names the setting a rule applies ("fixed Kf", "plane lock",
    "fixed"); an output whose dependencies reach no command is attributed to it.
    ``evaluate(values, context, state)`` returns at least every output.
    """

    name: str
    outputs: Mapping[str, tuple]
    evaluate: Callable
    policy: str = ""


@dataclass(frozen=True)
class Command:
    number: int                   # the box it was typed in: 1 or 2
    text: str
    quantity: str                 # canonical ID
    start: float
    stop: float
    step: float
    relative: bool


@dataclass(frozen=True)
class Provenance:
    """What one quantity does in a plan; exactly one role, and scanned wins."""

    role: str                     # SCANNED, SET_PER_POINT, USED_AS_TYPED or NOT_READ
    commands: tuple = ()          # SCANNED: its command; SET_PER_POINT: the commands driving it
    policies: tuple = ()          # SET_PER_POINT reached by no command: the settings that set it
    relative: bool = False        # SCANNED: steps from the value typed in its field


@dataclass(frozen=True)
class Plan:
    context: PlanContext
    calculation: str              # HKL_CALC, Q_CALC or MOTORS
    commands: tuple               # Command, in box order
    rules: tuple                  # Rule, in evaluation order
    inputs: frozenset             # the calculation's independent inputs, scanned ones included
    provenance: Mapping[str, Provenance] = field(default_factory=dict)

    @property
    def energy(self) -> str:
        """The energy semantics: the fixed side, or both energies from the crystals."""
        return "from the crystal angles" if self.calculation == MOTORS else self.context.fixed_policy

    @property
    def scanned(self) -> frozenset:
        return frozenset(c.quantity for c in self.commands)


@dataclass(frozen=True)
class Expansion:
    points: tuple                 # run order (command 2 outer); each maps every input to its value
    values: Mapping[int, tuple]   # command number -> the absolute values it runs
    bases: Mapping[int, float]    # relative command number -> the base read from the snapshot


@dataclass(frozen=True)
class PointCheck:
    feasible: bool
    reason: str | None = None
    kind: str | None = None       # "physical_infeasible" or "transmission"
    transmission: tuple = ()
    requested_q: tuple | None = None   # plane lock only: the Q asked for ...
    realized_q: tuple | None = None    # ... and the in-plane Q the stage reaches


def _name(qid):
    return by_id(qid).name


# ----------------------------------------------------------------- evaluators

def _hkl_to_q(v, ctx, state):
    q = component_q_to_instrument_q(np.array(state.sample_mount.hkl_to_q(*(v[i] for i in HKL))))
    return dict(zip(Q, (float(x) for x in q)))


def _fixed_energy(v, ctx, state):
    energy, k = ctx.fixed_energy_mev, float(energy2k(ctx.fixed_energy_mev))
    return {EF: energy, KF: k} if ctx.fixed_side == "Kf" else {EI: energy, KI: k}


def _q_energy_to_stage(v, ctx, state):
    angles, flags = state.calculate_stage_angles(
        *(v[i] for i in Q), v[DE], ctx.fixed_energy_mev, f"{ctx.fixed_side} Fixed",
        ctx.monocris, ctx.anacris, locked=ctx.plane_lock)
    if flags:
        raise ValueError(describe_scan_error_flags(flags))
    mtt, stt, sth, sgl, att, sgu = angles
    if ctx.fixed_side == "Kf":
        ei, ef = ctx.fixed_energy_mev + v[DE], ctx.fixed_energy_mev
    else:
        ei, ef = ctx.fixed_energy_mev, ctx.fixed_energy_mev - v[DE]
    return {MTT: mtt, STT: stt, STH: sth, ATT: att, SGL: sgl, SGU: sgu,
            EI: ei, KI: float(energy2k(ei)), EF: ef, KF: float(energy2k(ef))}


def _stage_to_energy(v, ctx, state):
    # None for a transmitting crystal, which selects no energy.
    ei, ef = state.nominal_energies_from_angles(v[MTT], v[ATT])
    return {EI: ei, EF: ef,
            KI: None if ei is None else float(energy2k(ei)),
            KF: None if ef is None else float(energy2k(ef)),
            DE: None if ei is None or ef is None else ei - ef}


def _crystal_theta(v, ctx, state):
    return {MTH: crystal_theta(v[MTT]), ATH: crystal_theta(v[ATT])}


def _lock_tilts(v, ctx, state):
    tilts = ctx.plane_lock["tilts"]
    return {SGL: tilts["sgl"], SGU: tilts["sgu"]}


def _autofocus(qid):
    def evaluate(v, ctx, state):
        axis = to_internal(qid)
        ideal = state.ideal_curvature(ctx.monocris, ctx.anacris, v[MTH], v[ATH],
                                      requested_axes=[axis])
        return {qid: abs(ideal[axis])}
    return evaluate


def _hardware_radius(qid):
    def evaluate(v, ctx, state):
        return {qid: ctx.curvature[qid].hardware.fixed_radius_m}
    return evaluate


def _radius_binding(v, ctx, state):
    point = copy.copy(state)
    point.mono_two_theta_deg, point.analyzer_two_theta_deg = v[MTT], v[ATT]   # the state's take-off fields: mono and analyzer 2θ
    point.set_crystal_bending(**{to_internal(qid): v[qid] for qid in ctx.curvature})
    return {f"applied_{qid}": getattr(point, to_internal(qid)) for qid in ctx.curvature}


# ---------------------------------------------------------------------- rules

def _rules(calc, ctx, scanned):
    """The rules active for this calculation, context and scanned set.

    Every activation condition is one branch here; the dependency tables are
    the physics: at fixed Kf the analyzer 2θ follows the fixed energy alone,
    the mono the transfer and the fixed energy, sample rotation and sample 2θ
    Q and the transfer, and the arcs Q alone (the solver levels the mounted Q,
    ``orientation.solve_stage``; the transfer does not move them at fixed Q).
    """
    rules = []
    q_mode = calc in (HKL_CALC, Q_CALC)
    if calc == HKL_CALC:
        rules.append(Rule("hkl_to_q", {q: HKL for q in Q}, _hkl_to_q))
    if q_mode:
        fixed = (EF, KF) if ctx.fixed_side == "Kf" else (EI, KI)
        rules.append(Rule("fixed_energy", {out: () for out in fixed}, _fixed_energy,
                          ctx.fixed_policy))
        if ctx.fixed_side == "Kf":
            energy = {ATT: (EF,), MTT: (DE, EF), EI: (DE, EF), KI: (DE, EF)}
        else:
            energy = {MTT: (EI,), ATT: (DE, EI), EF: (DE, EI), KF: (DE, EI)}
        moved = (*Q, DE, fixed[0])
        stage = {STT: moved, STH: moved, **energy}
        if ctx.plane_lock is None:
            stage.update({SGL: Q, SGU: Q})
        rules.append(Rule("q_energy_to_stage", stage, _q_energy_to_stage))
    else:
        # Direct motors: both energies from the crystals, the fixed side inactive;
        # Q is not back-calculated.
        rules.append(Rule("stage_to_energy",
                          {EI: (MTT,), KI: (MTT,), EF: (ATT,), KF: (ATT,), DE: (MTT, ATT)},
                          _stage_to_energy))
    if ctx.plane_lock is not None:
        # By design (amendment 2) a direct-motor point follows the lock's arcs and a typed
        # arc that disagrees is not refused: a future input path that admits one chooses so.
        rules.append(Rule("plane_lock", {SGL: (), SGU: ()}, _lock_tilts, "plane lock"))
    # The one producer of A1/A5; a rocking rule may replace it without renaming them.
    rules.append(Rule("crystal_theta", {MTH: (MTT,), ATH: (ATT,)}, _crystal_theta))
    for qid, policy in ctx.curvature.items():
        theta = MTH if RADIUS_CRYSTAL[qid] == MTT else ATH
        if not policy.hardware.driven:
            rules.append(Rule(f"hardware_radius:{qid}", {qid: ()}, _hardware_radius(qid),
                              "fixed"))
        elif policy.mode == CurvatureMode.AUTOFOCUS and qid not in scanned:
            # A command overrides the autofocus rule, which then does not run.
            rules.append(Rule(f"autofocus:{qid}", {qid: (theta,)}, _autofocus(qid)))
    if ctx.curvature:
        rules.append(Rule("radius_binding",
                          {f"applied_{qid}": (qid, RADIUS_CRYSTAL[qid]) for qid in ctx.curvature},
                          _radius_binding))
    return rules


def _calculation_inputs(calc, ctx):
    """The calculation's independent inputs this instrument has (rule outputs removed later)."""
    if calc == HKL_CALC:
        core = (*HKL, DE)
    elif calc == Q_CALC:
        core = (*Q, DE)
    else:
        core = (MTT, STT, STH, ATT, *(() if ctx.plane_lock is not None else ARCS))
    slits = {qid for qid in ctx.inputs if qid.startswith("slit.")}
    return frozenset(core) & ctx.inputs | frozenset(ctx.curvature) | slits


# ---------------------------------------------------------------- build_plan

def _parse(number, text, relative):
    parts = text.split()
    if len(parts) < 4:
        raise PlanRefused("Incomplete: needs 'variable start end step'", number)
    if len(parts) > 4:
        raise PlanRefused("Too many parts: use 'variable start end step'", number)
    try:
        quantity = resolve(parts[0], "scan")
    except QuantityRefused as refused:
        raise PlanRefused(str(refused), number) from None
    try:
        start, stop, step = (float(x) for x in parts[1:])
    except ValueError:
        raise PlanRefused("Invalid numbers. Check start, end, and step values.", number) from None
    error = scan_range_error(start, stop, step)
    if error:
        raise PlanRefused(error, number, quantity.id)
    return Command(number, text, quantity.id, start, stop, step, bool(relative))


def _hard_constraint(cmd, ctx):
    """Why a setting or the hardware owns what ``cmd`` drives, or None."""
    qid, name = cmd.quantity, _name(cmd.quantity)
    if qid not in ctx.inputs:
        if qid in RADIUS_CRYSTAL:   # context_from_state drops a radius whose crystal resolves to nothing
            side = "mono" if RADIUS_CRYSTAL[qid] == MTT else "analyzer"
            return (f"No {side} crystal this instrument installs is selected, "
                    f"so there is no {name} to scan.")
        return f"This instrument has no {name}."
    if qid in ARCS and ctx.plane_lock is not None:
        lock = ctx.plane_lock
        return (f"The plane lock holds {name}: "
                f"{locked_plane_text(lock['tilts'], (lock['hkl_u'], lock['hkl_v']))}. "
                "Release the lock to scan it.")
    policy = ctx.curvature.get(qid)
    if policy is not None and not policy.hardware.driven:
        radius = policy.hardware.fixed_radius_m
        at = "" if radius is None else f" at {radius:.4g} m"
        return f"The hardware holds {name}{at} ({policy.holder}), so it cannot be scanned."
    if qid.startswith("slit."):
        if ctx.engine == "deterministic":
            return f"{name} cannot be scanned here: the analytic engine has no aperture model."
        if qid not in ctx.slit_bindings:
            return f"{name} has no per-point binding on this instrument, so it cannot be scanned."
    return None


def _curvature_error(cmd, ctx, values=None):
    """The first scanned radius outside its assembly's travel, or None."""
    policy = ctx.curvature.get(cmd.quantity)
    if policy is None:
        return None
    axis = to_internal(cmd.quantity)
    if values is None:
        return curvature_scan_error(axis, cmd.start, cmd.stop, cmd.step, False, None,
                                    policy.hardware)
    return curvature_run_error(axis, values, policy.hardware)


def _closure(qid, producer):
    """(inputs, policies) a quantity's value reaches through the rules' dependencies."""
    inputs, policies, seen, stack = set(), [], set(), [qid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        rule = producer.get(current)
        if rule is None:
            if current != qid:
                inputs.add(current)
            continue
        if rule.policy and rule.policy not in policies:
            policies.append(rule.policy)
        stack.extend(rule.outputs[current])
    return inputs, policies


def _ordered(rules, producer):
    """The rules in evaluation order; a dependency cycle is a refusal naming the quantity."""
    order, state = [], {}

    def visit(rule, via):
        if state.get(rule.name) == "done":
            return
        if state.get(rule.name) == "open":
            raise PlanRefused(f"{_name(via)} depends on itself through {rule.name}; "
                              "the calculation has a cycle.", quantity=via)
        state[rule.name] = "open"
        for out, deps in rule.outputs.items():
            for dep in deps:
                if dep in producer:
                    visit(producer[dep], dep)
        state[rule.name] = "done"
        order.append(rule)

    for rule in rules:
        visit(rule, next(iter(rule.outputs)))
    return order


def _selected_calculation(scanned):
    if scanned & set(HKL):
        return HKL_CALC
    return Q_CALC if scanned & {*Q, DE} else MOTORS


def selected_calculation(commands):
    """The calculation ``commands`` (as ``build_plan`` takes them) select, or None.

    None when there is no command or one does not parse: ``build_plan`` refuses it later,
    so a caller that only wants to know whether the motors are held has nothing to do.
    """
    try:
        cmds = [_parse(number, text.strip(), relative)
                for number, (text, relative) in enumerate(commands, start=1)
                if text and text.strip()]
    except PlanRefused:
        return None
    return _selected_calculation({c.quantity for c in cmds}) if cmds else None


def build_plan(commands, context):
    """Compile two scan commands into one supported calculation, or refuse.

    ``commands`` is ``[(text, relative), (text, relative)]`` for boxes 1 and 2;
    empty text is no command. Precedence: (1) select the calculation from the
    commands, direct motors when they select none; (2) hard constraints: the
    plane lock owns the arcs, a fixed assembly its radius, a slit needs a
    binding and an engine with apertures, and ``derived_only`` quantities never
    resolve as inputs; (3) a command promotes the quantity it drives to scanned
    before any ownership check, so an overridden autofocus rule does not run;
    (4) every remaining output gets exactly one producer and no cycle, and every
    command must be a distinct independent input of the calculation.
    """
    cmds = tuple(_parse(number, text.strip(), relative)
                 for number, (text, relative) in enumerate(commands, start=1)
                 if text and text.strip())
    if len(cmds) == 2 and cmds[0].quantity == cmds[1].quantity:
        first, second = (c.text.split()[0] for c in cmds)
        raise PlanRefused(f"Both commands scan {_name(cmds[0].quantity)}, as {first!r} and as "
                          f"{second!r}; scan it once.", quantity=cmds[0].quantity, conflict=True)
    scanned = frozenset(c.quantity for c in cmds)

    # (1) The calculation; ruling 5: a scan that selects none never re-solves from HKL.
    calc = _selected_calculation(scanned)

    # (2) Hard constraints, then (3) the commands' range checks against the hardware.
    for cmd in cmds:
        reason = _hard_constraint(cmd, context) or (None if cmd.relative
                                                    else _curvature_error(cmd, context))
        if reason:
            raise PlanRefused(reason, cmd.number, cmd.quantity)

    # (4) One producer per output, no cycle, every command an independent input.
    rules = _rules(calc, context, scanned)
    producer = {}
    for rule in rules:
        for out in rule.outputs:
            if out in producer:
                raise PlanRefused(f"{_name(out)} has two producers, {producer[out].name} and "
                                  f"{rule.name}.", quantity=out)
            producer[out] = rule
    rules = _ordered(rules, producer)
    inputs = _calculation_inputs(calc, context) - producer.keys()
    label = CALCULATION_LABEL[calc]
    for cmd in cmds:
        if cmd.quantity in producer:
            reached, policies = _closure(cmd.quantity, producer)
            drivers = [_name(c.quantity) for c in cmds if c is not cmd and c.quantity in reached]
            if drivers:
                why = "calculated from " + " and ".join(drivers)
            else:
                sources = [_name(i) for i in sorted(reached)] + policies
                why = ("calculated from " if reached else "set by ") + " and ".join(sources)
            raise PlanRefused(f"{_name(cmd.quantity)} is {why} in the {label}, so it cannot "
                              "also be scanned.", cmd.number, cmd.quantity, conflict=True)
        if cmd.quantity not in inputs:
            raise PlanRefused(f"{_name(cmd.quantity)} is not read by the {label}, so it "
                              "cannot be scanned in it.", cmd.number, cmd.quantity, conflict=True)

    provenance = {}
    for qid in sorted(context.inputs | context.observables | producer.keys()):
        command = next((c for c in cmds if c.quantity == qid), None)
        if command is not None:
            provenance[qid] = Provenance(SCANNED, (command.number,), relative=command.relative)
        elif qid in producer:
            reached, policies = _closure(qid, producer)
            numbers = tuple(c.number for c in cmds if c.quantity in reached)
            provenance[qid] = Provenance(SET_PER_POINT, numbers,
                                         () if numbers else tuple(policies))
        elif qid in inputs:
            provenance[qid] = Provenance(USED_AS_TYPED)
        else:
            provenance[qid] = Provenance(NOT_READ)
    return Plan(context, calc, cmds, tuple(rules), inputs, provenance)


def point_plan(context, calculation):
    """A plan of no command for one point of ``calculation``, for a check that is no scan.

    The live reciprocal-space advisory judges a Q point; no command selects a calculation
    there, so its caller names it. Feasibility and snapshots read only the calculation and
    the context; nothing here is expanded or evaluated.
    """
    return Plan(context, calculation, (), (), frozenset())


# -------------------------------------------------------------------- expand

def _snapshot_value(snapshot, qid, refusal, command=None):
    value = snapshot.get(qid)
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value):
        raise PlanRefused(refusal, command, qid)
    return value


def _runs(plan, launch_snapshot):
    """The typed inputs and each command's run, from one snapshot: every refusal, no points."""
    typed = {}
    for qid in sorted(plan.inputs - plan.scanned):
        typed[qid] = _snapshot_value(
            launch_snapshot, qid, f"{_name(qid)} is used as typed, but the launch state holds "
                                  "no number for it.")
    values, bases = {}, {}
    for cmd in plan.commands:
        run = [float(v) for v in parse_scan_steps(cmd.text)[1]]
        if cmd.relative:
            base = _snapshot_value(
                launch_snapshot, cmd.quantity,
                f"Command {cmd.number} steps relative to {_name(cmd.quantity)}, but its field "
                "holds no number to step from.", cmd.number)
            run = [v + base for v in run]
            bases[cmd.number] = base
            error = _curvature_error(cmd, plan.context, run)
            if error:
                raise PlanRefused(error, cmd.number, cmd.quantity)
        values[cmd.number] = tuple(run)
    return typed, values, bases


def expand(plan, launch_snapshot):
    """The plan's points as named mappings, from one frozen snapshot (canonical ID -> value).

    Every input not scanned is read from the snapshot as typed, and a relative
    command's base once from its own quantity there: never from another point,
    another command's output or a later edit. A missing or non-finite value
    refuses, never reads as 0. Command 2 is the outer loop; a lone command 2
    is the only axis and keeps its number.
    """
    typed, values, bases = _runs(plan, launch_snapshot)
    axes = [(c.quantity, values[c.number]) for c in plan.commands]
    points = [dict(typed)]
    for qid, run in axes:   # each later axis is outer to the ones before it
        points = [{**point, qid: value} for value in run for point in points]
    return Expansion(tuple(points), values, bases)


def scan_axes(plan, launch_snapshot):
    """What ``expand`` refuses and each command's run, with no points: the live label's judgement.

    The point count is the product of the runs' lengths, so a preview that shows only the plan
    never builds the grid (``expand`` materialises every point).
    """
    _typed, values, bases = _runs(plan, launch_snapshot)
    return Expansion((), values, bases)


# ---------------------------------------------------------------- evaluation

def evaluate(plan, point, state):
    """Every output of the plan at one expanded point: its rules, in order, on the solvers.

    ``state`` is the scan-config state the context was built from. Raises
    ValueError for a point the stage solve refuses (``check_point`` says why first).
    """
    values = dict(point)
    for rule in plan.rules:
        produced = rule.evaluate(values, plan.context, state)
        values.update({out: produced[out] for out in rule.outputs})
    return values


def check_point(plan, point, state, axis_limits=None):
    """One expanded point through the plan's guards: today's feasibility, then the engine's.

    Today's ``check_point_feasibility`` covers Ei, Ef > 0, the scattering
    triangle, Bragg, axis limits, stage travel and the plane-lock relation;
    a transmitting crystal is recorded and runs, except on the analytic engine,
    which makes no claim there. Under a plane lock a Q point records the Q
    requested and the in-plane Q the stage realizes.
    """
    calculation = plan.calculation
    vals = {"deltaE": math.nan}   # only fills a transmitting point's record, never judged
    geom = _solve_point_geometry(copy.deepcopy(state), calculation, point, vals)
    feasible, reason = judge_point_geometry(state, geom, axis_limits)
    if not feasible:
        return PointCheck(False, reason, "physical_infeasible")
    ctx = plan.context
    locked_q = ctx.plane_lock is not None and calculation != MOTORS
    if ctx.engine != "deterministic" and not locked_q:
        return PointCheck(True)
    if ctx.engine == "deterministic" and geom["transmission"]:
        axes = tuple(geom["transmission"])
        return PointCheck(False, "direct transmission (%s): the analytic engine makes no claim"
                          % ", ".join(axes), "transmission", axes)
    if not locked_q:
        return PointCheck(True)
    requested, realized = plane_lock_q(state, geom, ctx.fixed_side)
    return PointCheck(True, requested_q=requested, realized_q=realized)


# ------------------------------------------------------------------- context

_STAGE = {"A3": STH, "sgl": SGL, "sgu": SGU}


def tas_capabilities(descriptor):
    """A TAS instrument's capabilities, derived from its descriptor.

    Inputs: HKL, Q, the transfer, the three 2θ, the goniometer's axes, the four
    requested radii and every slit gap the descriptor has. Observables: the
    crystal θ, both energies and wavevectors, the applied radii. Bindings: the
    ``ParameterSpec`` entries that name a quantity.
    """
    slits = {qid for slit in descriptor.slits for qid in slit_gap_ids(slit)}
    stage = {_STAGE[ax.name] for ax in descriptor.goniometer if ax.name in _STAGE}
    return Capabilities(
        inputs=frozenset({*HKL, *Q, DE, MTT, STT, ATT, *RADIUS_CRYSTAL, *slits, *stage}),
        observables=frozenset({MTH, ATH, EI, EF, KI, KF,
                               *(f"applied_{qid}" for qid in RADIUS_CRYSTAL)}),
        bindings={p.quantity: p for p in descriptor.scannable_parameters if p.quantity})


def context_from_state(state, vals, capabilities, engine="mcstas"):
    """The frozen context from a scan-config state (``plugin.scan_config``), its vals and
    the plugin's ``capabilities()``.

    A requested radius whose crystal is not selected is no input, and its applied
    radius no observable.
    """
    specs = dict(zip(("mono", "analyzer"), state._named_crystal_specs()))
    modes = vals.get("curvature_modes") or {}
    curvature = {}
    for qid, crystal in RADIUS_CRYSTAL.items():
        side = "mono" if crystal == MTT else "analyzer"
        spec = specs[side]
        if spec is None or qid not in capabilities.inputs:
            continue
        axis = to_internal(qid)
        hardware = state.effective_curvature_axis(axis, spec, modules=vals.get("modules"))
        if not spec.curvature.get(axis, CurvatureAxis()).driven:
            holder = f"fixed on the {spec.display_name} {side}"
        else:
            holder = hardware.provenance.rstrip(".") or "fixed by an installed module"
        curvature[qid] = AxisPolicy(CurvatureMode(modes.get(axis, CurvatureMode.HELD)),
                                    hardware, holder)
    unselected = RADIUS_CRYSTAL.keys() - curvature.keys()
    return PlanContext(
        engine=engine, fixed_side="Kf" if state.K_fixed == "Kf Fixed" else "Ki",
        fixed_energy_mev=float(state.fixed_E), monocris=state.monocris, anacris=state.anacris,
        plane_lock=state.plane_lock, curvature=curvature,
        inputs=capabilities.inputs - unselected,
        observables=capabilities.observables - {f"applied_{qid}" for qid in unselected},
        slit_bindings=capabilities.slit_bindings)
