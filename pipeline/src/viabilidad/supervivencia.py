"""Supervivencia con Kaplan-Meier, reemplazando la tasa `vigentes/total`.

Es el Paso 2 de `docs/proximo-paso.md`, con una corrección respecto de cómo
estaba planteado ahí. La receta original decía:

    duración = fechavencimientohab - fechahabaprobada  (para las vencidas)
    evento   = 1 si venció

Tomada literal, **reproduce el bug del Paso 1 en forma más sofisticada.** Esa
resta no es la vida del comercio: es el plazo que el municipio otorgó. Si los
permisos duran ~5 años, toda habilitación vencida tiene duración ~5 años por
definición administrativa, y toda vigente tiene duración menor porque todavía no
llegó. Kaplan-Meier sobre eso devuelve una curva plana con un escalón a los 5
años, y lo único que diferencia a un rubro de otro vuelve a ser qué proporción
de sus registros es reciente. Otra vez época disfrazada de supervivencia.

Lo que distingue a un comercio que sobrevive no es que su permiso venza —vence
siempre— sino **si lo renovó**. Así que la unidad de análisis no es la
habilitación: es el período de actividad (`spell`) de un titular en una
dirección, que puede abarcar varias habilitaciones encadenadas.

    spell = habilitaciones sucesivas de (cuitempresa, nro_catastral)
            sin un hueco mayor a HUECO_DIAS entre el vencimiento de una
            y el alta de la siguiente

    cierre    = el permiso caducó y no se renovó
    censura   = todavía tiene permiso vigente (sigue abierto hasta donde vemos)

`plazos()` mide el supuesto antes de usarlo: si el plazo otorgado resulta ser
aproximadamente constante, la advertencia de arriba aplica y consolidar por
renovación no es un refinamiento sino la única lectura válida.
"""

from __future__ import annotations

import logging
from datetime import datetime

import polars as pl

from . import config

log = logging.getLogger(__name__)

DIAS_ANIO = 365.25

# Dos habilitaciones del mismo titular en la misma dirección separadas por más
# de esto no son una renovación: es alguien que se fue y volvió.
HUECO_DIAS = 365

# Un permiso vencido hace poco todavía puede renovarse fuera de término. Darlo
# por cerrado en ese lapso inventa cierres; se censura en su lugar.
GRACIA_DIAS = 365

# Debajo de esto la curva de un rubro se mueve por ruido muestral.
MIN_SPELLS = 100

# Horizontes que se reportan. El de 3 años es el que pedía el roadmap; el de 5
# es el que importa acá, porque es donde cae el primer vencimiento.
HORIZONTES = (3, 5)

COLUMNAS_CLAVE = ["cuitempresa", "nro_catastral", "fechahabaprobada", "fechavencimientohab"]


def _historial() -> pl.DataFrame:
    archivo = config.DIR_CRUDO / "historial.parquet"
    if not archivo.exists():
        raise FileNotFoundError(
            f"Falta {archivo}. Corré `python -m viabilidad ingest` (necesita llegar al GIS)."
        )
    df = pl.read_parquet(archivo)
    if faltan := [c for c in COLUMNAS_CLAVE if c not in df.columns]:
        raise ValueError(f"El historial no trae {faltan}; sin eso no se puede medir duración.")
    return df


def plazos(h: pl.DataFrame) -> pl.DataFrame:
    """Distribución del plazo otorgado, en años. Mide el supuesto del módulo.

    Si la dispersión es chica, la duración de una habilitación suelta es una
    constante administrativa y no dice nada sobre el comercio: hay que
    consolidar renovaciones sí o sí.
    """
    return (
        h.filter(
            pl.col("fechavencimientohab").is_not_null() & pl.col("fechahabaprobada").is_not_null()
        )
        .select(
            (
                (pl.col("fechavencimientohab") - pl.col("fechahabaprobada")).dt.total_days()
                / DIAS_ANIO
            ).alias("plazo_anios")
        )
        .select(
            pl.len().alias("n"),
            pl.col("plazo_anios").mean().alias("media"),
            pl.col("plazo_anios").std().alias("desvio"),
            pl.col("plazo_anios").quantile(0.1).alias("p10"),
            pl.col("plazo_anios").median().alias("mediana"),
            pl.col("plazo_anios").quantile(0.9).alias("p90"),
        )
    )


def consolidar(h: pl.DataFrame) -> pl.DataFrame:
    """Encadena las renovaciones de un mismo titular en una misma dirección.

    Sin esto, un local de 20 años que renovó cuatro veces aparece como cuatro
    comercios de 5 años, y la supervivencia medida da exactamente el plazo del
    permiso.

    Las filas sin `cuitempresa` no se pueden encadenar con nada, así que cada
    una queda como su propio spell: es la lectura conservadora (subestima la
    duración) y no inventa vínculos entre titulares distintos.
    """
    base = h.filter(
        pl.col("fechahabaprobada").is_not_null() & pl.col("fechavencimientohab").is_not_null()
    )
    if base.is_empty():
        raise ValueError("Ninguna habilitación tiene las dos fechas; no hay duración que medir.")

    base = base.with_columns(
        pl.coalesce(pl.col("cuitempresa").cast(pl.Utf8), pl.lit("__sin_cuit__")).alias("_titular")
    ).sort("_titular", "nro_catastral", "fechahabaprobada")

    grupo = ["_titular", "nro_catastral"]
    # Un alta posterior al vencimiento acumulado del grupo, por más de HUECO_DIAS,
    # abre un spell nuevo. El máximo acumulado y no el vencimiento anterior:
    # los permisos se solapan y el orden por alta no garantiza el de vencimiento.
    cobertura_previa = pl.col("fechavencimientohab").cum_max().shift(1).over(grupo)
    hueco = (pl.col("fechahabaprobada") - cobertura_previa).dt.total_days()

    con_spell = base.with_columns(
        (
            cobertura_previa.is_null().cast(pl.Int32)
            | (hueco > HUECO_DIAS).fill_null(True).cast(pl.Int32)
        )
        .cum_sum()
        .over(grupo)
        .alias("_spell")
    ).with_columns(
        pl.when(pl.col("_titular") == "__sin_cuit__")
        .then(pl.col("objectid").cast(pl.Utf8))
        .otherwise(pl.col("_spell").cast(pl.Utf8))
        .alias("_spell")
    )

    return (
        con_spell.group_by("_titular", "nro_catastral", "_spell")
        .agg(
            pl.col("fechahabaprobada").min().alias("inicio"),
            pl.col("fechavencimientohab").max().alias("fin_cobertura"),
            pl.len().alias("habilitaciones"),
            pl.col("nivel2").first(),
            pl.col("nivel1").first(),
            pl.col("manzana").first(),
        )
        .drop("_spell", "_titular")
    )


def duraciones(spells: pl.DataFrame, hoy: datetime | None = None) -> pl.DataFrame:
    """Duración y evento de cada spell, con censura a derecha explícita.

    - Cerró: la cobertura caducó hace más de GRACIA_DIAS y nadie renovó.
    - Censurado: todavía tiene permiso, o venció hace tan poco que una
      renovación fuera de término sigue siendo plausible.

    Nunca se rellena la censura como cierre. Es el error que ya se cometió una
    vez con `vigente` nulo y produjo una tabla de ceros sin que nada fallara.
    """
    hoy = hoy or datetime.now()
    corte = pl.lit(hoy)

    dias_desde_fin = (corte - pl.col("fin_cobertura")).dt.total_days()
    cerro = dias_desde_fin > GRACIA_DIAS

    # El que cerró se observa hasta que caducó; el que sigue, hasta hoy.
    fin_observado = pl.when(cerro).then(pl.col("fin_cobertura")).otherwise(corte)

    return (
        spells.with_columns(
            cerro.cast(pl.Int8).alias("evento"),
            ((fin_observado - pl.col("inicio")).dt.total_days() / DIAS_ANIO).alias("duracion"),
        )
        # Una duración negativa es un registro con fechas invertidas, no un caso límite.
        .filter(pl.col("duracion") > 0)
    )


def kaplan_meier(d: pl.DataFrame, por: str) -> pl.DataFrame:
    """Curva de Kaplan-Meier por categoría, con la supervivencia a 3 y 5 años.

    KM es lo que maneja bien la censura: un local abierto hace 6 meses aporta
    "sobrevivió al menos 6 meses" sin contarse como éxito ni como fracaso.
    """
    from lifelines import KaplanMeierFitter

    filas = []
    for (categoria,), grupo in d.group_by(por, maintain_order=True):
        if len(grupo) < MIN_SPELLS:
            continue
        km = KaplanMeierFitter()
        km.fit(grupo["duracion"].to_numpy(), event_observed=grupo["evento"].to_numpy())

        fila = {
            por: categoria,
            "spells": len(grupo),
            "cierres": int(grupo["evento"].sum()),
            "mediana_anios": float(km.median_survival_time_),
        }
        for h in HORIZONTES:
            fila[f"s{h}"] = round(float(km.predict(h)), 3)
        filas.append(fila)

    if not filas:
        raise ValueError(f"Ninguna categoría de {por} llegó a {MIN_SPELLS} spells.")

    return pl.DataFrame(filas).sort(f"s{HORIZONTES[-1]}", descending=True)


def _alertar_si_degenerado(km: pl.DataFrame, por: str) -> None:
    """Una curva idéntica en todas las categorías es un bug, no un hallazgo."""
    columna = f"s{HORIZONTES[-1]}"
    if km[columna].n_unique() <= 1:
        log.error(
            "Todas las categorías de %s dan la misma supervivencia a %s años (%s). "
            "Revisá la consolidación de renovaciones antes de leer esto como resultado.",
            por,
            HORIZONTES[-1],
            km[columna].unique().to_list(),
        )


def chequeo_gastronomia_vs_farmacia(km_n1: pl.DataFrame, km_n2: pl.DataFrame) -> bool | None:
    """Sanity check del doc: gastronomía tiene que quedar por debajo de farmacia.

    Es conocimiento de dominio, no estadística: si da al revés, el objetivo
    sigue midiendo otra cosa. Devuelve None si falta alguno de los dos.
    """
    columna = f"s{HORIZONTES[-1]}"
    gastro = km_n1.filter(pl.col("nivel1") == "gastronomia")
    farmacia = km_n2.filter(pl.col("nivel2") == "farmacia")
    if gastro.is_empty() or farmacia.is_empty():
        log.warning("Sin volumen para el chequeo gastronomía vs farmacia.")
        return None

    g, f = gastro[columna][0], farmacia[columna][0]
    ok = g < f
    if g == f:
        veredicto = "EMPATE"
    elif ok:
        veredicto = "OK"
    else:
        veredicto = "AL REVÉS"

    print(f"\nChequeo de dominio — supervivencia a {HORIZONTES[-1]} años:")
    print(f"  gastronomía {g:.1%}  vs  farmacia {f:.1%}  ->  {veredicto}")
    if not ok:
        log.error(
            "Gastronomía debería morir más rápido que farmacia, y acá da %s. "
            "Revisar la consolidación antes de leer estas curvas como resultado.",
            veredicto.lower(),
        )
    return ok


def ejecutar() -> None:
    h = _historial()
    print(f"\n{'=' * 72}\n  Paso 2 — supervivencia con Kaplan-Meier\n{'=' * 72}")

    p = plazos(h)
    media, desvio = p["media"][0], p["desvio"][0]
    print(f"\nPlazo otorgado por habilitación (n={p['n'][0]:,}):")
    with pl.Config(tbl_hide_dataframe_shape=True, float_precision=2):
        print(p.select("media", "desvio", "p10", "mediana", "p90"))
    if desvio < 0.5:
        print(
            f"\n  El plazo es prácticamente constante ({media:.1f} +/- {desvio:.2f} años).\n"
            "  Confirma que la duración de una habilitación suelta es administrativa:\n"
            "  medir supervivencia exige encadenar las renovaciones."
        )

    spells = consolidar(h)
    renovados = spells.filter(pl.col("habilitaciones") > 1).height
    print(
        f"\n{len(h):,} habilitaciones -> {len(spells):,} períodos de actividad "
        f"({renovados:,} con al menos una renovación)."
    )

    d = duraciones(spells)
    print(
        f"{len(d):,} spells con duración válida | "
        f"{d['evento'].sum():,} cierres, {(1 - d['evento'].mean()):.1%} censurados a derecha"
    )

    for por, km in (("nivel1", kaplan_meier(d, "nivel1")), ("nivel2", kaplan_meier(d, "nivel2"))):
        print(f"\n{'-' * 72}\nSupervivencia por {por}\n{'-' * 72}")
        with pl.Config(tbl_rows=100, fmt_str_lengths=24, tbl_hide_dataframe_shape=True):
            print(km)
        _alertar_si_degenerado(km, por)
        km.write_csv(config.RAIZ / f"supervivencia_{por}.csv")

    chequeo_gastronomia_vs_farmacia(kaplan_meier(d, "nivel1"), kaplan_meier(d, "nivel2"))
    print(f"\nEscrito supervivencia_nivel1.csv y supervivencia_nivel2.csv en {config.RAIZ}")
