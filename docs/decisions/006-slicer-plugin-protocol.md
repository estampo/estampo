# ADR-006: Slicer Plugin Protocol — Engine Modules as First-Class Peers

**Status:** Accepted — refactoring in progress  
**Date:** 2026-04  

## Context

ADR-003 established that engine-specific code must live in engine modules (`slicer.py` for OrcaSlicer, `cura.py` for CuraEngine). In practice this was only half-implemented: CuraEngine got its own module, but OrcaSlicer remained embedded in `slicer.py`, `profiles.py`, and `init.py`. This made OrcaSlicer a first-class citizen with CuraEngine bolted on.

The result:
- `profiles.py` (1,000 lines) mixes OrcaSlicer profile discovery, CuraEngine def resolution, and shared dispatch logic
- `init.py` (1,500 lines) has engine branches scattered through the wizard flow
- Adding a third slicer (PrusaSlicer, KiriMoto, etc.) would require modifying all three files

## Decision

Each slicer engine is a **self-contained Python module** (`orca.py`, `cura.py`, `prusa.py`, ...) that implements a documented protocol. Top-level modules (`profiles.py`, `init.py`, `slicer.py`) are **pure dispatch layers** — they hold no engine-specific logic, only route to the active engine module.

OrcaSlicer is refactored into `orca.py` on the same footing as `cura.py`. Neither engine is a default; the dispatch layer treats them identically.

## The Slicer Module Protocol

Every engine module MUST implement the following. No function is optional — if an engine doesn't support a capability, it raises `NotImplementedError` with a clear message.

### Constants

```python
ENGINE_NAME: str   # Human-readable: "OrcaSlicer", "CuraEngine"
ENGINE_KEY: str    # TOML key: "orca", "cura"
```

### Binary discovery

```python
def find_binary() -> Path:
    """Locate the slicer executable on this system.
    
    Raises FileNotFoundError if not found.
    """

def docker_image(version: str | None) -> str:
    """Return the Docker image tag for this engine and version.
    
    Must use the estampo/estampo:<key>-<version> format.
    Always call this — never construct tag strings manually.
    """
```

### Slicing

```python
def slice_plate(
    plate_path: Path,
    output_dir: Path,
    config: EstampoConfig,
    resolved_filaments: ResolvedFilaments,
    *,
    local: bool = False,
    docker_version: str | None = None,
) -> Path:
    """Invoke the slicer. Returns output directory path.
    
    Handles Docker + local fallback internally.
    Must not write Bambu-specific packaging — plain G-code out only.
    """
```

### Profile / definition system

```python
def discover_profiles(
    project_dir: Path,
    profiles_dir: str,
) -> dict[str, list[str]]:
    """Return available profile/definition names by category.
    
    Categories are engine-specific (OrcaSlicer: machine/process/filament;
    CuraEngine: definitions). Return {} for unsupported categories.
    """

def load_profile(
    name: str,
    category: str,
    project_dir: Path,
    profiles_dir: str,
    version: str | None = None,
) -> dict:
    """Load a profile/definition by name and category.
    
    Search order: project-local → system → bundled.
    """

def pin_profiles(
    project_dir: Path,
    profiles_dir: str,
    version: str | None = None,
) -> list[Path]:
    """Pin profiles/definitions for reproducible builds.
    
    Writes pinned files to profiles/<engine>/ and returns their paths.
    Returns [] if the engine manages definitions differently (e.g. inline settings).
    """
```

### Init wizard

```python
def wizard_steps(
    console,
    existing_config: dict,
) -> dict:
    """Run engine-specific init wizard steps.
    
    Prompts for printer, process/quality, filaments, version, etc.
    Returns a dict of engine-specific config values to be written to TOML.
    
    Must use ui.pick(), ui.prompt() — no direct input() calls.
    Must be idempotent: re-running over an existing config updates it.
    """

def emit_toml(config_values: dict) -> list[str]:
    """Emit the [slicer.<key>] TOML section lines for this engine.
    
    Called by init.py after wizard_steps(). Lines must be valid TOML.
    """
```

### Bundled data

```python
def bundled_profile_names(version: str | None = None) -> dict[str, list[str]]:
    """Return profile/definition names from bundled data files.
    
    Used by init wizard when Docker / local slicer is unavailable.
    """
```

## Module layout (target state)

```
src/estampo/
  orca.py          # OrcaSlicer — implements full protocol
  cura.py          # CuraEngine — implements full protocol
  profiles.py      # Pure dispatch: routes to orca.py / cura.py
  init.py          # Pure dispatch: wizard scaffolding + routes to engine.wizard_steps()
  slicer.py        # Pure dispatch: routes slice_plate() to engine module
  pipeline.py      # Zero engine awareness — calls slicer.slice_plate()
```

## How to add a new slicer

1. **Create `<engine>.py`** implementing every function in the protocol above
2. **Register in the dispatch table** in `slicer.py` (one-line entry)
3. **Add bundled data** under `src/estampo/data/profiles.<engine>.<version>.json` (or equivalent)
4. **Add to `SLICER_PATHS`** in `slicer.py` for binary discovery
5. **Write tests** in `tests/test_<engine>.py` — at minimum: profile discovery, slicing invocation (mocked), wizard steps

That is the complete list. No changes to `pipeline.py`, `profiles.py`, `init.py`, or `config.py` should be required for a new engine.

## Migration plan

**Step 1:** Create `orca.py` — extract all OrcaSlicer-specific logic from `slicer.py`, `profiles.py`, and `init.py` into the new module, implementing the protocol.

**Step 2:** Make `profiles.py` a pure dispatch layer — `discover_profiles(engine, ...)` calls `orca.discover_profiles(...)` or `cura.discover_profiles(...)`. Remove all engine `if/elif` branches.

**Step 3:** Make `init.py` engine-agnostic — the wizard loop calls `engine_module.wizard_steps(...)` for the engine-specific part. Remove all engine `if/elif` branches from the wizard flow.

**Step 4:** Slim `slicer.py` to a dispatch layer — `slice_plate(engine, ...)` delegates to the engine module. Remove OrcaSlicer-specific invocation code.

Each step is a separate PR with its own tests.

## Consequences

- Adding a third slicer requires creating one new file — no changes to existing top-level modules
- `orca.py` will be large initially (it's inheriting years of OrcaSlicer-specific code), but it's isolated
- The dispatch layers become small and easy to hold in context
- The protocol is the specification — if a function is missing from an engine module, the dispatch layer will raise `NotImplementedError` at runtime (or a test will catch it)

## Anti-patterns to avoid

- Do not add engine `if/elif` branches to `profiles.py`, `init.py`, or `slicer.py` — add to the engine module and call through the dispatch
- Do not import `orca` or `cura` directly from `pipeline.py` — always go through `slicer.py`
- Do not put shared utility code in an engine module — shared code belongs in `gcode.py`, `config.py`, or a new `slicers/utils.py`
- Do not make any engine module depend on another engine module
