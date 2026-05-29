# Printer support

estampo is **printer-agnostic**: it produces a sliced G-code / `.gcode.3mf` on
disk and stops there. Packaging the output into a vendor-specific format and
sending it to a printer are handled by external CLIs wired into the pipeline as
[command stages](config.md#command-stages) (see ADR-005, ADR-007). This keeps
vendor-specific code out of estampo and lets you swap printer backends without
touching the build system.

## Bambu Lab

Use [bambox](https://github.com/estampo/bambox) to pack the sliced output into
the `.gcode.3mf` format Bambu printers expect:

```toml
[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
```

## Klipper / Moonraker

Any printer running Klipper + Moonraker (Voron, Ender with Klipper, etc.) can be
driven with a `curl`-based command stage — no extra tooling required:

```toml
[print]
command = "curl -F file=@{sliced_dir}/plate.gcode http://YOUR_PRINTER:7125/server/files/upload"
```

## Other printers

Any CLI that reads a sliced file and does something with it can be a command
stage. If your printer vendor ships a CLI, wire it in the same way; otherwise
`estampo run` already produces the G-code file for you to send however you
normally would.
