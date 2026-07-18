# IN8 live vTAS cross-check

Recorded 2026-07-02 while implementing the IN8 package.

- Live vTAS readbacks established scattering senses mono +1, sample +1,
  analyser -1. The bundled repository XML showed stale/mirrored sample and
  analyser signs.
- Four elastic/inelastic and skew-Q comparison cases matched TAVI angle
  magnitudes within 0.02 degrees after applying those senses.
- A second check established the Friedel/-Q branch convention for the sample
  angle. Cubic-equivalent settings may differ by 90 degrees between displayed
  a3 values.

The numeric goldens remain executable in `tests/test_sign_conventions.py`.
This record documents provenance and interpretation rather than duplicating
the test table.
