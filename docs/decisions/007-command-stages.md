# ADR-007: Command Stages — External CLI Tools as Pipeline Stages

**Status:** Accepted  
**Date:** 2026-04  

## Context

estampo's pipeline stages are Python functions wired via Hamilton (ADR-001). This works well for built-in logic (load, arrange, plate, slice), but we now need to call external CLI tools — specifically `bambox pack` and `bambox repack` — as pipeline stages.

bambox is a separate package with Rust FFI components. Importing it as a Python library would couple estampo to bambox's package version, Rust build toolchain, and internal API. The natural boundary is the CLI: bambox exposes `bambox pack`, `bambox repack`, etc. as stable commands.

Options considered:
1. **Python import** — `from bambox import pack; pack(...)`. Tight coupling, version pinning headaches, Rust FFI transitive dependency.
2. **Hardcoded subprocess calls** — like `orca.py` does today for OrcaSlicer. Works, but every new tool needs new Python code.
3. **Generic command stages in TOML** — any stage can declare a `command` that runs as a subprocess. No Python code needed per tool.

## Decision

Allow pipeline stages to be implemented as CLI commands defined in the project TOML. If a stage name has a corresponding TOML section with a `command` key, the pipeline runs it as a subprocess instead of looking for a Hamilton node.

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack", "print"]

[pack]
command = "bambox pack {sliced_3mf} -m {machine} -o {output_dir}"
output = "{output_dir}/{name}.3mf"
```

## Variable Substitution

Command strings use Python `str.format_map()` with a flat context dict. Variables are enclosed in `{braces}`.

A `COMMAND_VARIABLES` dict in the source code is the single source of truth for available variable names and their descriptions. This dict serves three purposes:

1. **Runtime** — `_command_context()` builds the substitution dict using exactly these keys
2. **Documentation** — a build step generates `docs/command-variables.md` from the dict
3. **Drift detection** — a test asserts `set(context.keys()) == set(COMMAND_VARIABLES.keys())`

Missing variables raise `KeyError` immediately — fail loud, no silent empty strings.

### Why `format_map` over Jinja2

The command templates are one-line shell commands, not pages. `format_map` is stdlib, zero dependencies, and uses `{var}` syntax that reads naturally in CLI context. If conditionals or filters are ever needed, Jinja2 uses compatible `{}` delimiters so migration is non-breaking.

### Why a flat namespace

Nested access (`{config.slicer.orca.printer}`) adds complexity for no current benefit. A flat dict of 5-10 well-named variables is easier to document, type, and test. The indirection layer (`COMMAND_VARIABLES` maps stable names to internal node outputs) means Hamilton nodes can be renamed without breaking user configs.

## Execution Model

1. The pipeline resolves stages in order from `[pipeline] stages`
2. For each stage, check if the TOML has a section with a `command` key
3. If yes: build context from prior stage outputs → `format_map` → `subprocess.run()` with `ui.status()` wrapper → capture output path from `output` field
4. If no: fall through to the Hamilton node as before
5. A command stage's output feeds into the context for downstream stages

Error handling follows existing patterns: non-zero exit code raises `RuntimeError` with truncated stderr.

## Consequences

- External tools (bambox, mesh repair, post-processors) can be wired into the pipeline without Python code
- Users can insert custom stages anywhere in the pipeline sequence
- The variable contract is enforced by tests and documented from code — no manual sync
- Command stages are not Hamilton nodes — they don't participate in Hamilton's dependency resolution or adapter hooks (progress, timing). They run in sequence at the position declared in `stages`.
- Shell injection is a risk since commands are built from string substitution. All context values are derived from config and prior stage outputs (paths, project name) — not from user-controlled free text. Document this boundary.

## Anti-patterns to avoid

- Do not put engine-specific logic in command stages — if it needs profile resolution, Docker fallback, or version pinning, it belongs in a dedicated module (`orca.py`, `cura.py`)
- Do not use command stages for built-in pipeline logic that benefits from Hamilton's dependency graph
- Do not add variables to the context without updating `COMMAND_VARIABLES` — the test will catch this, but treat the dict as the design contract, not just a test fixture
