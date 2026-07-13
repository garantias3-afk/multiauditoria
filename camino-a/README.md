# Camino A

Camino A es la capa orquestadora.

Responsabilidades:

- decidir el flujo
- coordinar pasos y validaciones
- producir estado resumido para el resto de las IA
- conservar trazabilidad de lo que se aprobo y lo que quedo pendiente

Notas:

- La separacion clave que hay que respetar es: Camino A orquesta y GPT actua como cerebro.
- Si hay duda, registrar primero el estado y despues ejecutar cambios.

