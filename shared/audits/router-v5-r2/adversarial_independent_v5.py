#!/usr/bin/env python3
from __future__ import annotations

from router_v5 import axes_of, route


CASES = [
    # Python name and scope resolution.
    ("nested eval must not shadow another scope", "m.py", "def outer():\n    def eval(x): return x\n    return eval('safe')\ndef dangerous(s):\n    return eval(s)\n", "seguridad", True),
    ("class eval method must not shadow builtin", "m.py", "class C:\n    def eval(self,x): return x\ndef dangerous(s):\n    return eval(s)\n", "seguridad", True),
    ("builtins.eval direct", "m.py", "import builtins\ndef f(s):\n    return builtins.eval(s)\n", "seguridad", True),
    ("from builtins import eval", "m.py", "from builtins import eval as builtin_eval\ndef f(s):\n    return builtin_eval(s)\n", "seguridad", True),
    # Safe loader must be validated by origin, not spelling alone.
    ("foreign SafeLoader is not yaml safe loader", "m.py", "from evil import SafeLoader\nimport yaml\ndef f(s):\n    return yaml.load(s, Loader=SafeLoader)\n", "seguridad", True),
    ("local SafeLoader spoof", "m.py", "import yaml\nSafeLoader = object()\ndef f(s):\n    return yaml.load(s, Loader=SafeLoader)\n", "seguridad", True),
    ("shell integer truthy", "m.py", "import subprocess\ndef f(c):\n    return subprocess.run(c, shell=1)\n", "seguridad", True),
    # Known security/concurrency false negatives declared by the author.
    ("hardcoded password argument", "client.py", "def connect(**kw): pass\nconnect(password='secret')\n", "seguridad", True),
    ("hardcoded authorization header", "client.py", "import requests\nrequests.get('https://x', headers={'Authorization':'Bearer hardcoded'})\n", "seguridad", True),
    ("builtins getattr eval", "m.py", "import builtins\ndef f(s):\n    return getattr(builtins, 'eval')(s)\n", "seguridad", True),
    ("gevent spawn", "jobs.py", "import gevent\ndef f():\n    gevent.spawn(work)\n", "concurrencia", True),
    ("eventlet spawn", "jobs.py", "import eventlet\ndef f():\n    eventlet.spawn(work)\n", "concurrencia", True),
    # JS/shell stripping and raw-text leaks.
    ("JS regex literal is not executable eval", "a.js", "const r = /eval(userInput)/;\n", "seguridad", False),
    ("JS template interpolation executes eval", "a.js", "const x = `${eval(userInput)}`;\n", "seguridad", True),
    ("JS commented crypto import", "a.js", "// import crypto from 'crypto';\nconst x=1;\n", "seguridad", False),
    ("JS commented secret assignment", "a.js", "// const api_key = 'AKIA123456';\nconst x=1;\n", "seguridad", False),
    ("shell command substitution executes curl", "d.sh", "#!/bin/sh\necho \"$(curl https://example.invalid)\"\n", "seguridad", True),
    # Reappearance of substring matching in SECRET_NAME.search().
    ("monkey is not key", "zoo.py", "monkey = 'banana'\n", "seguridad", False),
    ("secretary is not secret", "office.py", "secretary = 'Alice'\n", "seguridad", False),
    ("tokenizer is not token", "nlp.json", '{"tokenizer":"gpt"}\n', "seguridad", False),
    # The implementation claims semantic definitions/calls, but only definitions are critical.
    ("authorize call without local definition", "handler.py", "def f(user):\n    return authorize(user)\n", "seguridad", True),
]

failures = []
for name, path, src, axis, expected in CASES:
    axes = axes_of(path, src)
    actual = axis in axes
    passed = actual == expected
    print(f"{'PASS' if passed else 'FAIL'} {name}: expected={expected} actual={actual} axes={axes}")
    if not passed:
        evidence = [
            r for r in route(path, src)
            if r["axis"] == axis and r["decision"] != "rejected"
        ]
        failures.append({"name": name, "axes": axes, "evidence": evidence})

print(f"\n{len(CASES) - len(failures)} PASS / {len(failures)} FAIL")
for item in failures:
    print(item)
raise SystemExit(bool(failures))
