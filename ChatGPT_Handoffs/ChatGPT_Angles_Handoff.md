**The physical distinction you remember is right: a conventional TAS can be described by four nominal angular settings even though the ILL convention names six angles.** The monochromator and analyzer θ angles are **coupled to their respective 2θ angles**; their numerical values change when the selected energies change.

And your suspicion about TAVI has substance. I checked [`main` at revision `4547acb69d011`](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/tree/4547acb69d0117839ba7d2b96e20fc43ab594c3d). Its main Bragg-angle calculations handle the factor of two correctly, but I found misleading terminology and a concrete inconsistency between the scan commands `omega` and `A3`. The algebra is behaving better than the labels.

One qualification before assigning historical names: **I verified the ILL/MAD six-angle convention, but could not establish a definitive Brookhaven A1–A4 numbering from the primary sources I found.** I’ll therefore distinguish the verified ILL convention from the four-angle convention TAVI actually implements, rather than quietly assuming those four numbers have a universal Brookhaven meaning.

## 1. Why six angles can reduce to four settings

At each of the three scattering centers—monochromator, sample, analyzer—you can distinguish two things:

- The **orientation of the crystal or sample**.
- The **direction of the outgoing beam relative to the incoming beam**.

That gives six angles to name. At the monochromator and analyzer, however, the nominal crystal orientation and beam deflection are linked by the reflection geometry.

### Monochromator and analyzer: θ and 2θ are coupled

For a selected crystal reflection, Bragg’s law gives

\\[ n\\lambda=2d\\sin\\theta_B. \\]

Here \\(\\theta_B\\) is the angle between the incident beam and the reflecting lattice planes. The beam turns through \\(2\\theta_B\\).

For the ideal aligned geometry, using compatible angle signs and zeros,

\\[ \\theta_M=\\frac{1}{2}(2\\theta_M), \\qquad \\theta_A=\\frac{1}{2}(2\\theta_A). \\]

Thus, specifying the monochromator take-off angle determines its nominal crystal setting, and specifying the analyzer take-off angle determines its nominal crystal setting. The ILL-compatible MAD manual explicitly describes the expected half-angle relationship and warns when the crystal setting disagrees with it. [psi.ch](http://psi.ch)

So your recollection that “you don’t need to include the monochromator and analyzer theta angles separately” is right **for a nominal, correctly aligned instrument configuration**.

The word *fixed* needs a little care, though. For first-order reflection,

\\[ k=\\frac{\\pi}{d\\sin\\theta_B}, \\qquad E=\\frac{\\hbar^2 k^2}{2m_n}. \\]

Changing the energy changes the Bragg angle. Consequently:

- In **fixed-\\(E_f\\)** operation, the analyzer pair normally stays fixed while the monochromator pair changes during an energy scan.
- In **fixed-\\(E_i\\)** operation, the monochromator pair normally stays fixed while the analyzer pair changes.

Both pairs still obey their nominal θ–2θ coupling.

### The sample rotation is a different matter

At the sample, distinguish

\\[ \\omega_S=\\text{sample turntable rotation} \\]

from

\\[ \\phi_S=2\\theta_S =\\text{angle between }\\mathbf{k}\_i\\text{ and }\\mathbf{k}\_f. \\]

The scattering angle determines the magnitude of momentum transfer through

\\[ Q^2=k_i^2+k_f^2-2k_i k_f\\cos\\phi_S. \\]

The sample rotation determines **which direction in the crystal’s reciprocal lattice is presented to that scattering vector**. It depends on the mounted crystal orientation and the requested reciprocal-space point.

Therefore, there is no general requirement that

\\[ \\omega_S=\\frac{\\phi_S}{2}. \\]

That equality can occur for particular elastic geometries and choices of angular zero, but it is not a general sample-axis constraint. The ILL ResLibCal documentation makes this distinction explicitly: its sample scattering angle A4 is generally not twice its sample rotation A3. [ifit.mccode.org](http://ifit.mccode.org)

That leaves the four nominal settings you are remembering:

\\[ \\boxed{ 2\\theta_M,\\quad \\omega_S,\\quad 2\\theta_S,\\quad 2\\theta_A } \\]

This count concerns the main scattering-plane geometry. Sample tilt arcs and other alignment adjustments add further coordinates.

### Why real instruments still benefit from six separately named axes

The exact half-angle relationship describes the ideal aligned setting. Real monochromator and analyzer crystals need alignment, rocking scans, and zero calibration.

For example, ORNL’s instrument-alignment instructions explicitly scan the monochromator crystal motor `m1` through a small angular range and then move it to the measured peak. That operation requires treating crystal orientation as something that can be adjusted independently of the nominal take-off setting. [neutron.ornl.gov](http://neutron.ornl.gov)

So the distinction is between **four coordinates sufficient for nominal instrument positioning** and **six explicitly represented crystal/beam angles useful for describing and controlling the hardware**.

## 2. The exact ILL ↔ TAVI mapping

Here is the mapping established by the ILL/MAD manual and TAVI’s current code. The entries identify physical quantities; transferring raw numerical readings also requires compatible signs and angular zeros. [psi.ch](http://psi.ch) [TAVI’s angle definitions](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/docs/INSTRUMENT_LAYOUT.md#L24-L35)


| Physical quantity                              | ILL / MAD convention | Current TAVI convention  | TAVI descriptive field                |
| ---------------------------------------------- | -------------------- | ------------------------ | ------------------------------------- |
| Monochromator crystal angle \\(\\theta\_M\\)   | **A1**               | Derived from TAVI A1 / 2 | `mtt / 2`                             |
| Monochromator take-off angle \\(2\\theta\_M\\) | **A2**               | **A1**                   | `mtt`                                 |
| Sample rotation \\(\\omega\_S\\)               | **A3**               | **A3**                   | `sth` in geometry; `omega` in GUI/API |
| Sample scattering angle \\(2\\theta\_S\\)      | **A4**               | **A2**                   | `stt`                                 |
| Analyzer crystal angle \\(\\theta\_A\\)        | **A5**               | Derived from TAVI A4 / 2 | `att / 2`                             |
| Analyzer take-off angle \\(2\\theta\_A\\)      | **A6**               | **A4**                   | `att`                                 |


The particularly easy mistakes are:

- **ILL A2 is the monochromator take-off; TAVI A2 is the sample scattering angle.**
- **ILL A4 is the sample scattering angle; TAVI A4 is the analyzer take-off.**
- **ILL A1 is a Bragg θ angle; TAVI A1 is a take-off 2θ angle.**

This is also why “remove ILL A1 and A5, then renumber what remains” would not reproduce TAVI’s scheme: TAVI keeps the sample turntable named **A3**, with sample scattering named **A2**.

The repository actually recognizes this distinction. Its descriptor documentation calls these **“TAVI angle names”**, and its sign-convention tests explicitly record:

> TAVI A1 = vTAS a2, A2 = a4, A4 = a6, A3 = a3.

[Descriptor convention](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/descriptor.py#L378-L385) · [Recorded vTAS comparison](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/tests/test_sign_conventions.py#L253-L259)

**Selecting an ILL instrument model in TAVI does not switch its numbered angle names to ILL numbering.** IN8 and IN12 still participate in the same TAVI mapping. That is a legitimate internal design choice, but it needs to be obvious to anyone transferring settings or writing scan commands.

## 3. What I found in TAVI

### A. The main θ–2θ calculation is internally consistent

The shared state defines:

```
A1 = monochromator two-theta
A2 = sample two-theta
A3 = sample turntable
A4 = analyzer two-theta
```

The forward calculation obtains the crystal Bragg angle and doubles it when constructing the take-off angle:

```
mtt = sense_mono * 2 * k2angle(ki, dm)att = sense_ana  * 2 * k2angle(kf, da)
```

The inverse calculation halves the take-off angle before applying the Bragg inversion:

```
ki = angle2k(mtt / (2 * sense_mono), dm)kf = angle2k(att / (2 * sense_ana), da)
```

[State definitions](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/tas_runtime.py#L181-L202) · [Forward calculation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/tas_runtime.py#L879-L905) · [Inverse calculation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/tas_runtime.py#L798-L821)

The McStas geometry follows the same interpretation. For example, PUMA rotates the monochromator crystal by `A1_param/2`, then the outgoing arm by the full `A1_param`. The analyzer uses the corresponding `A4_param/2` and `A4_param`. I found the same pattern in the other three instrument models. [PUMA monochromator geometry](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/puma/model.py#L313-L331) · [PUMA analyzer geometry](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/puma/model.py#L588-L608)

**I found no confirmed factor-of-two error or ILL/TAVI axis permutation in this main numerical path.**

This also establishes a modeling limitation: the two crystal θ settings are derived in these component trees. Merely displaying six ILL labels would not give TAVI independent monochromator and analyzer crystal-rocking controls; those would need their own additional adjustments.

### B. Two conversion helpers describe the wrong angle

There is a definite terminology error in `[tavi/neutron_](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/tavi/neutron_conversions.py#L20-L30)[conversions.py](http://conversions.py)`[, lines 20–30](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/tavi/neutron_conversions.py#L20-L30):

- `k2angle()` says it returns **2θ**, but evaluates\\[ \\arcsin\\!\\left(\\frac{\\pi}{kd}\\right), \\]which returns **θ**.
- `angle2k()` says it accepts **2θ**, but evaluates\\[ \\frac{\\pi}{d\\sin(\\text{angle})}, \\]which expects **θ**.

I checked the actual functions numerically with \\(E=14.7\\ \\mathrm{meV}\\) and \\(d=3.355\\ \\text{Å}\\):


| Quantity                        | Result                          |
| ------------------------------- | ------------------------------- |
| \\(k\\), using TAVI’s constants | \\(2.663442\\ \\text{Å}^{-1}\\) |
| `k2angle(k, d)`                 | \\(20.58349^\\circ\\)           |
| Full take-off angle             | \\(41.16698^\\circ\\)           |
| `angle2k(20.58349, d)`          | Returns the original \\(k\\)    |


**The safe correction is to fix the descriptions and clarify the function names. Adding a factor of two inside** `k2angle()` **would break its existing, correct callers.**

Names such as `k_to_bragg_theta_deg()` and `bragg_theta_deg_to_k()` would remove the ambiguity while preserving the old names as compatibility wrappers if needed.

There is a smaller terminology collision too: the shared runtime calls sample scattering A2 “phi,” while model parameter descriptions call sample rotation A3 “phi.” Those values are not interchanged in the inspected calculations, but the same word is being used for different quantities. [Runtime terminology](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/tas_runtime.py#L189-L192) · [Model terminology](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/puma/model.py#L209-L219)

### C. `omega` and `A3` are advertised as aliases but execute differently

**This is the most consequential finding.**

The API guide calls scan variable `omega` “sample rotation (alias of A3).” The GUI’s A3 tooltip likewise says the angle is called `omega` in the API, saved files, and scan commands. [API guide](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/docs/API_USER_GUIDE.md#L1210-L1222) · [GUI tooltip](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/gui/docks/instrument_dock.py#L60-L69)

But the scan dispatcher does this:

```
'A3': 2,'omega': SLOT_PSI,
```

`A3` writes the raw sample-turntable coordinate. `omega` writes the **ψ correction**. They also select different scan modes: `A3` selects angle mode, while `omega` selects orientation mode, which recalculates the nominal sample angle from the specified Q. [Scan-variable mapping](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/TAVI_PySide6.py#L8157-L8185) · [Mode selection](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/TAVI_PySide6.py#L5010-L5027)

TAVI then constructs the physical sample-turntable setting as

\\[ \\omega\_{\\mathrm{physical}} = A3\_{\\mathrm{readout}} +\\psi +\\text{hidden zero error}. \\]

[Physical-angle calculation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/tas_runtime.py#L294-L305)

#### A concrete example

Take a valid point whose nominal sample rotation is \\(30^\\circ\\), with ψ and the hidden zero error both zero. For **absolute** scan commands:


| Command         | Sample turntable readout | ψ correction    | Physical sample rotation |
| --------------- | ------------------------ | --------------- | ------------------------ |
| `A3 35 35 1`    | \\(35^\\circ\\)          | \\(0^\\circ\\)  | **\\(35^\\circ\\)**      |
| `omega 35 35 1` | \\(30^\\circ\\)          | \\(35^\\circ\\) | **\\(65^\\circ\\)**      |


I reproduced the differing dispatch using the existing controller methods and the actual pure sample-stage solver. The physical-angle results follow the runtime’s readout-plus-correction calculation; this was not a full McStas simulation.

That is quite a lot of motion for an “alias.”

The repository is internally contradictory here: its geometry document explicitly says that scan `omega` steps the ψ slot, while the user-facing help promises an A3 alias. So this needs a decision about the intended public behavior, rather than treating it as an isolated typo. [Geometry document’s current description](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/docs/INSTRUMENT_LAYOUT.md#L227-L232)

**For the present version, use:**

- `A3` for scans of the raw sample-turntable angle.
- `psi` for scans of the turntable correction.

An API parameter write to `omega` does refer to the raw sample-turntable field. It is the **scan variable with the same spelling** that has the different meaning. [API field handler](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/TAVI_PySide6.py#L7770-L7780)

## 4. Signs and angular zeros need their own convention

Even once the A-number mapping is correct, the numerical angles can disagree because of scattering side, sample angular zero, mounting orientation, or the definition of Q.

TAVI already treats monochromator, sample, and analyzer scattering senses separately. It also deliberately applies a sign reversal to the target mount-frame Q on its positive sample-scattering branch, documented as its vTAS/Friedel convention. The inverse conversion reverses that choice again. [Sense definition](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/instruments/descriptor.py#L34-L47) · [Orientation convention](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/tavi/orientation.py#L1-L24)

I found that choice documented and consistently handled in the paths inspected; I have not established an additional sign bug from it. But it means **matching A3 labels alone does not guarantee identical sample-angle readings between TAVI and an external instrument**.

For comparing settings or importing a UB matrix, the contract should specify:

- Which physical quantity each axis name represents.
- The positive rotation/scattering direction and viewing convention.
- The angular zero and sample mounting frame.
- The definition of Q and treatment of the two scattering branches.
- Degrees versus radians, and the angle-wrapping interval.

That is particularly relevant to the sample angle: a 90° or 180° discrepancy can arise from the chosen orientation reference or reciprocal-lattice labeling, without being a θ–2θ mistake.

## 5. The cleanup I would make

For TAVI, I would keep this focused. The current findings call for a naming and scan-contract cleanup, with the following priorities:

1. **Give** `omega` **one public meaning.** My preference is that it consistently means the raw sample-turntable angle, including scan commands, while `psi` consistently means the correction. Existing saved `omega` scans currently carry correction semantics, so that behavior needs an explicit compatibility treatment.
2. **Correct the Bragg helper descriptions immediately.** Make θ and 2θ explicit in names, documentation, and units, while retaining the current numerical behavior.
3. **Publish one authoritative mapping table.** Identify the existing A1–A4 scheme as TAVI’s convention. If an ILL numbering option is added, resolve its A1–A6 labels through an explicit mapping. Physical labels such as **Mono 2θ**, **Sample rotation ω**, **Sample 2θ**, and **Analyzer 2θ** should remain prominent.
4. **Distinguish derived readouts from independent controls.** Under an ILL display, monochromator A1 and analyzer A5 could initially be shown as derived θ values. Independent crystal-rocking behavior would be a separate model capability.
5. **Add a few targeted convention checks.** The useful cases are an absolute nonzero `omega`/`A3` comparison, a known Bragg θ–2θ value, an explicit ILL/TAVI mapping check, and a sample orientation where \\(\\omega\_S\\neq\\phi\_S/2\\). Centered relative rocking scans can conceal the current alias discrepancy.

Any public-name or geometry-contract change should also be checked against ISAR and TAS_MCP, which the repository identifies as consumers of these interfaces. [Consumer dependencies](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/4547acb69d0117839ba7d2b96e20fc43ab594c3d/AGENTS.md#L23-L32)

My inspection covered the shared geometry/runtime, the four instrument models, relevant GUI/API scan paths, and existing tests, with targeted numerical and dispatch checks. I did not run the full GUI/McStas integration here. **I would fix the** `omega`**/**`A3` **contract first, then make the naming explicit; the inspected Bragg-angle formulas should retain their current factors of two.**