# ADR-008: Slicer Config Passthrough — Engine-Native Config, No Abstraction Layer

**Status:** Proposed — for discussion
**Date:** 2026-04
**Supersedes:** parts of ADR-004 (the squashing-based pinning approach for CuraEngine)

## Context

The CuraEngine integration in `cura.py` (~1,400 lines) has accumulated a thick layer of code that wraps, transforms, and re-implements parts of CuraEngine's own config system:

- `_squash_cura_def` — flattens the def-inheritance chain into a single file at pin time
- `_strip_value_overrides` — strips `value` expressions from staged defs so `-s` flags work (added in #584)
- `_settings_dict` — hardcodes a baseline settings dict including `adhesion_type="none"`, `roofing_layer_count=0`, manually-computed `infill_line_distance`, etc.
- `CuraProfile` dataclass — 20+ typed attributes shadowing CuraEngine setting names
- `cura_profile_from_config` — coerces TOML overrides through type-checked dataclass attributes; mostly stringifies values
- `orca_to_cura` map — translates 8 OrcaSlicer key names to CuraEngine equivalents
- `resolve_cura_machine_dims` — re-reads the def file ourselves (CuraEngine's resolution doesn't agree with ours — see #586)
- `_place_on_bed` — assumes corner-origin bed; reimplements logic CuraEngine already has
- `_check_local_def`, `_copy_extruder_defs`, `_local_defs_path`, `_fetch_printer_def` — file-shuffling for the staged-def model

A cluster of recent bugs (#584, #586, #587, #589, #590, #592, #593, #594) all trace to the same underlying cause: **we squash CuraEngine's def chain at pin time, which discards `fdmprinter`'s schema (default values, value-expression context) that downstream resolution depends on.** The codebase then spends substantial effort re-implementing fragments of that schema in Python — incompletely, with drift, and without surfacing failures to the user.

A second problem layered on top: a half-finished **abstraction layer** (`CuraProfile` dataclass + `orca_to_cura` map) suggests cross-engine portability that doesn't exist. Only ~8 OrcaSlicer keys actually translate; everything else falls through to raw `-s` overrides. The abstraction is the worst kind: visible enough to mislead, partial enough to silently drop config.

## Decision

estampo adopts **engine-native config passthrough** for all slicer engines:

1. **Pin = verbatim copy of the def/profile chain.** No squashing. CuraEngine resolves its own inheritance.
2. **No typed wrapper dataclass for engine settings.** TOML `[slicer.<engine>.overrides]` becomes `dict[str, str|int|float|bool]` of raw engine-native setting keys.
3. **No cross-engine key mapping.** Users write CuraEngine names for cura, OrcaSlicer names for orca. Validate against the engine's authoritative schema.
4. **estampo's value-add for slicer config = pinning + version locking + dispatch.** Not config translation, not config schema modeling.

## Rationale

**The workarounds disappear.** `_squash_cura_def`, `_strip_value_overrides`, `_settings_dict` baselines, the manual `infill_line_distance`, the `resolve_cura_machine_dims` (replaced by passing `-s` from values we read once), `_place_on_bed`'s corner-origin assumption — all of these exist to compensate for losing CuraEngine's own config resolution. Restore that resolution and they go away.

**Reproducibility is preserved.** Pinning was the goal of ADR-004 — making sure a slice today produces the same gcode as a slice in six months. That goal is met just as well by:
- Copying the leaf def + every ancestor def (up to and including `fdmprinter.def.json`) into `profiles/cura/definitions/`
- Recording the slicer version in `.slicer-version`
- Letting git history of those files serve as the audit trail

…with the added benefits that (a) CuraEngine's resolution still works correctly, (b) users can `git diff` to see exactly what their printer profile is, (c) the file format matches Cura's own — readable by Cura's UI for debugging.

**Engine-native naming is honest.** ADR-006 already established that engine modules are first-class peers. Each engine has its own config language; pretending otherwise is the abstraction trap. Users porting between engines should expect to learn the target engine's config — that's true regardless of estampo and is well-documented upstream.

**Validation > magic.** Walking `fdmprinter.def.json` to build the valid-keys set, then warning on unknown keys, gives users actionable feedback (#595) without locking them out of plugin/custom settings.

## Scope

### What changes

- `pin_cura_definitions` — copies def chain verbatim, no squash
- Delete: `_squash_cura_def`, `_deep_merge_cura_overrides`, `_strip_value_overrides`, `_profile_setting_keys`
- Delete or drastically slim: `CuraProfile` dataclass (replace with `dict`), `cura_profile_from_config` (replace with raw TOML passthrough + validation), `orca_to_cura` map
- Delete: hardcoded `adhesion_type="none"`, manual `infill_line_distance` computation in `_settings_dict`
- Add: `validate_cura_settings(overrides) -> list[Warning]` driven by `fdmprinter.def.json` walk
- Simplify: `_place_on_bed` becomes optional (CuraEngine's own `mesh_position_x/y/z` and `center_object` settings handle this, configurable per-printer)
- Simplify: `_run_docker_slice` passes user overrides directly as `-s` flags

### What stays

- ADR-001 (Hamilton DAG) — unchanged
- ADR-002 (Docker + local fallback) — unchanged
- ADR-003 (multi-engine facade) — unchanged
- ADR-004 (bundled profiles) — *bundling* stays; *squashing* is removed for cura. OrcaSlicer's bundled profile-name JSON is unaffected.
- ADR-005 (vendor-agnostic split) — unchanged
- ADR-006 (slicer plugin protocol) — unchanged; this ADR clarifies what "config" means within the protocol (= engine-native dict, not typed wrapper)
- ADR-007 (command stages) — unchanged

### What this does NOT mean

- estampo does not become "just a CLI wrapper around CuraEngine." The pipeline orchestration (Hamilton DAG, command stages, multi-engine dispatch, vendor-agnostic packaging) is the real product. Slicer config was never the product.
- OrcaSlicer's process/filament/machine profile system is **not** affected. OrcaSlicer's config model is JSON-profile-based, not flat-key-based; the principle "use the engine's own resolution" applies but the implementation differs.

## Implementation plan

Three PRs, each independently shippable:

**PR 1 — Pin verbatim:** Replace `_squash_cura_def` with copy-chain. Update `pin_cura_definitions` to walk inherits and copy each def file. Update `release-readiness.yml` to commit verbatim defs. Test: pin → re-pin produces identical files; CuraEngine slice with verbatim defs produces same gcode as direct Docker slice.

**PR 2 — Remove the abstraction layer:** Replace `CuraProfile` with `dict`. Drop `orca_to_cura`. Drop `_settings_dict` hardcoded baselines and manual `infill_line_distance`. Add `validate_cura_settings()` with `fdmprinter.def.json` schema walk. Surface warnings (closes #590, #592, #594, #595). User-visible breaking change: `wall_loops` → `wall_line_count` etc.

**PR 3 — Cleanup:** Delete now-unused code: `_strip_value_overrides`, `_profile_setting_keys`, `_deep_merge_cura_overrides`, `_check_local_def` (or fold into the verbatim-copy flow), simplify `_place_on_bed` or move to a per-printer setting. Closes #586, #587, #593.

Each PR adds tests; no PR removes tests without a replacement that asserts the same behavior at a different layer.

## Consequences

### Positive

- ~600-800 lines of `cura.py` deleted
- Closes #586, #587, #589 (likely), #590, #592, #593, #594, #595 — 8 open bugs in one architectural change
- New cura issues become easier to triage: "if it's a config problem, look at CuraEngine docs, not at estampo"
- Adding a new engine (per ADR-006) becomes simpler — no temptation to recreate the abstraction layer

### Negative / breaking

- **User config breaks** for anyone using `orca_to_cura` keys in `[slicer.cura.overrides]`. Migration: rename ~7 keys. Document in CHANGELOG with a clear table.
- **Pin file count grows** — `bambox_p1s_ams.def.json` becomes 3 files (`bambox_p1s_ams.def.json`, `bambox_p1s.def.json`, `fdmprinter.def.json`) instead of 1. `fdmprinter.def.json` is large (~800KB). Mitigate: dedup `fdmprinter` so it's stored once in `src/estampo/data/`, not copied per-printer.
- **Refactor risk** — `cura.py` is touched extensively. Mitigate: golden-file tests on gcode output before/after at each PR boundary.

### Neutral

- Bundled profiles JSON (ADR-004) for OrcaSlicer is unaffected; for CuraEngine the equivalent (def-name manifest) stays.
- Docker images and tag conventions unchanged.

## Anti-patterns to avoid (after adopting)

- Do not reintroduce a typed config wrapper (`CuraProfile2`, `CuraSettings`, etc.). Engine config is `dict[str, value]`, validated.
- Do not add cross-engine key translation. If users want orca→cura migration help, write a doc page.
- Do not squash def chains "for simplicity." The chain *is* the config.
- Do not hardcode setting baselines in Python. If a default differs from `fdmprinter`, put it in a printer's def.json where users can see it.
- Do not duplicate CuraEngine's resolution logic in Python. If we need a value, pass it as `-s` from a single read of the def, or let CuraEngine compute it.
