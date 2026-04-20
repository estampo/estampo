#!/usr/bin/env python3
"""Record estampo demo phases and merge into a single GIF.

Each phase is recorded as a separate .cast file, then merged into a
single demo.cast that ``agg`` renders to demo.gif.

Usage:
    # Record all phases and build the merged GIF:
    python scripts/record_demo.py

    # Re-record only specific phases:
    python scripts/record_demo.py --phases init,run

    # Just rebuild the merged cast/GIF from existing phase files:
    python scripts/record_demo.py --phases none

    # Convert to GIF (done automatically):
    agg --font-size 20 docs/recordings/demo.cast docs/recordings/demo.gif

Phases: init, profiles-pin, validate, run

The demo runs against ``examples/multi-part/``. Recording deletes the
checked-in estampo.toml / profiles/ / estampo_output/ in that directory —
restore with ``git checkout examples/multi-part/`` when done.

Requires: pexpect, asciinema, agg (brew install agg)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pexpect

RECORDINGS_DIR = Path(__file__).parent.parent / "docs" / "recordings"
DEMO_DIR = Path(__file__).parent.parent / "examples" / "multi-part"
TYPING_DELAY = 0.04

# Max idle gap in the final recording (seconds)
MAX_IDLE = 2.0

# Escape sequences
DOWN = "\x1b[B"

# Phase definitions: name → cast file
PHASE_FILES = {
    "init": RECORDINGS_DIR / "init.cast",
    "profiles-pin": RECORDINGS_DIR / "profiles-pin.cast",
    "validate": RECORDINGS_DIR / "validate.cast",
    "run": RECORDINGS_DIR / "run.cast",
}

# Phases that can be auto-recorded
AUTO_PHASES = ["init", "profiles-pin", "validate", "run"]

# Default phase order for the merged demo
PHASE_ORDER = ["init", "profiles-pin", "validate", "run"]


def status(msg: str) -> None:
    """Print a status message to stderr (not captured in recording)."""
    print(f"  → {msg}", file=sys.stderr)


def type_slowly(child: pexpect.spawn, text: str, delay: float = TYPING_DELAY) -> None:
    """Type text character by character with a delay."""
    for ch in text:
        child.send(ch)
        time.sleep(delay)


def type_comment(child: pexpect.spawn, text: str) -> None:
    """Type a bash comment, pause to let viewer read it."""
    type_slowly(child, text)
    time.sleep(0.5)
    child.send("\r")
    time.sleep(1)


def type_command(child: pexpect.spawn, text: str) -> None:
    """Type a command and press Enter."""
    type_slowly(child, text)
    time.sleep(0.5)
    child.send("\r")


def clean_buffer(child: pexpect.spawn) -> str:
    """Return the last 500 chars of the child buffer with ANSI codes stripped."""
    buf = child.before or ""
    return re.sub(r"\x1b\[[^m]*m|\x1b\([^)]*\)", "", buf)[-500:]


def expect(child: pexpect.spawn, pattern: str, timeout: int = 60) -> None:
    """Wait for pattern, with detailed debug on failure."""
    status(f"waiting for: {pattern}")
    try:
        child.expect(pattern, timeout=timeout)
        status(f"  matched: {pattern}")
    except pexpect.TIMEOUT:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"TIMEOUT waiting for: {pattern}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        print(f"Buffer:\n{clean_buffer(child)}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def start_recording(cast_file: Path, cwd: str | None = None) -> pexpect.spawn:
    """Start an asciinema recording session and return the child process."""
    cast_file.parent.mkdir(parents=True, exist_ok=True)
    cast_file.unlink(missing_ok=True)

    env = {
        **os.environ,
        "ESTAMPO_SKIP_SLICER_DETECT": "1",
        "PROMPT_TOOLKIT_NO_CPR": "1",
    }

    child = pexpect.spawn(
        f"asciinema rec --cols 80 --rows 25 --overwrite {cast_file}",
        cwd=cwd or str(Path.home()),
        encoding="utf-8",
        timeout=120,
        dimensions=(25, 80),
        env=env,
    )
    child.delaybeforesend = 0
    time.sleep(2)
    status("shell ready")
    return child


def stop_recording(child: pexpect.spawn) -> None:
    """Stop an asciinema recording session."""
    status("exiting asciinema")
    child.sendline("exit")
    try:
        child.expect(pexpect.EOF, timeout=10)
    except Exception:
        pass
    child.close()


# ---------------------------------------------------------------------------
# Phase recorders
# ---------------------------------------------------------------------------


def record_init() -> None:
    """Record the init phase.

    Drives the current wizard (see ``run_wizard`` in ``src/estampo/init.py``):
    engine pick → project name → CAD files (multi-select + per-file copies
    & orient) → printer profile → process profile → slicer version →
    filament → bed type → nozzle → overrides → preview.
    """
    cast_file = PHASE_FILES["init"]
    status("RECORDING PHASE: init")

    # Clean up any previously-generated config so the wizard starts fresh.
    import shutil

    estampo_toml = DEMO_DIR / "estampo.toml"
    if estampo_toml.exists():
        estampo_toml.unlink()
        status("removed existing estampo.toml")
    profiles_dir = DEMO_DIR / "profiles"
    if profiles_dir.exists():
        shutil.rmtree(profiles_dir)
        status("removed existing profiles/")
    output_dir = DEMO_DIR / "estampo_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
        status("removed existing estampo_output/")

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# an estampo project is just CAD files + estampo.toml")
        type_command(child, "ls")
        time.sleep(1.5)
        type_comment(child, "# estampo init creates the config from your project")
        type_command(child, "estampo init")

        # Engine pick — accept default (orca)
        expect(child, "Pick engine")
        time.sleep(1)
        child.send("\r")
        status("selected engine: orca")

        # Project name — accept default
        expect(child, "Project name")
        time.sleep(1)
        child.send("\r")
        status("accepted project name")

        # CAD Files — multi-select all three
        expect(child, "Select files")
        time.sleep(1)
        for _ in range(3):
            child.send(" ")
            time.sleep(0.3)
            child.send(DOWN)
            time.sleep(0.3)
        child.send("\r")
        time.sleep(1)
        status("selected CAD files")

        # Per-file copies + orient (3 parts, accept defaults)
        for i in range(3):
            expect(child, "copies")
            time.sleep(0.5)
            child.send("\r")
            expect(child, "orientation")
            time.sleep(0.5)
            child.send("\r")
            status(f"configured part {i + 1}")

        # Printer Profile — search P1S
        expect(child, "Pick a printer profile")
        time.sleep(1)
        type_slowly(child, "P1S 0.4")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected printer profile")

        # Process Profile — standard 0.20mm
        expect(child, "Pick a process profile")
        time.sleep(1)
        type_slowly(child, "0.20mm Standard @BBL X1C")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected process profile")

        # Slicer Version — accept pinned default
        expect(child, "Pick version|CuraEngine version")
        time.sleep(0.5)
        child.send("\r")
        time.sleep(1)
        status("accepted slicer version")

        # Filament — pick first suggestion
        expect(child, "Pick a filament|Pick filament for slot")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected filament")

        # Bed type — accept default / skip
        expect(child, "Pick bed type")
        time.sleep(0.5)
        child.send("\r")
        status("accepted bed type")

        # Nozzle type — accept default
        expect(child, "Pick nozzle type")
        time.sleep(0.5)
        child.send("\r")
        status("accepted nozzle type")

        # Slicer Overrides — pick infill density, then finish
        expect(child, "Pick override")
        time.sleep(0.5)
        child.sendline("1")

        expect(child, "Value for")
        time.sleep(0.5)
        type_slowly(child, "30")
        time.sleep(0.5)
        child.send("\r")
        status("set infill override to 30%")

        # Finish overrides
        expect(child, "Pick override")
        time.sleep(0.5)
        child.send("\r")
        status("finished overrides")

        # Packaging (P1S is a Bambu printer — wizard prompts to add pack stage)
        expect(child, "Add a pack stage")
        time.sleep(1)
        child.send("\r")
        status("added pack stage")

        # Preview — write
        expect(child, "Write.*Go back.*Quit")
        time.sleep(2)
        child.sendline("w")

        expect(child, "Wrote estampo.toml")
        time.sleep(2)
        status("init complete — wrote estampo.toml")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"init phase saved to {cast_file}")


def record_profiles_pin() -> None:
    """Record the profiles pin phase."""
    cast_file = PHASE_FILES["profiles-pin"]
    status("RECORDING PHASE: profiles-pin")

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# Pin slicer profiles for reproducibility")
        type_command(child, "estampo profiles pin")

        expect(child, "Pinned.*profile")
        time.sleep(3)
        status("profiles pinned")

        type_comment(child, "# estampo.toml and profiles/ are ready to commit")
        type_command(child, "ls -l")
        time.sleep(2)
    finally:
        stop_recording(child)

    status(f"profiles-pin phase saved to {cast_file}")


def record_validate() -> None:
    """Record the validate phase."""
    cast_file = PHASE_FILES["validate"]
    status("RECORDING PHASE: validate")

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# Validate config")
        type_command(child, "estampo validate")

        expect(child, "checks passed|warning")
        time.sleep(3)
        status("validate complete")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"validate phase saved to {cast_file}")


def record_run() -> None:
    """Record the run phase (full pipeline through slice + pack)."""
    cast_file = PHASE_FILES["run"]
    status("RECORDING PHASE: run")

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# Run the pipeline end-to-end")
        type_command(child, "estampo run")

        expect(child, "Loaded.*part")
        time.sleep(0.5)
        status("parts loaded")

        expect(child, "Arranged.*part")
        time.sleep(0.5)
        status("parts arranged")

        expect(child, "Plate exported")
        time.sleep(0.5)
        status("plate exported")

        expect(child, "Sliced", timeout=300)
        time.sleep(1)
        status("slicing complete")

        expect(child, "Print time|filament")
        time.sleep(1)

        # Pack stage is the final stage of the default pipeline for P1S.
        expect(child, "pack.*complete|Wrote.*gcode.3mf|Pipeline complete", timeout=120)
        time.sleep(3)
        status("run complete")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"run phase saved to {cast_file}")


# ---------------------------------------------------------------------------
# Cast file merging
# ---------------------------------------------------------------------------


def parse_cast(cast_path: Path) -> tuple[dict, list[list]]:
    """Parse a v3 asciicast file into (header, events)."""
    lines = cast_path.read_text().splitlines()
    if not lines:
        msg = f"Empty cast file: {cast_path}"
        raise ValueError(msg)

    header = json.loads(lines[0])
    events = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return header, events


def compress_events(events: list[list], max_idle: float = MAX_IDLE) -> list[list]:
    """Cap idle gaps in v3 events (relative timestamps)."""
    return [[round(min(e[0], max_idle), 3), *e[1:]] for e in events]


def strip_exit(events: list[list]) -> list[list]:
    """Remove trailing 'exit' command and shell exit output from events."""
    # Find the earliest 'exit' event in the tail and drop everything from there.
    # Non-exit events (ANSI escapes, prompts) may be interleaved, so scan the
    # entire tail rather than stopping at the first non-match.
    first_exit = len(events)
    for i in range(len(events) - 1, max(len(events) - 20, -1), -1):
        text = events[i][2] if len(events[i]) > 2 else ""
        if "exit" in text and len(text) < 30:
            first_exit = i
    # Also drop the prompt line immediately before the first exit
    if first_exit > 0:
        prev = events[first_exit - 1][2] if len(events[first_exit - 1]) > 2 else ""
        if prev.rstrip().endswith("$") or prev.rstrip().endswith("$ "):
            first_exit -= 1
    return events[:first_exit]


def merge_casts(phase_order: list[str], gap: float = 1.5) -> Path:
    """Merge multiple phase cast files into a single demo.cast.

    Inserts a small gap between phases for visual separation.
    Returns path to the merged file.
    """
    merged_events: list[list] = []
    header = None

    for phase in phase_order:
        cast_path = PHASE_FILES[phase]
        if not cast_path.exists():
            print(
                f"WARNING: {cast_path} not found, skipping phase '{phase}'",
                file=sys.stderr,
            )
            continue

        phase_header, events = parse_cast(cast_path)
        if header is None:
            header = phase_header

        events = compress_events(events)
        events = strip_exit(events)

        # Add a gap before this phase (except the first)
        if merged_events:
            merged_events.append([gap, "o", ""])

        merged_events.extend(events)

    if header is None:
        print("ERROR: no phase cast files found", file=sys.stderr)
        sys.exit(1)

    # Write merged file
    out_path = RECORDINGS_DIR / "demo.cast"
    out_lines = [json.dumps(header)]
    for event in merged_events:
        out_lines.append(json.dumps(event))

    out_path.write_text("\n".join(out_lines) + "\n")
    status(f"merged {len(phase_order)} phases → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

PHASE_RECORDERS: dict[str, object] = {
    "init": record_init,
    "profiles-pin": record_profiles_pin,
    "validate": record_validate,
    "run": record_run,
}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Record estampo demo phases and merge into a single GIF.",
        epilog="Examples:\n"
        "  record_demo.py                              # record all auto phases + merge\n"
        "  record_demo.py --phases init,run            # re-record only init and run\n"
        "  record_demo.py --phases none                # just merge existing cast files\n"
        "  record_demo.py --phases profiles-pin,validate  # re-record two phases\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--phases",
        type=str,
        default=",".join(AUTO_PHASES),
        help="Comma-separated phases to record "
        f"({', '.join(AUTO_PHASES)}), "
        "or 'none' to skip recording and just merge. Default: all auto phases.",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Record phases but don't merge into demo.cast",
    )
    args = parser.parse_args()

    # Parse phases
    if args.phases.lower() == "none":
        phases_to_record: list[str] = []
    else:
        phases_to_record = [p.strip() for p in args.phases.split(",")]
        for p in phases_to_record:
            if p not in PHASE_RECORDERS:
                valid = ", ".join(AUTO_PHASES)
                print(
                    f"ERROR: unknown phase '{p}'. Choose from: {valid}",
                    file=sys.stderr,
                )
                sys.exit(1)

    # Record requested phases
    for phase in phases_to_record:
        PHASE_RECORDERS[phase]()  # type: ignore[operator]

    # Merge all phases into demo.cast
    if not args.no_merge:
        merged = merge_casts(PHASE_ORDER)
        print(f"\nMerged:  {merged}", file=sys.stderr)
        print(f"Play:    asciinema play {merged}", file=sys.stderr)
        gif_path = RECORDINGS_DIR / "demo.gif"
        print(f"To GIF:  agg --font-size 20 {merged} {gif_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
