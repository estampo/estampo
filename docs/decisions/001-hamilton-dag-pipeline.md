# ADR-001: Hamilton DAG for Pipeline Orchestration

**Status:** Accepted  
**Date:** 2026-01  

## Context

estampo needs to orchestrate a multi-stage pipeline: load parts → arrange → plate → slice → package → print. Each stage is slow and the user may want to run only part of the pipeline (e.g. just arrange and plate without slicing, or just print a previously sliced file).

Options considered:
1. **Monolithic function** — one big `run()` calling stages in sequence
2. **Manual DAG** — hand-coded dependency graph with conditional execution
3. **Hamilton** — declarative DAG framework where each node is a plain function

## Decision

Use [Hamilton](https://github.com/DAGWorks-Inc/hamilton) as the pipeline DAG framework.

## Rationale

Hamilton gives us **lazy execution by default**: nodes are only computed if their output is requested. This enables:
- `--until plate` — computes `load → arrange → plate`, stops before slicing
- `--only slice` — loads plate 3MF from disk, runs only the slicer node
- `--only print` — sends a previously sliced file without re-running anything

Each pipeline stage is a plain Python function. There is no framework-specific boilerplate inside node code. Hamilton resolves the DAG by matching function parameter names to outputs of other functions. This makes nodes independently testable.

Adapters (`adapters.py`) plug into Hamilton's lifecycle hooks to add progress spinners and timing without touching node code.

## Consequences

- **Partial execution** is a first-class feature, not a special case
- **Node inputs are explicit** — no hidden global state between stages
- Hamilton's telemetry must be disabled (done in `_build_driver()` in `cli.py`)
- Adding a new pipeline stage means adding a function with the right signature — no wiring needed
- Stage names in `STAGE_OUTPUTS` and `STAGE_REQUIRES` (pipeline.py) must stay in sync with Hamilton node names

## Anti-patterns to avoid

- Do not add side effects (file writes, network calls) to nodes that are not the designated "output" nodes
- Do not share state between nodes via module-level globals — all data flows through function parameters
- Do not add G-code logic to pipeline.py — that belongs in `gcode.py`
- Do not add slicer invocation logic to pipeline.py — that belongs in `slicer.py`
