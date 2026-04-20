# Slicer-Agnostic TODO

Track remaining work to make estampo properly engine-neutral now that
CuraEngine exists alongside OrcaSlicer.

## Critical — breaks CuraEngine users

- [x] **G-code parsing** (`src/estampo/gcode.py`)
  CuraEngine patterns added: `;TIME:`, `;Filament used:`, `;LAYER:`.
  Detects engine from g-code header and parses accordingly.

- [x] **Status messages say "OrcaSlicer"** (`src/estampo/adapters.py`)
  Now detects engine from config and shows "CuraEngine" or "OrcaSlicer".

- [x] **CLI help text** (`src/estampo/cli.py`)
  `--docker-version` now says "slicer Docker image version".
  `--from-3mf` now says "slicer .3mf project file".

## High — init is OrcaSlicer-only

- [x] **Wizard hardcodes engine** (`src/estampo/init.py:1074`)
  Wizard now prompts user to choose OrcaSlicer or CuraEngine.
  CuraEngine path skips OrcaSlicer-specific profile discovery.

- [x] **Version detection OrcaSlicer-only** (`src/estampo/init.py:513-591`)
  `_wizard_pick_slicer_version()` now handles both engines.
  CuraEngine prompts with `CURAENGINE_VERSION` default.

- [x] **3MF extraction OrcaSlicer-only** (`src/estampo/init.py:1326-1365`)
  Won't fix — CuraEngine doesn't produce OrcaSlicer-style project 3MFs.
  `--from-3mf` is an OrcaSlicer convenience feature (see "Won't fix").

- [x] **TOML template hardcodes orca** (`src/estampo/init.py:31`)
  Template comment now documents both engines: `"orca" or "cura"`.
  Engine value set from wizard choice.

## Medium — profile system is OrcaSlicer-only

- [x] **Profile system paths** (`src/estampo/profiles.py:25-35,166`)
  `discover_profiles("cura")` now returns empty dicts instead of raising.
  Error messages no longer suggest installing OrcaSlicer specifically.

- [x] **`profiles list` defaults to orca** (`src/estampo/cli.py:780`)
  `profiles list --engine cura` now prints a clear message that CuraEngine
  uses inline settings and has no extractable profiles.

- [x] **Profile error messages** (`src/estampo/profiles.py:198`)
  Now says "Check your Docker setup or install the slicer locally."

## Medium — local fallback won't work

- [x] **`find_slicer()` OrcaSlicer-only** (`src/estampo/slicer.py:29-71`)
  Now includes CuraEngine paths and PATH lookup names for all platforms.

- [x] **Docker fallback messages** (`src/estampo/slicer.py`)
  Error messages now reference the engine being used and the specific
  Docker image, not hardcoded "OrcaSlicer".

## Low — cosmetic but confusing

- [x] **3MF metadata** (`src/estampo/printer.py:61`)
  Changed from `OrcaSlicer` to `estampo` in Application metadata field.

- [x] **Bambu Cloud header** (`src/estampo/auth.py:17`)
  Won't fix — header is for Bambu Cloud API compatibility. Changing it
  could break authentication (see "Won't fix").

## Won't fix (by design)

- **3MF extraction from CuraEngine files**: CuraEngine doesn't produce
  OrcaSlicer-style project 3MFs. `estampo init --from-3mf` is an OrcaSlicer
  convenience feature.

- **Profile pin/list for CuraEngine**: CuraEngine has no OrcaSlicer-style
  profile chain to pin or list. Printer settings come from pinned ``.def.json``
  files; per-slice process/filament settings are passed verbatim via
  ``[slicer.cura.overrides]`` (see ADR-008). No equivalent to OrcaSlicer's
  printer/process/filament profile discovery.

- **`auth.py` BBL client name**: This header is for Bambu Cloud API
  compatibility. Changing it could break authentication. Leave as-is unless
  Bambu documents alternative values.
