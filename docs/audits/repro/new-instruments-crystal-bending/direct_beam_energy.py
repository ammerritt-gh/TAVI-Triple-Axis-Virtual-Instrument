"""A direct-beam point invents an (Ei, Ef) pair and drives E0 from fixed_E."""
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from instruments.in8.plugin import IN8Plugin
    from tavi.neutron_conversions import energy2k, k2angle, k2energy, angle2k

    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.source_type = "Mono"     # a Mono source is steered onto Ei
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 14.68

    # Choose A1 so the monochromator selects Ei = 20 meV -- deliberately
    # different from fixed_E, which is what makes the fallback visible.
    target_ei = 20.0
    mono_info, _ = state.crystal_info(state.monocris, state.anacris)
    mtt = 2 * state.sense_mono * k2angle(energy2k(target_ei), mono_info['dm'])
    ei_from_a1 = k2energy(angle2k(mtt / (2 * state.sense_mono), mono_info['dm']))
    print(f"A1 = {mtt:.4f} deg selects Ei = {ei_from_a1:.4f} meV "
          f"(fixed_E = {state.fixed_E})")

    vals = {"deltaE": 0.0, "chi": 0.0,
            "curvature_modes": {a: "autofocus" for a in ("rhm", "rvm", "rha", "rva")}}

    import tempfile
    out = tempfile.mkdtemp(prefix="direct-beam-")
    results = {}
    for att in (-1.0, 0.0, 1.0):
        scans = [mtt, 30.0, 0.0, att, 0, 0, 0, 0, 0, 0, 0]
        feasible, reason = plugin.check_point_feasibility(state, "angle", scans, vals)
        assert feasible, f"A4={att} was refused: {reason}"
        snap = plugin.compute_snapshot(
            (scans, 0), 0, "angle", state, vals, out, variable_name1="A4")
        assert not snap.error_flags, snap.error_flags
        md = snap.metadata
        results[att] = md
        print(f"A4={att:+}: E0_param={md['E0_param']:.4f} "
              f"Ei={md['Ei']:.4f} Ef={md['Ef']:.4f}")

    zero = results[0.0]
    # The analyser selects nothing at A4 = 0, but the point still records a
    # complete fixed-mode pair and steers the source off A1's real Ei.
    assert abs(zero["E0_param"] - ei_from_a1) < 1e-6, (
        f"the direct-beam point drives E0_param from fixed_E "
        f"({zero['E0_param']:.4f}) instead of A1's Ei ({ei_from_a1:.4f}); "
        f"its neighbours use {results[-1.0]['E0_param']:.4f} and "
        f"{results[1.0]['E0_param']:.4f}"
    )


if __name__ == "__main__":
    run(check)
