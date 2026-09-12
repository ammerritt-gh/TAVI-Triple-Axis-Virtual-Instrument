"""Shared state, scan preparation, and execution for TAS instrument packages.

This module is deliberately McStasScript- and Qt-free. Instrument-specific models
subclass :class:`TAS_Instrument`; plugins delegate snapshot preparation,
feasibility checks, and point execution here.
"""
from __future__ import annotations

import copy
import logging
import math
import os
import subprocess

import numpy as np

from instruments.contract import (
    DEFAULT_MPI_COUNT,
    CurvatureMode,
    PointSnapshot,
    RunExecutionState,
)
from instruments.descriptor import CurvatureAxis
from tavi.instrument_helpers import find_crystal_spec
from tavi.mcstas_config import resolve_mpi_launcher_argv
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy
from tavi.sample_mount import SampleMount
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    q_instrument_from_angles,
    solve_instrument_angles,
)

log = logging.getLogger(__name__)

# The TAS class is a general tool for any TAS instrument
def _clamp_curvature_magnitude(magnitude, min_m, max_m):
    """Clamp a curvature magnitude to its declared mechanical travel.

    An exact 0 is a deliberate FLAT sentinel -- an unbent crystal, which is
    real hardware (PUMA with a nested mirror optic fitted, or any genuinely
    flat assembly) -- and not an out-of-range radius. It is returned
    untouched, never clamped up to a mechanical minimum. The pre-slice code
    made the same exception at both of its own clamp sites:
    ``calculate_crystal_bending`` gated its clamps on the caller's factor
    being nonzero, and the GUI's Ideal button returned from its flat branch
    before reaching clamp code at all.

    Shared by the two places that clamp -- ``ideal_curvature`` producing a
    radius and ``set_crystal_bending`` applying one -- because a rule enforced
    in only one of them is exactly the class of bug this change exists to
    remove. PUMA is the case that proves it: its declared 2.0 m / 0.5 m
    monochromator minima would otherwise bend the NMO's flat monochromator
    back up on the path that does not produce the radius but merely stores it.
    """
    if magnitude == 0.0:
        return magnitude
    if min_m is not None and magnitude < min_m:
        return min_m
    if max_m is not None and magnitude > max_m:
        return max_m
    return magnitude


def curvature_command_error(axis, magnitude, curvature_axis, crystal_name=None):
    """Why an explicitly commanded curvature radius cannot be honoured, or None.

    The refuse-vs-clamp counterpart to ``_clamp_curvature_magnitude``: an
    AUTOFOCUS ideal is a suggestion nobody chose, so it keeps being clamped by
    that helper; a HELD radius or a scan-range endpoint is something a person
    or an API client explicitly asked for, so it is refused here instead of
    silently rewritten into a different instrument. ``magnitude`` is the
    signed commanded value exactly as ``set_crystal_bending`` receives it --
    this compares ``abs(magnitude)``, mirroring both that setter's fixed-axis
    pin (``abs(value) != magnitude``) and this module's own clamp.

    An exact 0 always means FLAT, which is real hardware -- a minimum radius
    constrains how tightly a bender may bend, not whether it may be straight.
    It is exempt from the driven axis's mechanical min/max for the identical
    reason ``_clamp_curvature_magnitude`` exempts it. A fixed axis has no
    such exemption: its declared radius is the only value real hardware can
    be at, 0 included, so a fixed axis whose declared radius is nonzero still
    refuses a commanded 0.
    """
    value = abs(magnitude)
    # Read by a person in a GUI dialog and by a campaign client in an API error
    # body, so it is a sentence: which axis, on what, what was asked for, and
    # what the hardware allows -- in that order, because the operator already
    # knows what they typed and needs to find the limit.
    where = f" on the {crystal_name}" if crystal_name else ""
    if not math.isfinite(magnitude):
        return f"{axis}{where}: commanded radius must be a finite number, not {magnitude!r}."
    if not curvature_axis.driven:
        fixed = curvature_axis.fixed_radius_m
        if fixed is not None and value != fixed:
            return (
                f"{axis}{where} is fixed at {fixed:.4g} m and cannot be "
                f"commanded to {value:.4g} m."
            )
        return None
    if value == 0.0:
        return None
    min_m, max_m = curvature_axis.min_radius_m, curvature_axis.max_radius_m
    if min_m is not None and value < min_m:
        return (
            f"{axis}{where}: commanded radius {value:.4g} m is tighter than "
            f"the mechanical minimum of {min_m:.4g} m."
        )
    if max_m is not None and value > max_m:
        return (
            f"{axis}{where}: commanded radius {value:.4g} m is flatter than "
            f"the mechanical maximum of {max_m:.4g} m."
        )
    return None


def curvature_scan_error(axis, start, end, step, relative, base_value,
                          curvature_axis, crystal_name=None):
    """First ``curvature_command_error`` found among every value this scan
    command would actually run, absolute or relative alike.

    Expands ``(axis, start, end, step)`` through ``parse_scan_steps`` --
    the SAME expansion ``compute_scan_snapshot`` uses at execution -- and
    checks EVERY resulting value, not just the two endpoints: an absolute
    PUMA ``"rhm 0 2 1"`` has legal endpoints (0 = flat, 2.0 = the declared
    minimum) and an illegal interior point at 1.0 m.

    For a relative command the literal numbers are offsets from the current
    radius, not the requested radii themselves; ``relative`` adds
    ``base_value`` to every expanded value before checking, so a relative
    command is judged against the real radii it will run -- exactly what
    ``set_crystal_bending`` sees at execution. ``base_value`` is ignored for
    an absolute command. A caller checking one already-resolved value (e.g.
    a single scan point) may pass ``start == end`` with any nonzero ``step``
    and ``relative=False``; the expansion then degenerates to that one
    value.

    Returns the first refusal message, or ``None`` when every value is
    within the axis's declared policy.
    """
    from tavi.utilities import parse_scan_steps

    _, values = parse_scan_steps(f"{axis} {start} {end} {step}")
    if relative:
        values = values + base_value
    for value in values:
        error = curvature_command_error(axis, float(value), curvature_axis, crystal_name)
        if error:
            return error
    return None


class TAS_Instrument:
    """The general setup of a triple-axes spectrometer (TAS) instrument, with useful functions for setting the geometries."""
    def __init__(self, L1=1.0, L2=1.0, L3=1.0, L4=1.0, A1=0, A2=0, A3=0, A4=0, saz=0, **kwargs):
        self.parameters = kwargs
        self.L1 = L1 # source-mono arm length
        self.L2 = L2 # mono-sample arm length
        self.L3 = L3 # sample-ana arm length
        self.L4 = L4 # ana-det arm length
        self.A1 = A1 # mono two-theta angle
        self.A2 = A2 # sample two-theta angle (phi)
        self.A3 = A3 # sample theta angle (psi)
        self.A4 = A4 # ana two-theta angle
        self.saz = saz # sample z-angle
        # Scattering senses (vTAS sm/ss/sa convention): the numeric sign of the
        # mono/sample/analyzer two-theta readout. Defaults are TAVI's historical
        # baked convention (locked by tests/test_sign_conventions.py); each
        # instrument subclass sets its own from its descriptor Geometry.
        self.sense_mono = 1
        self.sense_sample = -1
        self.sense_ana = 1
        # Sample orientation angles (user-controllable)
        self.omega = 0  # in-plane sample rotation (about vertical Y axis) - actual instrument angle
        self.chi = 0    # static out-of-plane sample orientation offset
        # Sample alignment offsets (user-controllable)
        self.psi = 0    # omega alignment offset (in-plane) - set during alignment
        self.kappa = 0  # chi alignment offset (out-of-plane) - set during alignment
        # Hidden misalignment angles (for training exercises)
        self.mis_omega = 0  # hidden misalignment in omega (in-plane)
        self.mis_chi = 0    # hidden misalignment in chi (out-of-plane)
        self.K_fixed = "Ki_fixed" # working in Ki- or Kf-fixed mode
        self.monocris = None # must have some monochromator crystal
        self.anacris = None # must have some analyzer crystal
        self.fixed_E = 0 # The fixed energy to work with, for the source.
        self.source_type = "Maxwellian"  # "Mono" or "Maxwellian"
        self.sample_mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90)
        # Angle mode only: (Ei, Ef) inverted from the scanned A1/A4. Set per
        # point by _solve_point_geometry on its private copy of the state, so
        # the recorded energies, the transfer and the source parameter all read
        # one source of truth instead of re-deriving it three ways.
        self._angle_energies = None
        self.diagnostic_mode = False
        self.diagnostic_settings = {}
        # Which axes ideal_curvature last clamped, for the caller that builds
        # per-point metadata. Initialised here so the attribute always exists:
        # its one reader guards with getattr, and that guard is exactly the
        # kind of implicit contract this branch spent seven commits removing.
        self._last_ideal_clamped_axes = ()

    def set_parameters(self, **kwargs):
        """Method to set general parameters."""
        for key, value in kwargs.items():
            if key in self.parameters:
                self.parameters[key] = value
            else:
                print(f"Parameter '{key}' not found.")

    def set_angles(self, A1=None, A2=None, A3=None, A4=None, omega=None, chi=None, kappa=None, psi=None):
        """Method to set A1-A4 angles and sample orientation angles."""
        if A1 is not None:
            self.A1 = A1
        if A2 is not None:
            self.A2 = A2
        if A3 is not None:
            self.A3 = A3
        if A4 is not None:
            self.A4 = A4
        if omega is not None:
            self.omega = omega
        if chi is not None:
            self.chi = chi
        if kappa is not None:
            self.kappa = kappa
        if psi is not None:
            self.psi = psi

    def set_misalignment(self, mis_omega=None, mis_chi=None):
        """Method to set hidden misalignment angles for training exercises.

        Args:
            mis_omega: In-plane misalignment angle (degrees) - corrected by psi offset
            mis_chi: Out-of-plane misalignment angle (degrees) - corrected by kappa offset
        """
        if mis_omega is not None:
            self.mis_omega = mis_omega
        if mis_chi is not None:
            self.mis_chi = mis_chi

    def get_effective_sample_angles(self):
        """Return effective sample angle OFFSETS (not including calculated A3).

        The total in-plane rotation is: A3 (calculated) + psi (offset) + mis_omega
        The total out-of-plane tilt is: chi + kappa (offset) + mis_chi

        Note: omega is NOT added here because omega IS the calculated A3 (just displayed).

        Returns:
            tuple: (effective_omega_offset, effective_chi) for backwards compatibility
        """
        # Effective in-plane OFFSET: psi offset + omega misalignment (added to calculated A3)
        effective_omega_offset = self.psi + self.mis_omega
        # Effective out-of-plane tilt: chi + kappa offset + chi misalignment
        effective_chi = self.chi + self.kappa + self.mis_chi
        return effective_omega_offset, effective_chi

    def get_sample_angle_components(self):
        """Return all individual sample angle components for clear tracking.

        This method provides explicit access to each angle component separately,
        making it easier to understand how each angle contributes to the final
        sample orientation in the instrument.

        Returns:
            dict: Dictionary containing all individual angle components:
                - 'omega': Sample rotation angle (in-plane, user-controllable)
                - 'chi': Sample tilt angle (out-of-plane, user-controllable)
                - 'psi': Omega alignment offset (in-plane, set during alignment)
                - 'kappa': Chi alignment offset (out-of-plane, set during alignment)
                - 'mis_omega': Hidden omega misalignment (in-plane, for training)
                - 'mis_chi': Hidden chi misalignment (out-of-plane, for training)
                - 'effective_omega_offset': Combined in-plane offset (psi + mis_omega)
                - 'effective_chi': Combined out-of-plane tilt (chi + kappa + mis_chi)
        """
        effective_omega_offset = self.psi + self.mis_omega
        effective_chi = self.chi + self.kappa + self.mis_chi

        return {
            'omega': self.omega,
            'chi': self.chi,
            'psi': self.psi,
            'kappa': self.kappa,
            'mis_omega': self.mis_omega,
            'mis_chi': self.mis_chi,
            'effective_omega_offset': effective_omega_offset,
            'effective_chi': effective_chi,
        }

    def _named_crystal_specs(self):
        """(mono_spec, ana_spec) CrystalSpec objects for the crystals installed
        now (``self.monocris``/``self.anacris``), or None where unresolved."""
        descriptor = self.descriptor()
        mono_spec = find_crystal_spec(descriptor.mono_crystals, self.monocris)
        ana_spec = find_crystal_spec(descriptor.ana_crystals, self.anacris)
        return mono_spec, ana_spec

    def effective_curvature_axis(self, axis, crystal_spec, modules=None):
        """Resolve what ``axis`` may do RIGHT NOW: the crystal's declaration
        folded with the current module state.

        The ONE place that answers this question. Every consumer of curvature
        policy reads it instead of the raw ``CrystalSpec.curvature`` mapping:
        ``set_crystal_bending`` (pins a fixed axis to its resolved radius),
        the scan-command validator (refuses a resolved-fixed axis as a scan
        variable), and ``ideal_curvature`` (returns the resolved radius
        instead of inventing one). A rule answered independently at two of
        those three sites -- and not the third -- is exactly the defect this
        method exists to remove (a nested mirror optic (NMO) fitted on PUMA
        used to zero ``rhm``/``rvm`` in ``PUMAPlugin.scan_config`` AND in
        ``PUMA_Instrument.optical_radii``, and a SCANNED axis went through
        neither).

        The default here returns the crystal's own declaration unmodified --
        no installed module changes any axis's policy for a general TAS
        instrument. PUMA overrides this: a fitted NMO does the
        monochromator's own horizontal/vertical focusing, so ``rhm``/``rvm``
        read as fixed at 0.0 (FLAT) for as long as it stays fitted, regardless
        of what the mounted crystal itself declares.

        ``modules`` mirrors ``optical_radii``'s override argument: ``None``
        reads live module state off ``self``; a caller with no state object
        (e.g. a frozen API request naming a module configuration the GUI does
        not currently have selected) supplies it explicitly and it wins.
        """
        if crystal_spec is None:
            return CurvatureAxis()
        return crystal_spec.curvature.get(axis, CurvatureAxis())

    def set_crystal_bending(self, rhm=None, rvm=None, rha=None, rva=None):
        """Store bending radii, enforcing curvature policy in exactly one place.

        This is the boundary BOTH paths to the instrument state cross: the
        non-scanned config path, and the *scanned* path that bypasses
        ``scan_config`` entirely (``compute_scan_snapshot`` reads radii out of
        ``scans[4:8]`` and calls this setter directly). For each supplied
        axis:

          1. a fixed axis (``CurvatureAxis.driven is False``) is pinned to its
             declared ``fixed_radius_m``, overriding whatever was supplied;
          2. a driven axis is clamped (magnitude only) to ``curvature_limits``;
          3. the result is signed onto the crystal's ACTUAL LOCAL take-off
             branch -- ``sign(sin(A1/2))`` for rhm/rvm, ``sign(sin(A4/2))``
             for rha/rva.

        The sign NEVER comes from ``sense_mono``/``sense_ana``: those declare
        the instrument's normal kinematic branch, but direct-angle mode can
        put a crystal on the opposite one (PANDA's declared A4 range spans
        both signs), and deriving the sign from the sense would defocus a
        legitimate opposite-branch point by ~7 orders of magnitude.

        Every substitution -- a fixed axis overriding a supplied value, a
        clamp, a skipped sign -- is logged; nothing is corrected silently.

        RESOLVED: the distinction this used to defer is settled upstream, at
        submission -- an explicitly commanded radius (a HELD value or a scan
        range) is refused before anything runs, via ``curvature_command_error``
        in ``TAVI_PySide6.py``'s ``build_api_launch_state`` (API),
        ``_held_curvature_issues`` (GUI), and ``_validate_single_scan_command``
        (both, for a scan range). This method's own clamp remains, deliberately,
        as the backstop for the two callers that still cannot be refused: the
        AUTOFOCUS path (nobody chose that number, so there is no command to
        refuse -- see ``ideal_curvature``) and any caller that reaches this
        setter directly without going through a submission gate.

        Two deliberate asymmetries with ``ideal_curvature``, both raised in
        review and both intentional:

        * this method reads the angles off ``self``, while ``ideal_curvature``
          takes them as arguments. They answer different questions -- "apply
          this radius at the geometry the instrument is currently in" versus
          "what would the ideal be at these angles" -- so a caller asking the
          producer about a hypothetical point must not have its answer signed
          by wherever the instrument happens to be standing.
        * the zero check is exact. ``sin(theta) == 0`` means the take-off angle
          is precisely zero, i.e. ``set_angles`` never ran, which is the only
          case with no branch to sign onto. A tolerance would wrongly capture a
          legitimately small take-off angle, whose branch is perfectly well
          defined.
        """
        supplied = {"rhm": rhm, "rvm": rvm, "rha": rha, "rva": rva}
        mono_spec, ana_spec = self._named_crystal_specs()
        crystal_by_axis = {
            "rhm": mono_spec, "rvm": mono_spec, "rha": ana_spec, "rva": ana_spec,
        }
        # The Bragg angle (already halved) each axis takes its branch sign
        # from -- rhm/rvm off the monochromator two-theta, rha/rva off the
        # analyser two-theta.
        theta_by_axis = {
            "rhm": self.A1 / 2, "rvm": self.A1 / 2,
            "rha": self.A4 / 2, "rva": self.A4 / 2,
        }

        for axis, value in supplied.items():
            if value is None:
                continue
            crystal_spec = crystal_by_axis[axis]
            if crystal_spec is None:
                # No crystal selected, so there is no declaration to enforce:
                # the axis reads as driven and unlimited and the supplied value
                # is stored as given. Production never gets here -- scan_config
                # sets monocris/anacris before compute_scan_snapshot deep-copies
                # the state -- so this is a bare-state caller (a test, or a
                # future one), and it must not pass silently.
                log.warning(
                    "set_crystal_bending: %s has no selected crystal; curvature "
                    "policy (fixed radius, mechanical travel) cannot be enforced",
                    axis,
                )
            curvature_axis = self.effective_curvature_axis(axis, crystal_spec)

            if not curvature_axis.driven:
                magnitude = curvature_axis.fixed_radius_m
                if magnitude is not None and abs(value) != magnitude:
                    log.info(
                        "set_crystal_bending: %s is fixed at %.4g m on %r; "
                        "overriding supplied %.4g m",
                        axis, magnitude, getattr(crystal_spec, "id", None), value,
                    )
                if magnitude is None:
                    magnitude = abs(value)
            else:
                magnitude = abs(value)
                min_m, max_m = self.curvature_limits(
                    axis, crystal_spec, self.A1 / 2, self.A4 / 2,
                )
                clamped = _clamp_curvature_magnitude(magnitude, min_m, max_m)
                if clamped != magnitude:
                    log.info(
                        "set_crystal_bending: %s magnitude %.4g m clamped to "
                        "%.4g m", axis, magnitude, clamped,
                    )
                magnitude = clamped

            sin_theta = math.sin(math.radians(theta_by_axis[axis]))
            if sin_theta == 0:
                # An unsolved/infeasible point -- set_angles may not have run,
                # so there is no real take-off branch to sign onto. Leave the
                # existing stored radius in place rather than multiply by
                # zero and silently emit a flat crystal.
                log.info(
                    "set_crystal_bending: %s take-off angle is exactly zero; "
                    "leaving the existing radius (%s) in place",
                    axis, getattr(self, axis, None),
                )
                continue

            signed = math.copysign(magnitude, sin_theta)
            if math.copysign(1.0, signed) != math.copysign(1.0, value):
                log.info(
                    "set_crystal_bending: %s moved from %.4g to %.4g m onto the "
                    "take-off branch", axis, value, signed,
                )
            setattr(self, axis, signed)

    def update_diagnostic_settings(self, settings):
        """Update the diagnostic settings."""
        self.diagnostic_settings.update(settings)

    def crystal_info(self, monocris, anacris):
        """Return (monochromator_info, analyzer_info) dicts for the named crystals.

        Each instrument state resolves crystals against its own descriptor.
        """
        raise NotImplementedError("Instrument state must supply crystal_info().")

    def descriptor(self):
        """Return this instrument's InstrumentDescriptor.

        The single source of truth for crystal curvature policy: crystal_info()
        and the curvature producers below both resolve crystals against it.
        """
        raise NotImplementedError("Instrument state must supply descriptor().")

    def curvature_object_distances(self, modules=None):
        """{'mono_h': (L_in, L_out), 'mono_v': ..., 'ana_h': ..., 'ana_v': ...}

        L_in is math.inf for a plane this instrument treats as parallel-beam.
        The default is the general point-source pair: object distance L1/L3,
        image distance L2/L4. An instrument whose optics split the two mono
        planes onto different object distances (PANDA) or run one plane
        parallel-beam (PUMA) overrides this.
        """
        return {
            "mono_h": (self.L1, self.L2),
            "mono_v": (self.L1, self.L2),
            "ana_h": (self.L3, self.L4),
            "ana_v": (self.L3, self.L4),
        }

    def optical_radii(self, mth, ath, modules=None):
        """UNCONSTRAINED ideal radii (magnitudes) from this instrument's focusing law.

        The default is the general point-source pair: ``RH = 2*f/sin(theta)``,
        ``RV = 2*f*sin(theta)``, with ``f = 1/(1/L_in + 1/L_out)`` -- and
        ``f = L_out`` when ``L_in`` is infinite (guarded explicitly rather
        than letting ``1/inf`` do it silently). PUMA's "parallel beam" formula
        is exactly this identity with ``L_in = inf``.

        The ONE method a future instrument overrides when its optics are not
        a point-source (L_in, L_out) pair. Knows nothing about fixedness,
        limits or branch signs -- those are shared policy above it, in
        ``ideal_curvature``.
        """
        distances = self.curvature_object_distances(modules=modules)
        thetas = {"mono_h": mth, "mono_v": mth, "ana_h": ath, "ana_v": ath}
        radii = {}
        for axis_key, (l_in, l_out) in distances.items():
            f = l_out if math.isinf(l_in) else 1.0 / (1.0 / l_in + 1.0 / l_out)
            sin_theta = math.sin(math.radians(thetas[axis_key]))
            if axis_key.endswith("_h"):
                radii[axis_key] = abs(2.0 * f / sin_theta)
            else:
                radii[axis_key] = abs(2.0 * f * sin_theta)
        return radii

    def curvature_limits(self, axis, crystal_spec, mth, ath, modules=None):
        """(min_m, max_m) for a driven axis; defaults to the declared scalars.

        Resolved through ``effective_curvature_axis`` -- the one place a
        crystal's declaration and the live module state are folded together
        -- rather than reading ``CrystalSpec.curvature`` directly, which
        would let a module or subclass override the travel elsewhere (e.g.
        an angle-dependent bender) while this seam kept answering from the
        raw, unresolved declaration.

        A seam, not machinery: a bender whose travel depends on take-off
        angle overrides ``effective_curvature_axis``. Nothing in the tree
        needs that yet.
        """
        curvature_axis = self.effective_curvature_axis(axis, crystal_spec, modules=modules)
        return curvature_axis.min_radius_m, curvature_axis.max_radius_m

    def ideal_curvature(self, monocris, anacris, mth, ath, modules=None,
                         requested_axes=None):
        """Signed ideal radii for the NAMED crystals.

        Crystals are named by the caller, never read from live state: the
        GUI's live selection and a frozen API request can name different
        ones -- the same argument ``_fixed_curvature_axes``
        (``TAVI_PySide6.py``) already makes.

        Per axis: ``effective_curvature_axis`` resolves the crystal's own
        declaration together with the current module state (e.g. PUMA's NMO);
        if the resolved policy is ``driven=False``, its ``fixed_radius_m`` is
        used, otherwise ``optical_radii``'s magnitude is clamped to
        ``curvature_limits``. Every result is then signed onto the take-off
        branch at ``mth``/``ath``.

        ``requested_axes`` is the axes the CALLER actually wants an answer
        for -- ``None`` (the default) means all four, preserving every
        existing caller's behaviour. An axis outside it is skipped entirely
        (no key in the result, no exception), which is what lets a caller
        that only cares about e.g. ``rhm`` ask for it even when a wholly
        unrelated driven axis on the same crystal has no established
        focusing model. A REQUESTED driven axis whose resolved policy says
        ``focusing_known=False`` (IN12's Heusler ``rva``) is REFUSED rather
        than given an invented radius: there is no established focusing model
        for that assembly and falling back to flat would silently run a wrong
        instrument -- but only when somebody actually asked for it; an
        unrelated axis's ignorance must not disable this one.
        """
        descriptor = self.descriptor()
        mono_spec = find_crystal_spec(descriptor.mono_crystals, monocris)
        ana_spec = find_crystal_spec(descriptor.ana_crystals, anacris)
        if mono_spec is None:
            raise ValueError(f"Unknown monochromator crystal id {monocris!r}")
        if ana_spec is None:
            raise ValueError(f"Unknown analyser crystal id {anacris!r}")

        radii = self.optical_radii(mth, ath, modules=modules)
        axis_plan = (
            ("rhm", mono_spec, "mono_h", mth),
            ("rvm", mono_spec, "mono_v", mth),
            ("rha", ana_spec, "ana_h", ath),
            ("rva", ana_spec, "ana_v", ath),
        )
        result = {}
        clamped_axes = []
        for axis, crystal_spec, radii_key, theta in axis_plan:
            if requested_axes is not None and axis not in requested_axes:
                continue
            curvature_axis = self.effective_curvature_axis(
                axis, crystal_spec, modules=modules
            )
            if not curvature_axis.driven:
                magnitude = curvature_axis.fixed_radius_m
                if magnitude is None:
                    # validate_descriptor requires fixed_radius_m iff not
                    # driven, so this is an unvalidated or hand-built spec.
                    # Say which axis and crystal, rather than letting copysign
                    # raise TypeError on None three lines further down.
                    raise ValueError(
                        f"{crystal_spec.id} declares {axis} driven=False but "
                        "carries no fixed_radius_m: there is no radius to hold "
                        "it at."
                    )
            else:
                if not curvature_axis.focusing_known:
                    raise ValueError(
                        f"{crystal_spec.id} declares {axis} "
                        "focusing_known=False: no established focusing model "
                        "to compute an ideal radius from."
                    )
                magnitude = radii[radii_key]
                min_m, max_m = self.curvature_limits(
                    axis, crystal_spec, mth, ath, modules=modules
                )
                clamped_magnitude = _clamp_curvature_magnitude(magnitude, min_m, max_m)
                if clamped_magnitude != magnitude:
                    clamped_axes.append(axis)
                magnitude = clamped_magnitude
            result[axis] = math.copysign(magnitude, math.sin(math.radians(theta)))
        # Side channel for a caller that needs to know whether the mechanical
        # travel actually bit this call (AUTOFOCUS provenance in
        # ``compute_scan_snapshot``), without changing this method's
        # axis->float return shape for its existing callers (the GUI Ideal
        # buttons, the API default-value recompute). Same pattern as
        # ``_solve_point_geometry``'s ``point_state._angle_energies``.
        self._last_ideal_clamped_axes = tuple(clamped_axes)
        return result

    def build_point_params(self, deltaE):
        """Return the runtime parameter dict for one instrument point."""
        raise NotImplementedError("Instrument state must supply build_point_params().")

    def e0_param_value(self, deltaE):
        """Return the runtime source-energy parameter for the current point.

        A "Mono" source is a narrow band the model steers onto the energy the
        monochromator will select, so in Kf-fixed mode it tracks Ei. A
        Maxwellian source is a broadband moderator whose peak is a property of
        the source, not of the scan, so it stays put. Pinning that peak to
        ``fixed_E`` is a placeholder for every instrument here (no measured
        SR-2 / H144 / H10 spectrum is modelled); in Kf-fixed mode it therefore
        peaks at Ef, and large positive transfers sample the tail.
        """
        if self.source_type != "Mono":
            return self.fixed_E

        # A Mono source is steered onto the energy the monochromator selects,
        # which IS Ei: fixed_E in Ki-fixed mode, and fixed_E + deltaE in
        # Kf-fixed mode only because Ef is then held at fixed_E. In angle mode
        # neither is held, so that arithmetic drifts -- an A4 scan would move
        # E0 while A1, and therefore the real Ei, stood still, starving the
        # beam. Take Ei from the crystals when they are the authority.
        if self._angle_energies is not None:
            return self._angle_energies[0]
        if self.K_fixed == "Kf Fixed":
            return self.fixed_E + deltaE

        return self.fixed_E

    def point_energy_metadata(self, deltaE, energies=None):
        """Return the per-point energy values recorded with the scan output.

        ``energies`` is an (Ei, Ef) pair read straight off the crystal angles.
        Angle mode supplies it, because there the user drives A1 and A4 and
        neither energy is held at ``fixed_E``; every other mode leaves it None
        and the pair follows ``K_fixed`` below.

        The nominal energies follow ``K_fixed`` alone. They are exactly the
        energies the monochromator and analyser two-theta angles encode, and
        ``calculate_angles`` derives those from ``K_fixed`` without consulting
        the source type -- so this must not consult it either. Reading the
        source type here as well used to give a fixed-Ef Maxwellian point
        angles for (Ei = Ef + dE, Ef) alongside metadata for
        (Ei = fixed_E, Ef = fixed_E - dE); a consumer reconstructing kinematics
        or resolution from the saved Ki/Kf then disagreed with the crystals,
        and a large positive transfer could even record a negative Ef for an
        otherwise valid scan. Both branches coincide at dE = 0, which is why an
        elastic smoke test cannot see it.

        ``E0_param`` is a *source-distribution* parameter, not a nominal
        energy, and is resolved separately by :meth:`e0_param_value`.
        """
        energies = energies if energies is not None else self._angle_energies
        if energies is not None:
            Ei, Ef = energies
        elif self.K_fixed == "Kf Fixed":
            Ef = self.fixed_E
            Ei = Ef + deltaE
        else:
            Ei = self.fixed_E
            Ef = Ei - deltaE

        return {
            "E0_param": self.e0_param_value(deltaE),
            "Ei": Ei,
            "Ki": energy2k(max(Ei, 1e-9)),
            "Ef": Ef,
            "Kf": energy2k(max(Ef, 1e-9)),
        }

    def nominal_energies_from_angles(self, mtt, att):
        """(Ei, Ef) as the two crystals actually select them, or None.

        In ``angle`` scan mode the user drives A1 and A4 directly, so BOTH
        energies are whatever the monochromator and analyser select -- neither
        one is held at ``fixed_E``. An A4 scan in Kf-fixed mode moves the
        analyser, so recording Ef = fixed_E across it is wrong in exactly the
        way the momentum-mode fix addresses, and an A1 scan does the same to
        Ei. The launch state's frozen ``deltaE`` does not move either.

        This is the inverse of ``calculate_angles`` and agrees with
        ``calculate_q_and_deltaE``. Returns None when the crystals cannot be
        resolved or either angle is degenerate, so a point that would error out
        is left exactly as it was.
        """
        mono_info, ana_info = self.crystal_info(self.monocris, self.anacris)
        if 'dm' not in mono_info or 'da' not in ana_info:
            return None

        # Remove the signed readout sense before inverting Bragg, as
        # calculate_q_and_deltaE does.
        ki = angle2k(mtt / (2 * self.sense_mono), mono_info['dm'])
        kf = angle2k(att / (2 * self.sense_ana), ana_info['da'])
        if ki <= 0 or kf <= 0:
            return None
        return k2energy(ki), k2energy(kf)

    def calculate_angles(self, qx, qy, qz, deltaE, fixed_E, K_fixed, monocris, anacris):
        """Sets up the mono-sample-analyzer-detector angles based on the scattering parameters"""
        error_flags = []

        # Check for zero momentum transfer early to avoid division by zero
        if qx == 0 and qy == 0 and qz == 0:
            print("\nInvalid: zero momentum transfer (qx=qy=qz=0)")
            error_flags.append("zero_q")
            return [0, 0, 0, 0, 0], error_flags

        # Retrieve mono/ana crystal information
        monochromator_info, analyzer_info = self.crystal_info(monocris, anacris)
        if 'dm' not in monochromator_info or 'da' not in analyzer_info:
            print(f"\nInvalid: unknown crystal selection (mono: {monocris}, ana: {anacris})")
            error_flags.append("invalid_crystal")
            return [0, 0, 0, 0, 0], error_flags

        # pre-calculate values from parameters
        q = math.sqrt(qx**2 + qy**2 + qz**2)

        # A transfer larger than the neutron has to give leaves a
        # non-positive energy on one side. energy2k() is np.sqrt(), so that
        # becomes NaN rather than an exception: k2angle() then returns NaN,
        # math.isinf() does not catch it, and every axis-limit comparison
        # against NaN is False -- so the point passes feasibility and the
        # scan runs with NaN motor angles. Reject it here, where both
        # fixed-energy modes and every caller of the angle solve pass.
        if K_fixed == "Kf Fixed":
            Ei_nominal, Ef_nominal = fixed_E + deltaE, fixed_E
        else:
            Ei_nominal, Ef_nominal = fixed_E, fixed_E - deltaE
        if not (Ei_nominal > 0 and Ef_nominal > 0):
            print("\nInvalid: energy transfer %s leaves Ei=%s, Ef=%s; both must be positive"
                  % (deltaE, Ei_nominal, Ef_nominal))
            error_flags.append("energy")
            return [0, 0, 0, 0, 0], error_flags

        K = energy2k(fixed_E)

        if K_fixed == "Ki Fixed":
            mtt = self.sense_mono * 2 * k2angle(K, monochromator_info['dm'])
            Ei = fixed_E
            ki = energy2k(Ei)
            Ef = Ei - deltaE
            kf = energy2k(Ef)
            att = self.sense_ana * 2 * k2angle(kf, analyzer_info['da'])
            if math.isinf(mtt):
                print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
                error_flags.append("mtt")
            if math.isinf(att):
                print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
                error_flags.append("att")
        elif K_fixed == "Kf Fixed":
            att = self.sense_ana * 2 * k2angle(K, analyzer_info['da'])
            Ef = fixed_E
            kf = energy2k(Ef)
            Ei = Ef + deltaE
            ki = energy2k(Ei)
            mtt = self.sense_mono * 2 * k2angle(ki, monochromator_info['dm'])
            if math.isinf(mtt):
                print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
                error_flags.append("mtt")
            if math.isinf(att):
                print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
                error_flags.append("att")

        try:
            sample_angles = solve_instrument_angles(
                np.array([qx, qy, qz], dtype=float), ki, kf,
                sense_sample=self.sense_sample,
            )
            stt = sample_angles.stt
        except ValueError as exc:
            print("\nSample two theta angle invalid")
            stt = 0
            error_flags.append("stt")
            sample_angles = None

        if "stt" in error_flags:
            print("\nCannot compute sample theta angle as sample two theta angle invalid")
            sth = 0
            saz = 0
        else:
            sth = sample_angles.sth
            saz = sample_angles.saz


        print(f"\nmtt: {mtt:.2f} ki: {ki:.3f} Ei: {Ei:.3f} stt: {stt:.3f} sth: {sth:.3f} saz: {saz:.3f} Q: {q:.2f} kf: {kf:.3f} Ef: {Ef:.3f} att: {att:.2f}")

        angles_array = [mtt, stt, sth, saz, att]
        return(angles_array, error_flags)

    def calculate_q_and_deltaE(self, mtt, stt, sth, saz, att, fixed_E, K_fixed, monocris, anacris):
        """Computes qx, qy, qz, and deltaE based on the given angles and fixed energy configuration"""
        error_flags = []

        # Retrieve mono/ana crystal information
        monochromator_info, analyzer_info = self.crystal_info(monocris, anacris)
        if 'dm' not in monochromator_info or 'da' not in analyzer_info:
            print(f"\nInvalid: unknown crystal selection (mono: {monocris}, ana: {anacris})")
            error_flags.append("invalid_crystal")
            return [0, 0, 0, 0], error_flags

        # Calculate incident and scattered wavevectors based on the fixed energy
        if K_fixed == "Ki Fixed":
            ki = energy2k(fixed_E)
            Ei = fixed_E
            kf = angle2k(att / (2 * self.sense_ana), analyzer_info['da'])  # Remove signed readout sense before Bragg inversion
            Ef = k2energy(kf)
            deltaE = Ei - Ef
        elif K_fixed == "Kf Fixed":
            kf = energy2k(fixed_E)
            Ef = fixed_E
            ki = angle2k(mtt / (2 * self.sense_mono), monochromator_info['dm'])  # Remove signed readout sense before Bragg inversion
            Ei = k2energy(ki)
            deltaE = Ei - Ef
        else:
            error_flags.append("K_fixed")
            print("Invalid K_fixed value")
            return [0, 0, 0, 0], error_flags

        # Compute Q in the public instrument/GUI convention:
        # qx and qy span the horizontal scattering plane; qz is vertical.
        try:
            qx, qy, qz = q_instrument_from_angles(sth, saz, stt, ki, kf)
            if self.sense_sample > 0:
                # Flipped-branch solutions align the Friedel partner -Q with
                # the beam (vTAS convention; see solve_instrument_angles), so
                # the raw inverse recovers -Q.
                qx, qy, qz = -qx, -qy, -qz
        except Exception as exc:
            error_flags.append("q")
            print(f"Invalid Q from sample angles: {exc}")
            qx = qy = qz = 0.0

        # Validate Q magnitude
        q = math.sqrt(qx**2 + qy**2 + qz**2)
        if q <= 0:
            error_flags.append("q")
            print("Invalid Q magnitude")

        # Debugging output
        print(f"\nqx: {qx:.3f}, qy: {qy:.3f}, qz: {qz:.3f}, deltaE: {deltaE:.3f}, Q: {q:.3f}")

        return [qx, qy, qz, deltaE], error_flags


_ERROR_FLAG_REASONS = {
    "zero_q": "zero momentum transfer (Q = 0)",
    "invalid_crystal": "unknown monochromator/analyzer crystal selection",
    "mtt": "monochromator angle out of range (no Bragg reflection for Ki)",
    "att": "analyzer angle out of range (no Bragg reflection for Kf)",
    "stt": "scattering triangle does not close (|Q| unreachable for Ki, Kf)",
    "sth": "sample rotation undefined (scattering triangle does not close)",
    "q": "invalid Q from sample angles",
    "K_fixed": "invalid fixed-energy mode",
    "energy": "energy transfer leaves no neutron (Ei or Ef would be <= 0)",
}


def describe_scan_error_flags(error_flags):
    """Return a short human string for a list of TAS angle error flags.

    Empty flags -> empty string. Duplicate reasons are collapsed and joined
    with ``"; "`` so the caller gets one concise limiting-constraint phrase.
    """
    if not error_flags:
        return ""
    reasons = []
    for flag in error_flags:
        reason = _ERROR_FLAG_REASONS.get(flag, "angle solve failed (%s)" % flag)
        if reason not in reasons:
            reasons.append(reason)
    return "; ".join(reasons)


def _solve_point_geometry(point_state, scan_mode, scans, vals):
    """Solve Q and the TAS angles for one scan point (shared core).

    Extracted verbatim from ``compute_scan_snapshot`` so feasibility checks
    (``check_point_feasibility``) exercise the *exact* angle math the real run
    uses. For feasible momentum/rlu/orientation points -- and always for
    ``angle`` mode -- this applies ``point_state.set_angles``; callers that only
    want the error flags pass a throwaway copy. Returns a dict with keys
    ``qx qy qz H K L deltaE mtt stt sth saz att error_flags``.
    """
    error_flags = []
    angle_energies = None   # angle mode only: (Ei, Ef) from the crystals
    qx = qy = qz = None
    H = K = L = None
    deltaE = 0.0
    mtt = stt = sth = att = saz = 0.0

    if scan_mode in ("momentum", "orientation"):
        qx, qy, qz, deltaE = scans[:4]
        angles_array, error_flags = point_state.calculate_angles(
            qx, qy, qz, deltaE, point_state.fixed_E, point_state.K_fixed,
            point_state.monocris, point_state.anacris
        )
        if not error_flags:
            mtt, stt, sth, saz, att = angles_array
            point_state.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
    elif scan_mode == "rlu":
        H, K, L, deltaE = scans[:4]
        q_component = point_state.sample_mount.hkl_to_q(H, K, L)
        qx, qy, qz = component_q_to_instrument_q(np.array(q_component, dtype=float))
        angles_array, error_flags = point_state.calculate_angles(
            qx, qy, qz, deltaE, point_state.fixed_E, point_state.K_fixed,
            point_state.monocris, point_state.anacris
        )
        if not error_flags:
            mtt, stt, sth, saz, att = angles_array
            point_state.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
    else:
        A1, A2, A3, A4 = scans[:4]
        point_state.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)
        mtt, stt, sth, att = A1, A2, A3, A4
        # The scanned angles are the authority here, not the frozen field.
        angle_energies = point_state.nominal_energies_from_angles(mtt, att)
        point_state._angle_energies = angle_energies
        deltaE = (angle_energies[0] - angle_energies[1]
                  if angle_energies else vals['deltaE'])
        saz = vals.get('chi', 0.0)

    return {
        "qx": qx, "qy": qy, "qz": qz,
        "H": H, "K": K, "L": L,
        "deltaE": deltaE,
        "mtt": mtt, "stt": stt, "sth": sth, "saz": saz, "att": att,
        "nominal_energies": angle_energies,
        "error_flags": error_flags,
    }


def check_point_feasibility(state, scan_mode, scan_point, vals, axis_limits=None):
    """Return ``(feasible: bool, reason: str | None)`` for one scan point.

    Reuses ``_solve_point_geometry`` -- the same Q/angle solve
    ``compute_scan_snapshot`` runs per point -- so a point flagged infeasible
    here is exactly a point the real scan would skip. A point is infeasible
    when ``calculate_angles`` emits any error flag (scattering triangle cannot
    close, Bragg condition unreachable, zero Q, unknown crystal), or when an
    optional axis-limit mapping excludes a solved or raw readout angle.

    ``state`` must be a solved scan-config state (it carries ``fixed_E``,
    ``K_fixed``, ``monocris``, ``anacris`` and, for rlu mode, ``sample_mount``).
    A private deep copy is used so the caller's state is never mutated.
    """
    point_state = copy.deepcopy(state)
    geom = _solve_point_geometry(point_state, scan_mode, scan_point, vals)
    error_flags = geom["error_flags"]
    if error_flags:
        return False, describe_scan_error_flags(error_flags)

    axis_fields = {"A1": "mtt", "A2": "stt", "A4": "att"}
    for axis_name, field_name in axis_fields.items():
        limits = (axis_limits or {}).get(axis_name)
        if limits is None:
            continue
        value = float(geom[field_name])
        if value < limits.lower or value > limits.upper:
            return False, (
                f"{axis_name} ({field_name}) {value:.4g}° is outside "
                f"[{limits.lower:.4g}, {limits.upper:.4g}]°"
            )
    return True, None


def compute_scan_snapshot(scan_item, scan_index, scan_mode, state, vals, data_folder,
                          is_2d_scan=False, variable_name1="", variable_name2="",
                          scan_command1="", scan_command2=""):
    """Compute the complete runtime snapshot for one scan point."""
    point_state = copy.deepcopy(state)

    if is_2d_scan:
        scans, idx_x, idx_y = scan_item
        idx_1d = -1
    else:
        scans, idx_1d = scan_item
        idx_x, idx_y = -1, -1

    if len(scans) < 11:
        raise ValueError(
            f"Scan item for scan_index {scan_index} in mode {scan_mode} has {len(scans)} values; expected at least 11."
        )

    geom = _solve_point_geometry(point_state, scan_mode, scans, vals)
    qx, qy, qz = geom["qx"], geom["qy"], geom["qz"]
    H, K, L = geom["H"], geom["K"], geom["L"]
    deltaE = geom["deltaE"]
    mtt, stt, sth, saz, att = (
        geom["mtt"], geom["stt"], geom["sth"], geom["saz"], geom["att"]
    )
    error_flags = geom["error_flags"]

    q_vector = (qx, qy, qz) if qx is not None and qy is not None and qz is not None else None

    rhm, rvm, rha, rva = scans[4], scans[5], scans[6], scans[7]
    chi_scan, kappa_scan, psi_scan = scans[8], scans[9], scans[10]

    if scan_mode == "angle":
        omega_scan = scans[2]
    elif scan_mode in ["momentum", "rlu"] and not error_flags:
        omega_scan = sth
    elif scan_mode == "orientation":
        omega_scan = sth if not error_flags else vals.get('omega', 0)
    else:
        omega_scan = 0

    # Per-axis curvature policy for THIS point (design record: curvature
    # follows the measurement). A scanned axis is decided right here, from
    # the scan variables already in hand -- the operator never declares it.
    # Everything else defaults to HELD (today's frozen-launch-state
    # behaviour) unless the launch state names it AUTOFOCUS.
    radii = {"rhm": rhm, "rvm": rvm, "rha": rha, "rva": rva}
    curvature_modes = vals.get('curvature_modes') or {}
    scanned_axes = (variable_name1, variable_name2)
    effective_modes = {}
    autofocus_axes = []
    for axis in ("rhm", "rvm", "rha", "rva"):
        if axis in scanned_axes:
            effective_modes[axis] = CurvatureMode.SCANNED
            continue
        radii[axis] = getattr(point_state, axis)
        mode = curvature_modes.get(axis, CurvatureMode.HELD)
        effective_modes[axis] = mode
        # A point whose geometry did not solve must not autofocus off stale
        # angles (mtt/att are 0.0 or a pre-error leftover here) -- leave the
        # axis alone, exactly the degenerate-angle guard set_crystal_bending
        # already applies to a supplied value.
        if mode == CurvatureMode.AUTOFOCUS and not error_flags:
            autofocus_axes.append(axis)

    curvature_clamped = []
    if autofocus_axes:
        # This point's OWN solved two-theta, halved once into theta here --
        # ideal_curvature takes theta, mtt/att are two-theta. requested_axes
        # is exactly the AUTOFOCUS set: an unrelated HELD/SCANNED axis with
        # no established focusing model (IN12's Heusler rva) must not refuse
        # an autofocus this point never asked it to compute.
        ideal = point_state.ideal_curvature(
            point_state.monocris, point_state.anacris, mtt / 2, att / 2,
            requested_axes=autofocus_axes,
        )
        clamped_this_point = set(getattr(point_state, "_last_ideal_clamped_axes", ()))
        for axis in autofocus_axes:
            radii[axis] = ideal[axis]
            if axis in clamped_this_point:
                curvature_clamped.append(axis)

    rhm, rvm, rha, rva = radii["rhm"], radii["rvm"], radii["rha"], radii["rva"]

    point_state.omega = omega_scan
    point_state.chi = chi_scan
    point_state.kappa = kappa_scan
    point_state.psi = psi_scan
    point_state.saz = saz
    point_state.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)
    # Read the APPLIED values back off the state rather than keep the
    # pre-setter locals: set_crystal_bending signs each radius onto the
    # actual take-off branch (and pins a fixed axis to its declared radius),
    # so for a scanned curvature axis the pre-setter magnitude and the
    # emitted sign can disagree. The log line and metadata below must record
    # what this point actually ran with.
    rhm, rvm, rha, rva = point_state.rhm, point_state.rvm, point_state.rha, point_state.rva

    output_folder = os.path.join(data_folder, f"scan_{scan_index:04d}")
    orientation_info = f"ω={omega_scan:.2f}, χ={chi_scan:.2f}, ψ={psi_scan:.2f}, κ={kappa_scan:.2f}"
    if scan_mode == "momentum":
        log_message = (
            f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
            f"Orientation: {orientation_info}"
        )
    elif scan_mode == "rlu":
        log_message = (
            f"Scan parameters - H: {H}, K: {K}, L: {L}, deltaE: {deltaE}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
            f"Orientation: {orientation_info}"
        )
    elif scan_mode == "orientation":
        log_message = (
            f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
            f"Orientation: {orientation_info}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}"
        )
    else:
        log_message = (
            f"Scan parameters - A1: {point_state.A1}, A2: {point_state.A2}, A3: {point_state.A3}, A4: {point_state.A4}\n"
            f"rhm: {rhm:.2f}, rvm: {rvm:.2f}, rha: {rha:.2f}, rva: {rva:.2f}\n"
            f"Orientation: {orientation_info}"
        )

    metadata = {
        'scan_mode': scan_mode,
        'scan_command1': scan_command1,
        'scan_command2': scan_command2,
        'deltaE': deltaE,
        'qx': qx if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'qy': qy if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'qz': qz if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'q_vector': q_vector if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'H': H if scan_mode == "rlu" else None,
        'K': K if scan_mode == "rlu" else None,
        'L': L if scan_mode == "rlu" else None,
        'mtt': mtt,
        'stt': stt,
        'sth': sth,
        'att': att,
        'rhm': rhm,
        'rvm': rvm,
        'rha': rha,
        'rva': rva,
        # Provenance: the policy this point actually ran each axis under, and
        # whether a mechanical limit clipped an autofocus radius -- so a
        # headless campaign client can tell "focused" from "clamped" without
        # a log line a human might never see.
        'curvature_modes': {
            axis: CurvatureMode(mode).value for axis, mode in effective_modes.items()
        },
        'curvature_clamped': curvature_clamped,
        'omega': omega_scan,
        'chi': chi_scan,
        'psi': psi_scan,
        'kappa': kappa_scan,
    }
    metadata.update(point_state.point_energy_metadata(
        deltaE, energies=geom.get("nominal_energies")))

    return PointSnapshot(
        params=None if error_flags else point_state.build_point_params(deltaE),
        output_folder=output_folder,
        scan_index=scan_index,
        deltaE=deltaE,
        error_flags=error_flags,
        metadata=metadata,
        indices={
            'idx_1d': idx_1d,
            'idx_x': idx_x,
            'idx_y': idx_y,
        },
        log_message=log_message,
    )


def _resolve_materialized_binary_path(instrument):
    """Resolve the compiled binary path from a built McStas instrument."""
    instrument_input_path = getattr(instrument, "input_path", None)
    instrument_name = getattr(instrument, "name", None)
    if instrument_input_path and instrument_name:
        return os.path.abspath(os.path.join(instrument_input_path, f"{instrument_name}.exe"))

    return None


def _run_point_direct(execution_state, params_snapshot, output_folder, number_neutrons, mpi_count):
    """Run an already-materialized instrument binary without mcrun.py."""
    # McStas --dir creates the leaf folder itself and aborts if it already
    # exists (mcuse_dir), so only ensure the parent is present.
    parent_folder = os.path.dirname(os.path.abspath(output_folder))
    os.makedirs(parent_folder, exist_ok=True)
    args = [
        *(execution_state.mpi_launcher_argv or []),
        "-np",
        str(mpi_count),
        execution_state.binary_path,
        f"--ncount={number_neutrons}",
        f"--dir={output_folder}",
    ]
    for key, value in params_snapshot.params.items():
        args.append(f"{key}={value}")

    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=execution_state.binary_cwd,
    )


def _build_execution_info(mode, output_folder, binary_path=None, returncode=None, stdout=None, error_message=None,
                          launcher_argv=None, armed_direct_run=False):
    """Build execution metadata consumed by the controller for logging and timing."""
    return {
        "mode": mode,
        "returncode": returncode,
        "stdout": stdout,
        "binary_path": binary_path,
        "output_folder": output_folder,
        "error_message": error_message,
        "launcher_argv": list(launcher_argv or []),
        "armed_direct_run": armed_direct_run,
    }


def run_tas_point(instrument, params_snapshot, output_folder, number_neutrons, execution_state, mpi_count=DEFAULT_MPI_COUNT):
    """Run one point on an already-built TAS instrument."""
    error_flag_array = list(params_snapshot.error_flags)

    if error_flag_array:
        execution_state.last_execution_mode = "skipped"
        return math.nan, error_flag_array, _build_execution_info("skipped", output_folder)

    can_run_direct = bool(
        execution_state.direct_run_ready
        and execution_state.binary_path
        and execution_state.binary_cwd
        and execution_state.mpi_launcher_argv
        and os.path.isfile(execution_state.binary_path)
    )

    if can_run_direct:
        execution_state.last_execution_mode = "direct"
        try:
            result = _run_point_direct(
                execution_state,
                params_snapshot,
                output_folder,
                number_neutrons,
                mpi_count,
            )
        except OSError as exc:
            error_flag_array.append("direct_run_failed")
            execution_info = _build_execution_info(
                "direct",
                output_folder,
                binary_path=execution_state.binary_path,
                error_message=f"Direct McStas launch failed: {exc}",
                launcher_argv=execution_state.mpi_launcher_argv,
            )
            return math.nan, error_flag_array, execution_info
        execution_info = _build_execution_info(
            "direct",
            output_folder,
            binary_path=execution_state.binary_path,
            returncode=result.returncode,
            stdout=result.stdout,
            launcher_argv=execution_state.mpi_launcher_argv,
        )
        if result.returncode != 0:
            error_flag_array.append("direct_run_failed")
            execution_info["error_message"] = (
                f"Direct McStas run failed with return code {result.returncode}."
            )
            return math.nan, error_flag_array, execution_info

        detector_path = os.path.join(output_folder, "detector.dat")
        if not os.path.exists(detector_path):
            error_flag_array.append("detector_output_missing")
            execution_info["error_message"] = (
                "Direct McStas run completed without writing detector.dat."
            )
            return math.nan, error_flag_array, execution_info

        return None, error_flag_array, execution_info

    force_compile = not execution_state.first_backengine_succeeded

    instrument.settings(
        output_path=output_folder,
        ncount=number_neutrons,
        mpi=mpi_count,
        force_compile=force_compile,
        increment_folder_name=False,
    )

    instrument.set_parameters(**params_snapshot.params)
    data = instrument.backengine()
    execution_state.last_execution_mode = "backengine"

    was_direct_run_ready = execution_state.direct_run_ready
    resolved_binary_path = _resolve_materialized_binary_path(instrument)
    execution_state.first_backengine_succeeded = True
    execution_state.binary_path = resolved_binary_path
    execution_state.binary_cwd = (
        os.path.dirname(resolved_binary_path) if resolved_binary_path else None
    )
    if not execution_state.mpi_launcher_argv:
        execution_state.mpi_launcher_argv = resolve_mpi_launcher_argv()
    execution_state.direct_run_ready = bool(
        execution_state.mpi_launcher_argv
        and resolved_binary_path
        and os.path.isfile(resolved_binary_path)
    )

    execution_info = _build_execution_info(
        "backengine",
        output_folder,
        binary_path=resolved_binary_path,
        launcher_argv=execution_state.mpi_launcher_argv,
        armed_direct_run=not was_direct_run_ready and execution_state.direct_run_ready,
    )

    if not execution_state.direct_run_ready and execution_state.first_backengine_succeeded:
        if not resolved_binary_path or not os.path.isfile(resolved_binary_path):
            execution_info["error_message"] = (
                f"Compiled instrument binary not found after backengine materialization: {resolved_binary_path}"
            )
        elif not execution_state.mpi_launcher_argv:
            execution_info["error_message"] = "MPI launcher could not be resolved for direct instrument execution."

    return data, error_flag_array, execution_info


# The run layer is instrument-agnostic: the binary path comes from the built
# instrument's input_path and name.


# alpha_2 stacked collimators: (divergence_arcmin, component_name, at_z, ymax, length).
