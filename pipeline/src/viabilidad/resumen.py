"""Escribe resúmenes agregados de la última corrida, aptos para versionar.

Son agregados a propósito: no llevan CUIT, razón social ni domicilio, así que se
pueden commitear sin exponer datos de titulares.
"""

from __future__ import annotations

import logging

import polars as pl

from . import config

log = logging.getLogger(__name__)


def generar() -> None:
    mz = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")
    det = pl.read_parquet(config.DIR_PROCESADO / "manzana_rubro.parquet")

    mz.describe().write_csv(config.RAIZ / "resumen_manzanas.csv")

    por_rubro = (
        det.group_by("nivel2", "nivel1")
        .agg(
            # Trámites y no habilitaciones: el histórico trae una fila por
            # trámite y rubro, y un trámite habilita varios rubros a la vez.
            pl.col("total").sum().alias("tramites"),
            pl.col("vigentes").sum(),
            pl.len().alias("manzanas"),
        )
        .with_columns((pl.col("vigentes") / pl.col("tramites")).round(3).alias("tasa"))
        .sort("tramites", descending=True)
    )
    por_rubro.write_csv(config.RAIZ / "resumen_rubros.csv")

    log.info("%s manzanas | %s filas manzana x rubro", f"{len(mz):,}", f"{len(det):,}")
    _alertar_si_degenerado(por_rubro)

    print("\nSupervivencia por rubro (los 15 de más volumen):")
    with pl.Config(tbl_rows=15, fmt_str_lengths=24, tbl_hide_dataframe_shape=True):
        print(por_rubro.select("nivel2", "nivel1", "tramites", "vigentes", "tasa").head(15))


def _alertar_si_degenerado(por_rubro: pl.DataFrame) -> None:
    """Una tasa idéntica en todos los rubros es un bug, no un hallazgo.

    Pasó: `vigente` venía nulo y se leía como cierre, y el CSV salió con ceros
    en las 76 categorías sin que nada fallara.
    """
    if por_rubro["tasa"].n_unique() <= 1:
        log.error(
            "Todos los rubros tienen la misma tasa (%s). Es un problema de datos, "
            "no un resultado: revisá la vigencia en data/crudo/historial.parquet.",
            por_rubro["tasa"].unique().to_list(),
        )
