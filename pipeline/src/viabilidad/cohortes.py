"""Paso 2b: supervivencia estratificada por cohorte de alta.

Una sola curva por rubro mezcla doce años de aperturas, y eso deja que el rubro
hable por su época en vez de por su negocio. Los dos nomencladores se usaron en
períodos distintos, así que "qué rubro es" y "de qué año es" venían pegados:
después de arreglar el agrupamiento, `s5` todavía correlaciona 0,45 con el año
mediano del rubro.

La estratificación separa las dos cosas. Se compara cada rubro **contra la
ciudad de su misma cohorte**, no contra la ciudad entera:

    efecto(rubro) = promedio sobre cohortes de [ s5(rubro, cohorte)
                                                - s5(ciudad, cohorte) ]

Así, que 2014 haya sido un mal año para abrir no le suma ni le resta a ningún
rubro: se lo come el término de la ciudad.

**El test que decide si esto sirve** no es el efecto en sí, es su estabilidad:
si el orden de los rubros se mantiene entre cohortes independientes, hay un
efecto de rubro. Si cada cohorte ordena distinto, la tabla es ruido con nombres
y no hay nada que modelar a este nivel. Eso lo mide `estabilidad()` con una
correlación de rangos entre pares de cohortes.

Las cohortes necesitan ventana completa: para leer `s5` hay que haber podido
observar cinco años. Una cohorte más reciente no se estima, se extrapola.
"""

from __future__ import annotations

import logging
from datetime import datetime
from itertools import combinations

import polars as pl

from . import config, supervivencia

log = logging.getLogger(__name__)

# Bordes de cohorte, inclusive. De a dos años para que cada una junte ~13.000
# spells y los rubros medianos lleguen al mínimo sin quedarse sin cohortes.
# 2020-2021 queda afuera a propósito: las altas se desplomaron con la pandemia
# y la cohorte no junta volumen para estimar rubro por rubro.
COHORTES: tuple[tuple[int, int], ...] = ((2014, 2015), (2016, 2017), (2018, 2019))

# Mínimo por rubro **y cohorte**, no por rubro. Más bajo que el de la curva
# global porque acá el mismo rubro se estima varias veces y lo que importa es
# que el orden entre cohortes sea comparable, no cada punto por separado.
MIN_SPELLS_COHORTE = 80

HORIZONTE = supervivencia.HORIZONTE_PRINCIPAL
COLUMNA = supervivencia._columna(HORIZONTE)


def _etiqueta(desde: int, hasta: int) -> str:
    return f"{desde}-{hasta}"


def asignar(d: pl.DataFrame, hoy: datetime | None = None) -> pl.DataFrame:
    """Etiqueta cada spell con su cohorte de alta y descarta las incompletas.

    Corta las cohortes que todavía no cumplieron el horizonte: sin cinco años de
    seguimiento, `s5` no se mide, se extrapola desde los pocos que llegaron.
    """
    hoy = hoy or datetime.now()
    ultimo_completo = hoy.year - int(HORIZONTE)

    expr = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    usadas = []
    for desde, hasta in COHORTES:
        if hasta > ultimo_completo:
            log.warning(
                "La cohorte %s no tiene %s años de seguimiento a %s: se descarta.",
                _etiqueta(desde, hasta),
                HORIZONTE,
                hoy.year,
            )
            continue
        usadas.append((desde, hasta))
        expr = expr.when(pl.col("inicio").dt.year().is_between(desde, hasta)).then(
            pl.lit(_etiqueta(desde, hasta))
        )

    if not usadas:
        raise ValueError(
            f"Ninguna cohorte tiene {HORIZONTE} años completos a {hoy.year}. "
            "Revisá COHORTES: están todas por delante del horizonte."
        )
    return d.with_columns(expr.otherwise(pl.lit(None, dtype=pl.Utf8)).alias("cohorte")).filter(
        pl.col("cohorte").is_not_null()
    )


def linea_base(d: pl.DataFrame) -> pl.DataFrame:
    """Supervivencia de la ciudad en cada cohorte. Es el término que se resta."""
    filas = []
    for (cohorte,), grupo in d.group_by("cohorte", maintain_order=True):
        km = supervivencia.kaplan_meier(
            grupo.with_columns(pl.lit("ciudad").alias("_todo")), "_todo"
        )
        filas.append({"cohorte": cohorte, "spells_cohorte": len(grupo), "base": km[COLUMNA][0]})
    return pl.DataFrame(filas).sort("cohorte")


def por_cohorte(d: pl.DataFrame, por: str = "nivel2") -> pl.DataFrame:
    """Tabla larga rubro x cohorte con su supervivencia a `HORIZONTE` años."""
    original = supervivencia.MIN_SPELLS
    supervivencia.MIN_SPELLS = MIN_SPELLS_COHORTE
    try:
        filas = []
        for (cohorte,), grupo in d.group_by("cohorte", maintain_order=True):
            try:
                km = supervivencia.kaplan_meier(grupo, por)
            except ValueError:
                log.warning("Ningún rubro llegó al mínimo en la cohorte %s.", cohorte)
                continue
            filas.append(km.with_columns(pl.lit(cohorte).alias("cohorte")))
    finally:
        supervivencia.MIN_SPELLS = original

    if not filas:
        raise ValueError("Ninguna cohorte produjo curvas; ¿quedó sin spells?")
    return (
        pl.concat(filas)
        .join(linea_base(d), on="cohorte")
        .with_columns((pl.col(COLUMNA) - pl.col("base")).alias("efecto"))
    )


def estabilidad(tabla: pl.DataFrame, por: str = "nivel2") -> pl.DataFrame:
    """Correlación de rangos entre cohortes: ¿ordenan los rubros igual?

    Es el chequeo que decide. Dos cohortes son muestras independientes —locales
    distintos, años distintos—, así que si coinciden en el orden es porque el
    rubro dice algo. Rangos y no valores: no importa si una cohorte entera
    sobrevivió menos, importa quién le ganó a quién.
    """
    filas = []
    for a, b in combinations(sorted(tabla["cohorte"].unique()), 2):
        comun = (
            tabla.filter(pl.col("cohorte") == a)
            .select(por, pl.col(COLUMNA).alias("a"))
            .join(
                tabla.filter(pl.col("cohorte") == b).select(por, pl.col(COLUMNA).alias("b")), on=por
            )
        )
        if len(comun) < 3:
            continue
        filas.append(
            {
                "cohorte_a": a,
                "cohorte_b": b,
                "rubros": len(comun),
                "spearman": comun.select(pl.corr(pl.col("a").rank(), pl.col("b").rank())).item(),
            }
        )
    if not filas:
        raise ValueError("No hubo dos cohortes con rubros en común para comparar.")
    return pl.DataFrame(filas)


def efecto_rubro(tabla: pl.DataFrame, por: str = "nivel2") -> pl.DataFrame:
    """El efecto de cada rubro, promediado sobre las cohortes donde se midió.

    Solo se promedian rubros presentes en más de una cohorte: con una sola no se
    puede distinguir el efecto del rubro del de su época, que es justamente lo
    que se está tratando de separar.
    """
    return (
        tabla.group_by(por)
        .agg(
            pl.len().alias("cohortes"),
            pl.col("spells").sum(),
            pl.col("efecto").mean().alias("efecto"),
            pl.col("efecto").min().alias("efecto_min"),
            pl.col("efecto").max().alias("efecto_max"),
        )
        .filter(pl.col("cohortes") > 1)
        .sort("efecto", descending=True)
    )


def ejecutar() -> pl.DataFrame:
    h = supervivencia._historial()
    d = asignar(supervivencia.duraciones(supervivencia.consolidar(h)))

    print(f"\n{'=' * 72}\n  Paso 2b — supervivencia por cohorte de alta\n{'=' * 72}")

    base = linea_base(d)
    print(f"\nSupervivencia de la ciudad a {HORIZONTE} años, por cohorte de alta:")
    with pl.Config(tbl_hide_dataframe_shape=True):
        print(base)

    tabla = por_cohorte(d)
    est = estabilidad(tabla)
    print("\nEstabilidad del orden entre cohortes (correlación de rangos):")
    with pl.Config(tbl_hide_dataframe_shape=True):
        print(est)

    promedio = est["spearman"].mean()
    if promedio < 0.3:
        log.error(
            "Las cohortes ordenan los rubros de forma casi independiente (rho medio %.2f). "
            "La tabla por rubro no tiene efecto de rubro que extraer: no la uses como feature.",
            promedio,
        )
    else:
        print(
            f"\n  rho medio {promedio:.2f}: el orden entre rubros se sostiene "
            "en cohortes independientes."
        )

    efecto = efecto_rubro(tabla)
    print(f"\nEfecto de rubro (puntos de {COLUMNA} sobre la ciudad de su cohorte):")
    with pl.Config(tbl_rows=100, fmt_str_lengths=24, tbl_hide_dataframe_shape=True):
        print(efecto)

    salida = config.RAIZ / "efecto_rubro.csv"
    efecto.write_csv(salida)
    tabla.write_csv(config.RAIZ / "supervivencia_cohortes.csv")
    print(f"\nEscrito {salida.name} y supervivencia_cohortes.csv en {config.RAIZ}")
    return efecto
