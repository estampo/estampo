# The .gcode.3mf Format: Making Bambu Connect-Compatible Files from OrcaSlicer CLI

Bambu Connect is Bambu Lab's official middleware for sending sliced files to
printers from third-party tools. It accepts `.gcode.3mf` files -- ZIP archives
containing gcode and metadata produced by BambuStudio or OrcaSlicer.

This document covers what we learned getting OrcaSlicer's CLI to produce files
that Bambu Connect actually accepts. It was hard-won through extensive trial and
error, since Bambu Connect silently rejects malformed files with no error
message.

## Background: Two Different 3MF Export Formats

OrcaSlicer has two fundamentally different 3MF export modes:

| | **Project Export** | **Plate Sliced Export** |
|---|---|---|
| **GUI action** | File > Save Project | File > Export plate sliced file (Ctrl+G) |
| **Contains** | 3D models + mesh data + settings | Gcode + metadata only |
| **3dmodel.model** | Full mesh vertices/triangles | Empty `<resources/>` and `<build/>` |
| **model_settings.config** | Full object metadata (10KB+) | Simple plate config (~700 bytes) |
| **project_settings.config** | Full slicer settings | Full slicer settings |
| **File size** | Large (includes geometry) | Small (gcode + metadata) |
| **Bambu Connect** | Rejected | Accepted |

Bambu Connect only accepts the **plate sliced** format. The project format is
for re-opening in the slicer, not for printing.

## The CLI Flags You Need

```bash
orca-slicer \
  --load-settings "machine.json;process.json" \
  --load-filaments "filament_0.json;filament_1.json" \
  --slice 0 \
  --export-3mf plate_sliced.gcode.3mf \
  --min-save \
  --outputdir ./output \
  input.3mf
```

The two critical flags:

- **`--export-3mf <filename>`** -- export a 3mf archive alongside the gcode
- **`--min-save`** -- produce the "plate sliced" format (gcode-only, no 3D
  models). Without this flag, you get the project format that Bambu Connect
  rejects.

### Gotchas

- **`--min-save` takes no argument.** Writing `--min-save 1` fails with
  "No such file: 1" because OrcaSlicer treats `1` as an input filename.
  It's a standalone boolean flag.

- **`--export-3mf` must use a relative filename.** An absolute path like
  `--export-3mf /path/to/output/plate.3mf` gets prepended with `--outputdir`,
  producing a doubled path like `/path/to/output//path/to/output/plate.3mf`.
  Use just the filename: `--export-3mf plate_sliced.gcode.3mf`.

- **Use `.gcode.3mf` extension**, not `.3mf`. Bambu Connect uses the extension
  to distinguish sliced files from project files.

- **Shader errors in headless mode are harmless.** You'll see errors like
  "Unable to compile fragment shader" and "can not get shader for rendering
  thumbnail" when running without a display. Slicing still works; you just
  don't get thumbnails.

## Post-Processing: Four Fixes Required

The `--min-save` output is *almost* right, but Bambu Connect rejects it due to
four issues in the metadata. You need to patch the ZIP archive after slicing.

### Fix 1: project_settings.config -- Missing Keys and Short Arrays

`Metadata/project_settings.config` is a JSON file with ~553 keys. The CLI
export produces only ~544 keys. Bambu Connect validates for completeness; a
file with too few keys is silently rejected.

**The right fix** is to regenerate `project_settings.config` from a full
BambuStudio-style machine profile rather than patching OrcaSlicer's export.
`bambox` does this automatically by reading `printer_model` from OrcaSlicer's
settings and mapping it to the appropriate profile.

If you are patching manually, these 11 keys are commonly absent from the CLI
export:

```json
{
  "bbl_use_printhost": "1",
  "default_bed_type": "",
  "filament_retract_lift_above": ["0"],
  "filament_retract_lift_below": ["0"],
  "filament_retract_lift_enforce": [""],
  "host_type": "octoprint",
  "pellet_flow_coefficient": "0",
  "pellet_modded_printer": "0",
  "printhost_authorization_type": "key",
  "printhost_ssl_ignore_revoke": "0",
  "thumbnails_format": "BTT_TFT"
}
```

Adding only these 11 keys is **not sufficient** — BC requires ~178 additional
BambuStudio 02.05+ keys (machine geometry, filament behaviour tables, toolchange
coordinates, etc.). The only reliable approach is to start from a full machine
profile, not to patch the OrcaSlicer output.

**Short filament arrays.** The CLI sizes arrays to match the number of loaded
filaments (e.g. 3 elements if you loaded 3 filaments). Bambu Connect expects
arrays padded to the AMS slot count -- **5 for a P1S** (4 AMS slots + 1
external spool). Pad by repeating the last element.

For example, `filament_type` might be `["PLA", "PLA", "PETG-CF"]` from the CLI
but needs to be `["PLA", "PLA", "PETG-CF", "PETG-CF", "PETG-CF"]`.

### Fix 2: model_settings.config -- Missing Metadata Keys

`Metadata/model_settings.config` is an XML file describing the plate. The CLI
export is missing metadata entries that Bambu Connect requires. The complete
set of required keys, in order:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1 1 1 1 1"/>
    <metadata key="filament_volume_maps" value="0 0 0 0 0"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>
  </plate>
</config>
```

Key notes:
- `filament_maps` must be padded to AMS slot count (space-separated, one per slot): `"1"` → `"1 1 1 1 1"`
- `filament_volume_maps` is required (BambuStudio 02.05+) and must appear **before** `gcode_file`
- The thumbnail/bbox keys are required even if the actual PNG files are absent

### Fix 3: slice_info.config -- Missing BambuStudio 02.05 Keys

OrcaSlicer's `slice_info.config` is missing several keys that BambuStudio 02.05
always emits. The complete working structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.05.00.66"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="extruder_type" value="0"/>
    <metadata key="nozzle_volume_type" value="0"/>
    <metadata key="printer_model_id" value="C12"/>
    <metadata key="nozzle_diameters" value="0.4"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="681"/>
    <metadata key="weight" value="8.51"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="false"/>
    <metadata key="label_object_enabled" value="true"/>
    <metadata key="filament_maps" value="1 1 1 1 1"/>
    <metadata key="limit_filament_maps" value="0 0 0 0 0"/>
    <filament id="1" tray_info_idx="GFL99" type="PLA" color="#F2754E"
      used_m="0.12" used_g="0.36" used_for_object="true"
      used_for_support="false" group_id="0" nozzle_diameter="0.40"
      volume_type="Standard"/>
  </plate>
</config>
```

Keys OrcaSlicer omits that must be added:
- `X-BBL-Client-Version` — OrcaSlicer leaves this blank; set to `02.05.00.66`
- `extruder_type` — must appear **before** `printer_model_id`
- `nozzle_volume_type` — must appear **before** `printer_model_id`
- `limit_filament_maps` — space-separated zeros, one per AMS slot

OrcaSlicer also emits `weight=""` (empty string) when `filament_density = 0` in
the profile. Bambu Connect ignores the weight value, but a blank value causes
parse errors in some tooling. Compute it from the G-code footer:

```
; filament used [g] = 8.51       ← use this if present
; filament used [cm3] = 6.86     ← multiply by filament density as fallback
```

### Fix 4: Thumbnails (Optional but Recommended)

The CLI can't render thumbnails in headless mode. Without them, Bambu Connect
shows a blank/broken image. Adding placeholder PNGs at `Metadata/plate_1.png`
and `Metadata/plate_1_small.png` gives a cleaner appearance.

Real thumbnails can be generated from the G-code toolpath using matplotlib or
similar.

## Complete Archive Structure

A valid `.gcode.3mf` for Bambu Connect contains:

```
plate_sliced.gcode.3mf
  [Content_Types].xml              -- Standard OPC content types
  _rels/.rels                      -- Relationship to 3dmodel.model
  3D/3dmodel.model                 -- Empty model (no mesh data)
  Metadata/plate_1.gcode           -- The actual gcode
  Metadata/plate_1.gcode.md5       -- MD5 hex digest of gcode (uppercase hex)
  Metadata/model_settings.config   -- Plate config XML (with all required keys)
  Metadata/_rels/model_settings.config.rels  -- Links gcode to plate
  Metadata/slice_info.config       -- Print time, weight, filament info
  Metadata/project_settings.config -- Full slicer settings JSON (~553 keys)
  Metadata/plate_1.json            -- Plate bounding box / layout data
  Metadata/plate_1.png             -- Thumbnail (optional, but refs required)
  Metadata/plate_1_small.png       -- Small thumbnail (optional)
```

### What Doesn't Matter

Through testing, we confirmed these are **not** required or validated:

- **Actual thumbnail PNG files** -- the XML references are required but the
  files themselves are optional (placeholder 1×1 PNGs are fine)
- **`slice_info.config` values** -- `prediction`, `weight`, `printer_model_id`,
  `filament_maps` values are not validated by BC; the keys must be present
- **`_rels/.rels` whitespace** -- BC's XML parser ignores it
- **`3D/3dmodel.model` Application version** -- the version string
  (`BambuStudio-02.05.00.66` vs `BambuStudio-2.3.1`) and metadata element
  ordering are not validated
- **`[Content_Types].xml`** -- the OrcaSlicer CLI version works fine
- **`plate_1.json` bounding-box data** -- bbox coordinates and other non-`bed_type`
  keys are not validated by BC

### What Matters

- **`project_settings.config`** must be present with ~553 keys (full
  BambuStudio-style profile). OrcaSlicer's ~544-key CLI export is **not
  sufficient** — BC silently rejects files with too few keys. Regenerate from
  a machine profile rather than patching the OrcaSlicer output.
- **`model_settings.config`** must have `filament_volume_maps`, thumbnail/bbox
  metadata references, and `filament_maps` padded to AMS slot count
- **`slice_info.config`** must have `extruder_type`, `nozzle_volume_type`,
  `limit_filament_maps`, and a non-blank `X-BBL-Client-Version`; `extruder_type`
  and `nozzle_volume_type` must appear **before** `printer_model_id`
- **`plate_1.json`** `bed_type` must be `"textured_plate"` — OrcaSlicer CLI
  emits `"cool_plate"` for some profiles, which BC rejects
- **`plate_1.gcode.md5`** must contain the correct uppercase MD5 hex digest
  of the gcode bytes
- **File extension** must be `.gcode.3mf`
- **`--min-save` flag** must be used when slicing (no 3D model data in the
  archive)

## G-code Validation

Beyond file loading, `bambox validate` checks the G-code for firmware
compatibility issues:

- **E001** -- missing `HEADER_BLOCK_START`/`HEADER_BLOCK_END` delimiters
- **E002** -- `M620.1 E` toolchange feedrate below 1 mm/min (indicates
  misconfigured profile). **Note:** OrcaSlicer BBL G-code contains legitimate
  low-feedrate `M620.1 E` commands derived from
  `filament_max_volumetric_speed / 2.4053 * 60`; E002 is skipped for BBL
  G-code (detected by `; HEADER_BLOCK_START` presence)
- **W003** -- `weight=""` in `slice_info.config` when `filament_density = 0`
  in the OrcaSlicer profile. Compute weight from `; filament used [cm3]`
  in the G-code footer as a fallback

## Example Post-Processing Script

Here is a minimal Python script to patch a `--min-save` export. Note that this
approach is **not sufficient on its own** — you must also regenerate
`project_settings.config` from a full machine profile (see Fix 1 above).

```python
import io
import json
import re
import zipfile

MISSING_KEYS = {
    "bbl_use_printhost": "1",
    "default_bed_type": "",
    "filament_retract_lift_above": ["0"],
    "filament_retract_lift_below": ["0"],
    "filament_retract_lift_enforce": [""],
    "host_type": "octoprint",
    "pellet_flow_coefficient": "0",
    "pellet_modded_printer": "0",
    "printhost_authorization_type": "key",
    "printhost_ssl_ignore_revoke": "0",
    "thumbnails_format": "BTT_TFT",
}

MIN_SLOTS = 5  # P1S with AMS


def fix_gcode_3mf(path: str) -> None:
    with zipfile.ZipFile(path, "r") as zin:
        # Fix project_settings.config
        # WARNING: this only adds 11 keys. BC requires ~553 total.
        # For a production fix, regenerate from a full machine profile.
        ps = json.loads(zin.read("Metadata/project_settings.config"))
        for key, default in MISSING_KEYS.items():
            if key not in ps:
                ps[key] = default
        for key, val in ps.items():
            if isinstance(val, list) and 0 < len(val) < MIN_SLOTS:
                while len(val) < MIN_SLOTS:
                    val.append(val[-1])

        # Fix model_settings.config
        # Patching key-by-key produces wrong ordering. Regenerate from scratch,
        # preserving filament_maps from the original.
        ms_raw = zin.read("Metadata/model_settings.config").decode()
        fm_match = re.search(r'key="filament_maps" value="([^"]*)"', ms_raw)
        fm_parts = fm_match.group(1).split() if fm_match else []
        while len(fm_parts) < MIN_SLOTS:
            fm_parts.append(fm_parts[-1] if fm_parts else "1")
        fm = " ".join(fm_parts)
        fvm = " ".join(["0"] * MIN_SLOTS)
        ms = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="{fm}"/>
    <metadata key="filament_volume_maps" value="{fvm}"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>
  </plate>
</config>
"""

        # Fix slice_info.config
        si = zin.read("Metadata/slice_info.config").decode()
        # Set client version
        si = re.sub(
            r'(<header_item key="X-BBL-Client-Version" value=")(")',
            r"\g<1>02.05.00.66\g<2>",
            si,
        )
        # Add missing keys before printer_model_id
        for key, val in [("extruder_type", "0"), ("nozzle_volume_type", "0")]:
            if f'key="{key}"' not in si:
                si = si.replace(
                    '    <metadata key="printer_model_id"',
                    f'    <metadata key="{key}" value="{val}"/>\n'
                    f'    <metadata key="printer_model_id"',
                    1,
                )
        # Add limit_filament_maps
        if 'key="limit_filament_maps"' not in si:
            limit = " ".join(["0"] * MIN_SLOTS)
            si = si.replace(
                "  </plate>",
                f'    <metadata key="limit_filament_maps" value="{limit}"/>\n  </plate>',
            )

        # Fix plate_1.json: BC requires bed_type=textured_plate
        plate_json_override = None
        try:
            pj = json.loads(zin.read("Metadata/plate_1.json"))
            if pj.get("bed_type") != "textured_plate":
                pj["bed_type"] = "textured_plate"
                plate_json_override = json.dumps(pj, separators=(",", ":"))
        except KeyError:
            plate_json_override = '{"bed_type":"textured_plate"}'

        # Rewrite the archive
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "Metadata/project_settings.config":
                    zout.writestr(item, json.dumps(ps, indent=4))
                elif item.filename == "Metadata/model_settings.config":
                    zout.writestr(item, ms)
                elif item.filename == "Metadata/slice_info.config":
                    zout.writestr(item, si)
                elif item.filename == "Metadata/plate_1.json" and plate_json_override:
                    zout.writestr(item, plate_json_override)
                else:
                    zout.writestr(item, zin.read(item.filename))
            if plate_json_override and "Metadata/plate_1.json" not in zin.namelist():
                zout.writestr("Metadata/plate_1.json", plate_json_override)

    with open(path, "wb") as f:
        f.write(buf.getvalue())
```

## Per-Object Filament Assignment in the Input 3MF

When building a plate 3MF with parts assigned to different AMS slots, OrcaSlicer
needs to know which extruder each object uses. There are two mechanisms:

### `--load-filament-ids` (STL only)

The `--load-filament-ids` CLI flag assigns filaments to parts by index:

```bash
orca-slicer --load-filament-ids "0,2,2" part_a.stl part_b.stl part_c.stl
```

This only works with STL inputs. When the input is a 3MF, the flag is silently
ignored and all objects default to extruder 1.

### `model_settings.config` (3MF)

For 3MF inputs, per-object extruder assignment is stored in
`Metadata/model_settings.config` inside the 3MF archive:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata key="extruder" value="3"/>
  </object>
  <object id="2">
    <metadata key="extruder" value="3"/>
  </object>
</config>
```

The `id` attribute must match the object IDs in `3D/3dmodel.model`. The
`extruder` value is 1-indexed (matches AMS slot numbers).

This is what estampo uses: `export_plate()` writes a `model_settings.config`
with per-object extruder metadata so OrcaSlicer slices each part with the
correct filament.

### `paint_color` (per-triangle, avoid)

BambuStudio/OrcaSlicer also supports per-triangle extruder assignment via
`paint_color` attributes on `<triangle>` elements. However, OrcaSlicer 2.3.x
CLI segfaults when `paint_color` is combined with `--load-filaments`
([OrcaSlicer #12426](https://github.com/SoftFever/OrcaSlicer/issues/12426)).
Use `model_settings.config` instead.

## Opening in Bambu Connect Programmatically

On macOS, use the `bambu-connect://` URL scheme:

```bash
open "bambu-connect://import-file?path=%2Fpath%2Fto%2Fplate_sliced.gcode.3mf&name=my_print&version=1.0.0"
```

Parameters (all URL-encoded):
- `path` -- absolute filesystem path to the `.gcode.3mf`
- `name` -- display name for the print
- `version` -- fixed value `1.0.0`

## References

- [BambuStudio CLI issue #2930](https://github.com/bambulab/BambuStudio/issues/2930) --
  documents the `--min-save` flag
- [Bambu Connect Wiki](https://wiki.bambulab.com/en/software/bambu-connect) --
  official Bambu Connect documentation
- [Third-party Integration](https://wiki.bambulab.com/en/software/third-party-integration) --
  Bambu Lab's third-party integration docs
- [Bambu Connect file format error](https://forum.bambulab.com/t/bambu-connect-file-format-error/143571) --
  community discussion confirming sliced format requirement
