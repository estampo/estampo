# Open Questions: CuraEngine Printer Definitions & Filament Model

Open design questions related to the CuraEngine printer definition work
([design doc](cura-printer-definitions.md)) and broader multi-vendor
direction.

## 1. Filament model: material-centric vs slot-centric

The current TOML config ties parts to physical slots:

```toml
[slicer.orca]
filaments = ["Generic PLA @base", "Generic PETG-CF @base"]

[[parts]]
file = "body.stl"
filament = 2   # AMS slot number
```

This is fragile -- swap two AMS trays and the config breaks. It also
embeds a vendor-specific concept (AMS slot layout) into the project config.

**Proposed**: parts declare the material they need, not the slot:

```toml
[[parts]]
file = "body.stl"
filament = "PETG-CF"

[[parts]]
file = "insert.stl"
filament = "PLA"
```

Slot assignment (which tray, which extruder) is resolved later in the
pipeline or at print time.

**Open questions:**

- Where does slot resolution happen? Options:
  - In the slicer adapter (just before calling OrcaSlicer/CuraEngine)
  - At print time in bambu-3mf (query printer, auto-map)
  - A separate `[slots]` config that's printer-specific, not project-specific
- How granular should material types be? Just `"PETG-CF"` or full slicer
  profile names like `"Generic PETG-CF @BBL X1C"`? The slicer still needs
  a profile name to get temperature/retraction settings.
- Should there be a project-level filament dictionary for aliasing?
  ```toml
  [filaments]
  structural = "PETG-CF"
  decorative = "PLA"

  [[parts]]
  file = "body.stl"
  filament = "structural"
  ```
- How does this interact with OrcaSlicer's `--load-filaments` which expects
  ordered profile paths mapped to slot indices?
- What about single-filament projects? Should `filament` be optional on
  parts (default to the project's single material)?

## 2. Bambu Lab definition maintenance

The bundled `bambulab_base.def.json` and `bambulab_p1s.def.json` are
hand-crafted for estampo. The upstream Cura AppImage does not include
Bambu Lab printers.

**Open questions:**

- Who maintains these definitions as new Bambu printers ship (A1, A1 mini,
  X1E, etc.)? Are they contributed by users or maintained by the project?
- Should we extract machine geometry (bed size, start gcode, disallowed
  areas) from OrcaSlicer's Bambu profiles instead of writing defs from
  scratch? OrcaSlicer's BBL profiles are well-maintained.
- How do we validate that a custom def actually works with CuraEngine?
  Start gcode template variables differ between slicers.

## 3. Multi-filament detection during init

The design doc specifies asking "does your printer have multi-filament
support?" during `estampo init`. This replaces the current approach of
inferring AMS from OrcaSlicer's `single_extruder_multi_material` field.

**Open questions:**

- Should this also ask how many filament slots are available? Some systems
  have 4 (AMS), 8 (dual AMS), 5 (Prusa MMU3), or arbitrary (tool changers).
- Is `multi_filament = true` sufficient, or do we need a
  `filament_slots = 4` field?
- Where does this live in the TOML? `[slicer]` (engine-neutral) or
  `[printer]` (machine-specific)?

## 4. KiriMoto as a reference

KiriMoto is MIT-licensed and has Bambu Lab printer templates. It may be
useful as a reference for:

- How it maps materials to extruders/trays
- Its machine definition format (`Bambu.P1S.json`)
- Whether it separates machine geometry from material/slot config

**Action**: review KiriMoto's source for filament handling patterns before
finalising the material-centric model.

## 5. CuraEngine process profiles

CuraEngine has no equivalent of OrcaSlicer's process profiles (quality
presets like "0.20mm Standard"). All settings are flat `-s` overrides.

**Open questions:**

- Should estampo introduce its own process profile concept for CuraEngine?
  e.g. a JSON file with common override bundles that users can share.
- Or is `[slicer.cura.overrides]` sufficient for the foreseeable future?
- If we add process profiles, should they follow CuraEngine's `.def.json`
  format (with inheritance) or a simpler flat JSON?

## 6. Definition pinning practicality

Squashing a CuraEngine definition chain produces a large file because
`fdmprinter.def.json` has ~4000 settings. A pinned `bambulab_p1s.def.json`
would be several hundred KB.

**Open questions:**

- Is this acceptable for committing to version control?
- Should we strip settings that match the fdmprinter defaults (only keep
  overrides)? This defeats the purpose of pinning (self-contained) but
  keeps files small.
- Alternative: pin only the chain (multiple files, preserving inheritance)
  rather than squashing into one? Less portable but smaller.
