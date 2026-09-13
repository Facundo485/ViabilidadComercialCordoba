"""Agrega las parcelas a nivel manzana y calcula la tasa de supervivencia."""

from __future__ import annotations

import logging

import polars as pl

from . import config

log = logging.getLogger(__name__)

# Pseudo-observaciones para el suavizado bayesiano. Con m=10, una manzana necesita
# ~10 habilitaciones propias para que su tasa pese más que el promedio de la ciudad.
M_SUAVIZADO = 10


def agregar(parcelas: pl.DataFrame, historial: pl.DataFrame) -> pl.DataFrame:
    """Una fila por manzana, con su tasa de supervivencia y su centroide."""
    base = parcelas.group_by("manzana").agg(
        pl.col("hab_total").sum(),
        pl.col("hab_vigentes").sum(),
        pl.col("hab_novigentes").sum(),
        pl.len().alias("parcelas"),
        pl.col("lon").mean(),
        pl.col("lat").mean(),
        pl.col("barrio_identificado").mode().first().alias("barrio"),
    )

    base = base.filter(pl.col("hab_total") > 0)
    return _con_tasa_suavizada(base).sort("manzana")


def _con_tasa_suavizada(df: pl.DataFrame) -> pl.DataFrame:
    """Tasa cruda más una versión suavizada hacia el promedio de la ciudad.

    Sin esto, una manzana con 1 habilitación que sigue abierta puntúa 100% y le
    gana a una con 40 de 50. El suavizado la empuja hacia el promedio hasta que
    junte evidencia propia suficiente.
    """
    promedio_ciudad = df["hab_vigentes"].sum() / df["hab_total"].sum()
    log.info("Tasa de supervivencia de la ciudad: %.1f%%", promedio_ciudad * 100)

    return df.with_columns(
        (pl.col("hab_vigentes") / pl.col("hab_total")).alias("tasa_cruda"),
        (
            (pl.col("hab_vigentes") + M_SUAVIZADO * promedio_ciudad)
            / (pl.col("hab_total") + M_SUAVIZADO)
        ).alias("tasa_supervivencia"),
    )


def por_rubro(historial: pl.DataFrame) -> pl.DataFrame:
    """Tabla larga: una fila por manzana y rubro, con su tasa de supervivencia.

    Larga y no ancha a propósito: con 76 categorías de nivel 2 un pivot daría más
    de 150 columnas, casi todas vacías. El formato largo además es el que espera
    el modelo, que se ajusta por rubro.
    """
    detalle = historial.filter(pl.col("nivel1") != "industria y deposito")

    agregado = detalle.group_by("manzana", "nivel2", "nivel1").agg(
        pl.col("vigente").count().alias("total"),
        pl.col("vigente").sum().alias("vigentes"),
    )
    promedios = _promedio_por_rubro(detalle)

    return (
        agregado.join(promedios, on="nivel2", how="left")
        .with_columns(
            (pl.col("vigentes") / pl.col("total")).alias("tasa_cruda"),
            (
                (pl.col("vigentes") + M_SUAVIZADO * pl.col("promedio_rubro"))
                / (pl.col("total") + M_SUAVIZADO)
            ).alias("tasa_supervivencia"),
        )
        .drop("promedio_rubro")
        .sort("manzana", "nivel2")
    )


def _promedio_por_rubro(detalle: pl.DataFrame) -> pl.DataFrame:
    """Tasa de supervivencia de cada rubro en toda la ciudad.

    Es el valor hacia el que se suaviza cada manzana. Usar el promedio del rubro
    y no el global importa: una farmacia y un bar tienen expectativas de vida muy
    distintas, y comparar cada uno contra su propio rubro es lo que hace que el
    número signifique algo.
    """
    return detalle.group_by("nivel2").agg(pl.col("vigente").mean().alias("promedio_rubro"))


def ejecutar() -> pl.DataFrame:
    parcelas = pl.read_parquet(config.DIR_CRUDO / "parcelas.parquet")
    historial = pl.read_parquet(config.DIR_CRUDO / "historial.parquet")

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)

    manzanas = agregar(parcelas, historial)
    manzanas.write_parquet(config.DIR_PROCESADO / "manzanas.parquet")
    log.info("Manzanas: %s filas", f"{len(manzanas):,}")

    detalle = por_rubro(historial)
    detalle.write_parquet(config.DIR_PROCESADO / "manzana_rubro.parquet")
    log.info("Manzana x rubro: %s filas", f"{len(detalle):,}")

    return manzanas
