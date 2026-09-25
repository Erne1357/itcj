"""Elegibilidad automática contra el SII (spec 2026-09-25).

- `errors`: jerarquía `SiiError` (`SiiUnavailable` reintentable, `SiiQueryError`,
  `SiiRulesError`).
- `rules`: motor declarativo (`RuleSet`, `Verdict`, `RuleResult`, `Secret`).
- `client`: conector (`OdbcSiiClient` con `pyodbc` perezoso, `FakeSiiClient`,
  `get_sii_client()`).

Las reglas reales viven fuera del repo, en `database/SII/titulatec/`; el
formato está en `itcj2/apps/titulatec/docs/sii_rules_format.md`.
"""
