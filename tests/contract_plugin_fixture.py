"""A minimal instrument plugin built only from TAVI's public author contract.

Imports only ``instruments.contract``, ``instruments.descriptor``, ``instruments.rules``
(``tas_capabilities`` and the plan's ``PlanContext``) and ``tavi.quantities``, which
``docs/INSTRUMENT_AUTHORING.md`` names as the author surface. No controller, scan-slot
or GUI code. Used by ``tests/test_author_contract.py``.
"""
from instruments.descriptor import (
    CrystalSpec,
    Geometry,
    InstrumentDescriptor,
    ParameterSpec,
    tas_goniometer,
)
from instruments.rules import PlanContext, tas_capabilities

_PG002 = CrystalSpec(id="pg002", display_name="PG[002]", d_spacing=3.355)


def fixture_descriptor() -> InstrumentDescriptor:
    return InstrumentDescriptor(
        id="contract_fixture",
        display_name="Contract fixture",
        geometry=Geometry(l1_source_mono=2.0, l2_mono_sample=2.0,
                          l3_sample_ana=1.0, l4_ana_det=1.0),
        mono_crystals=(_PG002,),
        ana_crystals=(_PG002,),
        samples=(),
        scannable_parameters=(
            ParameterSpec("mono_two_theta_param", quantity="mono_two_theta_deg"),
            ParameterSpec("sample_two_theta_param", quantity="sample_two_theta_deg"),
            ParameterSpec("sample_rotation_param", quantity="sample_rotation_deg"),
            ParameterSpec("analyzer_two_theta_param", quantity="analyzer_two_theta_deg"),
        ),
        primary_detector="detector",
        goniometer=tas_goniometer(20.0),
    )


class ContractFixturePlugin:
    id = "contract_fixture"
    display_name = "Contract fixture"
    CONTRACT_VERSION = 1

    def descriptor(self):
        return fixture_descriptor()

    def capabilities(self):
        return tas_capabilities(self.descriptor())


class WrongVersionPlugin(ContractFixturePlugin):
    CONTRACT_VERSION = 2


class UndeclaredVersionPlugin:
    id = "contract_fixture"
    display_name = "Contract fixture"


def plan_context(plugin) -> PlanContext:
    """The launch context a host builds from its frozen state, with fixed Kf at 5 meV."""
    caps = plugin.capabilities()
    return PlanContext(engine="mcstas", fixed_side="Kf", fixed_energy_mev=5.0,
                       monocris="pg002", anacris="pg002", plane_lock=None, curvature={},
                       inputs=caps.inputs, observables=caps.observables,
                       slit_bindings=caps.slit_bindings)
