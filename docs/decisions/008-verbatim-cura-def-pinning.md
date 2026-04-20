# ADR-008: Verbatim CuraEngine Definition-Chain Pinning

**Status:** Accepted
**Date:** 2026-04

## Context

ADR-004 established that slicer profiles are pinned to `profiles/` for reproducible builds. For CuraEngine, the original implementation (`_squash_cura_def`) walked the `.def.json` inheritance chain (leaf → parent → ... → fdmprinter) and produced a *single* squashed file with a merged `overrides` dict.

This caused a cascade of silent-correctness bugs:

- **#587** — 30 of 47 overrides in the pinned `bambox_p1s_ams.def.json` were silently dropped by CuraEngine. Root cause: squashing merged only the `overrides` dict, not fdmprinter's `settings` schema tree, so leaf entries of the form `{"value": <literal>}` had no `default_value` to anchor them. CuraEngine logged `JSON setting 'X' has no [default_]value!` and reverted to internal defaults. Users believed they were getting printer-tuned slicing; they were getting mostly-generic fdmprinter defaults.
- **#584** — `-s adhesion_type=brim` silently lost to a pinned `{"value": "'skirt'"}`. Same mechanism, different symptom.
- **#586** — brim landed partially off the bed because `machine_disallowed_areas` was authored in center-origin coordinates but the squashed def had `machine_center_is_zero=false`.

Each bug accrued a workaround: `_normalize_value_literals` (promote literal `value` → `default_value`), `_strip_value_overrides` (delete `value` for any key we pass via `-s`), `_normalize_staging_value_literals` (re-run normalization on stale pinned defs). The workarounds compounded, each one papering over symptoms of the same root cause.

A `CuraProfile` dataclass wrapped the pinned def to mimic OrcaSlicer's three-category structure (machine/process/filament), but CuraEngine has only definitions plus per-extruder overrides — the wrapper mapped poorly and added indirection without substance.

## Decision

**Pin the CuraEngine definition chain verbatim.** Copy each `.def.json` file in the inheritance chain (leaf → parent → ... → fdmprinter) to `profiles/cura/definitions/` as-is, preserving the `inherits` link. CuraEngine resolves the chain at runtime via its `-d` search path.

Consequences of that decision:

1. **No squashing.** The `_squash_cura_def` / `_deep_merge_cura_overrides` functions are deleted.
2. **No value-literal normalization.** `fdmprinter.def.json` is in the pinned chain, so its `settings` schema anchors every leaf `value` entry. The `_normalize_value_literals` and `_normalize_staging_value_literals` workarounds are deleted.
3. **No `-s` precedence workaround.** With the inheritance chain intact, CuraEngine's `-s` flags correctly override leaf `value` expressions (verified against pinned `{"value": "'skirt'"}` — `-s adhesion_type=brim` wins). The `_strip_value_overrides` workaround is deleted.
4. **No `CuraProfile` wrapper.** `profiles.py` dispatches directly to `cura.py` functions that take a def name + overrides dict.
5. **`machine_center_is_zero` is resolved from the def chain** by a small helper (`resolve_cura_center_is_zero`), not from a squashed profile blob.

## Rationale

- **Trust CuraEngine's resolution machinery.** It already knows how to walk `inherits`, merge `settings` schema with `overrides`, and evaluate `value` expressions. Reimplementing any of that in Python produces a lossy approximation (the #587/#584 class of bugs).
- **Fewer moving parts.** The pinned output is byte-identical to the upstream def files. A diff against upstream shows exactly what the user is running.
- **Simplification propagates.** The workarounds existed to patch the squashing output; once squashing is gone, the workarounds are dead code, not load-bearing.

## Verification

Before removing `_strip_value_overrides` (PR #609), we verified experimentally that `-s adhesion_type=brim` wins over the pinned def's `{"value": "'skirt'"}`. Slicing g3d's test plate on the post-refactor branch produced:

| | brim | skirt |
|---|---:|---:|
| Layer-0 extrusion moves | 723 | 392 |
| `;TYPE:SKIRT` section span | ~445 lines | ~87 lines |
| Filament volume | 4082 mm³ | 3935 mm³ |

Confirming that the workaround's docstring — which framed the issue as a live CuraEngine behavior — was wrong. It was a squash-era artifact all along.

## Implementation

Three sequential PRs, landed April 2026:

- **PR #603** — Replace `_squash_cura_def` with `_copy_cura_def_chain`. Pinned defs are now multi-file, `inherits` preserved.
- **PR #608** — Drop the `CuraProfile` wrapper and orca-key map. `profiles.py` dispatches directly.
- **PR #609** — Delete the squash-era helpers (`_strip_value_overrides`, `_normalize_value_literals`, `_normalize_staging_value_literals`, `_profile_setting_keys`, `_deep_merge_cura_overrides`). Simplify `_place_on_bed` to take `center_is_zero: bool` from the new `resolve_cura_center_is_zero` helper.

Net code change across the three: ~600 lines removed from `cura.py` and its tests.

## Consequences

- `profiles/cura/definitions/` now contains N files per printer (one per inheritance level) instead of one. This is intentional — it is the CuraEngine-native layout.
- Users who had hand-edited a pinned squashed def must re-pin after upgrading. A breaking change, acceptable for a solo-dev beta project.
- CuraEngine stderr warnings about missing `default_value` are eliminated in normal operation. If they reappear, it signals a real gap in the inheritance chain (e.g. a parent def missing from the pinned set) rather than a squash bug — surface them loudly (see ADR where we landed stderr surfacing).

## Anti-patterns to avoid

- **Do not reintroduce squashing.** If you're tempted to "just merge these two defs for convenience," stop — that's how #587 happened.
- **Do not promote `value` to `default_value`** at pin time or slice time. The inheritance chain handles this.
- **Do not strip `value` entries** to make `-s` flags win. They already win when the chain is intact.
- **Do not wrap CuraEngine profiles to look like OrcaSlicer profiles.** The two engines have different profile models; the dispatch layer (ADR-006) handles that.
