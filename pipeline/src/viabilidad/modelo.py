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

# La referencia honesta no es el azar: es lo que cualquiera saca de los datos
# que el municipio ya publica. La capa 0 del GIS trae `hab_vigentes/hab_total`
# por parcela ya calculado, así que agregarlo por manzana es un group-by.
#
# Si el modelo no le gana a eso, toda la maquinaria de features no está
# comprando nada, por más que le gane al azar. Medido: le empata.
MUNICIPIO = ("tasa_municipio", "hab_municipio")

# Las únicas que no salen del churn comercial. Son de barrio y de 2025, así que
# son gruesas y levemente anacrónicas, pero **no cambian con el período**: si la
# capacidad de predecir hacia adelante va a mejorar, tiene que venir de acá.
ESTRUCTURA = (
    "poblacion",
    "densidad_hab_km2",
    "hogares",
    "porc_hogares_nbi",
    "indice_prioridad_social",
    "km_al_centro",
)

SPLITS_ESPACIALES = 5
FRACCION_TRAIN = 0.7
CORTES_TEMPORALES = (2016, 2017, 2018)


def _datos() -> pl.DataFrame:
    archivo = config.DIR_PROCESADO / features.ARCHIVO
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Corré `python -m viabilidad features`.")

    manzanas = config.DIR_PROCESADO / "manzanas.parquet"
    municipio = (
        pl.read_parquet(manzanas).select(
            "manzana",
            (pl.col("hab_vigentes") / pl.col("hab_total")).alias("tasa_municipio"),
            pl.col("hab_total").alias("hab_municipio"),
        )
        if manzanas.exists()
        else None
    )

    base = pl.read_parquet(archivo)
    if municipio is not None:
        base = base.join(municipio, on="manzana", how="left")
    return (
        base.with_columns(pl.col("inicio").dt.year().alias("anio"))
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
                "municipio": _auc(train, test, _municipio(d)),
                "municipio_rubro": _auc(train, test, _municipio(d) + RUBRO),
                "solo_rubro": _auc(train, test, RUBRO),
                "rubro_entorno": _auc(train, test, RUBRO + ENTORNO),
                "mas_estructura": _auc(train, test, RUBRO + ENTORNO + _estructura(d)),
            }
        )
    return pl.DataFrame(filas)


def _municipio(d: pl.DataFrame) -> tuple[str, ...]:
    return tuple(c for c in MUNICIPIO if c in d.columns)


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
    if "municipio" in temporal.columns:
        muni = temporal["municipio_rubro"].mean()
        nuestro = temporal["mas_estructura"].mean()
        print(
            f"\nContra lo que ya publica el municipio (temporal):\n"
            f"  su tasa + el rubro        {muni:.3f}\n"
            f"  nuestro modelo completo   {nuestro:.3f}   ({nuestro - muni:+.3f})"
        )
        if nuestro - muni < 0.01:
            log.warning(
                "El modelo no le gana a un group-by sobre los datos publicados. "
                "El aporte del proyecto no está en el score."
            )

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


# ---------------------------------------------------------------------------
# La auditoría que ningún score debería saltearse: contrastar contra alguien que
# conoce la ciudad.
# ---------------------------------------------------------------------------

MIN_LOCALES_BARRIO = 25


def calibracion_por_barrio(rubro: str = "bar_restaurante") -> pl.DataFrame:
    """Lo que el mapa predice por barrio contra lo que efectivamente pasó.

    Nació de una observación de dominio —"en Güemes y Nueva Córdoba hay muchos
    bares y el mapa los pone tres puntos abajo"— y confirmó dos cosas.

    **La primera es una limitación real.** El modelo correlaciona 0,77 con lo
    observado y acierta el promedio de ciudad, pero **comprime hacia la media**:
    subestima los barrios buenos (Güemes 14,6% real contra 10,4% predicho, Poeta
    Lugones 25,6% contra 16,1%) y sobreestima los malos. No es un error
    corregible con más variables —se probó agregar la historia del rubro en el
    barrio y aporta +0,002 con el signo inestable—: es lo que un modelo con AUC
    0,59 contra un techo de 0,61 tiene que hacer. Jugarse predicciones extremas
    con esta señal sería sobreajustar.

    **La segunda es un hallazgo.** Los barrios con más bares son los de menor
    supervivencia individual: Centro tiene 509 y sobrevive el 9%, Poeta Lugones
    tiene 43 y sobrevive el 25,6%. Un corredor gastronómico excelente rota más
    rápido, porque el alquiler y la competencia se quedan con el margen.

    Eso obliga a ser preciso sobre qué mide el score: **la probabilidad de que
    un negocio sobreviva, no la calidad de la ubicación.** Son cosas distintas y
    en gastronomía apuntan para lados opuestos.
    """
    d = _datos().filter(pl.col("rubro_principal") == rubro)
    archivo = config.DIR_PROCESADO / "score_manzanas.parquet"
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Corré `python -m viabilidad score`.")

    manzanas = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet").select(
        "manzana", "barrio"
    )
    predicho = (
        pl.read_parquet(archivo)
        .filter(pl.col("rubro") == rubro)
        .join(manzanas, on="manzana", how="inner")
        .group_by("barrio")
        .agg(pl.col("score").mean().alias("predicho"))
    )
    observado = (
        d.group_by("barrio")
        .agg(pl.len().alias("locales"), pl.col("y").mean().alias("real"))
        .filter(pl.col("locales") >= MIN_LOCALES_BARRIO)
    )
    return (
        observado.join(predicho, on="barrio", how="inner")
        .with_columns((pl.col("predicho") - pl.col("real")).alias("error"))
        .sort("locales", descending=True)
    )


def ejecutar_calibracion(rubro: str = "bar_restaurante") -> pl.DataFrame:
    t = calibracion_por_barrio(rubro)
    print(f"\n{'=' * 72}\n  El mapa contra la realidad, por barrio — {rubro}\n{'=' * 72}\n")
    with pl.Config(tbl_rows=25, fmt_str_lengths=22, tbl_hide_dataframe_shape=True):
        print(
            t.select(
                "barrio",
                "locales",
                pl.col("real").round(3),
                pl.col("predicho").round(3),
                pl.col("error").round(3),
            )
        )
    import numpy as np

    r = float(np.corrcoef(t["predicho"].to_numpy(), t["real"].to_numpy())[0, 1])
    print(
        f"\ncorrelación entre predicho y real: {r:+.3f}\n\n"
        "El modelo ordena bien los barrios pero comprime hacia la media: con un\n"
        "techo de 0,61 de AUC no puede jugarse predicciones extremas sin\n"
        "sobreajustar. Y los barrios con más locales del rubro son los de menor\n"
        "supervivencia individual: un corredor bueno rota más rápido. El score\n"
        "mide si el negocio sobrevive, no si la ubicación es buena."
    )
    return t
