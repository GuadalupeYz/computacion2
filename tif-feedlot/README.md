# TIF – Viabilidad de un sistema de apoyo a decisiones en feedlots

- `INFORME_viabilidad_TIF_feedlot.md`: informe completo (entregables 1 a 8).
- `experimentos/kenward_baseline.py`: pronóstico de peso a +14 d con validación agrupada por animal (datos reales `kenward.cattle`).
- `experimentos/ejemplo_economico.py`: ejemplo numérico ficticio de la comparación vender hoy vs. continuar h días.

Reproducir:

```bash
git clone --depth 1 https://github.com/cran/agridat /tmp/agridat
python3 -I experimentos/kenward_baseline.py /tmp/agridat/data/kenward.cattle.txt
python3 -I experimentos/ejemplo_economico.py
```
