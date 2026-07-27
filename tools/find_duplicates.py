#!/usr/bin/env python3
# tools/find_duplicates.py
# Detecta archivos idénticos (mismo SHA1) bajo los directorios indicados.
# Salida:
#  - imprime grupos de rutas con archivos idénticos
#  - exit code 0 si no hay duplicados, 2 si se encontraron duplicados

import hashlib
import os
import sys
from argparse import ArgumentParser

def sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(8192)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def find_duplicates(roots, exts=None, ignore_paths=None):
    byhash = {}
    ignore_paths = set(ignore_paths or [])
    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, _, files in os.walk(root):
            if any(os.path.commonpath([dirpath, p]) == p for p in ignore_paths):
                continue
            for fn in files:
                if exts and not any(fn.endswith(e) for e in exts):
                    # si se filtran extensiones, saltar
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    s = sha1_of_file(p)
                except Exception as e:
                    print(f"ERROR leyendo {p}: {e}", file=sys.stderr)
                    continue
                byhash.setdefault(s, []).append(p)
    return byhash

def main():
    p = ArgumentParser()
    p.add_argument("roots", nargs="*", default=["camino-a","camino-b","shared"])
    p.add_argument("--ext", action="append", help="filtrar por extensión (ej: .py)")
    p.add_argument("--ignore", action="append", help="paths a ignorar")
    args = p.parse_args()

    groups = find_duplicates(args.roots, exts=args.ext, ignore_paths=args.ignore or [])
    dup_found = False
    for h, paths in groups.items():
        if len(paths) > 1:
            dup_found = True
            print("DUPLICATE GROUP SHA1:", h)
            for pth in paths:
                print("  ", pth)
            print()

    if dup_found:
        print("Se detectaron duplicados.", file=sys.stderr)
        sys.exit(2)
    else:
        print("No se detectaron duplicados.")
        sys.exit(0)

if __name__ == "__main__":
    main()
