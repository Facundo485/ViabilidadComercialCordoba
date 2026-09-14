"""El score de viabilidad por manzana y rubro: lo que ve el usuario final.

Junta las piezas validadas del pipeline en un número por manzana y rubro:
la probabilidad de que un comercio de ese rubro, abierto hoy ahí, pase su
primer vencimiento.

**Qué NO es este score, y conviene tenerlo escrito acá.**

- No es una predicción por local. El objetivo tiene 61% de exactitud medida
  contra Places y eso pone un techo de AUC 0,608 que ninguna feature rompe. Por
  eso el número se muestra **agregado a manzana y rubro**, donde el ruido
  promedia, y nunca como un veredicto sobre una dirección.
- No es causal. Que una zona tenga cafés que sobreviven no prueba que un café
  nuevo vaya a funcionar: puede ser que ahí abran cafés mejor financiados.
- No dice si una zona va a mejorar. Seis hipótesis de trayectoria dieron nulo;
  el comercio de Córdoba ya está en equilibrio con su forma construida. Esto
  describe el presente.

**Cómo se arma el entorno "de hoy".** Las features de `features.py` están
medidas en la fecha de alta de cada local, que es lo correcto para entrenar.
Para scorear hace falta el entorno actual, así que por manzana se promedian las
features de los locales que abrieron en los últimos `ANIOS_RECIENTES` años, y
si no hay ninguno se cae a los más recientes que haya. Es una aproximación y
está declarada: una manzana sin aperturas recientes se describe con información
vieja.
"""

from __future__ import annotations

import logging

import polars as pl

from . import config, features, modelo

log = logging.getLogger(__name__)

ANIOS_RECIENTES = 4
RUBROS_EN_EL_MAPA = 12  # los de más volumen; más no entran cómodos en un selector
MIN_LOCALES_RUBRO = 300

ARCHIVO = "score_manzanas.parquet"


def _entrenar(d: pl.DataFrame, columnas: list[str]):
    from sklearn.ensemble import HistGradientBoostingClassifier

    m = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_depth=4, random_state=0
    )
    m.fit(d.select(columnas).to_numpy(), d["y"].to_numpy())
    return m


def _entorno_actual(f: pl.DataFrame, columnas: list[str]) -> pl.DataFrame:
    """Una fila por manzana con su entorno más reciente."""
    ultimo = f["inicio"].dt.year().max()
    recientes = f.filter(pl.col("inicio").dt.year() > ultimo - ANIOS_RECIENTES)

    def promedio(df: pl.DataFrame) -> pl.DataFrame:
        return df.group_by("manzana").agg(
            *[pl.col(c).mean() for c in columnas], pl.len().alias("_n")
        )

    con_recientes = promedio(recientes)
    todas = promedio(f)
    faltantes = todas.join(con_recientes.select("manzana"), on="manzana", how="anti")
    if len(faltantes):
        log.warning(
            "%s manzanas sin aperturas en los últimos %s años: se describen con datos más viejos.",
            f"{len(faltantes):,}",
            ANIOS_RECIENTES,
        )
    return pl.concat([con_recientes, faltantes]).drop("_n")


def calcular() -> tuple[pl.DataFrame, list[str], float]:
    f = pl.read_parquet(config.DIR_PROCESADO / features.ARCHIVO)
    entrenamiento = (
        f.filter(pl.col("inicio").dt.year() <= modelo.ULTIMO_ANIO)
        .with_columns(
            (pl.col("duracion") > modelo.HORIZONTE).cast(pl.Int8).alias("y"),
            pl.col("rubro_principal").cast(pl.Categorical).to_physical().alias("rubro_cod"),
        )
        .drop_nulls(["barrio"])
    )
    codigos = dict(
        zip(
            entrenamiento["rubro_principal"],
            entrenamiento["rubro_cod"],
            strict=True,
        )
    )

    estructura = [c for c in modelo.ESTRUCTURA if c in entrenamiento.columns]
    columnas = ["rubro_cod", *modelo.ENTORNO, *estructura]
    m = _entrenar(entrenamiento, columnas)
    base = float(entrenamiento["y"].mean())
    log.info(
        "Modelo entrenado sobre %s locales | base %.1f%%", f"{len(entrenamiento):,}", base * 100
    )

    rubros = (
        entrenamiento.group_by("rubro_principal")
        .len()
        .filter(pl.col("len") >= MIN_LOCALES_RUBRO)
        .sort("len", descending=True)
        .head(RUBROS_EN_EL_MAPA)["rubro_principal"]
        .to_list()
    )

    entorno = _entorno_actual(entrenamiento, [c for c in columnas if c != "rubro_cod"])
    filas = []
    for rubro in rubros:
        x = entorno.with_columns(pl.lit(codigos[rubro]).alias("rubro_cod")).select(columnas)
        p = m.predict_proba(x.to_numpy())[:, 1]
        filas.append(
            entorno.select("manzana").with_columns(
                pl.lit(rubro).alias("rubro"), pl.Series("score", p)
            )
        )
    return pl.concat(filas), rubros, base


def ejecutar() -> pl.DataFrame:
    s, rubros, base = calcular()
    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    s.write_parquet(config.DIR_PROCESADO / ARCHIVO)

    print(f"\n{'=' * 72}\n  Score de viabilidad por manzana y rubro\n{'=' * 72}")
    print(f"\n{s['manzana'].n_unique():,} manzanas x {len(rubros)} rubros")
    print(f"Base de la ciudad: {base:.1%} pasa el primer vencimiento\n")
    with pl.Config(tbl_rows=15, tbl_hide_dataframe_shape=True, float_precision=3):
        print(
            s.group_by("rubro")
            .agg(
                pl.col("score").mean().alias("medio"),
                pl.col("score").min().alias("min"),
                pl.col("score").max().alias("max"),
            )
            .sort("medio", descending=True)
        )
    print(f"\nEscrito en {config.DIR_PROCESADO / ARCHIVO}")
    return s
