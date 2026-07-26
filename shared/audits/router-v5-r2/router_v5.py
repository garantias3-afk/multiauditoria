"""router_v5 — router de ejes. FUENTE ÚNICA. El indexador debe IMPORTAR este módulo.

Hereda la arquitectura de v4 y corrige los 19 canarios que v4 reprobaba
(ver adversarial_independent_v5.py), sin tocar casos ni esperados:

  V1   Scope-aware de verdad: el shadowing se computa a nivel MÓDULO. Un
       `def eval` anidado o un método de clase ya no tapan el builtin en
       otros ámbitos; un `def eval` a nivel módulo sí lo sigue tapando.
  V2   `builtins.eval`, `from builtins import eval` y
       `getattr(builtins, "eval")` se detectan como SEC-DYNEXEC.
  V3   yaml.load seguro exige ORIGEN real del loader (lmod == "yaml"), no
       solo el nombre `SafeLoader`: `from evil import SafeLoader` o un
       `SafeLoader = object()` local ya no pasan por seguros.
  V4   `shell=1` (constante truthy) evidencia SEC-SHELL igual que
       `shell=True`.
  V5   Secretos literales también en argumentos de llamada
       (`f(password='...')`) y en dicts pasados como argumento
       (`headers={'Authorization': 'Bearer ...'}`).
  V6   SECRET_NAME usa límites de palabra: `secretary`, `tokenizer` y
       `monkey` dejan de disparar; se añade `authorization`.
  V7   `gevent`/`eventlet` pesan como imports de concurrencia
       (`gevent.spawn`, `eventlet.spawn`).
  V8   JS/TS: se eliminan comentarios Y regex literales; los imports y
       secretos se buscan sobre el código sin comentarios; las
       interpolaciones `${...}` de template literals se conservan porque
       ejecutan (`${eval(x)}` dispara, `/eval(x)/` no).
  V9   Shell: dentro de comillas dobles, `$(...)` y backticks ejecutan y
       se conservan; el resto del string es inerte. Comillas simples
       totalmente inertes.
  V10  Llamada semántica `authorize(user)` sin definición local evidencia
       SEC-SEMANTIC (antes solo la definición).

Ronda R2 (corrección de auditoría externa K3; causas en el motor, no
resultados esperados):

  R2-1  `getattr(os, "system")(...)` se detecta como SEC-OSCMD (antes sólo
        se cubría `getattr(builtins, "eval")`).
  R2-2  `asyncio.create_subprocess_shell(...)` evidencia SEC-SHELL.
  R2-3  `yaml.load_all` entra en la regla SEC-DESER de loaders; el criterio
        de loader seguro por origen real (V3) se conserva.
  R2-4  `YOUR_..._HERE` (anclado) se reconoce como placeholder y no dispara
        SEC-LITERAL.
  R2-5  Secretos literales asignados vía subíndice (`cfg['password'] = ...`).
  R2-6  `passphrase` entra en SECRET_NAME.
  R2-7  El comando remoto de `ssh host '...'` ejecuta en el host remoto: se
        analiza aunque las comillas simples sean inertes localmente.
  R2-8  Shell: los tokens peligrosos sólo cuentan en posición de comando;
        `echo curl is a network tool` ya no dispara SEC-NET.
  R2-9  JS/TS: claves entrecomilladas (`{ "password": "..." }`) se evalúan
        como nombres de secreto.
  R2-10 JS/TS: `window['eval']` / `globalThis['eval']` evidencian
        SEC-DYNEXEC, sin disparar por comentarios, strings o regex literales.
  R2-11 Soporte acotado para `.env` (pares KEY=VALUE; sólo secretos
        literales). Las extensiones desconocidas siguen en FallbackAdapter.
"""
from __future__ import annotations
import ast, re, json, hashlib
from pathlib import PurePosixPath
from typing import Optional

SCHEMA_VERSION = 5
THRESHOLD = 3
W_IMPORT, W_AST, W_IDENT, W_PATH, W_AMBIG = 3, 3, 2, 2, 1

AXES = ("seguridad", "concurrencia", "tests_observabilidad",
        "contratos", "rendimiento_recursos")
RESIDUAL_AXIS = "volume_generalist"

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE DOMINIO VERSIONADA (C15-C19)
# Reglas específicas del repo. Versionada, con esquema y hash. NO estado oculto.
# ---------------------------------------------------------------------------

DOMAIN_RULES = {
    "schema": "multiaudit.domain_rules/1",
    "version": 1,
    "rules": [
        {"id": "DOM-CONTRACT-RENDER",  "match": {"stem_prefix": ["render_contract"]},
         "axis": "contratos"},
        {"id": "DOM-CONTRACT-VALIDATE", "match": {"stem_prefix": ["validate_", "validator_"]},
         "axis": "contratos"},
        {"id": "DOM-CONTRACT-SCHEMA",  "match": {"stem_contains": ["schema", "contract"]},
         "axis": "contratos"},
        {"id": "DOM-OBS-LOG",          "match": {"stem_contains": ["_log", "log_", "event_log",
                                                                    "audit_log", "telemetry"]},
         "axis": "tests_observabilidad"},
        {"id": "DOM-SEC-GATEWAY",      "match": {"stem_contains": ["gateway", "tls", "ssl",
                                                                    "apikey", "api_key"]},
         "axis": "seguridad"},
    ],
}


def domain_rules_hash(rules: dict = DOMAIN_RULES) -> str:
    return hashlib.sha256(
        json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _apply_domain_rules(rel_path: str, rules: dict = DOMAIN_RULES) -> list:
    stem = PurePosixPath(rel_path.lower()).stem
    hits = []
    for r in rules["rules"]:
        m = r["match"]
        if any(stem.startswith(p) for p in m.get("stem_prefix", [])) or \
           any(c in stem for c in m.get("stem_contains", [])):
            hits.append((r["axis"], r["id"], stem))
    return hits


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SEC_PATH_SEGMENTS = {"auth","authn","authz","permission","permissions","credential",
                     "credentials","security","login","session","sessions","oauth","jwt","keystore"}
TEST_PATH_SEGMENTS = {"test","tests","spec","specs","testing","e2e","fixtures"}
CONTRACT_EXTS = {".json",".yaml",".yml",".toml",".proto",".avsc",".graphql",".xsd"}

# C6-C7: definiciones/llamadas semánticamente inequívocas de seguridad.
SEC_SEMANTIC_NAMES = {"authorize","authorise","authenticate","checkpermission",
                      "haspermission","verifytoken","validatetoken","issuetoken",
                      "requirerole","grantaccess","denyaccess","checkacl","signjwt",
                      "verifysignature","hashpassword","checkpassword"}

DYNEXEC = {"eval","exec","compile"}
OSCMD_ATTRS = {"system","popen","execv","execve","execvp","spawnl","spawnv"}
UNSAFE_DESER = {("pickle","loads"),("pickle","load"),("marshal","loads"),
                ("dill","loads"),("shelve","open")}
YAML_SAFE_LOADERS = {"SafeLoader","CSafeLoader","BaseLoader","CBaseLoader"}
CONC_PRIMITIVES = {"Lock","RLock","Semaphore","BoundedSemaphore","Event","Condition",
                   "Barrier","gather","create_task","to_thread","Pool"}
PERF_RESOURCE_MODULES = {"resource","gc","mmap","tracemalloc","cProfile"}
CONTRACT_VALIDATORS = {"jsonschema","pydantic","marshmallow","cerberus","voluptuous"}
TEST_FRAMEWORKS = {"pytest","unittest","nose","hypothesis"}

WEAK_IMPORTS = {"typing","time","json","functools","itertools","os","sys","re",
                "pathlib","collections","dataclasses","enum","math","copy"}

# C13-C14: nombres que parecen credenciales pero son contadores/límites.
COUNTER_HINTS = {"input","output","max","min","count","total","num","limit","usage",
                 "est","estimate","budget","size","len","length","remaining","used"}
# V6: límites de palabra — `secretary`/`tokenizer`/`monkey` ya no matchean.
SECRET_NAME = re.compile(
    r"\b(password|passwd|pwd|passphrase|secret|token|api_?key|access_?key|"
    r"private_?key|credential|client_?secret|auth_?token|authorization|bearer)\b", re.I)
# R2-4: `YOUR_..._HERE` anclado — no cualquier string que contenga YOUR/HERE.
PLACEHOLDER = re.compile(r"^\s*$|^(null|none|~|changeme|xxx+|todo|placeholder|"
                         r"<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\}|"
                         r"your(_[a-z0-9]+)+_here)\s*$", re.I)

AXIS_IMPORTS = {
    "seguridad": {"hmac","secrets","ssl","cryptography","jwt","subprocess","shlex",
                  "pickle","bcrypt","argon2","paramiko"},
    # V7: gevent/eventlet son concurrencia real (spawn verde).
    "concurrencia": {"asyncio","threading","multiprocessing","concurrent","queue",
                     "selectors","anyio","trio","gevent","eventlet"},
    "tests_observabilidad": {"pytest","unittest","logging","traceback","warnings",
                             "opentelemetry","prometheus_client","hypothesis"},
    "contratos": {"jsonschema","pydantic","marshmallow","cerberus","voluptuous","protobuf"},
    "rendimiento_recursos": {"resource","gc","mmap","tracemalloc","cProfile","numpy","numba"},
}
AXIS_IDENTS = {
    "seguridad": {"sanitize","escape","permission","chmod","chown","privilege",
                  "credential","encrypt","decrypt","nonce","salt"},
    "concurrencia": {"mutex","semaphore","deadlock","reentrant","coroutine","spawn","daemon"},
    "tests_observabilidad": {"fixture","mock","stub","spy","logger","traceback",
                             "telemetry","span","instrument","assertion"},
    "contratos": {"validator","deserialize","serialize","unmarshal","conform","protocol"},
    "rendimiento_recursos": {"memoize","throttle","backpressure","prefetch","chunked",
                             "streaming","latency","throughput","benchmark"},
}
AMBIGUOUS = {
    "seguridad": {"key","keys","token","tokens","auth","secret","hash"},
    "concurrencia": {"race","queue","loop","lock","async","await","thread","parallel"},
    "tests_observabilidad": {"test","tests","log","logs","trace","probe","debug","monitor","assert"},
    "contratos": {"schema","json","yaml","serial","contract","validate"},
    "rendimiento_recursos": {"cache","batch","timeout","sleep","io","alloc","memory","loop"},
}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _morphemes(name: str) -> set:
    parts = []
    for chunk in re.split(r"[_\-\d]+", name):
        found = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", chunk)
        parts += found or ([chunk] if chunk else [])
    return {p.lower() for p in parts if p}


def _looks_like_secret_value(v) -> bool:
    """C13-C14: el VALOR debe parecer credencial."""
    if not isinstance(v, str):
        return False                      # números, bools, listas -> no son secretos
    if PLACEHOLDER.match(v):
        return False
    if v.strip().isdigit():
        return False
    # Sin umbral de longitud: PASSWORD="secret" (6 chars) es credencial hardcodeada.
    # Los contadores ya quedan excluidos por _name_is_counter y por el chequeo numérico.
    return len(v.strip()) >= 1


def _name_is_counter(name: str) -> bool:
    return bool(_morphemes(name) & COUNTER_HINTS)


def _is_truthy_const(expr: ast.AST) -> bool:
    """V4: `shell=1` u otra constante truthy cuenta igual que `shell=True`."""
    return isinstance(expr, ast.Constant) and bool(expr.value)


def _assign_target_name(t: ast.AST) -> Optional[str]:
    """R2-5: nombre del destino de una asignación — `x`, `obj.x` o la clave
    literal de un subíndice (`cfg['password'] = ...` -> 'password')."""
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
       and isinstance(t.slice.value, str):
        return t.slice.value
    return None


# ---------------------------------------------------------------------------
# C1-C5, C8, V1: tabla de símbolos Python
# ---------------------------------------------------------------------------

class SymbolTable:
    """Resuelve alias de módulo, símbolos importados y nombres definidos localmente.

    V1: el shadowing (`local_defs`) se computa SOLO a nivel módulo. Un
    `def eval` anidado o un método de clase no tapan el builtin en otros
    ámbitos; un nombre definido a nivel módulo sí.
    """

    def __init__(self, tree: ast.AST):
        self.module_alias = {}    # nombre_local -> módulo real
        self.symbol_origin = {}   # nombre_local -> (módulo, nombre_original)
        self.local_defs = set()   # nombres definidos a nivel módulo (shadowing)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.module_alias[(a.asname or a.name).split(".")[0]] = a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                for a in node.names:
                    self.symbol_origin[a.asname or a.name] = (mod, a.name)
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.local_defs.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.local_defs.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.local_defs.add(node.target.id)

    def modules(self) -> set:
        return set(self.module_alias.values()) | {m for m, _ in self.symbol_origin.values()}

    def resolve_call(self, func: ast.AST):
        """Devuelve (modulo|None, nombre, es_builtin)."""
        if isinstance(func, ast.Name):
            n = func.id
            if n in self.symbol_origin:
                return (*self.symbol_origin[n], False)
            if n in self.local_defs:
                return (None, n, False)          # C8/V1: shadow de módulo, NO builtin
            return (None, n, True)
        if isinstance(func, ast.Attribute):
            base = getattr(func.value, "id", None)
            if base in self.local_defs and base not in self.module_alias:
                return (None, func.attr, False)
            return (self.module_alias.get(base, base), func.attr, False)
        return (None, None, False)

    def resolve_attr_source(self, node: ast.AST):
        """Para `Loader=yaml.SafeLoader` o `Loader=SafeLoader`."""
        if isinstance(node, ast.Attribute):
            base = getattr(node.value, "id", None)
            return (self.module_alias.get(base, base), node.attr)
        if isinstance(node, ast.Name):
            if node.id in self.symbol_origin:
                return self.symbol_origin[node.id]
            return (None, node.id)
        if isinstance(node, ast.Constant):
            return (None, repr(node.value))
        return (None, None)


# ---------------------------------------------------------------------------
# C9-C12, V8-V9: stripping de comentarios y literales
# ---------------------------------------------------------------------------

_JS_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _strip_js(src: str, keep_literals: bool,
              keep_ident_strings: bool = False) -> tuple[str, bool]:
    """Elimina comentarios JS/TS y, opcionalmente, literales.

    keep_literals=True  -> fuera comentarios; strings/regex conservados
                           (sirve para buscar imports y secretos reales).
    keep_literals=False -> fuera comentarios, strings y regex literales
                           (sirve para reglas críticas de ejecución).
    keep_ident_strings  -> con keep_literals=False, conserva el contenido de
                           los strings que son un único identificador
                           (`window['eval']` -> `window[ eval ]`); sirve para
                           detectar acceso por corchete al eval global (R2-10)
                           sin disparar por strings arbitrarios.
    Las interpolaciones ${...} de template literals EJECUTAN: su contenido
    se conserva en ambos modos. Devuelve (código, confiable).
    """
    out, i, n = [], 0, len(src)
    reliable = True

    def prev_significant() -> str:
        for ch in reversed(out):
            if not ch.isspace():
                return ch
        return ""

    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i+1] == "/":
            while i < n and src[i] != "\n": i += 1
        elif c == "/" and i + 1 < n and src[i+1] == "*":
            j = src.find("*/", i + 2)
            if j == -1: reliable = False; break
            i = j + 2
        elif c in "\"'":
            q, j = c, i + 1
            while j < n and src[j] != q:
                if src[j] == "\\": j += 1
                j += 1
            if j >= n: reliable = False; break
            if keep_literals:
                out.append(src[i:j+1])
            elif keep_ident_strings:
                inner_s = src[i+1:j]
                out.append(" " + inner_s + " " if _JS_IDENT.fullmatch(inner_s)
                           else " ")
            else:
                out.append(" ")
            i = j + 1
        elif c == "`":
            # Template literal: el texto es inerte, ${...} ejecuta.
            j, closed = i + 1, False
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                elif ch == "`":
                    closed, j = True, j + 1
                    break
                elif ch == "$" and j + 1 < n and src[j+1] == "{":
                    depth, j = 1, j + 2
                    expr = []
                    while j < n and depth:
                        if src[j] == "{": depth += 1
                        elif src[j] == "}":
                            depth -= 1
                            if not depth:
                                j += 1
                                break
                        expr.append(src[j])
                        j += 1
                    if depth: break
                    inner, inner_ok = _strip_js("".join(expr), keep_literals,
                                                keep_ident_strings)
                    reliable = reliable and inner_ok
                    out.append(" " + inner + " ")
                else:
                    j += 1
            if not closed: reliable = False; break
            out.append(" ")
            i = j
        elif c == "/":
            # V8: regex literal vs división. Si el token previo cierra un
            # operando (identificador, número, ), ], }) es división.
            p = prev_significant()
            if p and (p.isalnum() or p in "_)$]}"):
                out.append(c); i += 1
            else:
                j, in_class, closed = i + 1, False, False
                while j < n:
                    ch = src[j]
                    if ch == "\\": j += 2; continue
                    if ch == "\n": break
                    if ch == "[": in_class = True
                    elif ch == "]": in_class = False
                    elif ch == "/" and not in_class:
                        closed, j = True, j + 1
                        break
                    j += 1
                if not closed: reliable = False; break
                while j < n and src[j].isalpha(): j += 1   # flags del regex
                out.append(src[i:j] if keep_literals else " ")
                i = j
        else:
            out.append(c); i += 1
    return "".join(out), reliable


def strip_js(src: str) -> tuple[str, bool]:
    """Compatibilidad: código sin comentarios ni literales, como en v4."""
    return _strip_js(src, keep_literals=False)


def strip_shell(src: str) -> tuple[str, bool]:
    """V9: comillas simples inertes; en comillas dobles, $(...) y `...`
    ejecutan y su contenido se conserva. Devuelve (código, confiable).
    R2-8: el contenido sustituido se prefija con `;` para que quede en
    posición de comando (un `$(curl ...)` ejecuta aunque esté tras `echo`)."""
    out, reliable = [], True
    for line in src.splitlines():
        res, i, n = [], 0, len(line)
        while i < n:
            c = line[i]
            if c == "#" and (i == 0 or line[i-1] in " \t;&|"):
                break
            if c == "'":
                j = line.find("'", i + 1)
                if j == -1: reliable = False; break
                res.append(" "); i = j + 1
            elif c == '"':
                j, closed = i + 1, False
                while j < n:
                    ch = line[j]
                    if ch == "\\":
                        j += 2
                    elif ch == '"':
                        closed, j = True, j + 1
                        break
                    elif ch == "$" and j + 1 < n and line[j+1] == "(":
                        depth, j = 1, j + 2
                        expr = []
                        while j < n and depth:
                            if line[j] == "(": depth += 1
                            elif line[j] == ")":
                                depth -= 1
                                if not depth:
                                    j += 1
                                    break
                            expr.append(line[j])
                            j += 1
                        if depth: break
                        inner, inner_ok = strip_shell("".join(expr))
                        reliable = reliable and inner_ok
                        res.append("; " + inner + " ")
                    elif ch == "`":
                        k = line.find("`", j + 1)
                        if k == -1: break
                        inner, inner_ok = strip_shell(line[j+1:k])
                        reliable = reliable and inner_ok
                        res.append("; " + inner + " ")
                        j = k + 1
                    else:
                        j += 1
                if not closed: reliable = False; break
                res.append(" ")
                i = j
            else:
                res.append(c); i += 1
        out.append("".join(res))
    return "\n".join(out), reliable


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------

class Adapter:
    name = "base"
    def analyze(self, rel_path, src): raise NotImplementedError


class PythonAdapter(Adapter):
    name = "python"

    def analyze(self, rel_path, src):
        crit, sig = [], []
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return crit, sig
        st = SymbolTable(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                mod, fname, is_builtin = st.resolve_call(node.func)
                lf = (fname or "").lower()

                # V2: builtin directo, vía módulo `builtins` o importado de él.
                if (is_builtin or mod == "builtins") and lf in DYNEXEC:
                    crit.append(("seguridad", "SEC-DYNEXEC", f"builtin {fname}()"))
                # V2: getattr(builtins, "eval")(...) también ejecuta.
                # R2-1: getattr(os, "system")(...) es os.system con indirección.
                if isinstance(node.func, ast.Call):
                    inner = node.func
                    gm, gf, gbuiltin = st.resolve_call(inner.func)
                    if gbuiltin and gf == "getattr" and len(inner.args) >= 2 \
                       and isinstance(inner.args[1], ast.Constant) \
                       and isinstance(inner.args[1].value, str):
                        attr = inner.args[1].value
                        base = getattr(inner.args[0], "id", None)
                        bmod = st.module_alias.get(base, base)
                        if bmod == "builtins" and attr.lower() in DYNEXEC:
                            crit.append(("seguridad", "SEC-DYNEXEC",
                                         f"getattr(builtins, {attr!r})"))
                        if bmod == "os" and attr.lower() in OSCMD_ATTRS:
                            crit.append(("seguridad", "SEC-OSCMD",
                                         f"getattr(os, {attr!r})"))
                if mod == "os" and lf in OSCMD_ATTRS:                  # C1
                    crit.append(("seguridad", "SEC-OSCMD", f"os.{fname}()"))
                if mod == "subprocess" or (fname in ("run","Popen","call","check_output")
                                           and mod == "subprocess"):   # C20
                    if any(k.arg == "shell" and _is_truthy_const(k.value)   # V4
                           for k in node.keywords):
                        crit.append(("seguridad", "SEC-SHELL",
                                     f"subprocess.{fname}(shell=True)"))
                # R2-2: asyncio.create_subprocess_shell ejecuta vía shell.
                if mod == "asyncio" and lf == "create_subprocess_shell":
                    crit.append(("seguridad", "SEC-SHELL",
                                 "asyncio.create_subprocess_shell()"))
                if (mod, fname) in UNSAFE_DESER:
                    crit.append(("seguridad", "SEC-DESER", f"{mod}.{fname}()"))
                if mod == "yaml" and lf in ("load","load_all","full_load","unsafe_load"):  # C2-C5, R2-3
                    loader = next((k.value for k in node.keywords if k.arg == "Loader"), None)
                    lmod, lname = st.resolve_attr_source(loader) if loader is not None else (None, None)
                    # V3: seguro sólo si el loader VIENE de yaml, no por su nombre.
                    safe = lmod == "yaml" and lname in YAML_SAFE_LOADERS
                    if not safe:
                        crit.append(("seguridad", "SEC-DESER",
                                     f"yaml.{fname}(Loader={lname or 'ausente'})"))
                if mod in ("threading","asyncio","multiprocessing") and fname in CONC_PRIMITIVES:
                    crit.append(("concurrencia", "CON-PRIMITIVE", f"{mod}.{fname}"))
                if mod == "io" and fname in ("open","BytesIO","StringIO"):
                    crit.append(("rendimiento_recursos", "PRF-IO", f"io.{fname}()"))

                # V10: llamada semántica inequívoca aunque no haya def local.
                if is_builtin and lf.replace("_", "") in SEC_SEMANTIC_NAMES:
                    crit.append(("seguridad", "SEC-SEMANTIC", f"call {fname}()"))

                # V5: secreto literal en argumentos de la llamada.
                for k in node.keywords:
                    if k.arg and SECRET_NAME.search(k.arg) and not _name_is_counter(k.arg) \
                       and isinstance(k.value, ast.Constant) \
                       and _looks_like_secret_value(k.value.value):
                        crit.append(("seguridad", "SEC-LITERAL", k.arg))
                    if isinstance(k.value, ast.Dict):
                        for dk, dv in zip(k.value.keys, k.value.values):
                            if isinstance(dk, ast.Constant) and isinstance(dk.value, str) \
                               and SECRET_NAME.search(dk.value) \
                               and not _name_is_counter(dk.value) \
                               and isinstance(dv, ast.Constant) \
                               and _looks_like_secret_value(dv.value):
                                crit.append(("seguridad", "SEC-LITERAL", dk.value))

            if isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
                crit.append(("concurrencia", "CON-ASYNC", type(node).__name__))

            # C6: definición semánticamente inequívoca
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.lower().replace("_", "") in SEC_SEMANTIC_NAMES:
                    crit.append(("seguridad", "SEC-SEMANTIC", f"def {node.name}()"))

            # C13: secreto literal — nombre Y valor
            # R2-5: también destinos por subíndice (`cfg['password'] = ...`).
            targets = []
            if isinstance(node, ast.Assign):
                targets = [(_assign_target_name(t), node.value)
                           for t in node.targets]
            elif isinstance(node, ast.AnnAssign):
                targets = [(_assign_target_name(node.target), node.value)]
            for nm, val in targets:
                if not nm or not SECRET_NAME.search(nm) or _name_is_counter(nm):
                    continue
                if isinstance(val, ast.Constant) and _looks_like_secret_value(val.value):
                    crit.append(("seguridad", "SEC-LITERAL", nm))

        # R2-DET: st.modules() es un set; se itera ordenado para que la
        # evidencia (y por tanto la matriz persistida) sea determinista
        # entre procesos con distinto PYTHONHASHSEED. No cambia ejes ni
        # scores, sólo el orden de emisión de la evidencia.
        for mod in sorted(st.modules()):
            if mod in WEAK_IMPORTS: continue
            if mod in CONTRACT_VALIDATORS: crit.append(("contratos","CTR-VALIDATOR",mod))
            if mod in TEST_FRAMEWORKS:     crit.append(("tests_observabilidad","TST-FRAMEWORK",mod))
            if mod in PERF_RESOURCE_MODULES: crit.append(("rendimiento_recursos","PRF-RESOURCE",mod))
            for axis, mods in AXIS_IMPORTS.items():
                if mod in mods: sig.append((axis,"import",mod,W_IMPORT))

        idents = set()
        for node in ast.walk(tree):
            for attr in ("name","id","attr","arg"):
                v = getattr(node, attr, None)
                if isinstance(v, str): idents |= _morphemes(v)
        for axis in AXES:
            for tok in sorted(idents & (AXIS_IDENTS[axis] - AMBIGUOUS.get(axis,set()))):
                sig.append((axis,"identifier",tok,W_IDENT))
            for tok in sorted(idents & AMBIGUOUS.get(axis,set())):
                sig.append((axis,"identifier",f"{tok}(ambiguo)",W_AMBIG))
        return crit, sig


class JsTsAdapter(Adapter):
    name = "js_ts"
    IMPORT_RE = re.compile(r"""(?:import\s+.*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]""")
    JS_MODULES = {
        "seguridad": {"crypto","bcrypt","jsonwebtoken","passport","helmet","argon2"},
        "concurrencia": {"worker_threads","cluster","rxjs","p-limit"},
        "tests_observabilidad": {"jest","mocha","chai","vitest","winston","pino"},
        "contratos": {"zod","joi","yup","ajv","class-validator","io-ts"},
        "rendimiento_recursos": {"stream","perf_hooks"},
    }
    DANGEROUS = re.compile(r"\b(eval|new\s+Function|execSync)\s*\(")
    FN_DEF = re.compile(r"\b(?:function|const|let|var)\s+(\w+)|(\w+)\s*[:=]\s*(?:async\s*)?\(")
    # R2-10: acceso por corchete al eval global (`window['eval']`,
    # `globalThis['eval']`), incluido el aliasado posterior.
    GLOBAL_EVAL = re.compile(r"\b(?:window|globalThis)\s*\[\s*eval\s*\]")

    def analyze(self, rel_path, src):
        crit, sig = [], []
        # V8: dos vistas — sin comentarios (imports/secretos) y sin
        # comentarios ni literales (reglas críticas de ejecución).
        code_txt, ok_txt = _strip_js(src, keep_literals=True)
        code, ok_lit = _strip_js(src, keep_literals=False)
        reliable = ok_txt and ok_lit
        # R2-10: tercera vista — strings-identificador visibles, para ver el
        # contenido de `['eval']` sin exponer strings arbitrarios.
        code_gb, ok_gb = _strip_js(src, keep_literals=False,
                                   keep_ident_strings=True)
        if reliable:
            m = self.DANGEROUS.search(code)
            if m: crit.append(("seguridad","SEC-DYNEXEC",m.group(1)))
            for mm in self.FN_DEF.finditer(code):            # C7
                nm = (mm.group(1) or mm.group(2) or "").lower().replace("_","")
                if nm in SEC_SEMANTIC_NAMES:
                    crit.append(("seguridad","SEC-SEMANTIC",f"function {nm}()"))
        if ok_gb and self.GLOBAL_EVAL.search(code_gb):
            crit.append(("seguridad","SEC-DYNEXEC","global['eval']"))
        for m in self.IMPORT_RE.finditer(code_txt):          # imports reales, no comentados
            mod = m.group(1).split("/")[0]
            for axis, mods in self.JS_MODULES.items():
                if mod in mods: sig.append((axis,"import",mod,W_IMPORT))
        if reliable and re.search(r"(?:async\s+function|await\s+)", code):
            sig.append(("concurrencia","ast","async/await",W_AST))
        # R2-9: la clave puede venir entrecomillada ({ "password": "..." }).
        for m in re.finditer(r"""["']?(\w+)["']?\s*[:=]\s*['"]([^'"]+)['"]""", code_txt):
            nm, val = m.group(1), m.group(2)
            if SECRET_NAME.search(nm) and not _name_is_counter(nm) \
               and _looks_like_secret_value(val):
                crit.append(("seguridad","SEC-LITERAL",nm))
        idents = set()
        for w in _IDENT.findall(code if reliable else code_txt): idents |= _morphemes(w)
        for axis in AXES:
            for tok in sorted(idents & (AXIS_IDENTS[axis]-AMBIGUOUS.get(axis,set()))):
                sig.append((axis,"identifier",tok,W_IDENT))
        return crit, sig


class DataAdapter(Adapter):
    name = "data"
    MARKERS = ("$schema","openapi","swagger","definitions","properties","apiVersion")

    def analyze(self, rel_path, src):
        crit, sig = [], []
        if any(mk.lower() in src.lower() for mk in self.MARKERS):
            sig.append(("contratos","content","schema marker",W_AST))
        pairs = []
        try:
            def walk(o, prefix=""):
                if isinstance(o, dict):
                    for k, v in o.items():
                        pairs.append((str(k), v)); walk(v)
                elif isinstance(o, list):
                    for v in o: walk(v)
            walk(json.loads(src))
        except Exception:
            for m in re.finditer(r"""(?im)^\s*[\"']?([\w.-]+)[\"']?\s*[:=]\s*[\"']?([^\s\"',]*)""", src):
                pairs.append((m.group(1), m.group(2)))
        for k, v in pairs:                                    # C13-C14
            if SECRET_NAME.search(k) and not _name_is_counter(k) and _looks_like_secret_value(v):
                crit.append(("seguridad","SEC-LITERAL",k))
        return crit, sig


class ShellAdapter(Adapter):
    name = "shell"
    DANGEROUS = {"eval":"SEC-DYNEXEC","sudo":"SEC-PRIV","chmod":"SEC-PRIV",
                 "chown":"SEC-PRIV","curl":"SEC-NET","wget":"SEC-NET"}
    # R2-7: el comando remoto de `ssh host '...'` ejecuta en el host remoto;
    # las comillas simples son inertes sólo localmente, así que su contenido
    # se analiza como código. Excepción acotada a ssh.
    SSH_REMOTE = re.compile(r"(?m)^\s*ssh\s+(?:\S+\s+)*'([^'\n]*)'")

    def analyze(self, rel_path, src):
        crit, sig = [], []
        code, reliable = strip_shell(src)                     # C11-C12, V9
        for m in self.SSH_REMOTE.finditer(src):
            inner, ok = strip_shell(m.group(1))
            reliable = reliable and ok
            code += "\n" + inner
        if reliable:
            for tok, rule in self.DANGEROUS.items():
                # R2-8: sólo posición de comando — `echo curl ...` no ejecuta.
                if re.search(rf"(?m)(?:^|[|;&(`]|\$\()\s*{tok}(?:\s|$)", code):
                    crit.append(("seguridad", rule, tok))
            if re.search(r"(?i)(--cert|--key|tls|ssl|https://)", code):
                crit.append(("seguridad","SEC-TLS","tls/cert"))
        for m in re.finditer(r"""(?im)^\s*(?:export\s+)?([\w.]+)=[\"']?([^\s\"']*)""", code):
            nm, val = m.group(1), m.group(2)
            if SECRET_NAME.search(nm) and not _name_is_counter(nm):
                crit.append(("seguridad","SEC-SECFIELD" if not _looks_like_secret_value(val)
                             else "SEC-LITERAL", nm))
        if reliable and re.search(r"(?m)^\s*(wait\b|.*&\s*$|\bxargs\b.*-P)", code):
            sig.append(("concurrencia","content","job control",W_AST))
        return crit, sig


class EnvAdapter(Adapter):
    """R2-11: soporte acotado para `.env` — pares KEY=VALUE; sólo un secreto
    literal evidencia seguridad. Las extensiones desconocidas NO se tratan
    como seguridad por defecto: siguen cayendo en FallbackAdapter."""
    name = "env"

    def analyze(self, rel_path, src):
        crit = []
        for m in re.finditer(r"""(?im)^\s*(?:export\s+)?([\w.]+)\s*=\s*[\"']?([^\s\"'#]*)""", src):
            nm, val = m.group(1), m.group(2)
            if SECRET_NAME.search(nm) and not _name_is_counter(nm) \
               and _looks_like_secret_value(val):
                crit.append(("seguridad","SEC-LITERAL",nm))
        return crit, []


class FallbackAdapter(Adapter):
    name = "fallback"
    def analyze(self, rel_path, src):
        sig = []
        idents = set()
        for w in _IDENT.findall(src): idents |= _morphemes(w)
        for axis in AXES:
            for tok in sorted(idents & (AXIS_IDENTS[axis]-AMBIGUOUS.get(axis,set()))):
                sig.append((axis,"identifier",tok,W_IDENT))
        return [], sig


_ADAPTERS = {".py": PythonAdapter(), ".pyi": PythonAdapter(),
             ".js": JsTsAdapter(), ".jsx": JsTsAdapter(), ".ts": JsTsAdapter(),
             ".tsx": JsTsAdapter(), ".mjs": JsTsAdapter(),
             ".json": DataAdapter(), ".yaml": DataAdapter(), ".yml": DataAdapter(),
             ".toml": DataAdapter(), ".proto": DataAdapter(), ".env": EnvAdapter(),
             ".sh": ShellAdapter(), ".bash": ShellAdapter(), ".zsh": ShellAdapter()}


def pick_adapter(rel_path: str) -> Adapter:
    return _ADAPTERS.get(PurePosixPath(rel_path.lower()).suffix, FallbackAdapter())


def _critical_path_rules(rel_path: str) -> list:
    hits, low = [], rel_path.lower()
    p = PurePosixPath(low)
    segs = {s for s in p.parts} | {s for s in re.split(r"[._\-]+", p.stem) if s}
    if segs & SEC_PATH_SEGMENTS:
        hits.append(("seguridad","SEC-PATH",sorted(segs & SEC_PATH_SEGMENTS)[0]))
    if (segs & TEST_PATH_SEGMENTS) or low.endswith("conftest.py") \
       or re.search(r"(^|/)(test_|spec_)", low) or re.search(r"(_test|_spec)\.\w+$", low):
        hits.append(("tests_observabilidad","TST-PATH",rel_path))
    if p.suffix in CONTRACT_EXTS:
        hits.append(("contratos","CTR-FORMAT",p.suffix))
    return hits


def route(rel_path: str, src: str, rules: dict = DOMAIN_RULES) -> list:
    adapter = pick_adapter(rel_path)
    crit, sig = adapter.analyze(rel_path, src)
    crit = list(crit) + _critical_path_rules(rel_path) + _apply_domain_rules(rel_path, rules)

    ca, sa = {}, {}
    for axis, rule, value in crit:
        ca.setdefault(axis, []).append(
            {"source":"critical_rule","value":value,"rule":rule,"weight":None})
    for axis, source, value, weight in sig:
        sa.setdefault(axis, []).append({"source":source,"value":value,"weight":weight})

    out = []
    for axis in AXES:
        ev_c, ev_s = ca.get(axis, []), sa.get(axis, [])
        has_strong = any(e["weight"] and e["weight"] >= W_IDENT
                         and "(ambiguo)" not in str(e["value"]) for e in ev_s)
        score = sum(e["weight"] for e in ev_s
                    if e["weight"] and (has_strong or "(ambiguo)" not in str(e["value"])))
        decision = "critical" if ev_c else ("assigned" if score >= THRESHOLD else "rejected")
        out.append({"file":rel_path,"axis":axis,"adapter":adapter.name,
                    "evidence":ev_c+ev_s,"score":score,"threshold":THRESHOLD,
                    "decision":decision,"correctness_obligation":True,
                    "v":SCHEMA_VERSION,"domain_rules_hash":domain_rules_hash(rules)})
    if not any(r["decision"] in ("critical","assigned") for r in out):
        out.append({"file":rel_path,"axis":RESIDUAL_AXIS,"adapter":adapter.name,
                    "evidence":[{"source":"coverage","value":"NO_SPECIFIC_SIGNAL",
                                 "rule":"RES-COVER","weight":None}],
                    "score":0,"threshold":THRESHOLD,"decision":"residual",
                    "correctness_obligation":True,"v":SCHEMA_VERSION,
                    "domain_rules_hash":domain_rules_hash(rules)})
    return out


def axes_of(rel_path: str, src: str, rules: dict = DOMAIN_RULES) -> list:
    return sorted({r["axis"] for r in route(rel_path, src, rules)
                   if r["decision"] in ("critical","assigned","residual")})


def assignments_for_index(rel_path: str, src: str, rules: dict = DOMAIN_RULES) -> list:
    res = []
    for r in route(rel_path, src, rules):
        if r["decision"] not in ("critical","assigned","residual"): continue
        rule = {"critical":"CRITICAL","residual":"RESIDUAL"}.get(r["decision"],"HEURISTIC")
        res.append({"axis":r["axis"],"rule":rule,"v":SCHEMA_VERSION,
                    "adapter":r["adapter"],"score":r["score"],"threshold":r["threshold"],
                    "decision":r["decision"],"correctness_obligation":True,
                    "domain_rules_hash":r["domain_rules_hash"],"evidence":r["evidence"]})
    return res


# ---------------------------------------------------------------------------
# Definición canónica ÚNICA de la obligación transversal (requisito 11)
# ---------------------------------------------------------------------------

CORRECTNESS_OBLIGATION_ID = "correctness-obligation/1"
CORRECTNESS_OBLIGATION_TEXT = (
    "Además de los defectos de tu especialidad, reportá cualquier defecto de "
    "correctitud general que observes en el packet: lógica invertida, off-by-one, "
    "caso borde no manejado, retorno inconsistente, estado no reinicializado, "
    "condición muerta. Clasificalos con axis=\"correctness\" y "
    "specialty_origin=<tu especialidad>. No los omitas por estar fuera de tu "
    "especialidad. Si no observás ninguno, declaralo explícitamente."
)

def correctness_obligation_hash() -> str:
    return hashlib.sha256(
        (CORRECTNESS_OBLIGATION_ID + "\n" + CORRECTNESS_OBLIGATION_TEXT).encode()).hexdigest()

def render_specialty_prompt(specialty: str, body: str) -> str:
    """Única función que renderiza prompts de especialidad. Garantiza que la
    obligación transversal esté presente y sea verificable por hash."""
    return (f"[especialidad: {specialty}]\n{body}\n\n"
            f"[{CORRECTNESS_OBLIGATION_ID} sha256={correctness_obligation_hash()[:16]}]\n"
            f"{CORRECTNESS_OBLIGATION_TEXT}\n")
