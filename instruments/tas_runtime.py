"""Shared state, scan preparation, and execution for TAS instrument packages.

This module is deliberately McStasScript- and Qt-free. Instrument-specific models
subclass :class:`TAS_Instrument`; plugins delegate snapshot preparation,
feasibility checks, and point execution here.
"""
from __future__ import annotations

import copy
import math
import os
import subprocess

import numpy as np

from instruments.contract import DEFAULT_MPI_COUNT, PointSnapshot, RunExecutionState
from tavi.mcstas_config import resolve_mpi_launcher_argv
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy
from tavi.sample_mount import SampleMount
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    q_instrument_from_angles,
    solve_instrument_angles,
)

# The TAS class is a general tool for any TAS instrument
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
        self.diagnostic_mode = False
        self.diagnostic_settings = {}

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

    def set_crystal_bending(self, rhm=None, rvm=None, rha=None, rva=None):
        """Method to set rhm, rvm, rha, and rva values."""
        if rhm is not None:
            self.rhm = rhm
        if rvm is not None:
            self.rvm = rvm
        if rha is not None:
            self.rha = rha
        if rva is not None:
            self.rva = rva

    def update_diagnostic_settings(self, settings):
        """Update the diagnostic settings."""
        self.diagnostic_settings.update(settings)

    def crystal_info(self, monocris, anacris):
        """Return (monochromator_info, analyzer_info) dicts for the named crystals.

        Each instrument state resolves crystals against its own descriptor.
        """
        raise NotImplementedError("Instrument state must supply crystal_info().")

    def build_point_params(self, deltaE):
        """Return the runtime parameter dict for one instrument point."""
        raise NotImplementedError("Instrument state must supply build_point_params().")

    def e0_param_value(self, deltaE):
        """Return the runtime source-energy parameter for the current point."""
        if self.source_type == "Mono":
            if self.K_fixed == "Kf Fixed":
                return self.fixed_E + deltaE
            return self.fixed_E

        return self.fixed_E

    def point_energy_metadata(self, deltaE):
        """Return the per-point energy values recorded with the scan output."""
        if self.source_type == "Mono":
            if self.K_fixed == "Kf Fixed":
                E0_param = self.fixed_E + deltaE
                Ei = E0_param
                Ki = energy2k(Ei)
                Ef = self.fixed_E
                Kf = energy2k(Ef)
            else:
                E0_param = self.fixed_E
                Ei = self.fixed_E
                Ki = energy2k(Ei)
                Ef = self.fixed_E - deltaE
                Kf = energy2k(max(Ef, 1e-9))
        else:
            E0_param = self.fixed_E
            Ei = self.fixed_E
            Ki = energy2k(Ei)
            Ef = self.fixed_E - deltaE
            Kf = energy2k(max(Ef, 1e-9))

        return {
            "E0_param": E0_param,
            "Ei": Ei,
            "Ki": Ki,
            "Ef": Ef,
            "Kf": Kf,
        }

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
            kf = angle2k(att / 2, analyzer_info['da'])  # Compute scattered wavevector from analyzer angle
            Ef = k2energy(kf)
            deltaE = Ei - Ef
        elif K_fixed == "Kf Fixed":
            kf = energy2k(fixed_E)
            Ef = fixed_E
            ki = angle2k(mtt / 2, monochromator_info['dm'])  # Compute incident wavevector from monochromator angle
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
        deltaE = vals['deltaE']
        mtt, stt, sth, att = A1, A2, A3, A4
        saz = vals.get('chi', 0.0)

    return {
        "qx": qx, "qy": qy, "qz": qz,
        "H": H, "K": K, "L": L,
        "deltaE": deltaE,
        "mtt": mtt, "stt": stt, "sth": sth, "saz": saz, "att": att,
        "error_flags": error_flags,
    }


def check_point_feasibility(state, scan_mode, scan_point, vals):
    """Return ``(feasible: bool, reason: str | None)`` for one scan point.

    Reuses ``_solve_point_geometry`` -- the same Q/angle solve
    ``compute_scan_snapshot`` runs per point -- so a point flagged infeasible
    here is exactly a point the real scan would skip. A point is infeasible
    when ``calculate_angles`` emits any error flag (scattering triangle cannot
    close, Bragg condition unreachable, zero Q, unknown crystal). ``angle``-mode
    scans set raw instrument angles directly and are always feasible.

    ``state`` must be a solved scan-config state (it carries ``fixed_E``,
    ``K_fixed``, ``monocris``, ``anacris`` and, for rlu mode, ``sample_mount``).
    A private deep copy is used so the caller's state is never mutated.
    """
    point_state = copy.deepcopy(state)
    geom = _solve_point_geometry(point_state, scan_mode, scan_point, vals)
    error_flags = geom["error_flags"]
    if not error_flags:
        return True, None
    return False, describe_scan_error_flags(error_flags)


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

    if 'rhm' not in [variable_name1, variable_name2]:
        rhm = point_state.rhm
    if 'rvm' not in [variable_name1, variable_name2]:
        rvm = point_state.rvm
    if 'rha' not in [variable_name1, variable_name2]:
        rha = point_state.rha
    if 'rva' not in [variable_name1, variable_name2]:
        rva = point_state.rva

    point_state.omega = omega_scan
    point_state.chi = chi_scan
    point_state.kappa = kappa_scan
    point_state.psi = psi_scan
    point_state.saz = saz
    point_state.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)

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
        'omega': omega_scan,
        'chi': chi_scan,
        'psi': psi_scan,
        'kappa': kappa_scan,
    }
    metadata.update(point_state.point_energy_metadata(deltaE))

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
        result = _run_point_direct(
            execution_state,
            params_snapshot,
            output_folder,
            number_neutrons,
            mpi_count,
        )
        execution_state.last_execution_mode = "direct"
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
