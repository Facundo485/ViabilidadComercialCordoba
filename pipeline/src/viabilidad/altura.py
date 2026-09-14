"""Altura edificada por zona y año, desde Open Buildings Temporal.

Es el segundo intento de medir densificación, después de que el índice de
superficie construida de `satelital.py` fallara por una razón identificada: el
NDBI detecta la conversión de suelo o vegetación a construido —**expansión de
frontera**— y no ve que una torre reemplace una casa. El comercio de Córdoba
crece en zonas ya construidas, así que el indicador medía lo que no era.

La altura sí distingue las dos cosas. Una zona que pasa de casas bajas a torres
no cambia su superficie construida y cambia muchísimo su volumen, y es ese
volumen el que trae vecinos nuevos — que es el mecanismo de la hipótesis: la
construcción residencial precede a la demanda comercial.

    GOOGLE/Research/open-buildings-temporal/v1
    2016-2023, anual, 4 m efectivos
    bandas: building_height, building_presence, building_fractional_count

**Limitaciones que hay que tener presentes:**

- Llega hasta **2023**, así que el par (construcción, comercio posterior) queda
  corto: con horizonte de 3 años, la última ventana usable es 2020 -> 2023 para
  la construcción y 2023 -> 2026 para el comercio.
- Es una **estimación por modelo**, no una medición. La altura sale de inferir
  sobre imágenes, y su error no es independiente del tipo de barrio.
- El acceso es por Earth Engine, con cuenta gratuita de uso **no comercial**.
  Para evaluar factibilidad es uso de investigación; un producto pago necesita
  licencia comercial.

El cómputo se hace del lado del servidor —se pide la media por zona, no los
píxeles— así que no se descarga ningún ráster.
"""

from __future__ import annotations

import logging
import pathlib

import polars as pl

from . import config, zonas

log = logging.getLogger(__name__)

COLECCION = "GOOGLE/Research/open-buildings-temporal/v1"
BANDAS = ("building_height", "building_presence", "building_fractional_count")
PRIMER_ANIO, ULTIMO_ANIO = 2016, 2023
ESCALA_M = 10  # el nativo es 4 m; a 10 m alcanza para zonas de 800 m y es más barato

ARCHIVO = "altura_zonas.parquet"
VARIABLE_PROYECTO = "EARTHENGINE_PROJECT"
VARIABLE_CLAVE = "EARTHENGINE_KEY"


def _proyecto() -> str:
    """El proyecto de Cloud contra el que se factura la cuota de Earth Engine."""
    import os

    if proyecto := os.environ.get(VARIABLE_PROYECTO):
        return proyecto
    archivo = config.RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            if linea.startswith(f"{VARIABLE_PROYECTO}=") and (
                valor := linea.split("=", 1)[1].strip()
            ):
                return valor
    raise RuntimeError(
        f"Falta {VARIABLE_PROYECTO}. Es el id del proyecto de Google Cloud que\n"
        f"registraste en Earth Engine. Ponelo en {archivo}:\n"
        f"  echo '{VARIABLE_PROYECTO}=tu-proyecto' >> {archivo}"
    )


def _clave_de_servicio() -> str | None:
    """Ruta al JSON de la cuenta de servicio, si está configurada."""
    import os

    if ruta := os.environ.get(VARIABLE_CLAVE):
        return ruta
    archivo = config.RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            if linea.startswith(f"{VARIABLE_CLAVE}=") and (valor := linea.split("=", 1)[1].strip()):
                return valor
    return None


def iniciar() -> None:
    """Inicia Earth Engine, por cuenta de servicio si está configurada.

    La cuenta de servicio no es una comodidad sino la única vía cuando la cuenta
    de Google pertenece a una organización que bloquea el acceso de aplicaciones
    de terceros —el flujo de `earthengine authenticate` devuelve "esta
    aplicación está bloqueada" y no hay forma de destrabarlo desde el cliente—.
    Además no depende de una sesión de navegador, que para un pipeline es lo que
    corresponde.
    """
    import json

    import ee

    proyecto = _proyecto()
    if ruta := _clave_de_servicio():
        archivo = pathlib.Path(ruta).expanduser()
        if not archivo.exists():
            raise RuntimeError(f"{VARIABLE_CLAVE} apunta a {archivo}, que no existe.")
        correo = json.loads(archivo.read_text())["client_email"]
        credenciales = ee.ServiceAccountCredentials(correo, str(archivo))
        ee.Initialize(credenciales, project=proyecto)
        log.info("Earth Engine iniciado como %s", correo)
        return

    try:
        ee.Initialize(project=proyecto)
    except Exception as exc:
        raise RuntimeError(
            "No se pudo iniciar Earth Engine.\n\n"
            "Si `earthengine authenticate` devuelve 'esta aplicación está "
            "bloqueada', tu cuenta está en una organización que bloquea apps de "
            "terceros. En ese caso usá una cuenta de servicio: creala en la "
            "consola, bajá la clave JSON y agregá a pipeline/.env\n"
            f"  {VARIABLE_CLAVE}=/ruta/a/la/clave.json\n\n"
            f"Detalle: {exc}"
        ) from exc


def _grilla_ee():
    """La misma grilla de `zonas.py`, como FeatureCollection de Earth Engine.

    Se reconstruye acá en vez de subir un shapefile para que no haya dos
    definiciones de zona que puedan separarse con el tiempo.
    """
    import ee

    b = config.BBOX_CORDOBA
    paso_lon = zonas.LADO_CELDA_M / zonas.METROS_POR_GRADO_LON
    paso_lat = zonas.LADO_CELDA_M / zonas.METROS_POR_GRADO_LAT

    celdas = []
    gx = 0
    lon = zonas.ORIGEN_LON
    while lon < b["lon_max"]:
        gy = 0
        lat = zonas.ORIGEN_LAT
        while lat < b["lat_max"]:
            if lon >= b["lon_min"] and lat >= b["lat_min"]:
                celdas.append(
                    ee.Feature(
                        ee.Geometry.Rectangle([lon, lat, lon + paso_lon, lat + paso_lat]),
                        {"zona": gx * 10_000 + gy},
                    )
                )
            gy += 1
            lat += paso_lat
        gx += 1
        lon += paso_lon
    return ee.FeatureCollection(celdas)


def _del_anio(anio: int, grilla):
    """Media de cada banda por zona, calculada del lado del servidor."""
    import ee

    imagen = (
        ee.ImageCollection(COLECCION)
        .filterDate(f"{anio}-01-01", f"{anio + 1}-01-01")
        .select(list(BANDAS))
        .mosaic()
    )
    reducido = imagen.reduceRegions(collection=grilla, reducer=ee.Reducer.mean(), scale=ESCALA_M)
    return reducido.map(lambda f: f.set("anio", anio))


def panel(desde: int = PRIMER_ANIO, hasta: int = ULTIMO_ANIO) -> pl.DataFrame:
    """Altura, presencia y densidad de edificios por zona y año."""
    iniciar()
    grilla = _grilla_ee()

    filas = []
    for anio in range(desde, hasta + 1):
        log.info("  pidiendo %s...", anio)
        datos = _del_anio(anio, grilla).getInfo()
        for f in datos["features"]:
            p = f["properties"]
            if p.get("building_height") is None:
                continue
            filas.append(
                {
                    "zona": int(p["zona"]),
                    "anio": anio,
                    "altura": float(p["building_height"]),
                    "presencia": float(p.get("building_presence") or 0.0),
                    "densidad_edificios": float(p.get("building_fractional_count") or 0.0),
                }
            )
        log.info("    %s zonas acumuladas", f"{len(filas):,}")

    if not filas:
        raise ValueError(
            "Earth Engine no devolvió ninguna zona con altura. Revisá que el "
            "proyecto esté registrado y que la colección cubra Córdoba."
        )
    return pl.DataFrame(filas)


def _stock_comercial(anios: tuple[int, ...]) -> pl.DataFrame:
    """Participación de cada zona en el comercio activo de la ciudad, por año."""
    from . import supervivencia

    d = supervivencia.duraciones(supervivencia.consolidar(supervivencia._historial()))
    tramites = pl.read_parquet(config.DIR_CRUDO / "tramites.parquet").select(
        "id_tramite", "lon", "lat"
    )
    d = (
        d.join(tramites, left_on="ultimo_tramite", right_on="id_tramite", how="left")
        .drop_nulls(["lon", "lat"])
        .with_columns(
            pl.col("inicio").dt.year().alias("alta"),
            pl.col("fin_cobertura").dt.year().alias("baja"),
            ((pl.col("lon") - zonas.ORIGEN_LON) * zonas.METROS_POR_GRADO_LON / zonas.LADO_CELDA_M)
            .floor()
            .cast(pl.Int64)
            .alias("gx"),
            ((pl.col("lat") - zonas.ORIGEN_LAT) * zonas.METROS_POR_GRADO_LAT / zonas.LADO_CELDA_M)
            .floor()
            .cast(pl.Int64)
            .alias("gy"),
        )
        .with_columns((pl.col("gx") * 10_000 + pl.col("gy")).alias("zona"))
    )

    tabla = None
    for anio in anios:
        activo = d.filter((pl.col("alta") <= anio) & (pl.col("baja") > anio))
        total = activo.height
        parcial = (
            activo.group_by("zona")
            .len()
            .with_columns((pl.col("len") / total).alias(f"share{anio}"))
            .rename({"len": f"n{anio}"})
        )
        tabla = parcial if tabla is None else tabla.join(parcial, on="zona", how="inner")
    return tabla


def relacion_con_comercio(p: pl.DataFrame) -> dict[str, float]:
    """¿La altura explica el comercio? En nivel sí, en cambio no. Ese es el punto.

    Es el resultado que explica por qué fallaron los seis intentos de predecir
    zonas emergentes, y conviene poder recalcularlo:

    - **Nivel contra nivel**: las zonas con edificios más altos tienen mucho más
      comercio (r ~ 0,66). La forma construida y el comercio están alineados.
    - **Cambio contra cambio**: el crecimiento de altura no anticipa el
      crecimiento comercial (r ~ 0,00 a distintos horizontes y retardos).

    La lectura es que **el comercio de Córdoba ya está en equilibrio con su
    forma construida**. Lo que se mueve de un año a otro es churn alrededor de
    ese equilibrio, y el equilibrio casi no se mueve: la altura media creció
    0,114 m en siete años. La ciudad no se transforma lo bastante rápido, ni la
    ventana es lo bastante larga, como para que haya mucho que predecir.
    """
    alt = p.pivot("anio", index="zona", values="altura").drop_nulls()
    alt = alt.rename({c: f"h{c}" for c in alt.columns if c != "zona"})
    anios = (2019, 2022, 2026)
    j = _stock_comercial(anios).filter(pl.col(f"n{anios[0]}") >= 8).join(alt, on="zona")
    if len(j) < 50:
        raise ValueError(f"Solo {len(j)} zonas con altura y comercio; no alcanza para medir.")

    def corr(x: pl.Expr, y: pl.Expr) -> float:
        return float(j.select(pl.corr(x, y)).item())

    return {
        "zonas": len(j),
        "nivel": corr(pl.col("h2023"), pl.col("share2026").log()),
        "cambio": corr(
            pl.col("h2022") - pl.col("h2019"),
            pl.col("share2026").log() - pl.col("share2022").log(),
        ),
        "crecimiento_medio_m": float(
            (p.filter(pl.col("anio") == 2023)["altura"].mean() or 0)
            - (p.filter(pl.col("anio") == 2016)["altura"].mean() or 0)
        ),
    }


def ejecutar() -> pl.DataFrame:
    log.info("Pidiendo altura edificada a Earth Engine (cómputo del lado del servidor)...")
    p = panel()

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_PROCESADO / ARCHIVO
    p.write_parquet(salida)

    print(f"\n{'=' * 72}\n  Altura edificada por zona\n{'=' * 72}")
    print(f"\n{p['zona'].n_unique():,} zonas x {p['anio'].n_unique()} años\n")
    with pl.Config(tbl_rows=12, tbl_hide_dataframe_shape=True, float_precision=3):
        print(
            p.group_by("anio")
            .agg(
                pl.len().alias("zonas"),
                pl.col("altura").mean().alias("altura_media_m"),
                pl.col("densidad_edificios").mean().alias("edificios_medio"),
            )
            .sort("anio")
        )
    try:
        r = relacion_con_comercio(p)
    except (FileNotFoundError, ValueError) as exc:
        log.warning("No se pudo cruzar con el comercio: %s", exc)
    else:
        print(f"\n¿La altura explica el comercio? (n={r['zonas']} zonas)")
        print(f"  nivel   — altura 2023 vs comercio 2026      r = {r['nivel']:+.3f}")
        print(f"  cambio  — Δaltura 19-22 vs Δcomercio 22-26  r = {r['cambio']:+.3f}")
        print(
            f"\n  La altura media creció {r['crecimiento_medio_m']:+.3f} m en siete años.\n"
            "  Fuerte en nivel y nulo en cambio: el comercio ya está en equilibrio\n"
            "  con la forma construida, y la forma construida casi no se mueve."
        )

    print(f"\nEscrito en {salida}")
    return p
