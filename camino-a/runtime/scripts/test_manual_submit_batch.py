#!/usr/bin/env python3
"""Offline unit tests for multiformat manual submission bundles."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.camino_a_worker_bus import scan_worker_outputs  # noqa: E402
from scripts.manual_submit import main as submit_main  # noqa: E402


passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", name)
    else:
        failed += 1
        print("  FAIL:", name, detail)


with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    run = base / "RUN_20260710_165033_abcde_manual_test"
    run.mkdir()
    audit = base / "audit.md"
    audit.write_text("# Auditoría\n\n## Hallazgos\n\n- Hallazgo verificable sin credenciales.\n", encoding="utf-8")
    code = base / "evidence.py"
    code.write_text("def answer():\n    return 42\n", encoding="utf-8")
    image = base / "screen.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"safe-image-evidence")
    text_file = base / "second_audit.txt"
    text_file.write_text("Auditoría externa guardada como texto y con evidencia suficiente.\n", encoding="utf-8")

    print("=== MANUAL 1: lote multiformato cosechable ===")
    rc = submit_main([
        "--run", str(run),
        "--worker", "manual_gpt",
        "--stage", "external_audit",
        "--candidate-sha256", "a" * 64,
        "--file", str(audit),
        "--file", str(code),
        "--file", str(image),
        "--text-file", str(text_file),
        "--file-role", "%s=implementation_evidence" % code,
        "--text", "# Auditoría pegada\n\n- Segunda evidencia independiente y suficientemente detallada.",
        "--text-role", "manual_audit",
    ])
    check("submit success", rc == 0, str(rc))
    bundles = sorted((run / "13_WORKER_BUS/manual_gpt/OUT").iterdir())
    check("one final bundle", len(bundles) == 1, str(bundles))
    bundle = bundles[0]
    check("DONE present", (bundle / "MANUAL_SUBMISSION.DONE").is_file())
    metadata = json.loads((bundle / "submission.json").read_text(encoding="utf-8"))
    check("five related items", metadata.get("item_count") == 5, str(metadata))
    check("SHA/MIME/role present", all(
        len(item.get("sha256", "")) == 64 and item.get("mime_type") and item.get("role")
        for item in metadata.get("items", [])
    ))
    check("role override kept", any(
        item.get("role") == "implementation_evidence" and item.get("extension") == ".py"
        for item in metadata.get("items", [])
    ))
    outputs = scan_worker_outputs(run)
    check("worker bus accepts bundle", len(outputs) == 1 and outputs[0]["validation"]["status"] == "valid", str(outputs))

    print("=== MANUAL 2: single --file compatibility ===")
    run2 = base / "RUN_20260710_165034_bcdef_single"
    run2.mkdir()
    rc = submit_main([
        "--run", str(run2), "--worker", "manual_claude",
        "--stage", "external_audit", "--candidate-sha256", "b" * 64,
        "--file", str(audit),
    ])
    check("legacy single file succeeds", rc == 0, str(rc))

    print("=== MANUAL 3: formatos documentales/binarios permitidos ===")
    format_run = base / "RUN_20260710_165035_cdefa_formats"
    format_run.mkdir()
    format_files = {
        "data.json": b'{"finding": "safe"}\n',
        "notes.yaml": b"finding: safe\n",
        "table.csv": b"id,finding\n1,safe\n",
        "notes.txt": b"Auditoria textual suficientemente detallada y segura.\n",
        "photo.jpg": b"\xff\xd8\xff" + b"safe-jpeg-evidence",
        "capture.webp": b"RIFF\x10\x00\x00\x00WEBP" + b"safe-webp",
        "report.pdf": b"%PDF-1.4\n% safe minimal evidence\n",
    }
    paths = []
    for name, content in format_files.items():
        path = base / name
        path.write_bytes(content)
        paths.append(path)
    safe_zip = base / "evidence.zip"
    with zipfile.ZipFile(str(safe_zip), "w") as archive:
        archive.writestr("audit.md", "# Auditoría segura\n\n- evidencia incluida\n")
    paths.append(safe_zip)
    argv = [
        "--run", str(format_run), "--worker", "manual_gpt", "--stage", "external_audit",
        "--candidate-sha256", "c" * 64,
    ]
    for path in paths:
        argv.extend(["--file", str(path)])
    rc = submit_main(argv)
    check("all documented formats accepted", rc == 0, "rc=%s" % rc)
    format_bundle = next((format_run / "13_WORKER_BUS/manual_gpt/OUT").iterdir())
    format_metadata = json.loads((format_bundle / "submission.json").read_text(encoding="utf-8"))
    check("eight format items recorded", format_metadata.get("item_count") == 8, str(format_metadata))

    print("=== MANUAL 4: secrets/symlinks/ZIP traversal fail closed ===")
    secret = base / "secret.txt"
    secret.write_text('api_key = "sk-proj-ABCDEFGHIJKLMNOPQRSTUV123456789"\n', encoding="utf-8")
    before = len(list((run / "13_WORKER_BUS/manual_gpt/OUT").iterdir()))
    rc = submit_main([
        "--run", str(run), "--worker", "manual_gpt", "--stage", "external_audit",
        "--candidate-sha256", "a" * 64, "--file", str(secret),
    ])
    after = len(list((run / "13_WORKER_BUS/manual_gpt/OUT").iterdir()))
    check("secret rejected without bundle", rc == 1 and before == after, "rc=%s" % rc)

    symlink = base / "linked.md"
    try:
        symlink.symlink_to(audit)
    except OSError:
        check("symlink rejection", True, "symlink unsupported by host")
    else:
        rc = submit_main([
            "--run", str(run), "--worker", "manual_gpt", "--stage", "external_audit",
            "--candidate-sha256", "a" * 64, "--file", str(symlink),
        ])
        check("symlink rejection", rc == 1, "rc=%s" % rc)

    bad_zip = base / "unsafe.zip"
    with zipfile.ZipFile(str(bad_zip), "w") as archive:
        archive.writestr("../escape.txt", "safe text")
    rc = submit_main([
        "--run", str(run), "--worker", "manual_gpt", "--stage", "external_audit",
        "--candidate-sha256", "a" * 64, "--file", str(bad_zip),
    ])
    check("ZIP traversal rejected", rc == 1, "rc=%s" % rc)

    print("=== MANUAL 5: configurable limit ===")
    old_limit = os.environ.get("CAMINO_MANUAL_MAX_FILE_BYTES")
    os.environ["CAMINO_MANUAL_MAX_FILE_BYTES"] = "16"
    try:
        rc = submit_main([
            "--run", str(run), "--worker", "manual_gpt", "--stage", "external_audit",
            "--candidate-sha256", "a" * 64, "--file", str(audit),
        ])
    finally:
        if old_limit is None:
            os.environ.pop("CAMINO_MANUAL_MAX_FILE_BYTES", None)
        else:
            os.environ["CAMINO_MANUAL_MAX_FILE_BYTES"] = old_limit
    check("lower operator limit enforced", rc == 1, "rc=%s" % rc)

    print("=== MANUAL 6: archivo mayor a 10 MiB con validación streaming ===")
    large_run = base / "RUN_20260710_165036_defab_large"
    large_run.mkdir()
    large_pdf = base / "large_report.pdf"
    with large_pdf.open("wb") as handle:
        handle.write(b"%PDF-1.4\n")
        handle.seek(11 * 1024 * 1024 - 1)
        handle.write(b"\n")
    rc = submit_main([
        "--run", str(large_run), "--worker", "manual_gpt", "--stage", "external_audit",
        "--candidate-sha256", "d" * 64, "--file", str(large_pdf),
    ])
    check("large manual artifact accepted", rc == 0, "rc=%s" % rc)
    large_outputs = scan_worker_outputs(large_run)
    check("large manual bundle validates", len(large_outputs) == 1 and large_outputs[0]["validation"]["status"] == "valid", str(large_outputs))

print()
print("RESULTADO: %d passed, %d failed" % (passed, failed))
raise SystemExit(0 if failed == 0 else 1)
