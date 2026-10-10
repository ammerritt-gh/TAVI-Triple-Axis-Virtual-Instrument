"""One point solved outside a launch: its plan and its named inputs.

A launch compiles its plan from the scan commands (``rules.build_plan``); a test
that solves single points names the calculation instead, and the quantities its
commands would scan when a runtime path depends on them (``plan_for``), or gives
the commands themselves (``scan_plan``).
"""
from instruments.rules import Command, Plan, build_plan, context_from_state
from instruments.tas_runtime import ATT, DE, MTT, Q, SGL, SGU, STH, STT


def context(plugin, state, vals, engine="mcstas"):
    """The frozen plan context of a scan-config ``state`` and its ``vals``."""
    return context_from_state(state, vals, plugin.capabilities(), engine)


def plan_for(plugin, state, vals, calculation, scanned=(), engine="mcstas"):
    """A plan of ``calculation`` whose commands scan ``scanned`` (canonical IDs).

    Built without ``build_plan``'s judgment, so a test can reach a runtime
    backstop no accepted plan reaches (a scanned radius on a fixed assembly).
    """
    commands = tuple(Command(number, f"{qid} 0 0 1", qid, 0.0, 0.0, 1.0, False)
                     for number, qid in enumerate(scanned, start=1))
    return Plan(context(plugin, state, vals, engine), calculation, commands, (), frozenset())


def scan_plan(plugin, state, vals, cmd1="", cmd2="", engine="mcstas"):
    """The plan two absolute scan commands compile to."""
    return build_plan([(cmd1, False), (cmd2, False)], context(plugin, state, vals, engine))


def hkl_point(h, k, l, delta_e=0.0):
    return {"h": h, "k": k, "l": l, DE: delta_e}


def q_point(qx, qy, qz, delta_e=0.0):
    return {**dict(zip(Q, (qx, qy, qz))), DE: delta_e}


def motors_point(mtt, stt, sth, att, sgl=0.0, sgu=0.0):
    return {MTT: mtt, STT: stt, STH: sth, ATT: att, SGL: sgl, SGU: sgu}
