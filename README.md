# Score de Viabilidad Comercial — Córdoba Capital

Asigna un score de viabilidad a ubicaciones urbanas de Córdoba: qué tan probable
es que un comercio de un rubro dado sobreviva ahí, y qué rubro tiene más chances
en un local vacío.

Construido sobre el histórico de habilitaciones comerciales del municipio:
**144.743 registros entre 2014 y 2026**, sobre 7.533 manzanas.

> De cada 10 comercios que abrieron en Córdoba desde 2014, **7 ya cerraron**.

| | |
|---|---|
| `CLAUDE.md` | Contexto, decisiones y fuentes |
| `docs/roadmap.md` | Plan por fases |
| `pipeline/` | Ingesta y procesamiento de datos |

## Estado

Fase 1 (datos) completa. Fase 2 (variables) en curso.

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
python -m viabilidad todo
```

Ver `pipeline/README.md` para el detalle.

## Limitaciones

El modelo es **predictivo, no causal**: que una zona tenga comercios exitosos no
prueba que uno nuevo vaya a funcionar. La supervivencia se mide por vigencia del
permiso municipal, que es un proxy — alguien puede cerrar sin dar de baja, o
seguir operando con el permiso vencido.
