#!/usr/bin/env python3
"""Genera docs/architecture_diagram.mermaid a partir de graphify-out/graph.json.

El diagrama se DERIVA del grafo de conocimiento que Graphify reconstruye en cada
commit. No se edita a mano: si la arquitectura cambia, se vuelve a correr esto.

Uso:
    python3 tools/graph_to_mermaid.py [--repo .] [--out docs/architecture_diagram.mermaid]
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import subprocess
import sys

# Directorios cuyo segundo nivel es significativo (camino-a/runtime, apps/desktop...)
SPLIT_TWO_LEVELS = {"camino-a", "camino-b", "apps", "shared"}


def module_of(source_file: str | None) -> str | None:
    if not source_file:
        return None
    parts = source_file.split("/")
    if len(parts) == 1:
        return "(raiz)"
    if parts[0] in SPLIT_TWO_LEVELS and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def submodule_of(source_file: str | None, module: str) -> str | None:
    if not source_file:
        return None
    parts = source_file.split("/")
    depth = module.count("/") + 1
    if len(parts) <= depth:
        return None
    return "/".join(parts[: depth + 1])


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)


def git_head(repo: pathlib.Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "NO_CONSTA"


def build(repo: pathlib.Path, out_path: pathlib.Path) -> int:
    graph_path = repo / "graphify-out" / "graph.json"
    if not graph_path.exists():
        print(f"ERROR: no existe {graph_path}. Corre primero: graphify extract . --code-only",
              file=sys.stderr)
        return 1

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}

    mod_count: collections.Counter[str] = collections.Counter()
    sub_count: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for node in graph["nodes"]:
        mod = module_of(node.get("source_file"))
        if not mod:
            continue
        mod_count[mod] += 1
        sub = submodule_of(node.get("source_file"), mod)
        if sub:
            sub_count[mod][sub] += 1

    cross: collections.Counter[tuple[str, str]] = collections.Counter()
    for link in graph["links"]:
        a = module_of((nodes.get(link.get("source")) or {}).get("source_file"))
        b = module_of((nodes.get(link.get("target")) or {}).get("source_file"))
        if a and b and a != b:
            cross[(a, b)] += 1

    built_at = graph.get("built_at_commit", "NO_CONSTA")
    lines: list[str] = [
        "%% GENERADO AUTOMATICAMENTE — no editar a mano.",
        "%% Fuente: graphify-out/graph.json (Graphify reconstruye el grafo en cada commit).",
        "%% Regenerar con: python3 tools/graph_to_mermaid.py",
        f"%% graph.json built_at_commit: {built_at}",
        f"%% HEAD al generar: {git_head(repo)}",
        f"%% nodos: {len(graph['nodes'])}  aristas: {len(graph['links'])}"
        f"  aristas entre modulos: {sum(cross.values())}",
        "",
        "flowchart LR",
    ]

    for mod, count in mod_count.most_common():
        mid = sanitize(mod)
        lines.append(f'  subgraph {mid}["{mod} — {count} nodos"]')
        lines.append("    direction TB")
        subs = sub_count.get(mod, collections.Counter())
        if subs:
            for sub, scount in subs.most_common(8):
                leaf = sub.split("/")[-1]
                lines.append(f'    {sanitize(sub)}["{leaf}<br/>{scount}"]')
        else:
            lines.append(f'    {mid}_only["(sin submodulos)"]')
        lines.append("  end")

    if cross:
        lines.append("")
        for (a, b), count in cross.most_common():
            lines.append(f"  {sanitize(a)} -->|{count}| {sanitize(b)}")
    else:
        lines.append("")
        lines.append("  %% Graphify no detecto NINGUNA arista entre estos modulos:")
        lines.append("  %% son bases de codigo aisladas dentro del mismo repo.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"escrito: {out_path}")
    print(f"  modulos: {len(mod_count)}  nodos: {len(graph['nodes'])}"
          f"  aristas entre modulos: {sum(cross.values())}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="docs/architecture_diagram.mermaid")
    args = ap.parse_args()
    repo = pathlib.Path(args.repo).resolve()
    return build(repo, repo / args.out)


if __name__ == "__main__":
    raise SystemExit(main())
