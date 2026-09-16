"""Descarga las capas del GIS y las deja limpias en parquet."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

import polars as pl

from . import arcgis, config, mapeo

log = logging.getLogger(__name__)

# Fechas que ArcGIS devuelve como epoch en milisegundos.
FECHAS_HISTORIAL = ["fechahabaprobada", "fechavencimientohab"]


def _a_fecha(df: pl.DataFrame, columnas: list[str]) -> pl.DataFrame:
    presentes = [c for c in columnas if c in df.columns]
    return df.with_columns(pl.from_epoch(pl.col(c), time_unit="ms").alias(c) for c in presentes)


def descargar_parcelas() -> pl.DataFrame:
    """Capa 0: un punto por parcela con los conteos de habilitaciones."""
    log.info("Descargando parcelas (capa %s)...", config.CAPA_PARCELAS)
    filas = list(
        arcgis.paginar(
            config.GIS_BASE,
            config.CAPA_PARCELAS,
            con_geometria=True,
            page_size=config.PAGE_SIZE,
        )
    )
    df = pl.DataFrame(filas)
    antes = len(df)

    bb = config.BBOX_CORDOBA
    df = df.filter(
        pl.col("lon").is_between(bb["lon_min"], bb["lon_max"])
        & pl.col("lat").is_between(bb["lat_min"], bb["lat_max"])
    )
    if descartadas := antes - len(df):
        log.warning("Descartadas %s parcelas con coordenadas fuera de Córdoba", descartadas)

    # La manzana está embebida en el nro_catastral: "01-01-001-007" -> "01-01-001".
    return df.with_columns(
        pl.col("nro_catastral").str.slice(0, config.LARGO_ID_MANZANA).alias("manzana")
    )


def seudonimo(cuit: str | None) -> str | None:
    """Hash estable del CUIT, para encadenar renovaciones sin guardar el número.

    Estable entre corridas (misma sal, mismo hash) y suficiente para agrupar:
    lo único que se le pide al identificador de titular es que dos trámites de
    la misma persona caigan juntos. Ver la nota de `config.sal_cuit()` sobre por
    qué esto es seudonimización y no anonimización.
    """
    if cuit is None or not str(cuit).strip():
        return None
    return hashlib.blake2b(
        str(cuit).strip().encode(),
        key=config.sal_cuit().encode(),
        digest_size=config.LARGO_HASH_CUIT,
    ).hexdigest()


def descargar_tramites() -> pl.DataFrame:
    """Capa 0 de la vista: una fila por trámite, con el titular poblado.

    Es la capa que destraba el Paso 2. El histórico trae `cuitempresa` nula en
    el 100% de las filas, así que sin esto no hay forma de saber si una
    habilitación nueva es un comercio nuevo o la renovación del de al lado.

    El CUIT nunca llega al parquet: sale de acá ya hasheado como `titular`, y
    `razonsocial` ni se pide.
    """
    log.info("Descargando trámites (vista, capa %s)...", config.CAPA_TRAMITES)
    filas = list(
        arcgis.paginar(
            config.GIS_BASE_VISTA,
            config.CAPA_TRAMITES,
            con_geometria=True,
            page_size=config.PAGE_SIZE,
        )
    )
    # infer_schema_length=None: `numero` mezcla enteros con textos tipo "3660/70".
    df = pl.DataFrame(filas, infer_schema_length=None)

    if faltan := [c for c in ("id", "cuitempresa") if c not in df.columns]:
        raise ValueError(f"La vista de trámites no trae {faltan}; sin eso no hay titular.")

    df = df.select([c for c in config.CAMPOS_TRAMITE if c in df.columns]).rename(
        {"id": "id_tramite", "nrocatastral": "nro_catastral"}
    )
    df = df.with_columns(
        pl.col("cuitempresa")
        .cast(pl.Utf8)
        .map_elements(seudonimo, return_dtype=pl.Utf8)
        .alias("titular")
    ).drop("cuitempresa")

    _verificar_titulares(df)
    return df


def _verificar_titulares(df: pl.DataFrame) -> None:
    """Corta si la vista trae el titular tan vacío como el histórico.

    Es el modo de falla que ya se dio dos veces con esta fuente (`vigente` y
    `cuitempresa`): el schema declara la columna y nadie la popula. Detectarlo
    acá evita que `supervivencia` devuelva curvas planas sin que nada falle.
    """
    nulos = df["titular"].null_count()
    if nulos == len(df):
        raise ValueError(
            "La vista devolvió el titular vacío en todas las filas. Es el mismo "
            "problema que tiene `cuitempresa` en el histórico: sin titular no se "
            "pueden encadenar renovaciones. Revisá la capa antes de seguir."
        )
    if nulos:
        log.warning("%s trámites sin titular: cada uno queda como su propio período.", f"{nulos:,}")
    log.info(
        "Trámites: %s, %s titulares distintos", f"{len(df):,}", f"{df['titular'].n_unique():,}"
    )


def descargar_historial(tramites: pl.DataFrame | None = None) -> pl.DataFrame:
    """Tabla 1: un registro por trámite y rubro, con fechas y titular.

    Ojo con el conteo: las filas no son habilitaciones. Un mismo trámite habilita
    varios rubros a la vez (media 2,03, máximo 73) y aparece una vez por cada
    uno, así que contar filas infla todo al doble. La unidad es `id_tramite`.
    """
    log.info("Descargando historial (tabla %s)...", config.TABLA_HISTORIAL)
    filas = list(
        arcgis.paginar(
            config.GIS_BASE,
            config.TABLA_HISTORIAL,
            con_geometria=False,
            page_size=config.PAGE_SIZE,
        )
    )
    df = _a_fecha(pl.DataFrame(filas), FECHAS_HISTORIAL)

    df = df.with_columns(
        pl.col("nro_catastral").str.slice(0, config.LARGO_ID_MANZANA).alias("manzana"),
        _vigencia(),
    )
    _verificar_vigencia(df)
    return _con_titular(_con_rubro(df), tramites)


def _con_titular(df: pl.DataFrame, tramites: pl.DataFrame | None) -> pl.DataFrame:
    """Adjunta el titular hasheado uniendo por `id_tramite` contra la vista.

    El histórico es una fila por trámite y rubro; la vista, una por trámite. El
    join es 1:N y no duplica nada.
    """
    if tramites is None:
        tramites = descargar_tramites()

    unido = df.join(tramites.select("id_tramite", "titular"), on="id_tramite", how="left")
    _verificar_cobertura_titular(unido)
    return unido


def _verificar_cobertura_titular(df: pl.DataFrame) -> None:
    """Un join que no matchea casi nada deja el Paso 2 sin clave y hay que verlo."""
    sin_titular = df["titular"].null_count()
    cobertura = 1 - sin_titular / len(df) if len(df) else 0.0
    if cobertura == 0:
        raise ValueError(
            "Ningún registro del histórico matcheó con la vista de trámites. "
            "Revisá que `id_tramite` siga siendo la clave común entre las dos capas."
        )
    if cobertura < 0.9:
        log.warning(
            "Solo el %.1f%% del histórico quedó con titular. Las renovaciones de "
            "lo que falta no se van a poder encadenar.",
            cobertura * 100,
        )
    else:
        log.info("Historial con titular: %.1f%%", cobertura * 100)


def _vigencia() -> pl.Expr:
    """Resuelve `vigente` cayendo a la fecha de vencimiento cuando viene nulo.

    Es la variable objetivo del proyecto, así que no se la puede rellenar con un
    cero: eso convertiría "no sé" en "cerró" y sesgaría todo el modelo hacia
    abajo. Si la tabla no la trae, se deduce de si el permiso todavía no venció.
    """
    derivada = (pl.col("fechavencimientohab") > pl.lit(datetime.now())).cast(pl.Int8)
    return pl.coalesce(pl.col("vigente").cast(pl.Int8), derivada).alias("vigente")


def _verificar_vigencia(df: pl.DataFrame) -> None:
    """Corta si la vigencia quedó degenerada: sin ella no hay nada que modelar."""
    validas = df["vigente"].drop_nulls()
    if validas.is_empty() or validas.sum() == 0:
        raise ValueError(
            "Ninguna habilitación quedó como vigente. Sin esta columna no hay "
            "variable objetivo. Revisá `vigente` y `fechavencimientohab` en el "
            "parquet crudo antes de seguir."
        )
    if nulos := df["vigente"].null_count():
        log.warning(
            "%s habilitaciones sin vigencia ni fecha de vencimiento: se excluyen.",
            f"{nulos:,}",
        )
    log.info("Vigentes en el historial: %.1f%%", validas.mean() * 100)


def _con_rubro(df: pl.DataFrame) -> pl.DataFrame:
    """Adjunta nivel1/nivel2 uniendo contra referencia/mapeo_rubros.csv.

    La fuente de verdad es el CSV, no las reglas de rubros.py: corregir una
    clasificación es editar una fila, y el diff muestra qué cambió. Regenerarlo
    desde las reglas es `python -m viabilidad mapeo`.
    """
    ruta = config.DIR_REFERENCIA / mapeo.ARCHIVO
    if not ruta.exists():
        raise FileNotFoundError(f"Falta {ruta}. Corré `python -m viabilidad mapeo` para generarlo.")
    # Se une por el nombre normalizado y no por el crudo: el nomenclador tiene
    # entradas que solo difieren en un espacio doble, y un join exacto las perdería.
    tabla = (
        pl.read_csv(ruta)
        .with_columns(mapeo.normalizar().alias("_clave"))
        .select("_clave", "nivel2", "nivel1")
        .unique(subset="_clave", keep="first")
    )

    unido = df.with_columns(mapeo.normalizar().alias("_clave")).join(tabla, on="_clave", how="left")
    if huerfanos := unido.filter(pl.col("nivel2").is_null()).height:
        log.warning(
            "%s habilitaciones con un rubro que no está en el mapeo (quedan en 'otro'). "
            "Regenerá el mapeo si el nomenclador cambió.",
            f"{huerfanos:,}",
        )
    return unido.with_columns(
        pl.col("nivel2").fill_null("otro"), pl.col("nivel1").fill_null("otro")
    ).drop("_clave")


def ejecutar() -> tuple[pl.DataFrame, pl.DataFrame]:
    config.DIR_CRUDO.mkdir(parents=True, exist_ok=True)

    parcelas = descargar_parcelas()
    parcelas.write_parquet(config.DIR_CRUDO / "parcelas.parquet")
    log.info("Parcelas: %s filas", f"{len(parcelas):,}")

    tramites = descargar_tramites()
    tramites.write_parquet(config.DIR_CRUDO / "tramites.parquet")

    historial = descargar_historial(tramites)
    historial.write_parquet(config.DIR_CRUDO / "historial.parquet")
    # Las filas no son habilitaciones: un trámite habilita varios rubros a la vez
    # y aparece una vez por rubro. La unidad de conteo es el trámite.
    log.info(
        "Historial: %s filas (trámite x rubro) sobre %s trámites",
        f"{len(historial):,}",
        f"{historial['id_tramite'].n_unique():,}",
    )

    return parcelas, historial
