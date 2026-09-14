"""Calibra el proxy de supervivencia contra una fuente externa de cierres.

El proyecto no observa cierres: nadie le avisa al municipio que cerró, y por eso
`vigente` viene nula. Lo que observamos es **si renovó el permiso**, que es un
proxy. Este módulo existe para medir qué tan bueno es ese proxy en vez de
asumirlo.

El plan es una muestra chica y una sola consulta, no un proceso recurrente:

1. `muestra()` elige ~1.500 locales estratificados y anota, para cada uno, lo
   que el pipeline **predice** hoy: cerró (el permiso caducó y nadie renovó) o
   sigue abierto (todavía tiene permiso).
2. Esa muestra se consulta contra Google Places, que sí publica
   `businessStatus` por local.
3. La comparación da la matriz de confusión del proxy: de los que llamamos
   cerrados, cuántos Places confirma cerrados, y viceversa.

Sin ese número, cualquier métrica del modelo se apoya en un supuesto sin medir.

**Qué sale de acá y qué no.** El CSV lleva dirección, rubro, coordenadas y
nombre de fantasía —todo público, está en el GIS— y el estado predicho. No
lleva `titular`: para calibrar el proxy no hace falta saber de quién es el
local, y lo que no se necesita no se guarda.

De ese CSV, **a Google solo se le manda la dirección y el punto**. El nombre de
fantasía se usa del lado de acá, para comparar contra el nombre que devuelve la
consulta: es lo que distingue "el local cambió de dueño" (nuestro proxy acertó,
el negocio original cerró) de "el mismo negocio sigue operando con el permiso
vencido" (nuestro proxy erró). Sin ese desempate, un `OPERATIONAL` no dice nada
sobre el local que nos interesa.
"""

from __future__ import annotations

import logging
from datetime import datetime

import polars as pl

from . import config, supervivencia

log = logging.getLogger(__name__)

# Tamaño de la muestra. Con ~750 por grupo, una tasa de acierto del 80% se mide
# con un margen de +/-3 puntos, que alcanza de sobra para decidir si el proxy
# sirve. Más consultas no compran precisión que cambie la decisión.
N_MUESTRA = 1_500

# Ventana de cierres consultables. Un local que cerró hace siete años ya no está
# en el índice de Places —o su ficha la ocupa el negocio que vino después— así
# que preguntarle por él no mide nuestro proxy, mide la memoria de Google.
ANIO_CIERRE_MIN = 2019

ARCHIVO = "muestra_places.csv"


def _tramites() -> pl.DataFrame:
    archivo = config.DIR_CRUDO / "tramites.parquet"
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Corré `python -m viabilidad ingest`.")
    df = pl.read_parquet(archivo)
    claves = ("id_tramite", "domicilio_loc", "lon", "lat", "nombrefantasia")
    if faltan := [c for c in claves if c not in df.columns]:
        raise ValueError(
            f"La tabla de trámites no trae {faltan}. Es un parquet de antes de que "
            "el ingest pidiera la dirección y la geometría: volvé a correr `ingest`."
        )
    return df


def preparar(hoy: datetime | None = None) -> pl.DataFrame:
    """Un local por período de actividad, con su dirección y el estado predicho."""
    h = supervivencia._historial()
    d = supervivencia.duraciones(supervivencia.consolidar(h), hoy=hoy)

    con_dir = d.join(
        _tramites().select("id_tramite", "domicilio_loc", "lon", "lat", "barrio", "nombrefantasia"),
        left_on="ultimo_tramite",
        right_on="id_tramite",
        how="left",
    )
    if sin_dir := con_dir["domicilio_loc"].null_count():
        log.warning("%s períodos sin dirección: quedan fuera de la muestra.", f"{sin_dir:,}")

    return con_dir.filter(pl.col("domicilio_loc").is_not_null()).with_columns(
        pl.when(pl.col("evento") == 1)
        .then(pl.lit("cerrado"))
        .otherwise(pl.lit("abierto"))
        .alias("estado_predicho"),
        pl.col("nivel1").list.first().alias("grupo"),
        pl.col("nivel2").list.join("|").alias("rubros"),
    )


def _consultables(p: pl.DataFrame) -> pl.DataFrame:
    """Descarta lo que Places no puede responder aunque el proxy esté bien.

    Un cierre viejo ya no figura, y una dirección repetida no distingue cuál de
    los locales de esa dirección es el nuestro: las dos cosas meterían error de
    la fuente externa dentro de la medición del proxy.

    Y sobre todo: **sin nombre de fantasía la consulta no puede aportar nada.**
    Que Places diga que en esa dirección opera un negocio no distingue si es el
    nuestro o el que lo reemplazó, que es justo lo que hay que decidir. Medido
    sobre las primeras 60 consultas: las 22 sin nombre salieron `sin_dato`, las
    22. Son llamadas que se facturan y no informan.
    """
    p = p.filter(pl.col("nombrefantasia").fill_null("").str.strip_chars() != "")
    cerrados = p.filter(
        (pl.col("estado_predicho") == "cerrado")
        & (pl.col("fin_cobertura").dt.year() >= ANIO_CIERRE_MIN)
    )
    abiertos = p.filter(pl.col("estado_predicho") == "abierto")

    unicos = (
        pl.concat([cerrados, abiertos])
        .group_by("domicilio_loc")
        .agg(pl.len().alias("_n"))
        .filter(pl.col("_n") == 1)
        .select("domicilio_loc")
    )
    return pl.concat([cerrados, abiertos]).join(unicos, on="domicilio_loc", how="inner")


def muestra(n: int = N_MUESTRA, semilla: int = 7, hoy: datetime | None = None) -> pl.DataFrame:
    """Muestra estratificada por estado predicho y grupo de rubro.

    Mitad y mitad entre cerrados y abiertos, y dentro de cada mitad en la
    proporción real de cada grupo. Balanceada a propósito: lo que se quiere
    medir es el acierto en cada clase, y la clase chica es la que decide.
    """
    disponible = _consultables(preparar(hoy=hoy))
    por_clase = n // 2
    partes = []

    for estado in ("cerrado", "abierto"):
        clase = disponible.filter(pl.col("estado_predicho") == estado)
        if clase.is_empty():
            raise ValueError(f"No quedó ningún caso '{estado}' consultable.")
        if len(clase) <= por_clase:
            log.warning(
                "Solo hay %s casos '%s' consultables, menos que los %s pedidos.",
                f"{len(clase):,}",
                estado,
                f"{por_clase:,}",
            )
            partes.append(clase)
            continue
        partes.append(
            clase.with_columns(
                (pl.col("grupo").len().over("grupo") / len(clase) * por_clase)
                .round()
                .clip(1)
                .alias("_cupo")
            )
            .sample(fraction=1.0, shuffle=True, seed=semilla)
            .with_columns(pl.int_range(pl.len()).over("grupo").alias("_i"))
            .filter(pl.col("_i") < pl.col("_cupo"))
            .drop("_cupo", "_i")
        )

    return (
        pl.concat(partes)
        .select(
            "ultimo_tramite",
            "domicilio_loc",
            "lon",
            "lat",
            "barrio",
            "nombrefantasia",
            "grupo",
            "rubros",
            "estado_predicho",
            pl.col("inicio").dt.date(),
            pl.col("fin_cobertura").dt.date(),
        )
        .sort("estado_predicho", "grupo")
    )


def ejecutar() -> pl.DataFrame:
    m = muestra()
    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_PROCESADO / ARCHIVO
    m.write_csv(salida)

    print(f"\n{'=' * 72}\n  Muestra para calibrar el proxy contra Places\n{'=' * 72}")
    print(f"\n{len(m):,} locales. Por estado predicho:")
    with pl.Config(tbl_hide_dataframe_shape=True):
        print(m.group_by("estado_predicho").len().sort("estado_predicho"))
        print("\nPor grupo de rubro:")
        print(
            m.group_by("grupo", "estado_predicho")
            .len()
            .pivot("estado_predicho", index="grupo", values="len")
            .fill_null(0)
            .sort("grupo")
        )
    print(f"\nEscrito en {salida}")
    print("No se versiona: `data/` está gitignoreado. No lleva titular.")
    return m
