"""Descarga las dos capas del GIS y las deja limpias en parquet."""

from __future__ import annotations

import logging

import polars as pl

from . import arcgis, config

log = logging.getLogger(__name__)

# Fechas que ArcGIS devuelve como epoch en milisegundos.
FECHAS_HISTORIAL = ["fechahabaprobada", "fechavencimientohab"]


def _a_fecha(df: pl.DataFrame, columnas: list[str]) -> pl.DataFrame:
    presentes = [c for c in columnas if c in df.columns]
    return df.with_columns(
        pl.from_epoch(pl.col(c), time_unit="ms").alias(c) for c in presentes
    )


def descargar_parcelas() -> pl.DataFrame:
    """Capa 0: un punto por parcela con los conteos de habilitaciones."""
    log.info("Descargando parcelas (capa %s)...", config.CAPA_PARCELAS)
    filas = list(
        arcgis.paginar(
            config.GIS_BASE,
            config.CAPA_PARCELAS,
            con_geometria=True,
            page_size=config.PAGE_SIZE,
        )
    )
    df = pl.DataFrame(filas)
    antes = len(df)

    bb = config.BBOX_CORDOBA
    df = df.filter(
        pl.col("lon").is_between(bb["lon_min"], bb["lon_max"])
        & pl.col("lat").is_between(bb["lat_min"], bb["lat_max"])
    )
    if descartadas := antes - len(df):
        log.warning("Descartadas %s parcelas con coordenadas fuera de Córdoba", descartadas)

    # La manzana está embebida en el nro_catastral: "01-01-001-007" -> "01-01-001".
    return df.with_columns(
        pl.col("nro_catastral").str.slice(0, config.LARGO_ID_MANZANA).alias("manzana")
    )


def descargar_historial() -> pl.DataFrame:
    """Tabla 1: un registro por habilitación, con rubro y fechas."""
    log.info("Descargando historial (tabla %s)...", config.TABLA_HISTORIAL)
    filas = list(
        arcgis.paginar(
            config.GIS_BASE,
            config.TABLA_HISTORIAL,
            con_geometria=False,
            page_size=config.PAGE_SIZE,
        )
    )
    df = _a_fecha(pl.DataFrame(filas), FECHAS_HISTORIAL)

    return df.with_columns(
        pl.col("nro_catastral").str.slice(0, config.LARGO_ID_MANZANA).alias("manzana"),
        _clasificar_rubro(),
    )


def _clasificar_rubro() -> pl.Expr:
    """Mapea el texto libre de `rubronombre` a los rubros del MVP.

    Se evalúa en orden y gana el primer patrón que matchea, así que los rubros
    más específicos deben ir primero en config.RUBROS.
    """
    nombre = pl.col("rubronombre").fill_null("").str.to_lowercase()
    expr = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for rubro, patrones in config.RUBROS.items():
        patron = "|".join(patrones)
        expr = expr.when(nombre.str.contains(patron)).then(pl.lit(rubro))
    return expr.otherwise(pl.lit("otro")).alias("rubro")


def ejecutar() -> tuple[pl.DataFrame, pl.DataFrame]:
    config.DIR_CRUDO.mkdir(parents=True, exist_ok=True)

    parcelas = descargar_parcelas()
    parcelas.write_parquet(config.DIR_CRUDO / "parcelas.parquet")
    log.info("Parcelas: %s filas", f"{len(parcelas):,}")

    historial = descargar_historial()
    historial.write_parquet(config.DIR_CRUDO / "historial.parquet")
    log.info("Habilitaciones: %s filas", f"{len(historial):,}")

    return parcelas, historial
