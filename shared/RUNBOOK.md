# Runbook de ejecucion

Este archivo prepara las corridas pendientes y el orden de trabajo para Camino A y Camino B.

## Dónde esta el repo

- Ruta local: `/Users/mariano/Documents/multiauditoria`
- Repo GitHub: `garantias3-afk/multiauditoria`
- Rama de trabajo actual: `main`

## Orden recomendado

1. Leer `shared/STATUS.md`.
2. Verificar `git status` y el ultimo commit.
3. Resolver primero lo que quede como pendiente activa.
4. Registrar cualquier resultado nuevo en `shared/STATUS.md`.
5. Hacer un commit por cambio importante.

## Pendientes que siguen vigentes

- seguir distinguiendo Camino A como orquestador
- seguir distinguiendo Camino B como ejecucion y puente
- no mezclar recuperacion historica con una reforma grande en el mismo commit

La corrida `slot14_subscription_smoke` quedo cerrada con evidencia el 12 de
julio de 2026 (hora local). Ver `shared/evidence/2026-07-12-slot14-subscription-smoke.json`.

El backend local de Camino B quedo cerrado con Gateway, agente y smoke HTTP.
Ver `shared/evidence/2026-07-12-camino-b-bridge-smoke.json`. Solo resta la
publicacion HTTPS y la actualizacion manual de GPT Builder.

## Para la siguiente sesion con modelo alto

Cuando el usuario cambie al modelo mas alto:

- arrancar por Camino A si hace falta rearmar la secuencia y validaciones
- pasar luego a Camino B para ejecucion, evidencia y artefactos
- no reabrir trabajo antiguo salvo que bloquee el estado actual
- dejar cada avance en `shared/STATUS.md` antes del siguiente paso

## Formato minimo de cierre

- que se hizo
- que quedo pendiente
- evidencia disponible
- siguiente paso exacto
