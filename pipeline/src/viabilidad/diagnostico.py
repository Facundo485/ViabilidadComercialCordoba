"""¿La tasa `vigentes/total` mide supervivencia, o mide antigüedad?

Es el bloqueante que documenta `docs/proximo-paso.md`: la tasa da 95,6% en
`bar_restaurante` y 0% en `regaleria`, valores que ningún mercado produce.

La sospecha es que `rubronombre` mezcla dos nomencladores usados en épocas
distintas —el municipal viejo (Título, con acentos) y el CLANAE/CIIU nuevo
(MAYÚSCULAS)—, así que el rubro queda correlacionado con el año de habilitación.
Como el permiso dura ~5 años, lo reciente figura vigente por construcción y la
tasa termina midiendo el nomenclador en vez del negocio.

Este módulo lo mide en vez de suponerlo, por dos vías independientes:

- `nomenclador()` cruza, por rubro, la tasa contra la proporción de sus
  habilitaciones cargadas bajo el nomenclador nuevo. Usa solo tablas
  versionadas, así que corre sin red y sin haber descargado el GIS.
- `epoca()` cruza la tasa contra el año mediano de habilitación. Necesita
  `data/crudo/historial.parquet`, es decir un `ingest` previo.

Ninguna de las dos prueba causalidad; lo que muestran es que la tasa no sirve
para comparar rubros entre sí, que es lo que hace falta decidir.
"""

from __future__ import annotations

import logging

import polars as pl

from . import config, mapeo

log = logging.getLogger(__name__)

# Por debajo de esto la tasa de un rubro se mueve demasiado por ruido muestral
# para que la comparación entre rubros signifique algo.
MIN_HABILITACIONES = 300

# El umbral que fija docs/proximo-paso.md: por encima, la tasa cruda mide
# antigüedad y no sirve para comparar rubros entre sí.
UMBRAL_CORR = 0.7

ARCHIVO_RESUMEN = "resumen_rubros.csv"


def es_nomenclador_nuevo(col: str = "rubronombre") -> pl.Expr:
    """El CLANAE/CIIU se cargó en MAYÚSCULAS; el municipal viejo, en Título.

    Se detecta por ausencia de minúsculas y no comparando contra `to_uppercase`:
    así una entrada sin letras no cuenta como nueva por casualidad.
    """
    return ~pl.col(col).fill_null("").str.contains("[a-z" + "".join(config.ACENTOS) + "]")


def _tasas_por_rubro() -> pl.DataFrame:
    """La tasa por rubro de la última corrida, desde el resumen versionado."""
    archivo = config.RAIZ / ARCHIVO_RESUMEN
    if not archivo.exists():
        raise FileNotFoundError(
            f"Falta {archivo}. Generalo con `python -m viabilidad resumen` "
            "(requiere haber corrido ingest y manzanas)."
        )
    return pl.read_csv(archivo)


def _mezcla_de_nomencladores() -> pl.DataFrame:
    """Por rubro de nivel 2, qué proporción viene del nomenclador nuevo."""
    archivo = config.DIR_REFERENCIA / mapeo.ARCHIVO
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Generalo con `python -m viabilidad mapeo`.")

    return (
        pl.read_csv(archivo)
        .with_columns(es_nomenclador_nuevo().alias("nuevo"))
        .group_by("nivel2")
        .agg(
            pl.col("n").sum().alias("hab_mapeo"),
            (pl.col("n") * pl.col("nuevo")).sum().alias("hab_nuevo"),
        )
        .with_columns((pl.col("hab_nuevo") / pl.col("hab_mapeo")).alias("frac_nuevo"))
    )


def _correlaciones(df: pl.DataFrame, x: str, y: str) -> tuple[float, float]:
    """Pearson y Spearman. La segunda no asume que la relación sea lineal."""
    pearson = df.select(pl.corr(x, y)).item()
    spearman = df.select(pl.corr(pl.col(x).rank(), pl.col(y).rank())).item()
    return pearson, spearman


def nomenclador() -> pl.DataFrame:
    """Cruza la tasa de cada rubro contra su proporción de nomenclador nuevo.

    Corre sin red: se apoya en `referencia/mapeo_rubros.csv` y en
    `resumen_rubros.csv`, los dos versionados.
    """
    df = (
        _tasas_por_rubro()
        .join(_mezcla_de_nomencladores(), on="nivel2")
        # "otro" es el cajón de lo no clasificado: mezcla rubros sin relación y
        # su tasa promedia cosas que no se parecen.
        .filter((pl.col("nivel2") != "otro") & (pl.col("habilitaciones") >= MIN_HABILITACIONES))
        .with_columns((pl.col("tasa") - pl.col("frac_nuevo")).abs().alias("brecha"))
        .select("nivel2", "nivel1", "habilitaciones", "tasa", "frac_nuevo", "brecha")
        .sort("tasa", descending=True)
    )
    if df.is_empty():
        raise ValueError("Ningún rubro superó el umbral; ¿el resumen quedó vacío?")
    return df


def epoca() -> pl.DataFrame | None:
    """Cruza la tasa de cada rubro contra su año mediano de habilitación.

    Es la comprobación directa de la hipótesis, pero necesita el histórico
    crudo. Devuelve None si todavía no se descargó, para que el diagnóstico del
    nomenclador —que no necesita red— pueda correr igual.
    """
    archivo = config.DIR_CRUDO / "historial.parquet"
    if not archivo.exists():
        log.warning(
            "No está %s, se omite el cruce contra el año. Corré `python -m viabilidad ingest`.",
            archivo,
        )
        return None

    h = pl.read_parquet(archivo)
    return (
        h.filter(pl.col("nivel2") != "otro")
        .group_by("nivel2")
        .agg(
            pl.len().alias("habilitaciones"),
            pl.col("fechahabaprobada").dt.year().median().alias("anio_mediano"),
            pl.col("vigente").mean().alias("tasa"),
        )
        .filter(pl.col("habilitaciones") >= MIN_HABILITACIONES)
        .sort("tasa", descending=True)
    )


def ajuste_por_el_origen(df: pl.DataFrame) -> tuple[float, float]:
    """Ajusta `tasa = p * frac_nuevo` y devuelve (p, R²).

    El modelo dice algo concreto y falsable: que una habilitación del
    nomenclador viejo no sobrevive nunca, y que una del nuevo sobrevive con
    probabilidad p sin importar el rubro. Si ajusta bien, la tasa por rubro es
    aritmética del nomenclador, no una señal del negocio.
    """
    pendiente = (df["tasa"] * df["frac_nuevo"]).sum() / (df["frac_nuevo"] ** 2).sum()
    residuos = df["tasa"] - pendiente * df["frac_nuevo"]
    r2 = 1 - (residuos**2).sum() / (df["tasa"] ** 2).sum()
    return pendiente, r2


def ejecutar() -> None:
    """Corre las dos comprobaciones e imprime el veredicto."""
    df = nomenclador()
    pearson, spearman = _correlaciones(df, "frac_nuevo", "tasa")
    pendiente, r2 = ajuste_por_el_origen(df)

    print(f"\n{'=' * 72}\n  Paso 1 — ¿la tasa mide supervivencia o el nomenclador?\n{'=' * 72}")
    print(f"\n{len(df)} rubros de nivel 2 con >={MIN_HABILITACIONES} habilitaciones.\n")
    with pl.Config(tbl_rows=100, fmt_str_lengths=24, tbl_hide_dataframe_shape=True):
        print(df)

    print(f"\ncorrelación (frac_nuevo, tasa): Pearson {pearson:.3f} | Spearman {spearman:.3f}")
    cerca = df.filter(pl.col("brecha") < 0.10).height
    print(f"rubros donde |tasa - frac_nuevo| < 0,10: {cerca} de {len(df)}")
    print(f"ajuste tasa = p * frac_nuevo: p = {pendiente:.3f}, R² = {r2:.3f}")

    if pearson > UMBRAL_CORR:
        print(
            f"\nCONFIRMADO (Pearson {pearson:.3f} > {UMBRAL_CORR}). La tasa cruda no compara\n"
            "rubros entre sí: reproduce la proporción de nomenclador nuevo, que es un\n"
            "marcador de época. Reemplazarla por supervivencia (Paso 2) antes de\n"
            "construir features sobre ella."
        )
    else:
        print(
            f"\nNO confirmado por esta vía (Pearson {pearson:.3f} <= {UMBRAL_CORR}). "
            "Revisar el cruce contra el año antes de descartar la hipótesis."
        )

    por_anio = epoca()
    if por_anio is None:
        return

    pearson_anio, spearman_anio = _correlaciones(por_anio, "anio_mediano", "tasa")
    print(f"\n{'-' * 72}\nCruce contra el año de habilitación\n{'-' * 72}")
    with pl.Config(tbl_rows=100, fmt_str_lengths=24, tbl_hide_dataframe_shape=True):
        print(por_anio)
    print(
        f"\ncorrelación (anio_mediano, tasa): Pearson {pearson_anio:.3f} "
        f"| Spearman {spearman_anio:.3f}"
    )
    if pearson_anio > UMBRAL_CORR:
        print("CONFIRMADO también por año: la tasa sube con lo reciente del rubro.")


# ---------------------------------------------------------------------------
# El segundo problema del indicador publicado: además de medir época, se incluye
# a sí mismo.
# ---------------------------------------------------------------------------

VOLUMENES = (
    (1, 4, "1-3 habilitaciones"),
    (4, 10, "4-9"),
    (10, 25, "10-24"),
    (25, 10**9, "25 o mas"),
)


def fuga_del_indicador() -> pl.DataFrame:
    """Mide si el indicador publicado contiene al local que uno quiere consultar.

    La capa 0 del GIS publica `hab_vigentes/hab_total` por parcela, y leído como
    "qué tan bien le va al comercio en esta cuadra" parece una tasa de
    supervivencia de la zona. Pero se calcula sobre **todas** las habilitaciones
    de la manzana, incluida la que uno está por consultar.

    La prueba limpia son las manzanas con **exactamente una** habilitación: ahí
    el indicador no puede ser otra cosa que el estado de ese único local. Medido,
    coincide el 95,9% de las veces.

    Eso lo descalifica como línea base contra la cual comparar un modelo —le gana
    a cualquiera porque conoce la respuesta— y engaña a quien lo lea para decidir
    dónde poner un local.
    """
    f = pl.read_parquet(config.DIR_PROCESADO / "features.parquet")
    una = (
        pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")
        .filter(pl.col("hab_total") == 1)
        .select("manzana", pl.col("hab_vigentes").alias("vigentes_municipio"))
    )
    g = f.join(una, on="manzana", how="inner").with_columns(
        (pl.col("evento") == 0).cast(pl.Int8).alias("sigue_vigente")
    )
    if g.is_empty():
        raise ValueError("Ninguna manzana de una sola habilitación; no hay qué medir.")
    return pl.DataFrame(
        [
            {
                "manzanas_de_una_habilitacion": len(una),
                "locales_comparados": len(g),
                "coincide_con_su_vigencia": round(
                    g.filter(pl.col("vigentes_municipio") == pl.col("sigue_vigente")).height
                    / len(g),
                    3,
                ),
            }
        ]
    )


def veredictos_extremos() -> pl.DataFrame:
    """Cuántas manzanas reciben un 0% o un 100% por tener una o dos habilitaciones.

    Es la consecuencia práctica de lo anterior. Más de la mitad de Córdoba son
    manzanas con menos de cuatro habilitaciones en doce años, y ahí el cociente
    crudo casi solo puede dar un extremo. Una cuadra no tiene 0% de
    supervivencia porque el único local que abrió en 2015 haya cerrado.
    """
    mz = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet").with_columns(
        (pl.col("hab_vigentes") / pl.col("hab_total")).alias("tasa")
    )
    filas = []
    for lo, hi, etiqueta in VOLUMENES:
        g = mz.filter(pl.col("hab_total").is_between(lo, hi - 1))
        if not len(g):
            continue
        extremos = g.filter((pl.col("tasa") < 0.001) | (pl.col("tasa") > 0.999)).height
        filas.append(
            {
                "volumen": etiqueta,
                "manzanas": len(g),
                "da_un_extremo": round(extremos / len(g), 3),
                "mediana": round(g["tasa"].median(), 3),
            }
        )
    return pl.DataFrame(filas)


def ejecutar_fuga() -> None:
    print(f"\n{'=' * 72}\n  El indicador publicado se incluye a sí mismo\n{'=' * 72}\n")
    with pl.Config(tbl_hide_dataframe_shape=True):
        r = fuga_del_indicador()
        print(r)
        print(
            f"\nEn una manzana con una sola habilitación, el indicador del municipio\n"
            f"coincide con el estado de ese único local el "
            f"{r['coincide_con_su_vigencia'][0]:.1%} de las veces.\n"
            "No describe la cuadra: describe al local que uno está por consultar."
        )
        print("\nConsecuencia práctica, por manzana:")
        print(veredictos_extremos())
    mz = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")
    chicas = mz.filter(pl.col("hab_total") < 4).height
    print(
        f"\n{chicas:,} manzanas ({chicas / len(mz):.0%} de la ciudad) tienen menos de "
        "cuatro habilitaciones\nen doce años. Ahí el cociente crudo casi solo puede dar "
        "0% o 100%, y eso no es\nuna propiedad de la cuadra: es el destino de uno o dos "
        "locales."
    )
