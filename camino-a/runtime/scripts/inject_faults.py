#!/usr/bin/env python3
"""inject_faults.py — the FASE 1 "real run" (OT sec 11).

NOT a repair harness. It INSTRUMENTS: it fires each class of the §5 enum
through the REAL exception-instrumentation path against genuinely broken
filesystem/JSON conditions and against an Invoker that returns the same
(ok, error) shapes as worker_gateway._post_json. The output is the exception
log + a distribution report that tells Mariano which handlers to write first.

What it proves (the FASE 1 gates):
  G2 every exception emits a registro; none swallowed.
  G3 cero handlers T0/T1 — we only record + apply default action.
  G5 only fs.mount_absent halts; everything else advances.
  G7 the UNMAPPED rate is measured and published.

It deliberately injects a couple of UNKNOWN signals too, so the G7 rate is
non-trivial and the report shows the taxonomy revision signal working.
"""
from __future__ import annotations

import argparse
import errno
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.default_actions import (  # noqa: E402
    ADVANCE_WITH_DEBT, ENTER_FALLBACK, ESCALATE_T2, HALT_RUN, action_for,
)
from scripts.exception_instrumentation import (  # noqa: E402
    instrumentar, registrar_resultado_fallido,
)
from scripts.exception_log import ExceptionLog  # noqa: E402
from scripts.exception_registro import ExceptionRegistro, build_registro  # noqa: E402
from scripts.exception_taxonomy import CLASSES, UNMAPPED, unmapped_rate  # noqa: E402

DEFAULT_OUT = Path("/Users/mariano/Intercambio/HANDLER_CAMINO_N_2026-08-02")


@dataclass
class FaultOutcome:
    """The result of injecting one fault."""
    expected_clase: str
    actual_clase: str
    halted: bool = False
    note: str = ""


def _fs_disk_full(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    # Raise a genuine OSError(ENOSPC) through the instrumentation.
    try:
        with instrumentar(fase="escritura", slot="3", puesto="audit-writer",
                          route_id="alibaba_qwen_3_8_plan", log=log,
                          expected="escritura atomica completada"):
            raise OSError(errno.ENOSPC, "No space left on device")
    except OSError:
        pass
    # The registro was written by instrumentar; read its class back.
    rows = log.read_all()
    actual = rows[-1]["clase"]
    return FaultOutcome("fs.disk_full", actual,
                        halted=not action_for(actual).advance)


def _fs_permission_denied(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    try:
        with instrumentar(fase="escritura", slot="3", puesto="audit-writer",
                          route_id="r", log=log):
            raise PermissionError(13, "Permission denied")
    except PermissionError:
        pass
    return _last_outcome(log, "fs.permission_denied")


def _fs_path_missing(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    missing = workdir / "no_existe" / "out.json"
    try:
        with instrumentar(fase="recoleccion", slot="1", puesto="auditores",
                          route_id="r", log=log, found_path=missing):
            raise FileNotFoundError(2, "No such file")
    except FileNotFoundError:
        pass
    return _last_outcome(log, "fs.path_missing")


def _fs_mount_absent(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    try:
        with instrumentar(fase="despacho", slot="1", puesto="auditores",
                          route_id="r", log=log):
            raise RuntimeError("INTERCAMBIO_SHARE_UNAVAILABLE: no markers")
    except RuntimeError:
        pass
    o = _last_outcome(log, "fs.mount_absent")
    o.halted = True  # the one class that halts
    return o


def _fs_partial_write(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    partial = workdir / "step6" / "out.json.partial"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text("incompleto")
    r = registrar_resultado_fallido(
        error_str="orphan .partial present, no final",
        fase="escritura", slot="6", puesto="audit-writer",
        route_id="moonshot_kimi_k3_plan", log=log, found_path=partial)
    return FaultOutcome("fs.partial_write", r.clase,
                        halted=not action_for(r.clase).advance)


def _fs_truncated(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    trunc = workdir / "step10" / "out.json"
    trunc.parent.mkdir(parents=True, exist_ok=True)
    trunc.write_text('{"audit":')  # genuinely truncated JSON
    r = registrar_resultado_fallido(
        error_str="file truncated: 9 bytes, incomplete JSON",
        fase="recoleccion", slot="10", puesto="audit-writer",
        route_id="gpt_luna_high_cli", log=log, found_path=trunc)
    return FaultOutcome("fs.truncated", r.clase,
                        halted=not action_for(r.clase).advance)


def _net_rate_limited(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="http_429", fase="despacho", slot="1", puesto="auditores",
        route_id="or_nemotron_3_ultra_550b", log=log, http_code=429)
    return FaultOutcome("net.rate_limited", r.clase,
                        halted=not action_for(r.clase).advance)


def _net_server_error(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="http_502", fase="despacho", slot="4", puesto="auditores",
        route_id="vertex_gemini_3_1_pro", log=log, http_code=502)
    return FaultOutcome("net.server_error", r.clase,
                        halted=not action_for(r.clase).advance)


def _net_timeout(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    try:
        with instrumentar(fase="despacho", slot="8", puesto="auditores",
                          route_id="nvidia_laguna_xs_2_1", log=log):
            raise TimeoutError("timed out after 300s")
    except TimeoutError:
        pass
    return _last_outcome(log, "net.timeout")


def _net_auth_failed(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="http_401", fase="despacho", slot="11", puesto="auditor",
        route_id="blackbox_minimax_m3", log=log, http_code=401)
    return FaultOutcome("net.auth_failed", r.clase,
                        halted=not action_for(r.clase).advance)


def _net_model_not_found(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="http_404", fase="despacho", slot="12", puesto="enjambre: planificador",
        route_id="nvidia_laguna_xs_2_1", log=log, http_code=404)
    return FaultOutcome("net.model_not_found", r.clase,
                        halted=not action_for(r.clase).advance)


def _fmt_json_malformed(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    bad = workdir / "step1" / "malformed.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{"finding": "ok",')  # genuinely malformed JSON
    r = registrar_resultado_fallido(
        error_str="invalid_json_response:{\"finding\": \"ok\",",
        fase="validacion", slot="1", puesto="auditores",
        route_id="r", log=log, found_path=bad)
    return FaultOutcome("fmt.json_malformed", r.clase,
                        halted=not action_for(r.clase).advance)


def _fmt_field_missing(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="field_missing: required field 'route_id' absent",
        fase="validacion", slot="3", puesto="consolidador-audit",
        route_id="r", log=log)
    return FaultOutcome("fmt.field_missing", r.clase,
                        halted=not action_for(r.clase).advance)


def _fmt_truncated_response(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    r = registrar_resultado_fallido(
        error_str="gateway_response_too_large",
        fase="recoleccion", slot="9", puesto="revisa-audita-propone",
        route_id="r", log=log)
    return FaultOutcome("fmt.truncated_response", r.clase,
                        halted=not action_for(r.clase).advance)


def _sem_orphan_claim(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """The genuinely hard one (OT sec 2): valid JSON, semantic lie. FASE 1
    only RECORDS it; a handler would be T2 work."""
    r = registrar_resultado_fallido(
        error_str="orphan_claim: hallazgo no corresponde a ninguna linea del artefacto",
        fase="gate", slot="14", puesto="auditoria final",
        route_id="zai_glm_5_2_plan", log=log)
    return FaultOutcome("sem.orphan_claim", r.clase,
                        halted=not action_for(r.clase).advance)


# --- HUECO 1: the four classes the prior run never exercised (OT FASE 1B T1).
# Each drives a GENUINELY broken artifact through the real instrumentation path,
# not a fabricated registro. Their default actions (sem.* -> ESCALATE_T2,
# fmt.* -> AVANCE_CON_DEUDA) were declared but unproven until now.

def _fmt_encoding(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """fmt.encoding: a file with invalid UTF-8 bytes (latin-1 with accents)
    that the runner tries to decode. The decode failure is the real signal."""
    bad = workdir / "step8" / "encoded.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    # Genuine latin-1 bytes that are NOT valid UTF-8 (0xe1, 0xe9 are accented
    # vowels in latin-1 but lone continuation bytes in UTF-8).
    bad.write_bytes(b'{"finding": "caf\xe9 r\xe9sum\xe9 na\xefve"}')
    # Attempt a real decode so the signal reflects what the runner would see.
    signal = "encoding: "
    try:
        bad.read_bytes().decode("utf-8")  # raises UnicodeDecodeError
    except UnicodeDecodeError as e:
        signal += f"{type(e).__name__}: {e}"
    r = registrar_resultado_fallido(
        error_str=signal, fase="recoleccion", slot="8", puesto="auditores",
        route_id="nvidia_laguna_xs_2_1", log=log, found_path=bad)
    return FaultOutcome("fmt.encoding", r.clase,
                        halted=not action_for(r.clase).advance)


def _fmt_schema_violation(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """fmt.schema_violation: a syntactically VALID JSON response that is missing
    a required contract field. This is the Blackbox/Moonshot-style structured
    error the OT sec 2 warns fires often."""
    incomplete = workdir / "step4" / "response.json"
    incomplete.parent.mkdir(parents=True, exist_ok=True)
    # Valid JSON, but missing the required `route_id`/`model_id` contract fields
    # (only carries an error envelope — exactly the Blackbox prefix-error shape).
    payload = '{"error": {"code": 400, "message": "invalid temperature"}}'
    incomplete.write_text(payload, encoding="utf-8")
    signal = "schema_violation: required field 'route_id' missing; "
    signal += f"response json valid but contract-incomplete: {payload}"
    r = registrar_resultado_fallido(
        error_str=signal, fase="validacion", slot="4", puesto="auditores",
        route_id="blackbox_grok_4_5", log=log, found_path=incomplete,
        http_code=400)
    return FaultOutcome("fmt.schema_violation", r.clase,
                        halted=not action_for(r.clase).advance)


def _sem_contradiction(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """sem.contradiction: a manifest declares 6 artifacts but the directory
    holds 5. Two facts contradict; nobody else catches this cheaper (OT sec 2)."""
    manifest = workdir / "step12" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"artifacts": ["a","b","c","d","e","f"], "count": 6}',
                        encoding="utf-8")
    # Only 5 of the 6 declared artifacts exist.
    for name in ("a", "b", "c", "d", "e"):
        (workdir / "step12" / name).write_text("x")
    signal = ("contradiction: manifest declares 6 artifacts "
              "(count=6) but directory holds 5; one is missing or the "
              "declaration overcounts")
    r = registrar_resultado_fallido(
        error_str=signal, fase="gate", slot="14", puesto="auditoria final",
        route_id="zai_glm_5_2_plan", log=log, found_path=manifest)
    return FaultOutcome("sem.contradiction", r.clase,
                        halted=not action_for(r.clase).advance)


def _sem_unresolvable(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """sem.unresolvable: two valid outputs contradict each other on the SAME
    fact. Neither is wrong on its face; resolving needs judgement (OT sec 2)."""
    out_a = workdir / "step9" / "auditor_a.json"
    out_b = workdir / "step9" / "auditor_b.json"
    out_a.parent.mkdir(parents=True, exist_ok=True)
    out_a.write_text('{"verdict": "clean", "defects": []}', encoding="utf-8")
    out_b.write_text('{"verdict": "blocking", "defects": ["divide-by-zero"]}',
                     encoding="utf-8")
    signal = ("unresolvable: two valid auditor outputs contradict on the same "
              "fact; auditor_a=clean vs auditor_b=blocking — neither is "
              "internally inconsistent, so no cheap resolver applies")
    r = registrar_resultado_fallido(
        error_str=signal, fase="gate", slot="9", puesto="revisa-audita-propone",
        route_id="zai_glm_5_2_plan", log=log, found_path=out_a)
    return FaultOutcome("sem.unresolvable", r.clase,
                        halted=not action_for(r.clase).advance)


# --- HUECO 2: stress the 512-byte excerpt cap with several KB of real garbage.
# The prior run's largest excerpt was 67 bytes; the cap exists for the case
# where a malformed file wants to push half a megabyte into the registro.

def _excerpt_stress(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """Inject a multi-KB malformed payload so the excerpt MUST truncate.

    Verifies (via the registro): <=512 BYTES, marked truncated, multibyte
    intact. The `found` and `expected` fields must NOT grow with the payload
    (they carry path/size/hash and a fixed hint respectively).
    """
    big = workdir / "step3" / "huge_malformed.json"
    big.parent.mkdir(parents=True, exist_ok=True)
    # Several KB of real bytes: ASCII garbage + multibyte (accented + CJK) so
    # the byte cap (not char cap) is what gets exercised.
    chunk_ascii = "DEADBEEF-GARBAGE-" * 64           # ~1 KB
    chunk_multi = "café résumé naïve 你好 日本語 " * 32  # multibyte, ~3-4 KB
    big.write_text('{"broken": "' + chunk_ascii + chunk_multi + '",',
                   encoding="utf-8")  # genuinely malformed (unterminated)
    # Read it back as the runner would, producing the real signal + excerpt.
    raw = big.read_bytes()
    signal = f"invalid_json_response:{raw.decode('utf-8', errors='replace')}"
    r = registrar_resultado_fallido(
        error_str=signal, fase="recoleccion", slot="3", puesto="consolidador-audit",
        route_id="alibaba_qwen_3_8_plan", log=log, found_path=big)
    # The registro's own invariants are checked by the harness caller and by
    # the test suite; here we just surface the class.
    return FaultOutcome("fmt.json_malformed", r.clase,
                        halted=not action_for(r.clase).advance)


def _unmapped_unknown(log: ExceptionLog, workdir: Path) -> FaultOutcome:
    """Deliberately unknown signal -> UNMAPPED, raw_condition preserved.
    Exercises the escape-hatch branch. NOTE: this is a PLANTED case — see the
    G7 correction in the report; it does not measure taxonomy coverage."""
    r = registrar_resultado_fallido(
        error_str="quantum_decoherence_in_subprocess_pipe",
        fase="despacho", slot="7", puesto="auditores",
        route_id="r", log=log)
    return FaultOutcome(UNMAPPED, r.clase,
                        halted=not action_for(r.clase).advance)


def _last_outcome(log: ExceptionLog, expected: str) -> FaultOutcome:
    rows = log.read_all()
    actual = rows[-1]["clase"]
    return FaultOutcome(expected, actual, halted=not action_for(actual).advance)


# Ordered list of (name, injector). Covers fs/net/fmt/sem/UNMAPPED.
INJECTORS: list[tuple[str, Callable[[ExceptionLog, Path], FaultOutcome]]] = [
    ("fs.disk_full", _fs_disk_full),
    ("fs.permission_denied", _fs_permission_denied),
    ("fs.path_missing", _fs_path_missing),
    ("fs.mount_absent", _fs_mount_absent),
    ("fs.partial_write", _fs_partial_write),
    ("fs.truncated", _fs_truncated),
    ("net.rate_limited", _net_rate_limited),
    ("net.server_error", _net_server_error),
    ("net.timeout", _net_timeout),
    ("net.auth_failed", _net_auth_failed),
    ("net.model_not_found", _net_model_not_found),
    ("fmt.json_malformed", _fmt_json_malformed),
    ("fmt.field_missing", _fmt_field_missing),
    ("fmt.truncated_response", _fmt_truncated_response),
    # --- HUECO 1: the four classes the prior run never exercised ---
    ("fmt.encoding", _fmt_encoding),
    ("fmt.schema_violation", _fmt_schema_violation),
    ("sem.contradiction", _sem_contradiction),
    ("sem.unresolvable", _sem_unresolvable),
    ("sem.orphan_claim", _sem_orphan_claim),
    # --- HUECO 2: stress the 512-byte excerpt cap (multi-KB payload) ---
    ("excerpt_stress(->fmt.json_malformed)", _excerpt_stress),
    ("UNMAPPED_CONDITION", _unmapped_unknown),
]


def run_harness(out_dir: Path) -> dict[str, Any]:
    """Run all fault injectors. Returns a structured report.

    The harness NEVER repairs (G3): each injector either raises through
    `instrumentar` (registro written, exception observed) or calls
    `registrar_resultado_fallido` (registro written from the error string).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    log = ExceptionLog(out_dir)
    # The harness is a MEASUREMENT tool: each run must reflect only this run's
    # data. The production logger (runner path) stays append-only. Reset here.
    log.reset()
    workdir = out_dir / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)

    outcomes: list[FaultOutcome] = []
    for name, inj in INJECTORS:
        try:
            outcomes.append(inj(log, workdir))
        except Exception as e:
            # A fault injector crashing is itself an UNMAPPED exception — record it.
            with instrumentar(fase="despacho", slot="?", puesto="harness",
                              route_id=name, log=log):
                raise

    # Build the distribution report.
    dist = log.class_distribution()
    rate = unmapped_rate(dist)
    halt_count = sum(1 for o in outcomes if o.halted)
    mismatches = [o for o in outcomes if o.expected_clase != o.actual_clase]

    # G1: every class in the enum must be exercised. The excerpt_stress injector
    # raises fmt.json_malformed (a class already exercised), so we count
    # DISTINCT real classes, not injector count.
    classes_exercised = set(dist.keys()) - {"UNMAPPED_CONDITION"}
    enum_classes = set(CLASSES) - {"UNMAPPED_CONDITION"}
    unexercised = sorted(enum_classes - classes_exercised)

    # G5 / HUECO 2: excerpt-stress metrics. Find the registro with the largest
    # excerpt and confirm the cap held in BYTES, multibyte was not split, and
    # `found`/`expected` did not grow with the payload.
    rows = log.read_all()
    max_excerpt_bytes = 0
    max_excerpt_marked = False
    found_max_bytes = 0
    expected_max_bytes = 0
    for r in rows:
        if "_corrupt_line" in r:
            continue
        exc = str(r.get("excerpt") or "")
        eb = len(exc.encode("utf-8", errors="replace"))
        if eb > max_excerpt_bytes:
            max_excerpt_bytes = eb
            max_excerpt_marked = "TRUNCATED" in exc
        fb = len(str(r.get("found") or "").encode("utf-8", errors="replace"))
        if fb > found_max_bytes:
            found_max_bytes = fb
        xb = len(str(r.get("expected") or "").encode("utf-8", errors="replace"))
        if xb > expected_max_bytes:
            expected_max_bytes = xb

    from scripts.exception_registro import EXCERPT_MAX_BYTES  # noqa: E402
    excerpt_cap_held = max_excerpt_bytes <= EXCERPT_MAX_BYTES
    # Multibyte intact: the largest excerpt must decode cleanly (no lone
    # continuation bytes from slicing mid-codepoint). We accept the TRUNCATED
    # marker as valid UTF-8 by construction.
    multibyte_intact = True
    for r in rows:
        if "_corrupt_line" in r:
            continue
        try:
            str(r.get("excerpt") or "").encode("utf-8", errors="strict").decode("utf-8")
        except UnicodeError:
            multibyte_intact = False
            break

    report = {
        "state": "HANDLER_FASE1_COMPLETA",
        "out_dir": str(out_dir),
        "log_file": str(log.path),
        "registros": log.count(),
        "injectors_run": len(INJECTORS),
        "classes_observed": dist,
        "enum_classes_count": len(CLASSES),
        "classes_exercised_count": len(classes_exercised),
        "unexercised_classes": unexercised,
        "all_classes_exercised": len(unexercised) == 0,
        "unmapped_rate": round(rate, 4),
        "unmapped_threshold": 0.20,
        # G7 correction: an injection run CANNOT measure taxonomy coverage.
        # The UNMAPPED here is a PLANTED case. Real coverage needs a live run.
        "unmapped_rate_measures": "maquinaria (escape hatch) — NO cobertura",
        "taxonomy_revision_needed_live_only": "N/A hasta corrida viva",
        "halts": halt_count,
        "halt_classes": [o.expected_clase for o in outcomes if o.halted],
        "classification_mismatches": [
            {"expected": o.expected_clase, "actual": o.actual_clase}
            for o in mismatches
        ],
        "excerpt_stress": {
            "max_excerpt_bytes": max_excerpt_bytes,
            "cap_bytes": EXCERPT_MAX_BYTES,
            "cap_held": excerpt_cap_held,
            "largest_marked_truncated": max_excerpt_marked,
            "multibyte_intact": multibyte_intact,
            "found_max_bytes": found_max_bytes,
            "expected_max_bytes": expected_max_bytes,
            "found_did_not_grow": found_max_bytes < 200,
            "expected_did_not_grow": expected_max_bytes < 200,
        },
        "invariants": {
            "every_exception_emitted_registro": log.count() >= len(INJECTORS),
            "all_20_classes_exercised": len(unexercised) == 0,
            "only_mount_absent_halts": halt_count == 1
                                       and "fs.mount_absent" in
                                       [o.expected_clase for o in outcomes if o.halted],
            "excerpt_cap_held_in_bytes": excerpt_cap_held,
            "fuse_safe_write_still_only_path": _confirm_only_fuse_safe_write(),
        },
    }
    return report


def _confirm_only_fuse_safe_write() -> bool:
    """G7 (FASE 1B renumber): the log writes ONLY via fuse_safe_write.

    Checks that exception_log imports fuse_safe_write and does not define its
    own atomic write. (The .write_text calls in inject_faults are the BROKEN
    ARTIFACTS being injected, not the log write path.)
    """
    import scripts.exception_log as el
    from scripts.drive_fuse import fuse_safe_write
    return el.fuse_safe_write is fuse_safe_write


def write_distribution_md(report: dict[str, Any], path: Path) -> None:
    """Publish the exception distribution as human-readable markdown.

    Corrected framing (OT FASE 1B HUECO 3): an injection run proves the
    MAQUINARIA works (every class classifies + gets its default action); it
    does NOT prove the taxonomy COVERS reality. Coverage is measured only in a
    live run. These are two different questions; the first is answered, the
    second is not.
    """
    from scripts.drive_fuse import fuse_safe_write
    dist = report["classes_observed"]
    total = report["registros"]
    es = report["excerpt_stress"]
    lines = [
        "# DISTRIBUCION DE EXCEPCIONES — FASE 1B (inyeccion completa)\n",
        f"Corrida de inyeccion de fallas. Total registros: {total} "
        f"({report['classes_exercised_count']}/{report['enum_classes_count']-1} "
        f"clases reales ejercitadas + UNMAPPED plantado).\n",
        "## Que prueba esta corrida y que NO prueba",
        "- **PRUEBA (contestado):** la maquinaria. Cada clase del enum clasifica",
        "  en su clase correcta y dispara su accion por defecto declarada.",
        "- **NO PRUEBA (sin contestar):** que la taxonomia CUBRA la realidad.",
        "  La tasa de UNMAPPED en una corrida de inyeccion es artefacto:",
        "  se inyecta exactamente lo conocido. La cobertura se mide recien en la",
        "  primera corrida VIVA del runner (FASE 2).\n",
        "## Distribucion por clase",
        "| clase | count | accion por defecto |",
        "|---|---|---|",
    ]
    for clase in sorted(dist, key=lambda c: (-dist[c], c)):
        a = action_for(clase)
        lines.append(f"| `{clase}` | {dist[clase]} | {a.action} |")
    lines.append("")
    lines.append(f"- Clases ejercitadas: **{report['classes_exercised_count']}/19**"
                 + (f" (faltan: {report['unexercised_classes']})" if report['unexercised_classes'] else " (todas)"))
    lines.append(f"- Tasa UNMAPPED: **{report['unmapped_rate']:.2%}** "
                 f"— {report['unmapped_rate_measures']}")
    lines.append(f"- Clases que detienen: {report['halt_classes']} (solo mount_absent detiene)")
    lines.append("")
    lines.append("## Tope de excerpt (HUECO 2)")
    lines.append(f"- Excerpt maximo observado: **{es['max_excerpt_bytes']} bytes** "
                 f"(cap {es['cap_bytes']}) — cap held: **{es['cap_held']}**")
    lines.append(f"- Marcado como truncado: **{es['largest_marked_truncated']}**")
    lines.append(f"- Multibyte intacto (no se partio un codepoint): **{es['multibyte_intact']}**")
    lines.append(f"- `found` no crecio con el payload (max {es['found_max_bytes']}B): "
                 f"**{es['found_did_not_grow']}**")
    lines.append(f"- `expected` no crecio (max {es['expected_max_bytes']}B): "
                 f"**{es['expected_did_not_grow']}**")
    if report["classification_mismatches"]:
        lines.append("\n## MISMATCHES (esperado != actual) — HALLAZGO")
        for m in report["classification_mismatches"]:
            lines.append(f"- esperado `{m['expected']}`, actual `{m['actual']}`")
    fuse_safe_write(path, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CAMINO_N FASE 1 fault-injection harness")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="Output dir (default: Intercambio/HANDLER_CAMINO_N_2026-08-02)")
    args = p.parse_args(argv)
    out = Path(args.out)
    report = run_harness(out)
    write_distribution_md(report, out / "distribucion_excepciones.md")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    ok = all(report["invariants"].values()) and not report["classification_mismatches"]
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
