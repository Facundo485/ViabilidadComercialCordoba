"""Datos socioeconómicos por barrio: población, densidad, hogares y NBI.

Son las features **estructurales** que le faltan al modelo. Todo lo que sale de
`features.py` describe el churn comercial, que es justamente lo que cambia de un
período a otro: por eso el entorno separa lugares dentro de una época y casi no
predice hacia adelante. La composición socioeconómica de un barrio se mueve
mucho más despacio, así que es candidata a transferir mejor en el tiempo.

Dos capas del mismo GIS, las dos a nivel barrio:

    Sociedad/Datos_de_Poblacion/1         población, densidad, hogares, NBI
    PoliticaSocial/Barrios_Sociodemografico/0   índice de prioridad social

**Limitaciones que hay que declarar.**

- Son de **2025**, y se aplican a locales que abrieron desde 2014. Usar el NBI
  de hoy para explicar una apertura de 2016 es un anacronismo; se acepta porque
  la estructura socioeconómica de un barrio se mueve despacio, pero no es
  gratis y va dicho en el producto.
- Son de **barrio**, que es una unidad gruesa para un score de manzana. El
  propio diccionario de datos del municipio lo advierte: los radios censales se
  asignaron al barrio con el que más se superponen, así que "no reflejan la
  realidad territorial" dentro del barrio.
- Por eso no pueden distinguir dos esquinas del mismo barrio. Sirven para
  ubicar el barrio en la ciudad, no la cuadra en el barrio.
"""

from __future__ import annotations

import logging

import polars as pl

from . import arcgis, config

log = logging.getLogger(__name__)

BASE_POBLACION = (
    "https://gis.cordoba.gob.ar/server/rest/services/Sociedad/Datos_de_Poblacion/FeatureServer"
)
CAPA_BARRIOS = 1

BASE_SOCIO = "https://gis.cordoba.gob.ar/server/rest/services/PoliticaSocial/Barrios_Sociodemografico/FeatureServer"
CAPA_SOCIO = 0

ARCHIVO = "poblacion_barrios.parquet"


def _normalizar_barrio(col: str) -> pl.Expr:
    """Nombre de barrio comparable entre capas: mayúsculas, sin acentos ni dobles espacios.

    Las tres fuentes escriben el mismo barrio distinto ("ALTA CORDOBA", "Alta
    Córdoba", "ALTA  CORDOBA"), y un join exacto perdería la mitad.
    """
    expr = pl.col(col).fill_null("").str.to_uppercase()
    for acento, plano in config.ACENTOS.items():
        expr = expr.str.replace_all(acento.upper(), plano.upper(), literal=True)
        expr = expr.str.replace_all(acento, plano.upper(), literal=True)
    return expr.str.replace_all(r"\s+", " ").str.strip_chars()


def descargar() -> pl.DataFrame:
    log.info("Descargando población por barrio...")
    poblacion = pl.DataFrame(
        list(arcgis.paginar(BASE_POBLACION, CAPA_BARRIOS, con_geometria=False, page_size=5_000)),
        infer_schema_length=None,
    ).select(
        _normalizar_barrio("nombre").alias("barrio_norm"),
        pl.col("nuevo_total_pobla").cast(pl.Float64).alias("poblacion"),
        pl.col("nueva_densidad").cast(pl.Float64).alias("densidad_hab_km2"),
        pl.col("total_hogares").cast(pl.Float64).alias("hogares"),
        pl.col("porc_hog_nbi").cast(pl.Float64).alias("porc_hogares_nbi"),
    )

    log.info("Descargando índice sociodemográfico por barrio...")
    socio = pl.DataFrame(
        list(arcgis.paginar(BASE_SOCIO, CAPA_SOCIO, con_geometria=False, page_size=5_000)),
        infer_schema_length=None,
    ).select(
        _normalizar_barrio("barrio").alias("barrio_norm"),
        pl.col("ips_num").cast(pl.Float64).alias("indice_prioridad_social"),
    )

    unido = poblacion.join(socio, on="barrio_norm", how="left").unique(
        subset="barrio_norm", keep="first"
    )
    _verificar(unido)
    return unido


def _verificar(df: pl.DataFrame) -> None:
    """Corta si una capa vino declarada pero vacía, que en este GIS ya pasó cuatro veces."""
    vacias = [c for c in df.columns if c != "barrio_norm" and df[c].null_count() == len(df)]
    if vacias:
        raise ValueError(
            f"Las columnas {vacias} vinieron nulas en el 100% de los barrios. "
            "Es el mismo modo de falla que `vigente`, `cuitempresa` y `activa`: "
            "el schema declara el campo y nadie lo popula."
        )
    for c in df.columns:
        if c != "barrio_norm" and (n := df[c].null_count()):
            log.warning("%s barrios sin %s", n, c)
    log.info("Barrios con datos: %s", f"{len(df):,}")


def ejecutar() -> pl.DataFrame:
    config.DIR_CRUDO.mkdir(parents=True, exist_ok=True)
    df = descargar()
    df.write_parquet(config.DIR_CRUDO / ARCHIVO)

    print(f"\n{'=' * 72}\n  Socioeconómico por barrio\n{'=' * 72}\n")
    with pl.Config(tbl_hide_dataframe_shape=True, float_precision=1):
        print(df.select(pl.exclude("barrio_norm")).describe())
    print(f"\nEscrito en {config.DIR_CRUDO / ARCHIVO}")
    return df
