# pipeline

Descarga las habilitaciones comerciales del GIS de la Municipalidad de Córdoba
y las agrega a nivel manzana con su tasa de supervivencia.

## Fuente

ArcGIS FeatureServer `ComerdioIndustria/Histórico_Habilitaciones`:

| | |
|---|---|
| Capa 0 | Un punto por parcela, con `hab_total` / `hab_vigentes` / `hab_novigentes` |
| Tabla 1 | Un registro por habilitación: `rubronombre`, `fechahabaprobada`, `vigente` |
| Se unen por | `nro_catastral` |
| Cobertura | 2014-01-02 a 2026-09-02 |

La manzana no requiere join espacial: está embebida en `nro_catastral`
(`01-01-001-007` → manzana `01-01-001`).

## Uso

```bash
cd pipeline
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .

python -m viabilidad rubros   # lista los rubros reales del GIS, con conteos
python -m viabilidad todo     # descarga, agrega y muestra el resumen
```

El venv no es opcional en Debian/Ubuntu: desde PEP 668 `pip install` contra el
Python del sistema falla con `externally-managed-environment`. Adentro del venv
además `python` apunta a `python3`, así que los comandos andan tal cual.

Con [uv](https://docs.astral.sh/uv/) es `uv sync && uv run python -m viabilidad rubros`.

Comandos sueltos: `ingest` (solo descarga), `manzanas` (solo agrega),
`resumen` (escribe los CSV agregados).

`todo` ya corre `resumen` al final. Los CSV que deja son agregados, sin CUIT ni
razón social, así que se pueden commitear sin exponer datos de titulares.

## Tests

```bash
pip install -e '.[dev]'
pytest
```

Y una sola vez, desde la raíz del repo, para que corran solos en cada commit:

```bash
pre-commit install
```

Mockean el GIS y ejercitan las funciones `descargar_*` enteras, no sus helpers
sueltos: así se detecta que un paso quedó sin ejecutarse, que es justo lo que un
test por helper no ve.

Los datos quedan en `data/crudo/` y `data/procesado/` como parquet (sin versionar).
`rubros` además escribe `referencia/rubros.csv`, que sí se versiona porque es
el insumo para decidir el mapeo de `config.RUBROS`.

## Rubros

`rubronombre` trae 1377 valores: dos nomencladores mezclados (el municipal viejo
en Título con acentos, el CLANAE nuevo en MAYÚSCULAS) con variantes del mismo
concepto. Se agrupan en dos niveles, 76 rubros y 12 grupos, que cubren el 93%
de las habilitaciones.

| archivo | qué es |
|---|---|
| `rubros.py` | las reglas que generan el mapeo |
| `referencia/mapeo_rubros.csv` | **la fuente de verdad**, versionada y editable a mano |

El pipeline lee el CSV, no las reglas: corregir una clasificación es editar una
fila y el diff muestra qué cambió. `python -m viabilidad mapeo` lo regenera
desde las reglas (pisa las ediciones manuales).

Los mayoristas, fábricas y depósitos quedan en el grupo `industria y deposito` y
se excluyen del análisis: no son comercios a la calle.

## Salidas

| archivo | grano |
|---|---|
| `data/procesado/manzanas.parquet` | una fila por manzana |
| `data/procesado/manzana_rubro.parquet` | una fila por manzana y rubro |

La tasa de supervivencia se suaviza hacia el promedio **del propio rubro**, no
hacia el global: una farmacia y un bar tienen expectativas de vida distintas y
cada manzana se compara contra su categoría.
