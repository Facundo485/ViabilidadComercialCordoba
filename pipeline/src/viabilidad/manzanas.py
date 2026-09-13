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
    base = _con_tasa_suavizada(base)
    return base.join(_por_rubro(historial), on="manzana", how="left").sort("manzana")


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


def _por_rubro(historial: pl.DataFrame) -> pl.DataFrame:
    """Cuenta habilitaciones y vigentes por manzana y rubro, en columnas anchas."""
    largo = (
        historial.filter(pl.col("rubro") != "otro")
        .group_by("manzana", "rubro")
        .agg(
            pl.len().alias("total"),
            pl.col("vigente").fill_null(0).sum().alias("vigentes"),
        )
    )
    if largo.is_empty():
        return pl.DataFrame({"manzana": []}, schema={"manzana": pl.Utf8})

    return largo.pivot(
        on="rubro", index="manzana", values=["total", "vigentes"], aggregate_function="first"
    ).fill_null(0)


def ejecutar() -> pl.DataFrame:
    parcelas = pl.read_parquet(config.DIR_CRUDO / "parcelas.parquet")
    historial = pl.read_parquet(config.DIR_CRUDO / "historial.parquet")

    manzanas = agregar(parcelas, historial)

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    manzanas.write_parquet(config.DIR_PROCESADO / "manzanas.parquet")
    log.info("Manzanas: %s filas", f"{len(manzanas):,}")
    return manzanas
