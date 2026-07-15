#!/usr/bin/env python3
"""package_release.py — Empaqueta una release top-level verificable.

A diferencia de scripts/package_final.py (que arma el FINAL/ de UNA corrida),
este script arma la RELEASE COMPLETA (el ZIP que se entrega). Corre las
validaciones reales, escribe VALIDATION_RESULTS.json y RELEASE_MANIFEST.json con
resultados verificados (no a mano), arma el ZIP e imprime su SHA-256.

Uso:
    python3 scripts/package_release.py --root . --out ./dist

Reglas:
- VALIDATION_RESULTS.json registra la SUITE COMPLETA (bin/run_tests.sh), no
  subconjuntos. Si run_tests.sh falla, el packaging aborta (fail-closed).
- RELEASE_MANIFEST.json hashea todos los archivos de la release (excluye basura
  temporal y se excluye a sí mismo y al ZIP).
- El SHA-256 del ZIP se imprime y se guarda en un sidecar RELEASE_SHA256.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERSION = "v1.3.22-slot1-slot4-six-loops"
RELEASE_NAME = "Camino Nocturno Canon Mutable"

# Basura que nunca entra a la release.
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", "dist", "CAMINO_RUNS", "outputs", "work",
                "node_modules", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".orig"}
EXCLUDE_NAMES = {
    ".DS_Store",
    "RELEASE_SHA256.txt",
    "CLEAN_RELEASE_MANIFEST_v1_3_18.json",
    "MANIFEST_MINIMO_AUDITORIA.json",
    "AGENTS_HANDOFF_CONSOLIDADOR.md",
    "CONTEXTO_MINIMO_AUDITORIA.md",
    "PEDIDO_AUDITORIAS_MANUALES.md",
    "AUDIT_GLM_PROPOSALS_V1_3_13.md",
    "AUDIT_D1_LIVE_PROBES_V1_3_14.md",
    "CHANGELOG_LMSTUDIO_V1_3_16.md",
    "CHANGELOG_CORRECCION_AUDITORIA.md",
    "AUDIT_OPERATIVA_V1_3_19.md",
    "PRODUCTION_NEGATIVE_SMOKE_20260711.json",
    "CHANGELOG_V1_3_20_SOL56.md",
    "AUDIT_OPERATIVA_V1_3_20_SOL56.md",
    "PRODUCTION_NEGATIVE_SMOKE_V1_3_20_20260711.json",
    "PRODUCTION_NEGATIVE_SMOKE_V1_3_20_20260712.json",
    "GPT_BUILDER_SOL56_AUDIT_20260711.json",
}
KNOWLEDGE_PREFIX = "CAMINO_A_OVERNIGHT_KNOWLEDGE_BUNDLE_UNICO_"
CURRENT_KNOWLEDGE_PREFIX = f"{KNOWLEDGE_PREFIX}{VERSION.replace('.', '_')}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if rel.suffix in EXCLUDE_SUFFIXES:
        return True
    if rel.name in EXCLUDE_NAMES:
        return True
    if rel.name.startswith(KNOWLEDGE_PREFIX) and not rel.name.startswith(CURRENT_KNOWLEDGE_PREFIX):
        return True
    if rel.parts and rel.parts[0] == "reports" and rel.name.startswith("D1_LIVE_ROUTE_PROBE_"):
        return True
    return False


def iter_release_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if is_excluded(rel):
            continue
        yield p, rel


def run(cmd: list[str], root: Path, timeout: int, env: dict | None = None):
    cp = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                        timeout=timeout, env=env)
    summary = [
        line for line in cp.stdout.strip().splitlines()
        if (
            line.startswith("RESULTADO:")
            or line.startswith("CEREBRO_ACTIONS_CONTRACT_OK")
            or line.startswith("operation_ids=")
            or " passed in " in line
            or line == "RUN_TESTS_OK"
        )
    ]
    return {
        "command": " ".join(cmd),
        "exit_code": cp.returncode,
        "stdout_summary": summary[-20:],
        "stdout_tail": "\n".join(cp.stdout.strip().splitlines()[-12:]),
        "stderr_tail": "\n".join(cp.stderr.strip().splitlines()[-6:]),
    }


def build_validation(root: Path) -> dict:
    """Corre validaciones reales. Aborta (fail-closed) si run_tests.sh falla."""
    results: dict = {
        "release_name": RELEASE_NAME,
        "version": VERSION,
        "built_at_utc": utc_now(),
    }

    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(k, None)
    env["CAMINO_DISABLE_CODEX_WORKER"] = "1"
    env.setdefault(
        "PYTHONPYCACHEPREFIX",
        str(Path(tempfile.gettempdir()) / f"camino_release_pycache_{os.getuid()}"),
    )
    for k in ("CAMINO_A_TEST_RECURSION_GUARD", "CAMINO_A_RUN_TESTS_QUICK"):
        env.pop(k, None)

    # 0) generated instructions and published Knowledge must already match the
    # canonical sources.  Packaging never silently refreshes them because a
    # refresh changes the published Knowledge SHA and must remain deliberate.
    results["render_contracts_check"] = run(
        [sys.executable, "scripts/render_contracts.py", "--root", ".", "--check"],
        root, timeout=60, env=env)
    results["knowledge_current_check"] = run(
        [sys.executable, "scripts/build_gpt_knowledge_bundle.py", "--root", ".",
         "--version", VERSION, "--check"],
        root, timeout=60, env=env)
    if any(results[name]["exit_code"] != 0 for name in
           ("render_contracts_check", "knowledge_current_check")):
        results["aborted"] = "generated/ o Knowledge CURRENT no están sincronizados"
        return results, False

    # 1) compileall
    if not (root / "tests").is_dir():
        results["aborted"] = "tests/ ausente; release no verificable"
        return results, False
    compile_targets = ["scripts", "tests"]
    results["compileall"] = run(
        [sys.executable, "-m", "compileall", "-q", *compile_targets],
        root, timeout=120, env=env)
    if results["compileall"]["exit_code"] != 0:
        results["aborted"] = "compileall failed; packaging abortado (fail-closed)."
        return results, False

    # 2) suite completa autoritativa
    results["run_tests_sh"] = run(
        ["bash", str(root / "bin" / "run_tests.sh")],
        root, timeout=900, env=env)
    if results["run_tests_sh"]["exit_code"] != 0:
        results["aborted"] = "run_tests.sh no salió 0; packaging abortado (fail-closed)."
        return results, False

    # 2b) residual-risk hardening tests (kept separate from run_tests.sh to
    # avoid nested subprocess hangs in constrained sandboxes).
    residual_tests = [
        root / "tests" / "test_v132_residual_risks.py",
        root / "tests" / "test_v133_quality_log.py",
    ]
    if all(p.exists() for p in residual_tests):
        results["residual_risk_tests"] = run(
            [sys.executable, "-m", "pytest", "-q",
             "tests/test_v132_residual_risks.py", "tests/test_v133_quality_log.py", "--tb=short"],
            root, timeout=420, env={**env, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        if results["residual_risk_tests"]["exit_code"] != 0:
            results["aborted"] = "residual/quality-log tests failed; packaging abortado (fail-closed)."
            return results, False
    else:
        results["residual_risk_tests"] = {
            "command": "pytest tests/test_v132_residual_risks.py tests/test_v133_quality_log.py",
            "exit_code": 0,
            "not_applicable": "legacy_named_tests_replaced_by_full_mandatory_tests_directory",
        }

    # 3) canon --validate ambos perfiles
    results["canon_validate_without_claude"] = run(
        [sys.executable, "scripts/canon_loader.py", "--root", ".",
         "--profile", "without_claude", "--validate"], root, timeout=60, env=env)
    results["canon_validate_with_claude"] = run(
        [sys.executable, "scripts/canon_loader.py", "--root", ".",
         "--profile", "with_claude", "--validate"], root, timeout=60, env=env)
    if any(results[name]["exit_code"] != 0 for name in (
        "canon_validate_without_claude", "canon_validate_with_claude",
    )):
        results["aborted"] = "canon validation failed after the full suite"
        return results, False

    # 4) launch_sandbox plug-and-play
    sb = run([sys.executable, "scripts/launch_sandbox.py", "--json"],
             root, timeout=180, env=env)
    try:
        sb_json = json.loads(sb["stdout_tail"].splitlines()[-1]) if sb["stdout_tail"] else {}
    except Exception:
        # stdout_tail truncado; re-correr capturando todo
        cp = subprocess.run([sys.executable, "scripts/launch_sandbox.py", "--json"],
                            cwd=str(root), capture_output=True, text=True, timeout=180, env=env)
        try:
            sb_json = json.loads(cp.stdout)
        except Exception:
            sb_json = {"parse_error": True}
    results["launch_sandbox"] = {
        "command": "python3 scripts/launch_sandbox.py --json",
        "exit_code": sb["exit_code"],
        "result": {k: sb_json.get(k) for k in
                   ("status", "profile", "phase", "terminal_reason",
                    "final_zip_exists", "accepted", "rejected")},
    }
    if (
        sb["exit_code"] != 0
        or sb_json.get("status") != "ok"
        or sb_json.get("phase") != "closed"
        or sb_json.get("terminal_reason") != "reference_smoke_complete"
        or sb_json.get("final_zip_exists") is not True
    ):
        results["aborted"] = "sandbox reference smoke failed"
        return results, False

    # 5) Entrypoint canónico sobre target real efímero. Ahora ejercita el
    #    camino canónico (canon_loader + slot_runtime + internal_loop_runner +
    #    overnight_master + package_final) y el bucle agentic interno.
    tmp_target = Path(tempfile.mkdtemp(prefix="camino_rel_target_"))
    tmp_runs = Path(tempfile.mkdtemp(prefix="camino_rel_runs_"))
    (tmp_target / "ejemplo.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    cp = subprocess.run(
        [sys.executable, "scripts/run_multiaudit_cycle.py",
         "--input", str(tmp_target), "--drive-bus-root", str(tmp_runs),
         "--canon-profile", "sandbox_reference", "--execute-workers",
         "--watch-interval-seconds", "1", "--watch-timeout-minutes", "2",
         "--max-iterations", "1"],
        cwd=str(root), capture_output=True, text=True, timeout=240, env=env)
    entry_summary = {}
    try:
        marker = '{\n  "status"'
        entry_summary = json.loads(cp.stdout[cp.stdout.rindex(marker):])
    except Exception:
        entry_summary = {"parse_error": True}
    results["canonical_entrypoint"] = {
        "command": ("python3 scripts/run_multiaudit_cycle.py --input <target> "
                    "--drive-bus-root <runs> --canon-profile sandbox_reference "
                    "--execute-workers --watch-interval-seconds 1 "
                    "--watch-timeout-minutes 2 --max-iterations 1"),
        "exit_code": cp.returncode,
        "summary": {k: entry_summary.get(k) for k in
                    ("status", "phase", "terminal_reason",
                     "accepted_evidence", "final_zip_exists",
                     "quality_delta_count", "quality_sqlite_rows", "quality_log_connected",
                     "internal_loop", "residual_debt")},
        "stdout_tail": "\n".join(cp.stdout.strip().splitlines()[-6:]),
        "stderr_tail": "\n".join(cp.stderr.strip().splitlines()[-6:]),
    }
    # Fail-closed: un entrypoint canónico que no cierra en estado terminal
    # válido aborta la release (no se empaqueta un plug-and-play roto).
    if cp.returncode != 0 or entry_summary.get("status") != "ok" \
            or entry_summary.get("terminal_reason") not in (
                "reference_smoke_complete",) or not entry_summary.get("quality_log_connected"):
        results["aborted"] = ("entrypoint canónico no alcanzó estado terminal "
                              "válido; packaging abortado (fail-closed).")
        return results, False

    results["release_zip_sha256"] = None  # no puede auto-referenciarse; ver sidecar
    return results, True


def build_manifest(root: Path, validation: dict) -> dict:
    files = []
    total = 0
    for p, rel in iter_release_files(root):
        # RELEASE_MANIFEST se excluye a sí mismo (se escribe después).
        if rel.name == "RELEASE_MANIFEST.json":
            continue
        size = p.stat().st_size
        total += size
        files.append({
            "path": str(rel).replace(os.sep, "/"),
            "sha256": sha256_file(p),
            "size_bytes": size,
        })
    return {
        "release_name": RELEASE_NAME,
        "version": VERSION,
        "built_at_utc": utc_now(),
        "file_count": len(files),
        "total_size_bytes": total,
        "run_tests_exit_code": validation.get("run_tests_sh", {}).get("exit_code"),
        "files": files,
    }


EXECUTABLE_RELEASE_PATHS = {
    "bin/launch_sandbox.sh",
    "bin/run_tests.sh",
    "bin/start_overnight.sh",
    "bin/install_launchd.sh",
    "bin/uninstall_launchd.sh",
    "bin/manual_submit.sh",
    "bin/start_camino_b_gateway.sh",
    "bin/run_camino_b_agent.sh",
}

def ensure_executable_bits(root: Path) -> None:
    for rel in EXECUTABLE_RELEASE_PATHS:
        p = root / rel
        if p.exists():
            p.chmod(p.stat().st_mode | 0o111)

def build_zip(root: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"camino_nocturno_canon_mutable_{VERSION.replace('-', '_').replace('.', '_')}.zip"
    if zip_path.exists():
        zip_path.unlink()
    ensure_executable_bits(root)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, rel in iter_release_files(root):
            arcname = str(rel).replace(os.sep, "/")
            info = zipfile.ZipInfo.from_file(p, arcname=arcname)
            # Preserve Unix executable bits for plug-and-play shell entrypoints.
            if arcname in EXECUTABLE_RELEASE_PATHS:
                info.external_attr = (0o100755 & 0xFFFF) << 16
            zf.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Empaquetar release top-level verificable")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out_dir = Path(args.out).resolve()

    print(f"[package_release] root={root}")
    ensure_executable_bits(root)
    print("[package_release] Corriendo validaciones reales (esto tarda ~1-2 min)...")
    validation, ok = build_validation(root)
    (root / "VALIDATION_RESULTS.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")
    if not ok:
        print("[package_release] ABORTADO: validaciones fallaron (fail-closed).", file=sys.stderr)
        print(json.dumps(validation.get("run_tests_sh", {}), indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    manifest = build_manifest(root, validation)
    (root / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    zip_path = build_zip(root, out_dir)
    zip_sha = sha256_file(zip_path)
    (out_dir / "RELEASE_SHA256.txt").write_text(
        f"{zip_sha}  {zip_path.name}\n", encoding="utf-8")

    print("[package_release] OK")
    print(f"  version:        {VERSION}")
    print(f"  files:          {manifest['file_count']}")
    print(f"  zip:            {zip_path}")
    print(f"  zip_size_bytes: {zip_path.stat().st_size}")
    print(f"  zip_sha256:     {zip_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
