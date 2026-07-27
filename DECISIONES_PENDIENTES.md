# Decisiones pendientes — multiauditoria

Generado por Claude, chequeo en vivo del 27/jul/2026.

1. **Divergencia con GitHub**: la rama `main` local tiene 2 commits que
   GitHub no tiene, y GitHub tiene 4 que esta copia no tiene. Un
   `git push` directo va a fallar — revisá qué trajeron esos 4 commits
   remotos antes de mergear (`git pull` con merge o rebase).

2. **`deliverables/`** (9.1 MB, paquetes generados): ¿se versiona en git o
   se descarta? Por ahora está en `.gitignore` para no subirlo sin querer.
   Es regenerable vía `deliverables/build_camino_replication_handoff.py`.

3. **Slots 7/8 `max_iterations=10`** acá: en otros proyectos relacionados
   de la misma máquina el valor es 6 — confirmar cuál es el correcto para
   tu flujo antes de que la divergencia se vuelva permanente.
