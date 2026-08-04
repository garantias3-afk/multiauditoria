"""exception_instrumentation.py — E2 wiring (OT sec 4 / G2).

Wraps the runner's exception paths so EVERY raised exception or (ok=False)
invocation result emits an exception registro BEFORE the default action runs.
Nothing is swallowed in silence (G2): the registro is written even when the
default action later advances/halts.

Designed to wrap, not rewrite, the existing runner (decision: wrap existing
runner). Two entry points:

  instrumentar(fase, slot, puesto, route_id, log)  -> context manager
      Catches exceptions raised inside the `with` block, classifies, logs a
      registro, and re-raises (the caller applies the default action). The
      registro is always written; the exception is never eaten silently.

  registrar_resultado_fallido(result, *, fase, slot, puesto, route_id, log,
                              expected, found_path, http_code) -> registro | None
      For the (ok=False) return-shape used by Invoker/worker_gateway: builds and
      logs a registro from the error string without raising.

Both go through classify_from_signal so the classification is consistent with
the real worker_gateway._post_json error shapes.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator, Optional

from scripts.default_actions import action_for
from scripts.exception_log import ExceptionLog
from scripts.exception_registro import ExceptionRegistro, build_registro
from scripts.exception_taxonomy import classify_from_signal


@contextlib.contextmanager
def instrumentar(
    *,
    fase: str,
    slot: str,
    puesto: str,
    route_id: str,
    log: ExceptionLog,
    expected: str = "",
    found_path: Optional[Path] = None,
    http_code: Optional[int] = None,
) -> Iterator[None]:
    """Context manager that emits a registro for any exception raised inside.

    The exception is RE-RAISED after the registro is written. The caller is
    responsible for applying the default action (advance/halt/escalate) via
    `default_actions.action_for`. We do not swallow the exception here — that
    would violate G2 (nothing swallowed in silence) and would hide the signal
    from the caller's fallback-ladder logic.

    Why re-raise instead of applying the default action here: the runner's
    dispatch/fallback-ladder already knows how to react to a net.* (enter
    fallback) vs fs.mount_absent (halt). Centralising that reaction would
    duplicate the ladder. The instrumentation's job is to OBSERVE and RECORD,
    not to decide.
    """
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — we re-raise, we do not hide.
        # Classify from the live exception (carries errno/type) plus its str.
        cls = classify_from_signal(_signal_of(exc), fase=fase, exc=exc)
        registro = build_registro(
            slot=slot, puesto=puesto, route_id=route_id, fase=fase,
            clase=cls.clase, expected=expected or _expected_for(fase),
            excerpt=str(exc), found_path=found_path, http_code=http_code,
            raw_condition=cls.raw_condition,
        )
        try:
            log.append(registro)
        except Exception:
            # Logging must never mask the original exception. If the log write
            # itself fails (e.g. disk full — which would itself be a fs.* class),
            # we still re-raise the original so the runner's default action runs.
            pass
        raise


def registrar_resultado_fallido(
    *,
    error_str: str,
    fase: str,
    slot: str,
    puesto: str,
    route_id: str,
    log: ExceptionLog,
    expected: str = "",
    found_path: Optional[Path] = None,
    http_code: Optional[int] = None,
) -> ExceptionRegistro:
    """Build + log a registro from a (ok=False) result's error string.

    This is the path for worker_gateway._post_json-style results that return
    (False, {"error": "http_429"}) instead of raising. Returns the registro so
    the caller can read its class and apply the default action.
    """
    cls = classify_from_signal(error_str, fase=fase)
    registro = build_registro(
        slot=slot, puesto=puesto, route_id=route_id, fase=fase,
        clase=cls.clase, expected=expected or _expected_for(fase),
        excerpt=error_str, found_path=found_path, http_code=http_code,
        raw_condition=cls.raw_condition,
    )
    log.append(registro)
    return registro


def aplicar_accion_defecto(registro: ExceptionRegistro) -> Any:
    """Return the declared default action for a registro's class.

    The runner calls this to decide what to do after a registro is written.
    Returns a DefaultAction (advance / enter_fallback / escalate_t2 / halt).
    """
    return action_for(registro.clase)


# ----- helpers ----- #

def _signal_of(exc: BaseException) -> str:
    """Reconstruct a worker_gateway-style signal from a raised exception.

    _post_json returns error strings like 'http_429' or 'TimeoutError: ...';
    when the same failure surfaces as a raised exception we rebuild an
    equivalent signal so classify_from_signal maps it consistently.
    """
    # urllib.error.HTTPError carries a .code
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return f"http_{code}"
    return f"{type(exc).__name__}: {exc}"


def _expected_for(fase: str) -> str:
    """A human hint of what the runner expected at each fase."""
    return {
        "despacho": "la invocacion del proveedor devuelve (ok, contenido)",
        "recoleccion": "artefacto final presente y legible",
        "validacion": "artefacto conforme al esquema",
        "escritura": "escritura atomica completada (archivo final presente)",
        "gate": "el gate del slot pasa",
    }.get(fase, "operacion exitosa")
