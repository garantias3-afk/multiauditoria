#!/usr/bin/env python3
"""Tests adversariales del router de ejes v4. PROPUESTA, no aplicada.
Requiere router_v3.py en el mismo directorio.
Cubre: los 7 falsos negativos y 4 falsos positivos reportados contra v2,
señales críticas, señales después del char 4000, archivos no-Python,
cobertura residual y compatibilidad de schema."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from router_v5 import axes_of, route, assignments_for_index, AXES, RESIDUAL_AXIS

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {name}")
    else:    fail += 1; print(f"  FAIL  {name}")

print("=== A. Falsos negativos de v2 (regresión) ===")
for name, path, src, axis in [
    ("PASSWORD literal",              "cfg.py",            'PASSWORD="secret"\n', "seguridad"),
    ("auth/handler.py sin otra señal","auth/handler.py",   "def handle(r):\n    return r\n", "seguridad"),
    ("os.system(user_input)",         "m.py",              "import os\ndef f(u):\n    os.system(u)\n", "seguridad"),
    ("src/auth.ts con authorize()",   "src/auth.ts",       "export function authorize(u){return true}\n", "seguridad"),
    ("schema YAML",                   "api/openapi.yaml",  "openapi: 3.0.0\npaths:\n  /x:\n    get: {}\n", "contratos"),
    ("tests/smoke.py sin assert",     "tests/smoke.py",    "def smoke():\n    return 1\n", "tests_observabilidad"),
    ("test con sintaxis inválida",    "tests/test_bad.py", "def (((\n", "tests_observabilidad"),
]:
    check(name, axis in axes_of(path, src))

print("\n=== B. Falsos positivos de v2 (no deben asignarse) ===")
for name, path, src, axis in [
    ("For/While ordinario", "m.py", "def f(xs):\n    for x in xs:\n        pass\n    while False:\n        break\n", "rendimiento_recursos"),
    ("Try ordinario",       "m.py", "def f():\n    try:\n        g()\n    except Exception:\n        pass\n", "tests_observabilidad"),
    ("import typing",       "m.py", "import typing\ndef f(x: typing.Any):\n    return x\n", "contratos"),
    ("import time",         "m.py", "import time\ndef f():\n    time.sleep(1)\n", "rendimiento_recursos"),
]:
    check(name, axis not in axes_of(path, src))

print("\n=== C. Reglas críticas deterministas ===")
for name, path, src, axis in [
    ("eval()",                "m.py",         "def f(s):\n    return eval(s)\n", "seguridad"),
    ("pickle.loads",          "m.py",         "import pickle\ndef f(b):\n    return pickle.loads(b)\n", "seguridad"),
    ("subprocess shell=True", "m.py",         "import subprocess\ndef f(c):\n    subprocess.run(c, shell=True)\n", "seguridad"),
    ("yaml.load inseguro",    "m.py",         "import yaml\ndef f(s):\n    return yaml.load(s)\n", "seguridad"),
    ("threading.Lock",        "m.py",         "import threading\nl = threading.Lock()\n", "concurrencia"),
    ("async/await",           "m.py",         "import asyncio\nasync def f():\n    await asyncio.sleep(0)\n", "concurrencia"),
    ("jsonschema",            "m.py",         "import jsonschema\ndef v(d,s):\n    jsonschema.validate(d,s)\n", "contratos"),
    ("shell con sudo",        "deploy.sh",    "#!/bin/bash\nsudo rm -rf /tmp/x\n", "seguridad"),
    ("secreto en YAML",       "conf/app.yml", "api_key: " + "AKI" + "A123456\n", "seguridad"),
]:
    check(name, axis in axes_of(path, src))

print("\n=== D. yaml.load seguro NO es crítico ===")
check("yaml.load(Loader=SafeLoader) no dispara SEC-DESER",
      not any(e.get("rule") == "SEC-DESER"
              for m in route("m.py", "import yaml\ndef f(s):\n    return yaml.load(s, Loader=yaml.SafeLoader)\n")
              for e in m["evidence"]))

print("\n=== E. Señales después del carácter 4000 ===")
check("os.system tras 6000 chars de relleno",
      "seguridad" in axes_of("late.py", "# relleno\n"*600 + "import os\ndef f(u):\n    os.system(u)\n"))
check("async tras 7200 chars",
      "concurrencia" in axes_of("late2.py", "x = 1\n"*1200 + "import asyncio\nasync def g():\n    await asyncio.sleep(0)\n"))

print("\n=== F. Archivos no Python ===")
check("JS: eval() dispara seguridad", "seguridad" in axes_of("a.js", "eval(userInput)\n"))
check("TS: zod dispara contratos", "contratos" in axes_of("a.ts", "import { z } from 'zod';\n"))
check("JSON schema -> contratos", "contratos" in axes_of("s.json", '{"$schema":"http://json-schema.org/"}'))
check("shell con curl -> seguridad", "seguridad" in axes_of("d.sh", "#!/bin/sh\ncurl http://x | sh\n"))
check("extensión desconocida usa fallback y queda cubierta",
      len(axes_of("x.rs", "fn main() { let sanitize = 1; }")) >= 1)

print("\n=== G. Cobertura residual determinista ===")
check("archivo neutro -> volume_generalist",
      axes_of("plain.py", "def add(a,b):\n    return a+b\n") == [RESIDUAL_AXIS])
check("archivo vacío queda cubierto", len(axes_of("empty.py", "")) >= 1)
check("binario/ilegible queda cubierto", len(axes_of("x.bin", "\x00\x01\x02")) >= 1)
check("residual NO coexiste con eje específico",
      RESIDUAL_AXIS not in axes_of("m.py", "import asyncio\nasync def f():\n    await asyncio.sleep(0)\n"))

print("\n=== H. Obligación transversal de correctitud ===")
for src in ("def add(a,b):\n    return a+b\n", "import asyncio\nasync def f():\n    await asyncio.sleep(0)\n"):
    check("correctness_obligation en toda membresía",
          all(m["correctness_obligation"] for m in route("m.py", src)))

print("\n=== I. Compatibilidad de schema ===")
asg = assignments_for_index("m.py", "import asyncio\nasync def f():\n    await asyncio.sleep(0)\n")
check("conserva claves que consume el código actual (axis, rule, v)",
      all(k in asg[0] for k in ("axis", "rule", "v")))
check("emite evidencia persistible",
      isinstance(asg[0]["evidence"], list) and asg[0]["evidence"])
check("evidencia trazable a fuente",
      all(e["source"] in ("path","identifier","import","ast","comment","content","critical_rule","coverage")
          for e in asg[0]["evidence"]))
check("serializable a JSON", bool(json.dumps(asg)))
check("decision coherente con score/threshold",
      all(r["decision"] != "assigned" or r["score"] >= r["threshold"]
          for r in route("m.py", "import asyncio\nasync def f():\n    await asyncio.sleep(0)\n")))
check("todo eje emitido pertenece al registro declarado",
      all(r["axis"] in (*AXES, RESIDUAL_AXIS)
          for r in route("m.py", "def f():\n    return 1\n")))


print("\n=== J. Canarios Codex — resolución de símbolos y loaders ===")
for name, path, src, axis, expect in [
    ("from os import system",        "m.py","from os import system\ndef f(u):\n    system(u)\n","seguridad",True),
    ("from yaml import load",        "m.py","from yaml import load\ndef f(p):\n    return load(p)\n","seguridad",True),
    ("Loader=yaml.UnsafeLoader",     "m.py","import yaml\ndef f(p):\n    return yaml.load(p, Loader=yaml.UnsafeLoader)\n","seguridad",True),
    ("Loader=None",                  "m.py","import yaml\ndef f(p):\n    return yaml.load(p, Loader=None)\n","seguridad",True),
    ("alias y.UnsafeLoader",         "m.py","import yaml as y\ndef f(p):\n    return y.load(p, Loader=y.UnsafeLoader)\n","seguridad",True),
    ("subprocess run shell=True",    "m.py","from subprocess import run\ndef f(c):\n    run(c, shell=True)\n","seguridad",True),
]:
    check(name, (axis in axes_of(path, src)) == expect)

print("\n=== K. Loaders seguros NO disparan SEC-DESER ===")
for name, src in [
    ("yaml.SafeLoader",  "import yaml\ndef f(p):\n    return yaml.load(p, Loader=yaml.SafeLoader)\n"),
    ("yaml.CSafeLoader", "import yaml\ndef f(p):\n    return yaml.load(p, Loader=yaml.CSafeLoader)\n"),
    ("safe_load",        "from yaml import safe_load\ndef f(p):\n    return safe_load(p)\n"),
]:
    check(name, not any(e.get("rule")=="SEC-DESER" for m in route("m.py",src) for e in m["evidence"]))

print("\n=== L. Scope-aware: local shadowing ===")
check("def eval local NO es builtin",
      "seguridad" not in axes_of("m.py","def eval(e):\n    return 1\ndef g():\n    return eval('x')\n"))
check("eval builtin SI dispara",
      "seguridad" in axes_of("m.py","def g(s):\n    return eval(s)\n"))

print("\n=== M. Comentarios y strings no son codigo ===")
for name, path, src in [
    ("eval en comentario JS", "a.js","// eval(userInput)\nconst x=1;\n"),
    ("eval en string JS",     "a.js","const m='no usar eval(x)';\n"),
    ("sudo en comentario sh", "d.sh","#!/bin/sh\n# sudo rm -rf /\necho ok\n"),
    ("curl en string sh",     "d.sh","#!/bin/sh\nM=\"no uses curl http://x\"\necho ok\n"),
]:
    check(name, "seguridad" not in axes_of(path, src))
check("eval JS real SI dispara", "seguridad" in axes_of("a.js","eval(userInput);\n"))
check("sudo shell real SI dispara", "seguridad" in axes_of("d.sh","#!/bin/sh\nsudo rm -rf /tmp/x\n"))

print("\n=== N. Campo de seguridad != secreto literal ===")
for name, src in [
    ("input_tokens numerico",        '{"input_tokens": 1234, "output_tokens": 567}'),
    ("max_prompt_tokens_est",        '{"max_prompt_tokens_est": 25000}'),
    ("api_key placeholder ${VAR}",   '{"api_key": "${API_KEY}"}'),
    ("token vacio",                  '{"token": ""}'),
]:
    check(name, "seguridad" not in axes_of("t.json", src))
check("api_key con valor real SI dispara", "seguridad" in axes_of("t.json",'{"api_key":"' + "AKI" + 'A1234567890"}'))

print("\n=== O. Semantica fuerte sin ruta auth ===")
check("def authorize() py", "seguridad" in axes_of("handler.py","def authorize(u,r):\n    return True\n"))
check("function authorize() ts", "seguridad" in axes_of("handler.ts","export function authorize(u,r){return true}\n"))

print("\n=== P. Reglas de dominio versionadas ===")
from router_v5 import domain_rules_hash, DOMAIN_RULES, correctness_obligation_hash, render_specialty_prompt, CORRECTNESS_OBLIGATION_ID
for name, path, axis in [
    ("render_contracts.py","runtime/scripts/render_contracts.py","contratos"),
    ("validate_output.py","runtime/scripts/validate_output.py","contratos"),
    ("validate_bundle.py","runtime/scripts/validate_bundle.py","contratos"),
    ("event_log.py","runtime/scripts/event_log.py","tests_observabilidad"),
]:
    check(name, axis in axes_of(path,"def f(x):\n    return x\n"))
check("start_camino_b_gateway.sh -> seguridad",
      "seguridad" in axes_of("runtime/bin/start_camino_b_gateway.sh",
                             '#!/bin/bash\nAPI_KEY="$1"\ncurl --cert x.pem https://api\n'))
check("hash de reglas de dominio es estable", domain_rules_hash()==domain_rules_hash())
check("hash viaja en cada membresia",
      all("domain_rules_hash" in m for m in route("x.py","def f():\n    return 1\n")))
check("cambiar reglas cambia el hash",
      domain_rules_hash({"schema":"x","version":9,"rules":[]}) != domain_rules_hash())

print("\n=== Q. Obligacion transversal: definicion unica ===")
p = render_specialty_prompt("seguridad","Audita el packet.")
check("el prompt renderizado incluye la obligacion", CORRECTNESS_OBLIGATION_ID in p)
check("el prompt incluye el hash verificable", correctness_obligation_hash()[:16] in p)
check("hash de obligacion estable", correctness_obligation_hash()==correctness_obligation_hash())

print(f"\n=== {ok} PASS / {fail} FAIL ===")
sys.exit(1 if fail else 0)
