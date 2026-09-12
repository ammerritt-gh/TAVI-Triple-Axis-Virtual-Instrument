# PANDA Sources

> **Status:** live

| Snapshot | Source date/version | Captured | Used for | Status |
|---|---|---|---|---|
| [MLZ instrument page](2026-09-09__mlz-panda-page__v01.md) | live page | 2026-09-09 | crystal menu, ki/kf ranges, axis travel, energy/momentum reach, detectors, BAMBUS status | current; authoritative for published specifications |
| [Research dossier](2026-07-18__panda-research-dossier__v01.md) | 2026-07-18 | 2026-07-18 | reconciliation of every source below, plus the source hierarchy the descriptor follows | current; the descriptor's rulings come from here |
| [PANDA overview](2007-01-01__panda-overview__v01.md) | 2007; day normalized | before 2026-07-03 | general instrument and optics description | comparison |
| [Extracted table](2007-01-01__panda-table__v01.csv) | associated 2007 source | before 2026-07-03 | comparison values; the only published monochromator two-theta travel | comparison |
| [Supermirror guide paper](2013-01-01__panda-supermirror-guide__v01.md) | 2013; day normalized | before 2026-07-03 | guide and virtual-source design; the proposed elliptic mono→sample guide | comparison |
| [Historical McStas instrument](2026-07-03__vpanda-mcstas__v01.instr) | upstream version unknown | 2026-07-03 | component placement, aperture sizes, parameter naming, scattering senses | comparative; known defects recorded in `../MODEL_STATUS.md` |

The January 1 dates encode a known publication year, not a known publication
day. The McStas filename uses its repository capture date because its upstream
version date is unknown.

The research dossier was renamed from `PANDA_instrument_research.md` on
2026-09-09 to satisfy the `YYYY-MM-DD__source-id__vNN.ext` reference-naming
rule (`instruments/package_validation.py`); its date is the research date in
its own header. Contents are unchanged.

Documents the dossier cites but that are not mirrored here (network sources,
retrieved through it rather than captured): the 2015 instrument paper
(`10.17815/jlsrf-1-35`), the 2016 guide-optimization paper
(`10.1016/j.nima.2016.08.060`), the PANDA teaching notes, the 2015 BAMBUS
design paper, and the PANDA team's public McStas repository at
`forge.frm2.tum.de`. Where a descriptor field rests on one of these, the code
comment names it.
