"""¿Se puede predecir qué zonas van a mejorar? Diagnóstico, y da que no.

Es una pregunta distinta de la que responde `modelo.py`. Ese predice **nivel**:
qué tan buena es una zona hoy. Esto sería **trayectoria**: qué zona va a estar
mejor en cinco años. Para un producto de "zonas con potencial" es la que
importa, y la buena noticia de entrada es que el techo de 0,608 no aplica acá
—ese techo es para predecir el desenlace de un local desde una etiqueta ruidosa
por local; al agregar decenas de locales por zona el error del proxy se promedia
y se achica con la raíz de n—.

La mala es que **no alcanzan los datos**, y el motivo es estructural, no una
falla del método.

**Dos trampas que hay que esquivar para siquiera plantear la pregunta.**

1. El stock absoluto de comercios activos crece de 6.690 en 2014 a 33.368 en
   2018 y después cae. Eso no es la ciudad creciendo: es la ventana de
   observación llenándose, porque en 2014 solo vemos permisos otorgados en 2014.
   Por eso acá todo se mide en **participación de la zona sobre la ciudad**, que
   es invariante a la ventana.
2. El estado futuro de una zona está pegadísimo al actual, así que un modelo que
   prediga el **nivel** da métricas hermosas sin predecir nada. Hay que predecir
   el **cambio**, y compararlo contra la persistencia y no contra el azar.

**Lo que se encontró.** Ni momentum ni reversión estable:

    corr(Δshare 2014-18, Δshare 2018-22) = +0,31   <- tramo contaminado por la ventana
    corr(Δshare 2018-22, Δshare 2022-26) = +0,07   <- tramo limpio: nada

    corr(momentum, Δshare futuro), por tamaño de zona:
       chicas   +0,03      medianas  -0,34      grandes  +0,15

Los signos se dan vuelta entre estratos, así que el -0,225 global no es un
fenómeno: es un estrato. Las features de nivel tampoco aportan (share actual
+0,01, aperturas +0,05, supervivencia previa de la zona +0,16).

**Por qué no alcanza.** El histórico va de 2014 a 2026, pero solo desde 2019 la
ventana está completa. Con un horizonte de 3 o 4 años, eso deja **una o dos
transiciones independientes** de zona. No es que la trayectoria sea impredecible:
es que con dos observaciones no se puede aprender ni validar nada, y cualquier
correlación que aparezca no tiene con qué replicarse.

Eso se destraba con más años —llegan a uno por año— o con una señal externa que
vea el crecimiento urbano sin depender del registro de habilitaciones. El
roadmap ya le había asignado ese papel a la capa satelital.
"""

from __future__ import annotations

import logging
from itertools import pairwise

import numpy as np
import polars as pl

from . import config, supervivencia

log = logging.getLogger(__name__)

LADO_CELDA_M = 800  # más chico deja celdas sin volumen; más grande, sin variación
MIN_STOCK = 8
PRIMER_ANIO_LIMPIO = 2019  # antes de esto la ventana de observación no está llena

METROS_POR_GRADO_LON = 88_500.0
METROS_POR_GRADO_LAT = 111_300.0
ORIGEN_LON, ORIGEN_LAT = -64.35, -31.55


def panel() -> pl.DataFrame:
    """Stock de comercios activos y participación sobre la ciudad, por zona y año."""
    h = supervivencia._historial()
    d = supervivencia.duraciones(supervivencia.consolidar(h))
    tramites = pl.read_parquet(config.DIR_CRUDO / "tramites.parquet").select(
        "id_tramite", "lon", "lat"
    )
    d = (
        d.join(tramites, left_on="ultimo_tramite", right_on="id_tramite", how="left")
        .drop_nulls(["lon", "lat"])
        .with_columns(
            pl.col("inicio").dt.year().alias("alta"),
            pl.col("fin_cobertura").dt.year().alias("baja"),
            ((pl.col("lon") - ORIGEN_LON) * METROS_POR_GRADO_LON / LADO_CELDA_M)
            .floor()
            .cast(pl.Int32)
            .alias("gx"),
            ((pl.col("lat") - ORIGEN_LAT) * METROS_POR_GRADO_LAT / LADO_CELDA_M)
            .floor()
            .cast(pl.Int32)
            .alias("gy"),
        )
        .with_columns((pl.col("gx") * 10_000 + pl.col("gy")).alias("zona"))
    )

    # Hasta el último año con altas, no hasta el último vencimiento: los permisos
    # llegan vigentes hasta 2031, pero de 2027 en adelante no hay observación —
    # solo permisos que todavía no vencieron. Contarlos daría una caída inventada.
    anios = range(d["alta"].min(), d["alta"].max() + 1)
    filas = [
        d.filter((pl.col("alta") <= a) & (pl.col("baja") > a))
        .group_by("zona")
        .len()
        .rename({"len": "stock"})
        .with_columns(pl.lit(a).alias("anio"))
        for a in anios
    ]
    return pl.concat(filas).with_columns(
        # Participación y no stock: el stock absoluto mide cuánta ventana de
        # observación llevamos acumulada, no cuánto comercio hay.
        (pl.col("stock") / pl.col("stock").sum().over("anio")).alias("share")
    )


def transiciones(p: pl.DataFrame, cortes: tuple[int, ...]) -> pl.DataFrame:
    """Cambio de participación entre los años de `cortes`, por zona.

    Solo zonas presentes en todos los cortes y con volumen: en una zona de tres
    locales, un cierre mueve la participación un tercio y eso es ruido, no una
    trayectoria.
    """
    w = p.filter(pl.col("anio").is_in(list(cortes))).pivot("anio", index="zona", values="share")
    stock = p.filter(pl.col("anio").is_in(list(cortes))).pivot("anio", index="zona", values="stock")
    columnas = [str(a) for a in cortes]
    grandes = stock.drop_nulls().filter(
        pl.min_horizontal([pl.col(c) for c in columnas]) >= MIN_STOCK
    )
    w = w.drop_nulls().join(grandes.select("zona"), on="zona", how="inner")

    return w.with_columns(
        [
            (pl.col(str(b)).log() - pl.col(str(a)).log()).alias(f"d{a}_{b}")
            for a, b in pairwise(cortes)
        ]
    )


def _corr(df: pl.DataFrame, x: str, y: str) -> float:
    return float(np.corrcoef(df[x].to_numpy(), df[y].to_numpy())[0, 1])


def ejecutar() -> pl.DataFrame:
    p = panel()
    print(f"\n{'=' * 72}\n  ¿Se puede predecir qué zonas van a mejorar?\n{'=' * 72}")

    ciudad = p.group_by("anio").agg(pl.col("stock").sum().alias("stock_ciudad")).sort("anio")
    print("\nStock de la ciudad por año. El crecimiento hasta 2018 es la ventana de")
    print("observación llenándose, no la ciudad creciendo. Por eso se mide en share:")
    with pl.Config(tbl_rows=15, tbl_hide_dataframe_shape=True):
        print(ciudad)

    sucio = transiciones(p, (2014, 2018, 2022))
    limpio = transiciones(p, (2018, 2022, 2026))
    print(f"\n¿El crecimiento pasado predice el futuro? (zonas de {LADO_CELDA_M} m)")
    print(
        f"  tramo con ventana incompleta  Δ14-18 -> Δ18-22 : "
        f"{_corr(sucio, 'd2014_2018', 'd2018_2022'):+.3f}  (n={len(sucio)})"
    )
    print(
        f"  tramo limpio                  Δ18-22 -> Δ22-26 : "
        f"{_corr(limpio, 'd2018_2022', 'd2022_2026'):+.3f}  (n={len(limpio)})"
    )

    print("\nMomentum por tamaño de zona. Si los signos se dan vuelta entre estratos,")
    print("no es un fenómeno: es ruido muestral con distinta cara en cada corte.")
    stock2018 = p.filter(pl.col("anio") == 2018).select("zona", pl.col("stock").alias("s0"))
    porte = limpio.join(stock2018, on="zona", how="inner")
    for lo, hi, etiqueta in (
        (MIN_STOCK, 15, "chicas"),
        (15, 40, "medianas"),
        (40, 10**6, "grandes"),
    ):
        g = porte.filter(pl.col("s0").is_between(lo, hi - 1))
        if len(g) < 25:
            continue
        print(f"  {etiqueta:<10} n={len(g):>4}  corr = {_corr(g, 'd2018_2022', 'd2022_2026'):+.3f}")

    print(
        f"\nVeredicto: el histórico va de 2014 a 2026 y solo desde {PRIMER_ANIO_LIMPIO} la\n"
        "ventana está completa. Con horizontes de 3-4 años eso deja una o dos\n"
        "transiciones independientes por zona: no alcanza para aprender ni para\n"
        "validar una trayectoria. No es que sea impredecible; es que no hay con qué."
    )
    return limpio
