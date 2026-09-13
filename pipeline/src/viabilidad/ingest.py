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


def _normalizado() -> pl.Expr:
    """`rubronombre` comparable: minúsculas, sin acentos, espacios colapsados.

    Hace falta porque el campo mezcla dos nomencladores (municipal en Título con
    acentos, CLANAE en MAYÚSCULAS) y hay entradas que solo difieren en un espacio
    doble.
    """
    expr = pl.col("rubronombre").fill_null("").str.to_lowercase()
    for acento, plano in config.ACENTOS.items():
        expr = expr.str.replace_all(acento, plano, literal=True)
    return expr.str.replace_all(r"\s+", " ").str.strip_chars()


def _clasificar_rubro() -> pl.Expr:
    """Mapea el texto libre de `rubronombre` a los rubros del MVP.

    Gana el primer rubro que matchea, así que config.RUBROS va de específico a
    amplio. Lo que cae en EXCLUSIONES (mayoristas, fábricas, depósitos) sale como
    "otro" antes de evaluar nada: no son comercios a la calle.
    """
    nombre = _normalizado()
    expr = pl.when(nombre.str.contains(config.EXCLUSIONES)).then(pl.lit("otro"))

    for rubro, reglas in config.RUBROS.items():
        cond = nombre.str.contains(reglas["incluye"])
        if excluye := reglas.get("excluye"):
            cond = cond & ~nombre.str.contains(excluye)
        expr = expr.when(cond).then(pl.lit(rubro))

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
