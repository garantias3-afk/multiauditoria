#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from router_v5 import axes_of, route, domain_rules_hash


def main() -> None:
    # Corpus relativo incluido en inputs/camino-a (sin rutas absolutas externas).
    root = Path(__file__).resolve().parent.parent / "inputs" / "camino-a"
    exts = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".json", ".yaml", ".yml", ".toml", ".proto", ".avsc", ".graphql", ".xsd", ".sh", ".bash", ".zsh"}
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        src = path.read_text(errors="ignore")
        rows.append({
            "file": rel,
            "suffix": path.suffix.lower(),
            "axes": axes_of(rel, src),
            "memberships": [r for r in route(rel, src) if r["decision"] != "rejected"],
        })

    by_axis = Counter(a for row in rows for a in row["axes"])
    by_ext: dict[str, Counter] = defaultdict(Counter)
    decisions = Counter()
    evidence = Counter()
    for row in rows:
        for membership in row["memberships"]:
            by_ext[row["suffix"]][membership["axis"]] += 1
            decisions[(membership["axis"], membership["decision"])] += 1
            for item in membership["evidence"]:
                evidence[(membership["axis"], item.get("rule") or f"{item['source']}:{item['value']}")] += 1

    payload = {
        "root": "../inputs/camino-a",
        "n": len(rows),
        "extensions": dict(sorted(Counter(r["suffix"] for r in rows).items())),
        "mean": round(sum(len(r["axes"]) for r in rows) / len(rows), 3),
        "histogram": dict(sorted(Counter(len(r["axes"]) for r in rows).items())),
        "axis_counts": dict(sorted(by_axis.items())),
        "by_extension": {k: dict(v) for k, v in sorted(by_ext.items())},
        "decisions": {f"{a}:{d}": n for (a, d), n in sorted(decisions.items())},
        "top_evidence": [{"axis": a, "rule": rule, "count": n} for (a, rule), n in evidence.most_common(40)],
        "residuals": [r["file"] for r in rows if r["axes"] == ["volume_generalist"]],
        "domain_rules_hash": domain_rules_hash(),
        "rows": rows,
    }
    out = Path(__file__).with_name("axis_matrix_v5_current.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
