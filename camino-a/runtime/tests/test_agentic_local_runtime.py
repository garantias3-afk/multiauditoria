from pathlib import Path

from scripts.internal_loop_runner import independent_test_verification
from scripts.worker_agentic_local import AgenticLocalWorker


def test_local_agentic_checks_do_not_depend_on_user_cache_permissions(
    tmp_path: Path, monkeypatch,
) -> None:
    workdir = tmp_path / "target"
    workdir.mkdir()
    (workdir / "sample.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/root/not-writable/camino")

    worker = AgenticLocalWorker(test_timeout_seconds=15)
    assert worker.audit(workdir) == []
    verification = independent_test_verification(workdir)
    assert verification["passed"] is True
    assert all(check["returncode"] == 0 for check in verification["checks"])
