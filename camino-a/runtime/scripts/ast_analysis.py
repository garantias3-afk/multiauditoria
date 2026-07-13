"""ast_analysis.py — Deep AST analysis for generated Python code safety.

Detects dangerous patterns that py_compile and simple regex cannot catch:
  - Dynamic imports (eval, exec, __import__, importlib)
  - Dangerous modules (os, sys, subprocess, socket, ctypes, pickle)
  - Network access (urllib, requests, http.client)
  - File system access outside sandbox
  - Process spawning
  - System command execution
  - Credential/env access
  - Self-modification patterns
  - Anti-analysis tricks (sys.argv branching, try/except pass)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Module classification
# ---------------------------------------------------------------------------

DANGEROUS_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "ctypes", "importlib",
    "pickle", "shelve", "marshal", "code", "codeop",
    "compile", "compileall", "py_compile", "pyclbr",
    "multiprocessing", "threading", "_thread",
    "signal", "resource",
})

NETWORK_MODULES = frozenset({
    "urllib", "urllib2", "requests", "http", "http.client",
    "httplib", "ftplib", "smtplib", "poplib", "imaplib",
    "telnetlib", "xmlrpc", "xmlrpc.client", "xmlrpc.server",
    "asyncio", "aiohttp", "websockets", "paramiko",
})

FILE_MODULES = frozenset({
    "shutil", "pathlib", "glob", "fnmatch", "tempfile",
    "fileinput", "linecache", "zipfile", "tarfile", "gzip",
    "bz2", "lzma", "csv", "configparser", "plistlib",
})

CREDENTIAL_ENV_VARS = frozenset({
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PAT",
    "CREDENTIAL", "AUTH", "API_KEY", "OPENAI", "ANTHROPIC",
    "AWS", "GCP", "AZURE", "GITHUB", "GITLAB",
})

# Allowed imports for generated code (whitelist approach)
ALLOWED_MODULES = frozenset({
    "json", "re", "math", "datetime", "collections", "itertools",
    "functools", "operator", "string", "textwrap", "unicodedata",
    "enum", "dataclasses", "typing", "abc", "copy", "pprint",
    "hashlib", "hmac", "secrets", "base64", "binascii",
    "random", "statistics", "decimal", "fractions",
    "io", "struct", "codecs",
})


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------

class SafetyViolation:
    """A detected safety violation in code."""
    def __init__(self, kind: str, detail: str, line: int = 0, severity: str = "HIGH"):
        self.kind = kind
        self.detail = detail
        self.line = line
        self.severity = severity

    def __repr__(self) -> str:
        return f"Violation({self.severity}:{self.kind} L{self.line}: {self.detail})"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "line": self.line,
            "severity": self.severity,
        }


class DeepSafetyAnalyzer(ast.NodeVisitor):
    """Deep AST visitor that detects dangerous patterns."""

    def __init__(self):
        self.violations: list[SafetyViolation] = []
        self.imports: list[str] = []
        self.functions_called: list[str] = []
        self.has_self_test = False
        self.has_sys_argv_check = False
        self.has_try_except_pass = False

    def _add(self, kind: str, detail: str, node: ast.AST | None = None, severity: str = "HIGH"):
        line = getattr(node, "lineno", 0) if node else 0
        self.violations.append(SafetyViolation(kind, detail, line, severity))

    # --- Import analysis ---

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            mod = alias.name.split(".")[0]
            self.imports.append(mod)
            if mod in DANGEROUS_MODULES:
                self._add("dangerous_import", f"import {alias.name}", node, "CRITICAL")
            elif mod in NETWORK_MODULES:
                self._add("network_import", f"import {alias.name}", node, "HIGH")
            elif mod in FILE_MODULES:
                self._add("file_import", f"import {alias.name}", node, "MEDIUM")
            elif mod not in ALLOWED_MODULES:
                self._add("unknown_import", f"import {alias.name}", node, "MEDIUM")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = (node.module or "").split(".")[0]
        self.imports.append(mod)
        if mod in DANGEROUS_MODULES:
            names = [a.name for a in node.names]
            self._add("dangerous_import", f"from {node.module} import {names}", node, "CRITICAL")
        elif mod in NETWORK_MODULES:
            self._add("network_import", f"from {node.module} import ...", node, "HIGH")
        elif mod in FILE_MODULES:
            self._add("file_import", f"from {node.module} import ...", node, "MEDIUM")
        elif mod not in ALLOWED_MODULES and mod:
            self._add("unknown_import", f"from {node.module} import ...", node, "MEDIUM")
        self.generic_visit(node)

    # --- Dynamic code execution ---

    def visit_Call(self, node: ast.Call):
        func_name = self._get_call_name(node)

        # eval/exec
        if func_name in ("eval", "exec"):
            self._add("dynamic_exec", f"{func_name}() called", node, "CRITICAL")

        # __import__
        if func_name == "__import__":
            self._add("dynamic_import", "__import__() called", node, "CRITICAL")

        # getattr(__builtins__, ...)
        if func_name == "getattr":
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id == "__builtins__":
                    self._add("builtin_bypass", "getattr(__builtins__, ...)", node, "CRITICAL")

        # importlib.import_module
        if func_name in ("importlib.import_module", "importlib.__import__"):
            self._add("dynamic_import", f"{func_name}()", node, "CRITICAL")

        # os.system, os.popen
        if func_name in ("os.system", "os.popen", "os.popen2", "os.popen3", "os.popen4"):
            self._add("shell_exec", f"{func_name}()", node, "CRITICAL")

        # subprocess.*
        if func_name.startswith("subprocess."):
            self._add("subprocess_call", f"{func_name}()", node, "HIGH")

        # os.exec*, os.spawn*
        if func_name.startswith(("os.exec", "os.spawn", "os.popen")):
            self._add("process_exec", f"{func_name}()", node, "CRITICAL")

        # os.fork
        if func_name in ("os.fork", "os.forkpty"):
            self._add("fork", f"{func_name}()", node, "CRITICAL")

        # ctypes
        if func_name.startswith("ctypes."):
            self._add("native_code", f"{func_name}()", node, "CRITICAL")

        # pickle.loads, marshal.loads
        if func_name in ("pickle.loads", "pickle.load", "marshal.loads", "marshal.load"):
            self._add("deserialization", f"{func_name}()", node, "CRITICAL")

        # open() with mode containing 'w', 'a', 'x'
        if func_name == "open" and node.args:
            mode_arg = node.args[1] if len(node.args) > 1 else None
            if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                if any(c in mode_arg.value for c in ("w", "a", "x")):
                    # Check if writing outside current dir
                    path_arg = node.args[0] if node.args else None
                    if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
                        if path_arg.value.startswith(("/", "~", "..")):
                            self._add("absolute_write", f"open('{path_arg.value}', '{mode_arg.value}')", node, "HIGH")

        # socket.*
        if func_name.startswith("socket."):
            self._add("network_access", f"{func_name}()", node, "HIGH")

        # urllib.*
        if func_name.startswith(("urllib.", "urllib.request.", "urllib2.")):
            self._add("network_access", f"{func_name}()", node, "HIGH")

        # requests.*
        if func_name.startswith("requests."):
            self._add("network_access", f"{func_name}()", node, "HIGH")

        self.generic_visit(node)

    # --- Attribute access ---

    def visit_Attribute(self, node: ast.Attribute):
        # os.environ access
        if isinstance(node.value, ast.Attribute):
            if isinstance(node.value.value, ast.Name) and node.value.value.id == "os":
                if node.value.attr == "environ":
                    self._add("env_access", "os.environ access", node, "HIGH")
        elif isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr == "environ":
                self._add("env_access", "os.environ access", node, "HIGH")

        # sys.argv access
        if isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr == "argv":
            self.has_sys_argv_check = True
            self._add("sys_argv", "sys.argv access (potential self-test bypass)", node, "HIGH")

        self.generic_visit(node)

    # --- String analysis ---

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            val = node.value
            # Detect embedded commands
            if any(p in val for p in ("curl ", "wget ", "bash -c", "/bin/sh", "powershell")):
                self._add("embedded_command", f"String contains shell command: {val[:60]}...", node, "CRITICAL")
            # Detect URLs
            if re.match(r"https?://", val):
                self._add("url_reference", f"URL found: {val[:80]}", node, "MEDIUM")
            # Detect file paths
            if val.startswith(("/etc/", "/root/", "~/.ssh", "~/.aws")):
                self._add("sensitive_path", f"Sensitive path: {val[:60]}", node, "HIGH")
        self.generic_visit(node)

    # --- Anti-analysis patterns ---

    def visit_Try(self, node: ast.Try):
        # Detect try/except pass (swallowing errors)
        for handler in node.handlers:
            if isinstance(handler.body, list) and len(handler.body) == 1:
                stmt = handler.body[0]
                if isinstance(stmt, ast.Pass):
                    self.has_try_except_pass = True
                    self._add("silent_exception", "try/except:pass (swallowing errors)", node, "MEDIUM")
        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        # Detect self-test bypass: if "--self-test" in sys.argv
        test_str = ast.dump(node.test)
        if "self-test" in test_str or "self_test" in test_str:
            self.has_self_test = True
            self._add("self_test_branch", "Conditional on --self-test flag", node, "HIGH")
        self.generic_visit(node)

    # --- Helpers ---

    def _get_call_name(self, node: ast.Call) -> str:
        """Extract function name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            if isinstance(node.func.value, ast.Attribute):
                # nested: os.path.join
                inner = self._get_call_name_inner(node.func.value)
                return f"{inner}.{node.func.attr}"
        return ""

    def _get_call_name_inner(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            inner = self._get_call_name_inner(node.value)
            return f"{inner}.{node.attr}"
        return "?"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_code_ast(source: str, *, filename: str = "<generated>") -> dict:
    """Perform deep AST safety analysis on Python source code.

    Returns:
        {
            "safe": bool,
            "violations": [{"kind", "detail", "line", "severity"}],
            "imports": [str],
            "summary": str,
        }
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return {
            "safe": False,
            "violations": [{"kind": "syntax_error", "detail": str(e), "line": e.lineno or 0, "severity": "CRITICAL"}],
            "imports": [],
            "summary": f"Syntax error: {e}",
        }

    analyzer = DeepSafetyAnalyzer()
    analyzer.visit(tree)

    violations = [v.to_dict() for v in analyzer.violations]

    # Classify safety
    critical = [v for v in violations if v["severity"] == "CRITICAL"]
    high = [v for v in violations if v["severity"] == "HIGH"]

    # Unsafe if any CRITICAL, or any network/dangerous/import violations
    has_danger = any(v["kind"] in ("dangerous_import", "network_import", "network_access",
                                    "dynamic_exec", "builtin_bypass", "shell_exec",
                                    "subprocess_call", "process_exec", "fork",
                                    "native_code", "deserialization") for v in violations)
    safe = len(critical) == 0 and not has_danger

    summary_parts = []
    if critical:
        summary_parts.append(f"{len(critical)} CRITICAL")
    if high:
        summary_parts.append(f"{len(high)} HIGH")
    if not summary_parts:
        summary_parts.append("no critical issues")

    return {
        "safe": safe,
        "violations": violations,
        "imports": analyzer.imports,
        "has_self_test_branch": analyzer.has_self_test,
        "has_sys_argv_check": analyzer.has_sys_argv_check,
        "summary": f"AST analysis: {', '.join(summary_parts)}",
    }


def analyze_file_ast(path: Path) -> dict:
    """Analyze a Python file for safety violations."""
    source = path.read_text(encoding="utf-8", errors="replace")
    return analyze_code_ast(source, filename=str(path))


def assert_safe_ast(path: Path, *, context: str = "") -> None:
    """Raise SystemExit if AST analysis finds critical violations."""
    result = analyze_file_ast(path)
    if not result["safe"]:
        critical = [v for v in result["violations"] if v["severity"] == "CRITICAL"]
        high = [v for v in result["violations"] if v["severity"] == "HIGH"]
        details = []
        for v in critical[:3]:
            details.append(f"CRITICAL:{v['kind']}:{v['detail'][:60]}")
        for v in high[:3]:
            details.append(f"HIGH:{v['kind']}:{v['detail'][:60]}")
        raise SystemExit(
            f"ast_unsafe:{context}:{'; '.join(details)}"
        )
