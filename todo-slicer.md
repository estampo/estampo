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

- [ ] **3MF extraction OrcaSlicer-only** (`src/estampo/init.py:1326-1365`)
  Reads `Metadata/project_settings.config` (OrcaSlicer format).
  Error message: "open it in OrcaSlicer and re-save".
  CuraEngine 3MFs have different internal structure.

- [x] **TOML template hardcodes orca** (`src/estampo/init.py:31`)
  Template comment now documents both engines: `"orca" or "cura"`.
  Engine value set from wizard choice.

## Medium — profile system is OrcaSlicer-only

- [ ] **Profile system paths** (`src/estampo/profiles.py:25-35,166`)
  System directories (macOS/Windows/Linux) and Docker path
  (`/opt/orca-slicer/resources/profiles/BBL`) only defined for OrcaSlicer.
  CuraEngine uses inline `CuraProfile` defaults — no equivalent profile
  discovery needed today, but error messages should not suggest installing
  OrcaSlicer.

- [ ] **`profiles list` defaults to orca** (`src/estampo/cli.py:780`)
  Should be engine-aware or require explicit engine flag.

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

- [ ] **Bambu Cloud header** (`src/estampo/auth.py:17`)
  `"X-BBL-Client-Name": "OrcaSlicer"` — may not matter in practice but is
  technically wrong for CuraEngine slices.

## Won't fix (by design)

- **3MF extraction from CuraEngine files**: CuraEngine doesn't produce
  OrcaSlicer-style project 3MFs. `estampo init --from-3mf` is an OrcaSlicer
  convenience feature.

- **Profile pin/list for CuraEngine**: CuraEngine has no extractable profile
  chain — settings are inline in `CuraProfile`. No equivalent to OrcaSlicer's
  printer/process/filament profile discovery.

- **`auth.py` BBL client name**: This header is for Bambu Cloud API
  compatibility. Changing it could break authentication. Leave as-is unless
  Bambu documents alternative values.
