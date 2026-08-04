"""Tests for exception_instrumentation — OT E2 / G2."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import pytest  # noqa: E402

from scripts.exception_instrumentation import (  # noqa: E402
    aplicar_accion_defecto, instrumentar, registrar_resultado_fallido,
)
from scripts.default_actions import ENTER_FALLBACK, HALT_RUN  # noqa: E402
from scripts.exception_log import ExceptionLog  # noqa: E402


def test_instrumentar_emits_registro_and_reraises(tmp_path: Path) -> None:
    """G2: a raised exception inside `instrumentar` emits a registro AND
    re-raises (it is NOT swallowed)."""
    log = ExceptionLog(tmp_path / "run")
    with pytest.raises(TimeoutError):
        with instrumentar(fase="despacho", slot="1", puesto="auditores",
                          route_id="r", log=log, expected="200 OK"):
            raise TimeoutError("timed out after 30s")
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["clase"] == "net.timeout"
    assert rows[0]["fase"] == "despacho"


def test_instrumentar_no_registro_when_no_exception(tmp_path: Path) -> None:
    """No exception => no registro. Happy path is not noisy."""
    log = ExceptionLog(tmp_path / "run")
    with instrumentar(fase="despacho", slot="1", puesto="p", route_id="r", log=log):
        pass  # happy path
    assert log.count() == 0


def test_registrar_resultado_fallido_logs_from_error_string(tmp_path: Path) -> None:
    """The (ok=False) return-shape path: build a registro from the error str."""
    log = ExceptionLog(tmp_path / "run")
    r = registrar_resultado_fallido(
        error_str="http_429", fase="despacho", slot="1", puesto="p",
        route_id="r", log=log, expected="200 OK")
    assert r.clase == "net.rate_limited"
    assert log.count() == 1


def test_aplicar_accion_defecto_for_net_enters_fallback(tmp_path: Path) -> None:
    log = ExceptionLog(tmp_path / "run")
    r = registrar_resultado_fallido(
        error_str="http_503", fase="despacho", slot="1", puesto="p",
        route_id="r", log=log)
    a = aplicar_accion_defecto(r)
    assert a.action == ENTER_FALLBACK


def test_aplicar_accion_defecto_for_mount_absent_halts(tmp_path: Path) -> None:
    log = ExceptionLog(tmp_path / "run")
    with pytest.raises(Exception):
        with instrumentar(fase="despacho", slot="1", puesto="p", route_id="r",
                          log=log):
            raise Exception("INTERCAMBIO_SHARE_UNAVAILABLE: no markers")
    rows = log.read_all()
    assert rows[0]["clase"] == "fs.mount_absent"
    from scripts.exception_instrumentation import aplicar_accion_defecto
    # rebuild a registro-like from the row to check the action
    from scripts.exception_registro import build_registro
    reg = build_registro(slot="1", puesto="p", route_id="r", fase="despacho",
                         clase="fs.mount_absent", expected="x", excerpt="x")
    assert aplicar_accion_defecto(reg).action == HALT_RUN


def test_log_failure_does_not_mask_original_exception(tmp_path: Path) -> None:
    """If the log write itself raises, the original exception still propagates."""
    class BrokenLog(ExceptionLog):
        def append(self, registro):
            raise OSError("log disk full")
    log = BrokenLog(tmp_path / "run")  # type: ignore[arg-type]
    with pytest.raises(TimeoutError):  # original, not the OSError
        with instrumentar(fase="despacho", slot="1", puesto="p", route_id="r",
                          log=log):
            raise TimeoutError("timed out")
