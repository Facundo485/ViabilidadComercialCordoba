"""Genera referencia/mapeo_rubros.csv aplicando las reglas de `rubros.py`."""

from __future__ import annotations

import logging

import polars as pl

from . import config, rubros

log = logging.getLogger(__name__)

ARCHIVO = "mapeo_rubros.csv"


def normalizar(col: str = "rubronombre") -> pl.Expr:
    """Texto comparable: minúsculas, sin acentos, espacios colapsados.

    El campo mezcla dos nomencladores (municipal en Título con acentos, CLANAE en
    MAYÚSCULAS) y hay entradas que solo difieren en un espacio doble.
    """
    expr = pl.col(col).fill_null("").str.to_lowercase()
    for acento, plano in config.ACENTOS.items():
        expr = expr.str.replace_all(acento, plano, literal=True)
    return expr.str.replace_all(r"\s+", " ").str.strip_chars()


def clasificar(nombre: pl.Expr) -> pl.Expr:
    """Primera regla que matchea gana; de ahí que el orden de REGLAS importe."""
    expr = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for nivel2, _, incluye, excluye in rubros.REGLAS:
        cond = nombre.str.contains(incluye)
        if excluye:
            cond = cond & ~nombre.str.contains(excluye)
        expr = expr.when(cond).then(pl.lit(nivel2))
    return expr.otherwise(pl.lit("otro"))


def generar() -> pl.DataFrame:
    origen = config.DIR_REFERENCIA / "rubros.csv"
    df = pl.read_csv(origen).sort("n", descending=True)

    df = df.with_columns(clasificar(normalizar()).alias("nivel2")).with_columns(
        pl.col("nivel2")
        .replace_strict(rubros.NIVEL1_DE, default="otro")
        .alias("nivel1")
    )

    salida = config.DIR_REFERENCIA / ARCHIVO
    df.select("rubronombre", "n", "nivel2", "nivel1").write_csv(salida)
    log.info("Escrito %s", salida)
    return df


def resumen(df: pl.DataFrame) -> None:
    total = df["n"].sum()
    sin_clasificar = df.filter(pl.col("nivel2") == "otro")["n"].sum()

    print(f"\n{len(df):,} rubros -> {df['nivel2'].n_unique()} de nivel 2, "
          f"{df['nivel1'].n_unique()} de nivel 1")
    print(f"Clasificado: {1 - sin_clasificar / total:.1%} de las {total:,} habilitaciones\n")

    por_n1 = (
        df.group_by("nivel1")
        .agg(pl.col("n").sum().alias("habilitaciones"), pl.len().alias("rubros"))
        .sort("habilitaciones", descending=True)
    )
    with pl.Config(tbl_rows=20, tbl_hide_dataframe_shape=True):
        print(por_n1)

    # Umbral para modelar: ~200 habilitaciones dan ~100 cierres, que es el mínimo
    # razonable para estimar un modelo con del orden de 10 variables.
    por_n2 = df.group_by("nivel2", "nivel1").agg(pl.col("n").sum().alias("habilitaciones"))
    modelables = por_n2.filter(
        (pl.col("habilitaciones") >= 200) & (pl.col("nivel2") != "otro")
    )
    print(f"\nCategorías de nivel 2 con >=200 habilitaciones: {len(modelables)} "
          f"de {por_n2['nivel2'].n_unique() - 1}")

    print("\nLo que quedó sin clasificar, por volumen:")
    with pl.Config(tbl_rows=12, fmt_str_lengths=78, tbl_hide_dataframe_shape=True):
        print(df.filter(pl.col("nivel2") == "otro").select("rubronombre", "n").head(12))
