"""Features del entorno comercial de cada período de actividad.

Responde qué había alrededor del local **el día que abrió**: cuánto comercio,
cuánta competencia de su mismo rubro, qué tan diversa era la zona y qué había
pasado antes ahí.

**La regla que ordena todo el módulo es que nada mire hacia adelante.** Un local
que abrió en 2016 solo puede ver el entorno de 2016. Calcular la competencia
sobre el dataset entero —que llega hasta 2026— metería en la variable
explicativa información que en ese momento no existía, y el modelo aprendería a
predecir el pasado con el futuro. La métrica daría espectacular y el score no
serviría para nadie parado hoy frente a un local vacío.

Por eso cada vecino se cuenta solo si **estaba activo en la fecha de alta** del
local que se está describiendo: abrió antes y su permiso todavía no había
vencido. Lo mismo con el historial de la zona, que solo mira períodos ya
terminados a esa altura.

La otra decisión es la escala. Se miden radios de 100, 300 y 500 m porque la
competencia no actúa igual a media cuadra que a cinco: a 100 m es el local de
enfrente, a 500 m es el barrio comercial. Y se espera una **U invertida**, no
monotonía —pocos competidores puede ser mercado inexistente, muchos saturación,
un nivel intermedio aglomeración que atrae demanda—, así que las features se
dejan crudas y es el modelo el que tiene que encontrar la curva.
"""

from __future__ import annotations

import logging

import numpy as np
import polars as pl
from scipy.spatial import cKDTree

from . import config, poblacion, supervivencia

log = logging.getLogger(__name__)

RADIOS = (100, 300, 500)
RADIO_ENTROPIA = 300
RADIO_HISTORIAL = 500

# Chunk de puntos por vuelta. Los pares dentro de 500 m son ~73 millones en
# total; de a 2.000 puntos entran cómodos en memoria y se procesan vectorizados.
CHUNK = 2_000

METROS_POR_GRADO = 111_320.0
DIAS_ANIO = supervivencia.DIAS_ANIO

ARCHIVO = "features.parquet"


def _base() -> pl.DataFrame:
    """Un período de actividad por fila, con su punto y su rubro principal."""
    h = supervivencia._historial()
    d = supervivencia.duraciones(supervivencia.consolidar(h))

    tramites = pl.read_parquet(config.DIR_CRUDO / "tramites.parquet")
    faltan = [c for c in ("id_tramite", "lon", "lat") if c not in tramites.columns]
    if faltan:
        raise ValueError(f"La tabla de trámites no trae {faltan}; volvé a correr `ingest`.")

    d = d.join(
        tramites.select("id_tramite", "lon", "lat", "superficietotal", "barrio"),
        left_on="ultimo_tramite",
        right_on="id_tramite",
        how="left",
    )
    if sin_punto := d["lon"].null_count():
        log.warning("%s períodos sin coordenadas: quedan fuera.", f"{sin_punto:,}")

    d = _con_socioeconomico(d).with_columns(
        (
            ((pl.col("lon") - CENTRO[0]) * KM_POR_GRADO_LON) ** 2
            + ((pl.col("lat") - CENTRO[1]) * KM_POR_GRADO_LAT) ** 2
        )
        .sqrt()
        .alias("km_al_centro")
    )

    return d.filter(pl.col("lon").is_not_null() & pl.col("lat").is_not_null()).with_columns(
        # Un período puede tener varios rubros. Para "competencia del mismo
        # rubro" hace falta uno solo, y se toma el primero en orden alfabético:
        # es arbitrario pero estable, y no se usa para nada más que emparejar.
        pl.col("nivel2").list.sort().list.first().alias("rubro_principal")
    )


# Plaza San Martín. La distancia al centro es la variable estructural más obvia
# de una ciudad monocéntrica y faltaba: entra como feature para que el modelo
# decida cuánto pesa, en vez de imponerle una penalización a mano —que sería
# hacer que el mapa diga lo que esperamos y no lo que dicen los datos—.
CENTRO = (-64.1810, -31.4167)
KM_POR_GRADO_LON = 88.5
KM_POR_GRADO_LAT = 111.3


SOCIOECONOMICAS = (
    "poblacion",
    "densidad_hab_km2",
    "hogares",
    "porc_hogares_nbi",
    "indice_prioridad_social",
    "km_al_centro",
)


def _con_socioeconomico(d: pl.DataFrame) -> pl.DataFrame:
    """Adjunta las variables de barrio, si están descargadas.

    Son las únicas features del modelo que **no** salen del churn comercial, y
    por eso son las candidatas a transferir en el tiempo: la composición
    socioeconómica de un barrio se mueve mucho más despacio que sus locales.

    Van como opcionales a propósito: el pipeline tiene que poder correr sin
    haber bajado esta capa, y el modelo avisa si no están.
    """
    archivo = config.DIR_CRUDO / poblacion.ARCHIVO
    if not archivo.exists():
        log.warning(
            "Falta %s: las features quedan sin las variables de barrio. "
            "Corré `python -m viabilidad poblacion`.",
            archivo.name,
        )
        return d

    barrios = pl.read_parquet(archivo)
    unido = d.with_columns(poblacion._normalizar_barrio("barrio").alias("_barrio")).join(
        barrios.rename({"barrio_norm": "_barrio"}), on="_barrio", how="left"
    )
    sin_match = unido["poblacion"].null_count()
    if sin_match:
        log.warning(
            "%s de %s períodos no matchearon con ningún barrio del censo.",
            f"{sin_match:,}",
            f"{len(unido):,}",
        )
    return unido.drop("_barrio")


def _proyectar(d: pl.DataFrame) -> np.ndarray:
    """Lon/lat a metros. Equirectangular local: sobra para una ciudad."""
    lat0 = float(d["lat"].mean())
    x = d["lon"].to_numpy() * np.cos(np.radians(lat0)) * METROS_POR_GRADO
    y = d["lat"].to_numpy() * METROS_POR_GRADO
    return np.c_[x, y]


def calcular(d: pl.DataFrame | None = None) -> pl.DataFrame:
    """Features del entorno de cada período, medidas en su fecha de alta."""
    d = _base() if d is None else d
    puntos = _proyectar(d)
    arbol = cKDTree(puntos)

    inicio = d["inicio"].to_numpy().astype("datetime64[D]").astype(np.int64)
    fin = d["fin_cobertura"].to_numpy().astype("datetime64[D]").astype(np.int64)
    # A códigos enteros: el rubro solo se usa para emparejar iguales y para
    # indexar la matriz de la entropía.
    rubro = d["rubro_principal"].cast(pl.Categorical).to_physical().to_numpy()
    n_rubros = int(rubro.max()) + 1
    n = len(d)

    salidas = {
        **{f"densidad_{r}": np.zeros(n, dtype=np.int32) for r in RADIOS},
        **{f"competencia_{r}": np.zeros(n, dtype=np.int32) for r in RADIOS},
        "entropia_rubros": np.zeros(n),
        "cierres_previos_zona": np.full(n, np.nan),
        "antiguedad_zona_anios": np.full(n, np.nan),
    }

    for desde in range(0, n, CHUNK):
        hasta = min(desde + CHUNK, n)
        vecinos = arbol.query_ball_point(puntos[desde:hasta], r=max(RADIOS), workers=-1)

        # Aplanar el chunk a pares (i, j) para poder filtrar vectorizado.
        largos = np.fromiter((len(v) for v in vecinos), dtype=np.int64, count=hasta - desde)
        if not largos.sum():
            continue
        i = np.repeat(np.arange(desde, hasta), largos)
        j = np.concatenate([np.asarray(v, dtype=np.int64) for v in vecinos])

        propio = i == j
        dist = np.hypot(puntos[i, 0] - puntos[j, 0], puntos[i, 1] - puntos[j, 1])

        # El corazón del módulo: el vecino cuenta solo si ya había abierto y
        # todavía no había cerrado el día en que abrió el local descripto.
        activo = (inicio[j] <= inicio[i]) & (inicio[i] < fin[j]) & ~propio
        mismo_rubro = activo & (rubro[j] == rubro[i])

        local = i - desde
        for r in RADIOS:
            dentro = dist <= r
            np.add.at(salidas[f"densidad_{r}"], i[activo & dentro], 1)
            np.add.at(salidas[f"competencia_{r}"], i[mismo_rubro & dentro], 1)

        _entropia(salidas, i, j, dist, activo, local, desde, hasta, rubro, n_rubros)
        _historial(salidas, i, j, dist, propio, local, desde, hasta, inicio, fin)

        log.info("  %s/%s períodos", f"{hasta:,}", f"{n:,}")

    columnas = [
        "ultimo_tramite",
        "manzana",
        "barrio",
        "rubro_principal",
        "superficietotal",
        "inicio",
        "duracion",
        "evento",
        *[c for c in SOCIOECONOMICAS if c in d.columns],
    ]
    crudas = d.select(columnas).with_columns(**{k: pl.Series(v) for k, v in salidas.items()})
    # "No había vecinos previos" es no saber, no un cero: va como null y no como
    # NaN, que además contaminaría la media de la cohorte al relativizar.
    crudas = crudas.with_columns(
        pl.col(c).fill_nan(None) for c in RELATIVAS_AL_ANIO if c in crudas.columns
    )
    return _relativizar_al_anio(crudas)


# Estas dos no describen la zona sino la ventana de observación, y hay que
# corregirlas o no usarlas.
#
# El histórico arranca en 2014: un local que abrió ese año ve cero predecesores
# ya terminados **por construcción**, no porque su cuadra sea joven. Medidas en
# crudo, `antiguedad_zona_anios` correlaciona 0,986 con el año de alta y
# `cierres_previos_zona` 0,925 — son el calendario con otro nombre, el mismo
# artefacto que arruinó la tasa de vigentes y la primera tabla de Kaplan-Meier.
#
# Lo que sí dice algo del lugar es la **diferencia contra las demás zonas del
# mismo año**: en 2022, una zona con 80% de cierres previos y otra con 30% no
# son la misma zona. Por eso se les resta la media de su cohorte de alta.
RELATIVAS_AL_ANIO = ("cierres_previos_zona", "antiguedad_zona_anios")


def _relativizar_al_anio(f: pl.DataFrame) -> pl.DataFrame:
    anio = pl.col("inicio").dt.year()
    return f.with_columns(
        [(pl.col(c) - pl.col(c).mean().over(anio)).alias(f"{c}_rel") for c in RELATIVAS_AL_ANIO]
    ).drop(RELATIVAS_AL_ANIO)


def _entropia(salidas, i, j, dist, activo, local, desde, hasta, rubro, n_rubros) -> None:
    """Entropía de Shannon sobre los rubros vecinos activos.

    Mide qué tan diversa es la zona: un corredor con veinte rubros distintos y
    uno con veinte kioscos tienen la misma densidad y no son el mismo lugar.
    """
    sel = activo & (dist <= RADIO_ENTROPIA)
    if not sel.any():
        return
    conteo = np.zeros((hasta - desde, n_rubros))
    np.add.at(conteo, (local[sel], rubro[j[sel]]), 1)

    total = conteo.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(total > 0, conteo / total, 0)
        aporte = np.where(p > 0, -p * np.log(p), 0)
    salidas["entropia_rubros"][desde:hasta] = aporte.sum(axis=1)


def _historial(salidas, i, j, dist, propio, local, desde, hasta, inicio, fin) -> None:
    """Qué había pasado en la zona antes de que este local abriera.

    Dos cosas: qué proporción de los comercios que ya habían cerrado el capítulo
    terminó cerrando, y hace cuánto que hay actividad comercial ahí. Las dos
    miran únicamente hacia atrás.
    """
    cerca = (dist <= RADIO_HISTORIAL) & ~propio
    previos = cerca & (inicio[j] < inicio[i])
    if not previos.any():
        return

    # Ya terminados a esa altura: son los únicos cuyo desenlace se conocía.
    terminados = previos & (fin[j] <= inicio[i])
    n_previos = np.zeros(hasta - desde)
    n_cerrados = np.zeros(hasta - desde)
    np.add.at(n_previos, local[previos], 1)
    np.add.at(n_cerrados, local[terminados], 1)

    with np.errstate(divide="ignore", invalid="ignore"):
        tasa = np.where(n_previos > 0, n_cerrados / n_previos, np.nan)
    salidas["cierres_previos_zona"][desde:hasta] = tasa

    # Antigüedad comercial: desde la primera alta vista en el radio.
    primera = np.full(hasta - desde, np.inf)
    np.minimum.at(primera, local[previos], inicio[j[previos]])
    anios = (inicio[desde:hasta] - primera) / DIAS_ANIO
    salidas["antiguedad_zona_anios"][desde:hasta] = np.where(np.isfinite(anios), anios, np.nan)


def ejecutar() -> pl.DataFrame:
    log.info("Calculando features del entorno...")
    f = calcular()

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_PROCESADO / ARCHIVO
    f.write_parquet(salida)

    print(f"\n{'=' * 72}\n  Features del entorno comercial\n{'=' * 72}")
    print(f"\n{len(f):,} períodos con entorno medido en su fecha de alta.\n")
    columnas = [
        c
        for c in f.columns
        if c.startswith(("densidad", "competencia", "entropia", "cierres", "antiguedad"))
    ]
    with pl.Config(tbl_cols=12, tbl_hide_dataframe_shape=True, float_precision=2):
        print(f.select(columnas).describe())
    print(f"\nEscrito en {salida}")
    return f
