"""resolve_root.py — resolve the INTERCAMBIO exchange root for CAMINO_N.

OT RUNNER CAMINO_N v2, FASE 2 (single primitive). The previous OT v1 failed on
the MBP because a directory named "Intercambio" existed locally with DIFFERENT
content; the executor reported inputs as missing. A path existing does NOT prove
it is the correct root. This module therefore resolves the host role, picks a
candidate root, and VERIFIES it against mandatory markers before accepting it.

Reuses host_runtime.detect_host() for host/role detection (iMac18,3 path
host_runtime.py:258). On absence or ambiguity it raises
IntercambioShareUnavailable -> caller emits RUNNER_BLOCKED_INTERCAMBIO_SHARE_UNAVAILABLE.

Atomic write is NOT implemented here: the OT mandates reusing fuse_safe_write
(drive_fuse.py:40). This module is read-only with respect to the filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol


# Markers every correct INTERCAMBIO root MUST contain (OT section 0).
# Either marker missing => the chosen root is wrong, regardless of its name.
CANINO_COMMONS_DIR = "MEGA_OT_WORK/camino_commons"
QUALITY_LOG_REL = "L6_R4_bee4d86ca9c0/AI_QUALITY_LOG.jsonl"


class HostDetector(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]: ...


class IntercambioShareUnavailable(RuntimeError):
    """Raised when the Intercambio root is absent, ambiguous, or invalid.

    Maps to terminal state RUNNER_BLOCKED_INTERCAMBIO_SHARE_UNAVAILABLE.
    Never raise this for a transient mount: callers should retry once, then
    surface the block. The message MUST state every candidate tried and why
    each was rejected, so a human can see what failed.
    """


def validate_root_markers(root: Path) -> list[str]:
    """Return a list of reasons root is NOT a valid Intercambio root.

    Empty list => root is valid. A directory can be named "Intercambio" and
    still lack the markers; that is exactly the v1 failure mode, so the name
    alone is never trusted.
    """
    problems: list[str] = []
    commons = root / CANINO_COMMONS_DIR
    if not commons.is_dir():
        problems.append(f"missing marker dir: {commons}")
    else:
        # camino_commons must carry at least the ledger/identity modules, not
        # be an empty stub. Count non-cache python modules.
        modules = [p for p in commons.glob("*.py") if p.name != "__init__.py"]
        if len(modules) < 7:
            problems.append(
                f"marker dir incomplete: {commons} has {len(modules)} modules (expect >=7)"
            )
    qlog = root / QUALITY_LOG_REL
    if not qlog.is_file():
        problems.append(f"missing marker file: {qlog}")
    return problems


def _imac_default_root() -> Path:
    # On the iMac the share IS the local home Intercambio directory.
    return Path("/Users/mariano/Intercambio")


def _enumerate_volume_candidates(volumes_dir: Path) -> list[Path]:
    """Enumerate plausible Intercambio roots under a volumes mountpoint dir.

    On the MBP the iMac home lives behind a mounted share; the volume name is
    NOT assumed (OT section 0: `ls /Volumes` without assuming a name). We
    consider both `<vol>/Users/mariano/Intercambio` and `<vol>/Intercambio`,
    since the share may be the whole disk or just the home dir.
    """
    candidates: list[Path] = []
    if not volumes_dir.is_dir():
        return candidates
    for vol in sorted(volumes_dir.iterdir()):
        if not vol.is_dir():
            continue
        name = vol.name
        # Skip obvious non-data mountpoints.
        if name.startswith(".") or name in {".timemachine", "BOOTCAMP"}:
            continue
        # Symlink roots (e.g. "Macintosh SSD -> /") point back to the boot
        # volume; only follow real candidate directories.
        for rel in (
            Path("Users/mariano/Intercambio"),
            Path("Intercambio"),
        ):
            cand = vol / rel
            if cand.is_dir() and not cand.is_symlink():
                candidates.append(cand)
    return candidates


def resolve_root(
    *,
    detect: Optional[Callable[[], Mapping[str, Any]]] = None,
    environ: Optional[Mapping[str, str]] = None,
    volumes_dir: Path = Path("/Volumes"),
    extra_candidates: Iterable[Path] = (),
) -> Path:
    """Resolve and VERIFY a single INTERCAMBIO_ROOT.

    Strategy:
      1. Honour an explicit override (CAMINO_DRIVE_BUS_ROOT or
         CAMINO_INTERCAMBIO_ROOT) exactly once and verify it. This mirrors
         start_overnight.py:182 (--shared-root -> CAMINO_DRIVE_BUS_ROOT).
      2. Detect host role via host_runtime.detect_host() (reused, not
         reimplemented). On iMac use the local home path. On macbook/generic,
         enumerate /Volumes without assuming the volume name.
      3. Verify markers. A candidate with the right name but without markers
         is REJECTED (the v1 failure case).
      4. Exactly one valid candidate must remain. Zero => share unavailable;
         more than one => ambiguous => share unavailable.

    Returns the verified Path. Raises IntercambioShareUnavailable otherwise.
    """
    env = os.environ if environ is None else environ

    # Allow callers (and tests) to inject a detector; default to the real one.
    if detect is None:
        # Imported lazily so the module remains import-safe even if a host
        # lacks system_profiler/sysctl in a test sandbox.
        from scripts.host_runtime import detect_host
        detect = detect_host  # type: ignore[assignment]

    # Honour explicit operator override, then verify. The override does not
    # bypass marker verification: an operator can point at the wrong place too.
    override = (
        env.get("CAMINO_INTERCAMBIO_ROOT", "").strip()
        or env.get("CAMINO_DRIVE_BUS_ROOT", "").strip()
    )
    tried: list[tuple[Path, list[str]]] = []
    override_path: Optional[Path] = None
    if override:
        override_path = Path(override).expanduser()

    host = detect()
    role = str(host.get("role") or "generic").lower()

    if role == "imac":
        candidates = [_imac_default_root()]
    else:
        # macbook / generic: enumerate mounted volumes, do NOT assume the name.
        candidates = [*_enumerate_volume_candidates(volumes_dir)]
    # Operator override is considered first (highest priority) but it goes
    # through the SAME marker verification as everything else.
    if override_path is not None:
        candidates.insert(0, override_path)
    candidates.extend(extra_candidates)

    # De-duplicate while preserving order, so the same path provided twice
    # (e.g. override == default) does not look like ambiguity.
    seen: set[str] = set()
    unique_candidates: list[Path] = []
    for cand in candidates:
        key = str(cand)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(cand)

    verified: list[Path] = []
    for cand in unique_candidates:
        problems = validate_root_markers(cand)
        if not problems:
            verified.append(cand)
        else:
            label = "override rejected" if cand == override_path else None
            tried.append((cand, ([label] if label else []) + problems))

    # Exactly one verified root is acceptable. Ambiguity (more than one) is a
    # block: guessing between two valid shares would reintroduce the very
    # "path exists != correct path" hazard this module exists to prevent.
    if len(verified) == 1:
        return verified[0]
    if len(verified) > 1:
        names = "\n".join(f"  - {p}" for p in verified)
        raise IntercambioShareUnavailable(
            f"ambiguous: {len(verified)} candidates passed markers:\n{names}"
        )

    # Nothing verified. Report every candidate and why it failed, so the human
    # can distinguish "share not mounted" from "wrong dir named Intercambio".
    if tried:
        lines = ["no candidate passed marker verification:"]
        for path, problems in tried:
            lines.append(f"  - {path}: {'; '.join(problems) or 'unknown'}")
    else:
        lines = [
            "no Intercambio candidate found",
            f" (role={role}, volumes_dir={volumes_dir})",
        ]
    raise IntercambioShareUnavailable("".join(lines) if not tried else "\n".join(lines))


def main() -> int:
    """CLI shim: print the resolved root or a block reason. For operators."""
    try:
        root = resolve_root()
    except IntercambioShareUnavailable as exc:
        print(f"RUNNER_BLOCKED_INTERCAMBIO_SHARE_UNAVAILABLE\n{exc}", flush=True)
        return 2
    print(str(root), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
