"""Shared Docker utilities for slicer engine modules."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from estampo import EstampoError

log = logging.getLogger(__name__)


def has_image(image: str) -> bool:
    """Check if the given Docker image exists locally."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def pull_image(image: str, *, cached: bool) -> bool:
    """Pull a Docker image from the registry. Returns True on success."""
    from estampo import ui

    label = "Checking for updated image" if cached else "Pulling Docker image"
    log.info("Pulling Docker image %s ...", image)
    try:
        with ui.status(f"{label} [bold]{image}[/bold]"):
            # Published images are amd64-only, so an arm64 host needs the
            # explicit platform or the pull fails on a manifest mismatch. See #746
            r = subprocess.run(
                ["docker", "pull", "--platform", "linux/amd64", image],
                capture_output=True,
                text=True,
                timeout=300,
            )
        if r.returncode == 0:
            return True
        log.debug("docker pull failed: %s", r.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def ensure_image(image: str) -> bool:
    """Ensure an up-to-date Docker image is available locally.

    Always attempts a pull so that image updates are picked up
    automatically.  If the pull fails (no network, registry down)
    the locally cached image is used instead.  Returns False only
    when no usable image is available at all.
    """
    cached = has_image(image)
    if pull_image(image, cached=cached):
        return True
    if cached:
        log.warning("Could not pull %s — using locally cached image", image)
        return True
    return False


@contextmanager
def stopped_container(image: str) -> Iterator[str]:
    """Create a stopped Docker container and yield its ID.

    The container is removed when the context exits (even on error).
    """
    result = subprocess.run(
        ["docker", "create", "--platform", "linux/amd64", image, "true"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise EstampoError(f"docker create failed: {result.stderr.strip()}")
    container_id = result.stdout.strip()
    try:
        yield container_id
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            capture_output=True,
            timeout=15,
        )


def copy_from_container(
    container_id: str,
    src: str,
    dest: Path,
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run ``docker cp`` from a container path to a local directory."""
    return subprocess.run(
        ["docker", "cp", f"{container_id}:{src}", str(dest)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def extract_files(
    image: str,
    container_path: str,
    *,
    tmp_prefix: str = "estampo_",
    status_label: str = "Extracting files from Docker image",
) -> Path:
    """Extract files from a Docker image to a temp directory.

    Uses ``docker create`` + ``docker cp`` + ``docker rm`` — the
    container is never started.  Returns a temp directory whose
    cleanup is the caller's responsibility.
    """
    if not ensure_image(image):
        raise EstampoError(f"Docker image {image} is not available and could not be pulled.")

    from estampo import ui

    tmp_dir = Path(tempfile.mkdtemp(prefix=tmp_prefix))

    with ui.status(status_label):
        with stopped_container(image) as container_id:
            cp = copy_from_container(
                container_id,
                f"{container_path}/.",
                tmp_dir,
                timeout=60,
            )
            if cp.returncode != 0:
                raise EstampoError(f"Failed to copy files from Docker: {cp.stderr.strip()}")

    return tmp_dir
