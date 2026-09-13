"""Punto de entrada: python -m viabilidad <comando>"""

from __future__ import annotations

import argparse
import logging

import polars as pl

from . import arcgis, config, ingest, manzanas


def _log():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")


def cmd_rubros(_) -> None:
    """Lista los valores reales de `rubronombre` con su cantidad."""
    filas = arcgis.rubros_con_conteo(config.GIS_BASE, config.TABLA_HISTORIAL)
    df = pl.DataFrame(filas).sort("n", descending=True)
    with pl.Config(tbl_rows=200, fmt_str_lengths=60):
        print(df)
    print(f"\n{len(df)} rubros distintos")


def cmd_ingest(_) -> None:
    ingest.ejecutar()


def cmd_manzanas(_) -> None:
    df = manzanas.ejecutar()
    _resumen(df)


def cmd_todo(args) -> None:
    ingest.ejecutar()
    _resumen(manzanas.ejecutar())


def _resumen(df: pl.DataFrame) -> None:
    print(f"\n{'=' * 60}\n  {len(df):,} manzanas con al menos una habilitación\n{'=' * 60}")
    print(
        df.select("hab_total", "hab_vigentes", "tasa_cruda", "tasa_supervivencia").describe()
    )
    print("\nLas 10 manzanas con mejor supervivencia (mínimo 20 habilitaciones):")
    with pl.Config(tbl_rows=10):
        print(
            df.filter(pl.col("hab_total") >= 20)
            .sort("tasa_supervivencia", descending=True)
            .select("manzana", "barrio", "hab_total", "hab_vigentes", "tasa_supervivencia")
            .head(10)
        )


COMANDOS = {
    "rubros": cmd_rubros,
    "ingest": cmd_ingest,
    "manzanas": cmd_manzanas,
    "todo": cmd_todo,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="viabilidad", description=__doc__)
    parser.add_argument("comando", choices=COMANDOS, help="qué ejecutar")
    args = parser.parse_args()
    _log()
    COMANDOS[args.comando](args)


if __name__ == "__main__":
    main()
