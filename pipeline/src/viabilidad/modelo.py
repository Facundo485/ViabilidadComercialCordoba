"""Valida si el entorno predice supervivencia, con los dos cortes que importan.

**Por qué el problema se modela binario y no como duración.** El 55% de los
períodos dura exactamente 5,0 años, que es el plazo del permiso. Con más de la
mitad de los pares empatados, el índice de concordancia de un Cox no puede
discriminar: da 0,507 aunque haya coeficientes significativos. Lo que de verdad
separa a un comercio de otro es binario —renovó o no—, así que se modela así y
se mide con AUC.

Solo entran los locales que **tuvieron la oportunidad** de renovar: alta hasta
2021, para que a 2026 hayan podido cumplir los 5,5 años. Los más nuevos son
censura a derecha, no fracaso.

**Los dos protocolos de validación no miden lo mismo, y la diferencia es el
hallazgo principal de esta etapa.**

- *Espacial*: entrena en unos barrios y testea en otros, del mismo período.
  Responde "¿el modelo ordena bien lugares que nunca vio?".
- *Temporal*: entrena con altas hasta un año y testea con las posteriores.
  Responde "¿el modelo sirve para alguien parado hoy frente a un local vacío?".

La segunda es la que el producto necesita, y da bastante peor. Tiene sentido:
en el corte espacial, train y test comparten la época, así que el modelo puede
apoyarse en regularidades de ese período que no son estables hacia adelante. No
es fuga de la variable objetivo, pero es optimismo, y reportar solo el número
espacial sería vender una capacidad que el modelo no tiene.

`anio` queda fuera de los dos: no existe para una fecha futura, y adentro infla
el resultado sin que se pueda usar al scorear.
"""

from __future__ import annotations

import logging

import numpy as np
import polars as pl

from . import config, features

log = logging.getLogger(__name__)

# Alta hasta acá: a 2026 tuvieron los 5,5 años para renovar o no.
ULTIMO_ANIO = 2021
HORIZONTE = 5.5

ENTORNO = (
    "densidad_100",
    "densidad_300",
    "densidad_500",
    "competencia_100",
    "competencia_300",
    "competencia_500",
    "entropia_rubros",
    "cierres_previos_zona_rel",
    "antiguedad_zona_anios_rel",
    "superficietotal",
)
RUBRO = ("rubro_cod",)

# Las únicas que no salen del churn comercial. Son de barrio y de 2025, así que
# son gruesas y levemente anacrónicas, pero **no cambian con el período**: si la
# capacidad de predecir hacia adelante va a mejorar, tiene que venir de acá.
ESTRUCTURA = (
    "poblacion",
    "densidad_hab_km2",
    "hogares",
    "porc_hogares_nbi",
    "indice_prioridad_social",
)

SPLITS_ESPACIALES = 5
FRACCION_TRAIN = 0.7
CORTES_TEMPORALES = (2016, 2017, 2018)


def _datos() -> pl.DataFrame:
    archivo = config.DIR_PROCESADO / features.ARCHIVO
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Corré `python -m viabilidad features`.")
    return (
        pl.read_parquet(archivo)
        .with_columns(pl.col("inicio").dt.year().alias("anio"))
        .filter(pl.col("anio") <= ULTIMO_ANIO)
        .drop_nulls(["barrio"])
        .with_columns(
            (pl.col("duracion") > HORIZONTE).cast(pl.Int8).alias("y"),
            pl.col("rubro_principal").cast(pl.Categorical).to_physical().alias("rubro_cod"),
        )
    )


def _auc(train: pl.DataFrame, test: pl.DataFrame, columnas: tuple[str, ...]) -> float:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    m = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_depth=4, random_state=0
    )
    m.fit(train.select(columnas).to_numpy(), train["y"].to_numpy())
    p = m.predict_proba(test.select(columnas).to_numpy())[:, 1]
    return float(roc_auc_score(test["y"].to_numpy(), p))


def validacion_espacial(d: pl.DataFrame) -> pl.DataFrame:
    """Entrena en unos barrios y testea en otros. Split por barrio y no al azar:
    los locales vecinos están autocorrelacionados, y un split aleatorio deja al
    de al lado en train y en test a la vez, inflando la métrica."""
    filas = []
    barrios = d["barrio"].unique().to_list()
    for semilla in range(SPLITS_ESPACIALES):
        mezclados = list(barrios)
        np.random.default_rng(semilla).shuffle(mezclados)
        corte = int(len(mezclados) * FRACCION_TRAIN)
        train = d.filter(pl.col("barrio").is_in(mezclados[:corte]))
        test = d.filter(pl.col("barrio").is_in(mezclados[corte:]))
        filas.append(
            {
                "split": semilla,
                "n_test": len(test),
                "solo_rubro": _auc(train, test, RUBRO),
                "rubro_entorno": _auc(train, test, RUBRO + ENTORNO),
                "mas_estructura": _auc(train, test, RUBRO + ENTORNO + _estructura(d)),
            }
        )
    return pl.DataFrame(filas)


def _estructura(d: pl.DataFrame) -> tuple[str, ...]:
    """Las columnas estructurales que efectivamente están en los datos."""
    presentes = tuple(c for c in ESTRUCTURA if c in d.columns)
    if not presentes:
        log.warning(
            "No hay features estructurales: corré `python -m viabilidad poblacion` y "
            "volvé a generar las features. Sin ellas el modelo solo ve churn comercial."
        )
    return presentes


def validacion_temporal(d: pl.DataFrame) -> pl.DataFrame:
    """Entrena con lo viejo y testea con lo nuevo. Es el corte que corresponde al
    uso real del producto: predecir hacia adelante, no hacia el costado."""
    filas = []
    for corte in CORTES_TEMPORALES:
        train = d.filter(pl.col("anio") <= corte)
        test = d.filter(pl.col("anio") > corte)
        if len(test) < 2_000:
            continue
        filas.append(
            {
                "train_hasta": corte,
                "n_test": len(test),
                "solo_rubro": _auc(train, test, RUBRO),
                "rubro_entorno": _auc(train, test, RUBRO + ENTORNO),
                "mas_estructura": _auc(train, test, RUBRO + ENTORNO + _estructura(d)),
            }
        )
    return pl.DataFrame(filas)


def ejecutar() -> tuple[pl.DataFrame, pl.DataFrame]:
    d = _datos()
    print(f"\n{'=' * 72}\n  ¿El entorno predice supervivencia?\n{'=' * 72}")
    print(f"\n{len(d):,} locales con ventana completa | sobreviven {d['y'].mean():.1%}\n")

    espacial = validacion_espacial(d)
    temporal = validacion_temporal(d)
    with pl.Config(tbl_hide_dataframe_shape=True, float_precision=4):
        print("Validación ESPACIAL (barrios no vistos, mismo período):")
        print(espacial)
        print("\nValidación TEMPORAL (altas posteriores, el uso real del producto):")
        print(temporal)

    ganancia_e = (espacial["rubro_entorno"] - espacial["solo_rubro"]).mean()
    ganancia_t = (temporal["rubro_entorno"] - temporal["solo_rubro"]).mean()
    extra_e = (espacial["mas_estructura"] - espacial["rubro_entorno"]).mean()
    extra_t = (temporal["mas_estructura"] - temporal["rubro_entorno"]).mean()
    print(f"\n{'aporte sobre el rubro':<34} espacial    temporal")
    print(f"{'  entorno comercial':<34} {ganancia_e:+.3f}      {ganancia_t:+.3f}")
    print(f"{'  + estructura socioeconómica':<34} {extra_e:+.3f}      {extra_t:+.3f}")
    print(f"{'  total':<34} {ganancia_e + extra_e:+.3f}      {ganancia_t + extra_t:+.3f}")

    if ganancia_t < 0.02:
        log.warning(
            "El entorno aporta %.3f de AUC hacia adelante, que es casi nada. El "
            "número espacial (%.3f) comparte época entre train y test y por eso "
            "es optimista: no reportarlo solo.",
            ganancia_t,
            ganancia_e,
        )

    espacial.write_csv(config.RAIZ / "validacion_espacial.csv")
    temporal.write_csv(config.RAIZ / "validacion_temporal.csv")
    print(f"\nEscrito validacion_espacial.csv y validacion_temporal.csv en {config.RAIZ}")
    return espacial, temporal
