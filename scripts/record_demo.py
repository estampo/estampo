#!/usr/bin/env python3
"""Record fabprint demo phases and merge into a single GIF.

Each phase (init, validate, run, status) is recorded as a separate .cast file.
The setup phase uses a pre-recorded cast file (setup.fixed.cast) since it
requires interactive login.

Usage:
    # Record all auto phases and build the merged GIF:
    python scripts/record_demo.py

    # Re-record only specific phases:
    python scripts/record_demo.py --phases init,run

    # Just rebuild the merged cast/GIF from existing phase files:
    python scripts/record_demo.py --phases none

    # Convert to GIF (done automatically):
    agg --font-size 20 docs/recordings/demo.cast docs/recordings/demo.gif

Phases: setup (pre-recorded), init, validate, run, status

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
DEMO_DIR = Path.home() / "repos" / "decoy-case"
TYPING_DELAY = 0.04

# Max idle gap in the final recording (seconds)
MAX_IDLE = 2.0

# Escape sequences
DOWN = "\x1b[B"

# Phase definitions: name → cast file
PHASE_FILES = {
    "setup": RECORDINGS_DIR / "setup.fixed.cast",
    "init": RECORDINGS_DIR / "init.cast",
    "validate": RECORDINGS_DIR / "validate.cast",
    "run": RECORDINGS_DIR / "run.cast",
    "status": RECORDINGS_DIR / "status.cast",
}

# Phases that can be auto-recorded (setup is always pre-recorded)
AUTO_PHASES = ["init", "validate", "run", "status"]

# Default phase order for the merged demo
PHASE_ORDER = ["setup", "init", "validate", "run", "status"]


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
        "FABPRINT_SKIP_SLICER_DETECT": "1",
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


def record_init(dry_run: bool = True) -> None:
    """Record the init phase."""
    cast_file = PHASE_FILES["init"]
    status("RECORDING PHASE: init")

    # Clean up for fresh demo
    fabprint_toml = DEMO_DIR / "fabprint.toml"
    if fabprint_toml.exists():
        fabprint_toml.unlink()
        status("removed existing fabprint.toml")

    child = start_recording(cast_file)

    try:
        type_comment(child, "# Step 2: cd to project directory and run fabprint init")
        type_command(child, "cd repos/decoy-case")
        time.sleep(0.5)
        type_command(child, "fabprint init")

        # Project name — accept default
        expect(child, "Project name")
        time.sleep(1)
        child.send("\r")
        status("accepted project name")

        # CAD Files — multi-select both
        expect(child, "Select files")
        time.sleep(1)
        child.send(" ")
        time.sleep(0.3)
        child.send(DOWN)
        time.sleep(0.3)
        child.send(" ")
        time.sleep(0.3)
        child.send("\r")
        time.sleep(1)
        status("selected CAD files")

        # First file — copies + orient (accept defaults)
        expect(child, "copies")
        time.sleep(0.5)
        child.send("\r")
        expect(child, "orient")
        time.sleep(0.5)
        child.send("\r")
        status("configured first file")

        # Second file — copies + orient
        expect(child, "copies")
        time.sleep(0.5)
        child.send("\r")
        expect(child, "orient")
        time.sleep(0.5)
        child.send("\r")
        status("configured second file")

        # Printer Connection — select workshop
        expect(child, "Printer Connection")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected printer connection")

        # Printer Profile — search P1S
        expect(child, "Printer Profile")
        time.sleep(1)
        type_slowly(child, "P1S 0.4")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected printer profile")

        # Process Profile
        expect(child, "Process Profile")
        time.sleep(1)
        type_slowly(child, "0.20mm Standard @BBL X1C")
        time.sleep(1)
        child.send("\r")
        time.sleep(1)
        status("selected process profile")

        # Slicer Version — pick first
        expect(child, "Pick version")
        time.sleep(0.5)
        child.sendline("1")
        time.sleep(1)
        status("selected slicer version")

        # Filaments — accept AMS suggestions
        expect(child, "Use these filaments")
        time.sleep(1)
        child.sendline("y")
        time.sleep(1)
        status("accepted AMS filaments")

        # Filament Assignment — slot 3 for both
        expect(child, r"slot \(1-")
        time.sleep(0.5)
        child.sendline("3")
        expect(child, r"slot \(1-")
        time.sleep(0.5)
        child.sendline("3")
        time.sleep(1)
        status("assigned filament slots")

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

        # Preview — write
        expect(child, "Write.*Go back.*Quit")
        time.sleep(2)
        child.sendline("w")

        expect(child, "Wrote fabprint.toml")
        time.sleep(2)
        status("init complete — wrote fabprint.toml")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"init phase saved to {cast_file}")


def record_validate() -> None:
    """Record the validate phase."""
    cast_file = PHASE_FILES["validate"]
    status("RECORDING PHASE: validate")

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# Step 3: fabprint validate — check config")
        type_command(child, "fabprint validate")

        expect(child, "checks passed|warning")
        time.sleep(3)
        status("validate complete")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"validate phase saved to {cast_file}")


def record_run(dry_run: bool = True) -> None:
    """Record the run phase."""
    cast_file = PHASE_FILES["run"]
    mode = "--dry-run" if dry_run else ""
    status(f"RECORDING PHASE: run {mode}".strip())

    child = start_recording(cast_file, cwd=str(DEMO_DIR))

    try:
        type_comment(child, "# Step 4: fabprint run — build and send to printer")
        cmd = "fabprint run --dry-run" if dry_run else "fabprint run"
        type_command(child, cmd)

        expect(child, "Loaded.*part")
        time.sleep(0.5)
        status("parts loaded")

        expect(child, "Arranged.*part")
        time.sleep(0.5)
        status("parts arranged")

        expect(child, "Plate exported")
        time.sleep(0.5)
        status("plate exported")

        expect(child, "Sliced", timeout=180)
        time.sleep(1)
        status("slicing complete")

        expect(child, "Print time|filament")
        time.sleep(1)

        expect(child, "Dry run|Sent to printer")
        time.sleep(3)
        status("run complete")
        time.sleep(1)
    finally:
        stop_recording(child)

    status(f"run phase saved to {cast_file}")


def record_status() -> None:
    """Record the status phase."""
    cast_file = PHASE_FILES["status"]
    status("RECORDING PHASE: status")

    child = start_recording(cast_file)

    try:
        type_comment(child, "# Step 5: fabprint status -w — live printer dashboard")
        type_command(child, "fabprint status -w --interval 1")

        # Let the dashboard refresh a few times
        time.sleep(10)

        # Ctrl-C to stop
        child.send("\x03")
        time.sleep(2)
        status("status dashboard done")
    finally:
        stop_recording(child)

    status(f"status phase saved to {cast_file}")


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
            print(f"WARNING: {cast_path} not found, skipping phase '{phase}'", file=sys.stderr)
            continue

        phase_header, events = parse_cast(cast_path)
        if header is None:
            header = phase_header

        events = compress_events(events)

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

PHASE_RECORDERS = {
    "init": record_init,
    "validate": record_validate,
    "run": record_run,
    "status": record_status,
}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Record fabprint demo phases and merge into a single GIF.",
        epilog="Examples:\n"
        "  record_demo.py                    # record all auto phases + merge\n"
        "  record_demo.py --phases init,run  # re-record only init and run\n"
        "  record_demo.py --phases none      # just merge existing cast files\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--phases",
        type=str,
        default=",".join(AUTO_PHASES),
        help="Comma-separated phases to record (init,validate,run,status), "
        "or 'none' to skip recording and just merge. Default: all auto phases.",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually send to printer during run phase (default: dry run)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Record phases but don't merge into demo.cast",
    )
    args = parser.parse_args()
    dry_run = not args.no_dry_run

    # Parse phases
    if args.phases.lower() == "none":
        phases_to_record: list[str] = []
    else:
        phases_to_record = [p.strip() for p in args.phases.split(",")]
        for p in phases_to_record:
            if p == "setup":
                print("ERROR: setup phase is pre-recorded (use setup.fixed.cast).", file=sys.stderr)
                print("Re-record it manually when needed.", file=sys.stderr)
                sys.exit(1)
            if p not in PHASE_RECORDERS:
                valid = ", ".join(AUTO_PHASES)
                print(f"ERROR: unknown phase '{p}'. Choose from: {valid}", file=sys.stderr)
                sys.exit(1)

    # Record requested phases
    for phase in phases_to_record:
        if phase == "run":
            record_run(dry_run=dry_run)
        else:
            PHASE_RECORDERS[phase]()

    # Merge all phases into demo.cast
    if not args.no_merge:
        merged = merge_casts(PHASE_ORDER)
        print(f"\nMerged:  {merged}", file=sys.stderr)
        print(f"Play:    asciinema play {merged}", file=sys.stderr)
        gif_path = RECORDINGS_DIR / "demo.gif"
        print(f"To GIF:  agg --font-size 20 {merged} {gif_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
