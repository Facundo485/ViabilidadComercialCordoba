"""Serie anual de superficie construida, desde Sentinel-2.

Es el intento de contestar "¿qué zonas van a mejorar?", después de que fallaran
las tres hipótesis que se podían probar con los datos propios (momentum,
features de nivel, y desbalance oferta-demanda).

**Por qué el satélite y no otra cosa.** Todo registro administrativo se va
llenando: las habilitaciones arrancan en 2014, OSM crece porque hay más
mapeadores. Eso produce una "ventana de observación" que se confunde con
crecimiento real, y ya arruinó tres análisis en este proyecto. Un satélite, en
cambio, **observa cada píxel en cada pasada**: la imagen de 2016 está tan
completa como la de 2025. Por eso acá sí hay transiciones limpias — diez, contra
las una o dos que deja el registro de habilitaciones.

**La hipótesis, que esta vez tiene un mecanismo físico detrás.** La construcción
residencial precede a la demanda comercial: una torre nueva mete cientos de
vecinos antes de que abra el primer local. No es una regularidad estadística que
uno espera que se repita, es una secuencia con un retardo de dos a cuatro años.

**Decisiones que hacen que la serie sea comparable año a año.**

- **Siempre el mismo verano.** Comparar una imagen de marzo con una de septiembre
  mide el ciclo de la vegetación, no la ciudad. Se toma la ventana diciembre a
  febrero todos los años.
- **Mediana de varias escenas** en vez de la mejor sola: aunque el catálogo
  reporte 0% de nubes, quedan neblinas y sombras que una mediana de tres saca.
- **Lectura decimada a ~80 m.** Las zonas de análisis son de 800 m, así que
  leer a 10 m sería 64 veces más caro para el mismo resultado.
- **NDBI y NDVI, los dos.** El NDBI sube tanto con lo construido como con el
  suelo desnudo; restarle el NDVI separa "se construyó" de "se peló el terreno",
  que en el borde de la ciudad es una confusión muy fácil de cometer.

Los COG están en AWS Open Data y se leen por ventana, así que no se descarga
ninguna escena entera y no hace falta cuenta en ningún lado.
"""

from __future__ import annotations

import logging
from itertools import pairwise

import numpy as np
import polars as pl
import requests

from . import config, zonas

log = logging.getLogger(__name__)

STAC = "https://earth-search.aws.element84.com/v1/search"
COLECCION = "sentinel-2-l2a"
CABECERAS = {"User-Agent": "viabilidad-cordoba/0.1 (pipeline de investigacion urbana)"}

# Un solo tile MGRS cubre la ciudad entera; mezclar tiles metería diferencias de
# fecha y de ángulo solar adentro de la misma imagen.
TILE = "MGRS-20JLL"

# Ventana de verano. El hemisferio sur tiene el cielo más limpio y la vegetación
# en su punto, y lo que importa es que sea **la misma** todos los años.
# Enero-febrero y no diciembre-febrero: en un clima de lluvias estivales,
# diciembre y febrero son dos estados de vegetación distintos, y elegir por
# nubes hacía que un año cayera todo en diciembre y el siguiente todo en
# febrero. Eso metía el ciclo de la vegetación adentro de la serie.
MES_DESDE, MES_HASTA = "01-01", "02-28"
NUBES_MAX = 10
ESCENAS_POR_ANIO = 3

DECIMACION = 8  # 10 m -> 80 m
PRIMER_ANIO = 2016  # antes no hay L2A consistente para esta zona

ARCHIVO = "satelital_zonas.parquet"


def _buscar(anio: int) -> list[dict]:
    """Escenas del verano que arranca en `anio`, de menos a más nubes."""
    r = requests.post(
        STAC,
        json={
            "collections": [COLECCION],
            "bbox": [
                config.BBOX_CORDOBA["lon_min"],
                config.BBOX_CORDOBA["lat_min"],
                config.BBOX_CORDOBA["lon_max"],
                config.BBOX_CORDOBA["lat_max"],
            ],
            # El verano se etiqueta con el año en que arranca, pero la ventana
            # cae toda en el año calendario siguiente.
            "datetime": f"{anio + 1}-{MES_DESDE}T00:00:00Z/{anio + 1}-{MES_HASTA}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": NUBES_MAX}},
            "limit": 50,
        },
        headers=CABECERAS,
        timeout=180,
    )
    r.raise_for_status()
    escenas = [f for f in r.json().get("features", []) if f["properties"]["grid:code"] == TILE]
    return sorted(escenas, key=lambda f: f["properties"]["eo:cloud_cover"])[:ESCENAS_POR_ANIO]


# A partir del baseline 04.00, ESA le suma 1000 a todas las bandas. Element84
# normalmente lo revierte al generar el COG y lo informa en el STAC; cuando no
# lo hizo hay que restarlo a mano. No es cosmético: NDBI y NDVI son cocientes,
# así que un offset constante no se cancela, desplaza el índice. Sin esto, el
# verano 2021-22 daba un NIR medio de 4306 contra ~2900 de todos los demás años.
OFFSET_BASELINE_04 = 1000.0


def _correccion(escena: dict) -> float:
    ya_aplicado = escena["properties"].get("earthsearch:boa_offset_applied", True)
    baseline = escena["properties"].get("s2:processing_baseline", "00.00")
    if not ya_aplicado and baseline >= "04.00":
        return OFFSET_BASELINE_04
    return 0.0


def _leer(href: str) -> tuple[np.ndarray, object, object]:
    """Lee la ventana de Córdoba, decimada. Devuelve la banda y su georreferencia."""
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    b = config.BBOX_CORDOBA
    with rasterio.open(href) as src:
        limites = transform_bounds(
            "EPSG:4326", src.crs, b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"]
        )
        v = from_bounds(*limites, transform=src.transform)
        alto, ancho = int(v.height) // DECIMACION, int(v.width) // DECIMACION
        banda = src.read(1, window=v, out_shape=(alto, ancho)).astype("float32")
        # `window_transform` describe la ventana a resolución nativa. Leída
        # decimada, el array tiene menos píxeles y cada uno cubre más terreno,
        # así que hay que escalar el transform o las coordenadas quedan mal por
        # un factor de DECIMACION — y el ráster entero mapea a una esquina.
        from rasterio.transform import Affine

        transformacion = src.window_transform(v) * Affine.scale(v.width / ancho, v.height / alto)
        return banda, transformacion, src.crs


def indices_del_anio(anio: int) -> tuple[np.ndarray, np.ndarray, object, object] | None:
    """NDBI y NDVI medianos del verano, más la georreferencia de la grilla."""
    escenas = _buscar(anio)
    if not escenas:
        log.warning("Sin escenas limpias para el verano %s-%s.", anio, anio + 1)
        return None

    ndbis, ndvis, geo = [], [], None
    forma_comun: tuple[int, int] | None = None
    for escena in escenas:
        correccion = _correccion(escena)
        nir, transformacion, crs = _leer(escena["assets"]["nir"]["href"])
        swir, _, _ = _leer(escena["assets"]["swir16"]["href"])
        rojo, _, _ = _leer(escena["assets"]["red"]["href"])
        if correccion:
            log.info("    corrigiendo offset del baseline 04.00 (-%.0f)", correccion)
            nir, swir, rojo = (np.where(b > 0, b - correccion, np.nan) for b in (nir, swir, rojo))
        # El SWIR viene a 20 m nativos, así que decimado queda a la mitad. Se lo
        # duplica y después se recortan las tres bandas a la forma común: el
        # redondeo de la ventana puede dejar un píxel de diferencia, y recortar
        # con un slice no alcanza porque no puede agrandar el array más chico.
        if swir.shape != nir.shape:
            swir = np.kron(swir, np.ones((2, 2), dtype="float32"))
        alto = min(nir.shape[0], swir.shape[0], rojo.shape[0])
        ancho = min(nir.shape[1], swir.shape[1], rojo.shape[1])
        nir, swir, rojo = nir[:alto, :ancho], swir[:alto, :ancho], rojo[:alto, :ancho]

        with np.errstate(divide="ignore", invalid="ignore"):
            ndbis.append(np.where(swir + nir > 0, (swir - nir) / (swir + nir), np.nan))
            ndvis.append(np.where(nir + rojo > 0, (nir - rojo) / (nir + rojo), np.nan))
        # Entre escenas del mismo verano también puede haber un píxel de
        # diferencia; se fija la forma de la primera y se recortan las demás.
        if forma_comun is None:
            forma_comun = (alto, ancho)
        else:
            forma_comun = (min(forma_comun[0], alto), min(forma_comun[1], ancho))
        geo = (transformacion, crs)
        log.info(
            "  %s-%s: %s (%.1f%% nubes)",
            anio,
            anio + 1,
            escena["id"],
            escena["properties"]["eo:cloud_cover"],
        )

    f0, f1 = forma_comun
    return (
        np.nanmedian(np.stack([a[:f0, :f1] for a in ndbis]), axis=0),
        np.nanmedian(np.stack([a[:f0, :f1] for a in ndvis]), axis=0),
        *geo,
    )


def _zonas_de_pixeles(forma: tuple[int, int], transformacion, crs) -> np.ndarray:
    """A qué zona de la grilla cae cada píxel."""
    from rasterio.transform import xy
    from rasterio.warp import transform as reproyectar

    filas, columnas = np.mgrid[0 : forma[0], 0 : forma[1]]
    x, y = xy(transformacion, filas.ravel(), columnas.ravel())
    lon, lat = reproyectar(crs, "EPSG:4326", list(x), list(y))
    lon, lat = np.asarray(lon), np.asarray(lat)

    gx = np.floor(
        (lon - zonas.ORIGEN_LON) * zonas.METROS_POR_GRADO_LON / zonas.LADO_CELDA_M
    ).astype(np.int64)
    gy = np.floor(
        (lat - zonas.ORIGEN_LAT) * zonas.METROS_POR_GRADO_LAT / zonas.LADO_CELDA_M
    ).astype(np.int64)
    return (gx * 10_000 + gy).reshape(forma)


def panel(desde: int = PRIMER_ANIO, hasta: int | None = None) -> pl.DataFrame:
    """NDBI y NDVI medios por zona y año."""
    hasta = hasta if hasta is not None else 2025
    filas = []
    for anio in range(desde, hasta + 1):
        resultado = indices_del_anio(anio)
        if resultado is None:
            continue
        ndbi, ndvi, transformacion, crs = resultado
        zona = _zonas_de_pixeles(ndbi.shape, transformacion, crs)
        filas.append(
            pl.DataFrame(
                {
                    "zona": zona.ravel(),
                    "ndbi": ndbi.ravel(),
                    "ndvi": ndvi.ravel(),
                }
            )
            .drop_nulls()
            .filter(pl.col("ndbi").is_not_nan() & pl.col("ndvi").is_not_nan())
            .group_by("zona")
            .agg(
                pl.col("ndbi").mean(),
                pl.col("ndvi").mean(),
                pl.len().alias("pixeles"),
            )
            .with_columns(pl.lit(anio).alias("anio"))
        )
    if not filas:
        raise ValueError("Ningún año devolvió escenas utilizables.")
    return pl.concat(filas).with_columns(
        # Construido menos vegetación: separa "se construyó" de "se peló el
        # terreno", que en el borde de la ciudad dan los dos NDBI alto.
        (pl.col("ndbi") - pl.col("ndvi")).alias("construido")
    )


def relativo(p: pl.DataFrame) -> pl.DataFrame:
    """Índice de cada zona relativo a la ciudad de ese verano.

    El nivel de toda la ciudad se mueve con la lluvia: un verano húmedo da más
    vegetación y baja el índice en todos lados a la vez. Medido en crudo, el
    promedio de ciudad oscilaba entre -0,87 y -0,23 de un año a otro, que es
    muchísimo más que cualquier construcción real. Restarle la media del año
    saca ese factor común y deja la señal espacial.
    """
    return p.with_columns(
        (pl.col("construido") - pl.col("construido").mean().over("anio")).alias("construido_rel")
    )


def estabilidad(p: pl.DataFrame) -> pl.DataFrame:
    """Correlación del índice entre veranos consecutivos. Es el chequeo sanitario.

    Una zona construida sigue construida: los edificios no desaparecen. Si la
    correlación entre años consecutivos no es alta, lo que se está midiendo es
    ruido y no la ciudad. Sirvió para encontrar dos errores que daban
    correlaciones negativas —el offset del baseline 04.00 sin corregir y una
    ventana estacional demasiado ancha— y sin este chequeo los dos habrían
    pasado por resultado.
    """
    w = relativo(p).pivot("anio", index="zona", values="construido_rel").drop_nulls()
    anios = sorted(int(c) for c in w.columns if c != "zona")
    filas = [
        {
            "desde": a,
            "hasta": b,
            "corr": float(np.corrcoef(w[str(a)].to_numpy(), w[str(b)].to_numpy())[0, 1]),
        }
        for a, b in pairwise(anios)
    ]
    filas.append(
        {
            "desde": anios[0],
            "hasta": anios[-1],
            "corr": float(
                np.corrcoef(w[str(anios[0])].to_numpy(), w[str(anios[-1])].to_numpy())[0, 1]
            ),
        }
    )
    return pl.DataFrame(filas)


def ejecutar() -> pl.DataFrame:
    log.info("Componiendo veranos de Sentinel-2 (una pasada por año)...")
    p = panel()

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_PROCESADO / ARCHIVO
    p.write_parquet(salida)

    print(f"\n{'=' * 72}\n  Superficie construida por zona, desde Sentinel-2\n{'=' * 72}")
    print(f"\n{p['zona'].n_unique():,} zonas x {p['anio'].n_unique()} veranos\n")
    with pl.Config(tbl_rows=15, tbl_hide_dataframe_shape=True, float_precision=4):
        print(
            p.group_by("anio")
            .agg(
                pl.len().alias("zonas"),
                pl.col("construido").mean().alias("construido_medio"),
            )
            .sort("anio")
        )
    est = estabilidad(p)
    print("\n¿Es estable el índice? Una zona construida sigue construida:")
    with pl.Config(tbl_rows=15, tbl_hide_dataframe_shape=True, float_precision=3):
        print(est)
    consecutivas = est.head(len(est) - 1)["corr"]
    if consecutivas.min() < 0.3:
        log.error(
            "Hay veranos consecutivos con correlación %.2f. Los edificios no "
            "desaparecen: eso es un problema de medición, no de la ciudad. "
            "Revisá el offset del baseline y la ventana estacional.",
            consecutivas.min(),
        )

    print(f"\nEscrito en {salida}")
    return p
