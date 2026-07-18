# vTAS reference material (local only)

The `examples/vTAS/` folder is intentionally untracked (see `.gitignore`) and
its earlier commits were purged from this repository's history.

It contained the ILL **vTAS** virtual triple-axis application
(`vTAS.jar`, `vTAS-JNLP.dmg`, downloaded from the ILL vTAS page) together with
a locally decompiled copy of the jar (`vTAS.jar.src/`) used as a reference
while building TAVI's IN8 instrument model. The jar bundles BSD/Apache-licensed
libraries (Jama, Apache commons-math, hamcrest), but vTAS itself ships no
clear redistribution license, so neither the binaries nor the decompiled
source belong in a public repository — and at ~96 MB they also dominated the
repository size.

Everything TAVI actually derived from vTAS (IN8 senses, angle conventions,
crystal table values) is recorded with provenance in
`docs/CONFIGURABLE_INSTRUMENTS.md` §20 and
`instruments/in8/MODEL_STATUS.md`. To
recreate the local reference, download vTAS from the ILL website and decompile
the jar with any Java decompiler (CFR was used).
