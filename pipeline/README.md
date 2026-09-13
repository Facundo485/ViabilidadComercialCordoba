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
uv sync                       # o: pip install -e .

python -m viabilidad rubros     # lista los rubros reales del GIS, con conteos
python -m viabilidad todo       # descarga, agrega y muestra el resumen
```

Comandos sueltos: `ingest` (solo descarga), `manzanas` (solo agrega).

Los datos quedan en `data/crudo/` y `data/procesado/` como parquet.

## Pendiente

`config.RUBROS` mapea texto libre a los 5 rubros del MVP con patrones puestos a
ojo. Correr `python -m viabilidad rubros` y ajustarlos contra los valores reales.
