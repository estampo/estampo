# ADR-009: Vendor Printer Defs via Python Entry Points

**Status:** Proposed — for discussion
**Date:** 2026-04
**Relates to:** ADR-005 (vendor-agnostic split), ADR-006 (slicer plugin protocol), ADR-008 (engine-native config passthrough)

## Context

Two unresolved tensions in the current code shape this ADR:

**1. The bambox_p1s defs are bundled in `cura-p1s`, not estampo — but the user experience pushes us toward putting them in estampo anyway.**

ADR-005 says estampo is printer-agnostic: no Bambu code, no P1S defs. Today the P1S printer definition (`bambox_p1s_ams.def.json`, `bambox_p1s.def.json`, `bambox_p1s_extruder_0.def.json`) lives in `cura-p1s`, a separate package. The clean separation came at a real UX cost:

- `pip install estampo` alone cannot slice for a P1S — the user has to discover and install `cura-p1s`
- The user has to know to copy defs out of `cura-p1s/data/` into their project's `profiles/cura/definitions/`
- The bundled `ultimaker2.def.json` in `src/estampo/data/` is a smoke-test artifact, not a vendor printer — but its presence has been used to justify "well, we already bundle one printer, what's one more?" (a slippery slope toward the kludge)

The honest reading: today's split is correct in spirit but the install/discovery layer was never finished. A user who follows the README ends up needing two `pip install`s, manual file copying, and often hits #586/#590-class issues because they grabbed a stale def.

**2. `cura-p1s` is two unrelated things in one package: a vendor-specific def bundle and a generic CuraEngine template resolver.**

`cura_p1s/resolver.py` (193 lines) implements CuraEngine's `{variable}` / `{expression}` / `{if/elif/else/endif}` template syntax. There is **nothing P1S-specific in it.** It is a faithful port of CuraEngine's `GcodeTemplateResolver` — code that CuraEngine the application already runs, but CuraEngine the CLI (`CuraEngine slice ...`) does not.

The resolver exists in `cura-p1s` as an accident of history: the same project that needed Bambu-specific post-processing also needed template resolution, so they got bundled. But the resolver is general infrastructure that every CuraEngine consumer needs, and putting it behind a `cura-p1s resolve` command stage (see `examples/cura-p1s/estampo.toml`) means:

- Every project using estampo+CuraEngine has to install `cura-p1s` even if their printer is not a P1S
- The `[resolve_templates]` stage in user TOML is wired to a vendor-specific binary name
- When CuraEngine eventually ships their own template resolver, our migration path is blocked by the binary-name choice

## Decision

estampo adopts a **two-part change**:

### Part A — Discover vendor defs via Python entry points

estampo defines a new entry-point group, `estampo.cura_defs`. Vendor packages (cura-p1s, hypothetical future cura-prusa, etc.) register their bundled `.def.json` directories under this group. estampo discovers them at startup and treats them as a search path for definition resolution, alongside the user's project-local `profiles/cura/definitions/`.

```toml
# cura-p1s/pyproject.toml
[project.entry-points."estampo.cura_defs"]
bambu_p1s = "cura_p1s:defs_path"
```

```python
# cura_p1s/__init__.py
from importlib.resources import files
def defs_path() -> str:
    return str(files("cura_p1s") / "data")
```

estampo's def resolver walks: project-local → entry-point providers → estampo-bundled (`fdmprinter`, `fdmextruder` only). First match wins, with a logged source.

### Part B — Lift the resolver into estampo as `cura_resolve`

The generic resolver (`cura_p1s.resolver`) moves into estampo as `src/estampo/cura_resolve.py`. The `[resolve_templates]` stage becomes an in-process post-slice hook in `cura.py` rather than a separate command-stage subprocess. The vendor-specific binary `cura-p1s resolve` is deprecated; cura-p1s drops the resolver and the CLI, becoming a thin def-bundling package.

The rename from `resolver.py` to `cura_resolve.py` is deliberate:
- `cura_resolve` namespaces it to the engine — leaves room for `orca_resolve` if OrcaSlicer ever needs analogous infrastructure
- It avoids the trap of pretending we built a generic template engine — we built a CuraEngine compatibility shim
- It signals deletion intent: when CuraEngine ships their own resolver, this module disappears

## Rationale

### Why entry points, not a hardcoded list

estampo never has to know what vendor packages exist. A future `cura-creality` package can ship its def files and register them without an estampo release. ADR-005's "printer-agnostic" promise becomes structurally enforced: estampo's source contains zero printer-specific data.

### Why this beats "just bundle everything in estampo"

Bundling all printer defs in estampo would solve the install UX (`pip install estampo` works for everyone) but reopens every problem ADR-005 closed:
- estampo becomes a Bambu/Prusa/Creality coupling
- Every printer def update needs an estampo release
- License contamination (vendor profiles often have AGPL/GPL terms that don't match estampo's MIT)
- `src/estampo/data/` grows unbounded

Entry points give us "feels like one install" UX (`pip install 'estampo[bambu]'`) without any of those costs.

### Why lift the resolver

The resolver is not vendor code. Three independent observations confirm this:

1. **Code inspection** — `cura_p1s/resolver.py` has zero references to `p1s`, `bambu`, or any printer model. It is `{var}` / `{expr}` / `{if}` parsing.
2. **Upstream parity** — CuraEngine the application already does this resolution. We are filling a gap in the CLI, not extending the engine.
3. **Plugin protocol fit** — ADR-006 says engine modules own their engine's quirks. Template resolution is a CuraEngine quirk. It belongs in `cura.py`'s neighborhood, not in a vendor package.

Keeping it in `cura-p1s` would force every non-Bambu CuraEngine user to install a Bambu-named package. That is worse than the def-bundling problem we are solving.

### Why an in-process hook, not a command stage

`[resolve_templates]` is currently a command stage that shells out to `cura-p1s resolve`. After lifting the resolver:
- The function is pure Python — no subprocess, no JSON file round-trip for settings
- Errors surface as Python exceptions with full tracebacks instead of stage-failure exit codes
- The stage no longer appears in user TOML; it runs implicitly as part of the cura slice

This crosses ADR-007's grain (which prefers external CLI command stages for tools). The justification: the resolver is *part of CuraEngine's contract* — like how `_place_on_bed` (ADR-008) is part of CuraEngine's contract. It is engine-bundled, not user-pluggable.

## Scope

### What changes

- **estampo**:
  - New: `src/estampo/cura_resolve.py` (lifted from `cura_p1s/resolver.py`, renamed)
  - New: def discovery walks `entry_points(group="estampo.cura_defs")`
  - New: ships only `fdmprinter.def.json` and `fdmextruder.def.json` (the engine schema roots, AGPL but unavoidable — no alternative)
  - Modified: `cura.py` calls `cura_resolve.resolve(...)` after slice, before pack
  - Modified: `pyproject.toml` adds `[project.optional-dependencies] bambu = ["cura-p1s>=0.2.0"]`
  - Removed: hardcoded path assumptions about where vendor defs live
  - Removed: `[resolve_templates]` from default pipeline stages list (it becomes implicit)

- **cura-p1s** (separate repo, separate release):
  - Modified: `pyproject.toml` registers `[project.entry-points."estampo.cura_defs"]`
  - Removed: `src/cura_p1s/resolver.py` (lifted to estampo)
  - Removed: `src/cura_p1s/cli.py` (the `defs` and `resolve` subcommands are no longer needed)
  - Removed: `[project.scripts] cura-p1s = ...`
  - Becomes: ~50-line package whose entire job is `data/*.def.json` + entry-point registration
  - Version bump to 0.2.0; old `cura-p1s>=0.1.x` is end-of-life

- **bambox** (separate repo): unchanged. ADR-005's "estampo never imports bambox" stays.

### What stays

- ADR-001 through ADR-007: unchanged
- ADR-005: unchanged in spirit; this ADR *strengthens* it (zero vendor data in estampo source)
- ADR-006: unchanged; engine modules still own engine quirks
- ADR-007: still applies for genuinely external tools (bambox, vendor packagers, etc.); only the resolver moves in-process
- ADR-008: this ADR is independent of ADR-008 but composes well with it (both reduce the surface area of vendor- and config-shaped kludges)

### What this does NOT mean

- estampo does not start bundling printer defs. The single counter-example is `fdmprinter.def.json` / `fdmextruder.def.json`, which are CuraEngine's own schema roots and have no vendor specificity.
- Entry-point discovery is not a generic plugin system. It is one narrow lookup for one specific resource type. Resist the temptation to add `estampo.engines`, `estampo.stages`, etc. on the same mechanism — those have different lifecycle and validation requirements.

## Implementation plan

Two PRs in estampo + one coordinated release in cura-p1s:

**PR 1 (estampo) — Lift the resolver.** Copy `cura_p1s/resolver.py` to `src/estampo/cura_resolve.py`. Add tests (port from `cura-p1s/tests/`). Wire into `cura.py` as a post-slice step. Keep the existing `[resolve_templates]` command-stage support for backward compatibility for one release — log a deprecation warning when a user still has it in their stages list. Closes the resolver duplication issue.

**PR 2 (estampo) — Entry-point discovery.** Add the def search-path walker. Add `[project.optional-dependencies] bambu`. Update docs/examples to recommend `pip install 'estampo[bambu]'`. Update `examples/cura-p1s/estampo.toml` to drop the `[resolve_templates]` stage. Add a smoke test that mocks an entry-point provider.

**cura-p1s 0.2.0 (separate repo) — Become a def-only package.** Drop resolver.py and cli.py. Add the entry-point registration. Bump version. Publish.

PRs 1 and 2 are independently mergeable; cura-p1s 0.2.0 is required before users can drop the `[resolve_templates]` stage from their TOML, but everything keeps working with cura-p1s 0.1.x via the deprecation path.

## Consequences

### Positive

- **One-command install for the common case**: `pip install 'estampo[bambu]'` produces a working slice for P1S users.
- **ADR-005 structurally enforced**: no path inside estampo's source can hold vendor defs; reviewers don't need to police it.
- **Resolver becomes a first-class part of estampo's CuraEngine contract**: tracebacks improve, no JSON round-trip, no extra subprocess in the hot path.
- **`cura-p1s` becomes maintainable by someone who knows P1S but not Python infrastructure**: ~50 lines, no CLI, no resolver.
- **Future vendors are free**: `cura-prusa`, `cura-creality`, etc. can ship without coordination with estampo.

### Negative / breaking

- **`cura-p1s` 0.1.x is end-of-life.** Anyone pinning `cura-p1s==0.1.x` and depending on `cura-p1s resolve` as a CLI keeps working in isolation but loses the def-discovery integration. Migration: upgrade cura-p1s, remove `[resolve_templates]` from `estampo.toml`.
- **Entry points add a small layer of "magic"** — first-time users may wonder where defs come from. Mitigate: `estampo doctor` (or equivalent) prints discovered providers and their paths.
- **`fdmprinter.def.json` lives in estampo** (~800KB AGPL). This is unavoidable — it is CuraEngine's schema root, not a vendor file. Document the AGPL boundary clearly in `LICENSING.md`.
- **One coordinated release** between estampo and cura-p1s. Sequence: cura-p1s 0.2.0 first, then estampo's PR 2 merges with the new dependency lower bound.

### Neutral

- Docker images unchanged (Docker bundles its own profiles; this ADR is about the local Python install path).
- ADR-007 command stages remain the right model for bambox, vendor packagers, and any future tool that *isn't* part of the engine contract.

## Anti-patterns to avoid (after adopting)

- **Do not add more printer defs to `src/estampo/data/`**. The only files that belong there are CuraEngine's own schema roots (`fdmprinter`, `fdmextruder`). If you find yourself wanting to add a printer "just for testing," put the test fixture in `tests/` instead.
- **Do not promote `estampo.cura_defs` into a generic `estampo.plugins` mechanism**. Engines, stages, and resolvers each have different lifecycle requirements. One narrow entry-point group per real need, no speculative plugin framework.
- **Do not re-bundle the resolver in vendor packages**. After this ADR, `cura_resolve` is estampo's. A vendor package re-implementing it is a code smell, not a feature.
- **Do not deprecate the entry-point search path in favor of "just symlink it" tutorials**. The whole point is that the user does not have to know where vendor defs live.
- **Do not couple `[bambu]` extras to bambox**. The `bambu` extra installs `cura-p1s` (def discovery only). Bambu printer integration (3MF packaging, firmware upload) is bambox's job and stays a command stage per ADR-007.
