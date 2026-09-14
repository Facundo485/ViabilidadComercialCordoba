"""Descarga de OpenStreetMap la estructura urbana: red vial y equipamientos.

Es lo que le falta al modelo. Todas las features que salen de `features.py`
describen el **churn comercial** —cuántos locales hay, de qué rubro, cuántos
cerraron— y eso es justamente lo que cambia de un período a otro. Por eso el
entorno separa lugares dentro de una época y casi no predice hacia adelante.

La red vial y los equipamientos son **estructurales**: una avenida, una escuela
o una terminal siguen ahí cinco años después. Si la capacidad predictiva a
futuro va a mejorar, tiene que venir de acá.

Se consulta Overpass directo en vez de `osmnx` para no arrastrar geopandas
entero: lo único que hace falta son puntos, y los vecinos ya se calculan con un
cKDTree. Cada capa se guarda en `data/crudo/` y no se vuelve a bajar: la
consulta de vías tarda unos cuatro minutos.
"""

from __future__ import annotations

import logging
import time

import polars as pl
import requests

from . import config

log = logging.getLogger(__name__)

# El endpoint principal de Overpass devuelve 504 seguido con consultas de este
# tamaño; el mirror de kumi las aguanta. Se prueban en orden.
ESPEJOS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
# Overpass rechaza con 406 el User-Agent por defecto de `requests`.
CABECERAS = {"User-Agent": "viabilidad-cordoba/0.1 (pipeline de investigacion urbana)"}
TIMEOUT = 420

# Jerarquía vial. Se separa la red principal del resto: estar sobre una avenida
# no es lo mismo que estar en una calle interna, y esa diferencia es la que se
# espera que prediga.
PRINCIPALES = ("primary", "secondary", "trunk")
SECUNDARIAS = ("tertiary", "residential", "unclassified", "living_street")

# Equipamientos que generan circulación de gente y no son comercio (el comercio
# ya lo tenemos del GIS, y meterlo de nuevo seria contar dos veces lo mismo).
ANCLAS = {
    "educacion": '["amenity"~"^(school|university|college|kindergarten)$"]',
    "salud": '["amenity"~"^(hospital|clinic|doctors)$"]',
    "transporte": '["highway"="bus_stop"]',
    "publico": '["amenity"~"^(townhall|police|post_office|bank|courthouse)$"]',
}


# La ciudad entera en una sola consulta hace que Overpass devuelva 504 cuando
# está cargado. Partida en tiles, cada pedido es chico y se puede reintentar sin
# perder lo ya bajado.
TILES = 4
REINTENTOS = 3


def _grilla() -> list[str]:
    b = config.BBOX_CORDOBA
    alto = (b["lat_max"] - b["lat_min"]) / TILES
    ancho = (b["lon_max"] - b["lon_min"]) / TILES
    return [
        f"{b['lat_min'] + i * alto},{b['lon_min'] + j * ancho},"
        f"{b['lat_min'] + (i + 1) * alto},{b['lon_min'] + (j + 1) * ancho}"
        for i in range(TILES)
        for j in range(TILES)
    ]


def _pedir(consulta: str) -> list[dict]:
    """Un pedido, probando espejos y reintentando ante saturación."""
    ultimo: Exception | None = None
    for intento in range(REINTENTOS):
        for url in ESPEJOS:
            try:
                r = requests.post(url, data={"data": consulta}, headers=CABECERAS, timeout=TIMEOUT)
                if r.status_code != 200:
                    raise RuntimeError(f"{url.split('/')[2]} respondió {r.status_code}")
                return r.json()["elements"]
            except Exception as exc:
                ultimo = exc
        espera = 10 * (intento + 1)
        log.warning("Overpass saturado (%s). Reintento en %ss.", ultimo, espera)
        time.sleep(espera)
    raise RuntimeError("Ningún espejo de Overpass respondió.") from ultimo


def _consultar(plantilla: str) -> list[dict]:
    """Corre la consulta tile por tile. `plantilla` lleva `{bbox}`."""
    elementos: list[dict] = []
    inicio = time.time()
    for n, bbox in enumerate(_grilla(), 1):
        elementos.extend(_pedir(plantilla.format(bbox=bbox)))
        log.info("  tile %s/%s — %s elementos acumulados", n, TILES * TILES, f"{len(elementos):,}")
    log.info("  total %s elementos en %.0fs", f"{len(elementos):,}", time.time() - inicio)
    return elementos


def _puntos(elementos: list[dict], tipo: str) -> pl.DataFrame:
    """Un punto por elemento. Los `way` traen su centro con `out center`."""
    filas = []
    for e in elementos:
        centro = e.get("center") or e
        if (lon := centro.get("lon")) is None or (lat := centro.get("lat")) is None:
            continue
        filas.append(
            {
                "tipo": tipo,
                "subtipo": e.get("tags", {}).get("highway", tipo),
                "lon": lon,
                "lat": lat,
            }
        )
    return pl.DataFrame(
        filas, schema={"tipo": pl.Utf8, "subtipo": pl.Utf8, "lon": pl.Float64, "lat": pl.Float64}
    )


def descargar_vias() -> pl.DataFrame:
    tipos = "|".join(PRINCIPALES + SECUNDARIAS)
    consulta = f'[out:json][timeout:180];(way["highway"~"^({tipos})$"]({{bbox}}););out center tags;'
    log.info("Descargando red vial de OSM (tarda unos minutos)...")
    return _puntos(_consultar(consulta), "via")


def descargar_anclas() -> pl.DataFrame:
    partes = []
    for nombre, filtro in ANCLAS.items():
        consulta = (
            "[out:json][timeout:180];"
            f"(node{filtro}({{bbox}}); way{filtro}({{bbox}}););"
            "out center tags;"
        )
        log.info("Descargando %s...", nombre)
        partes.append(_puntos(_consultar(consulta), nombre))
    return pl.concat(partes)


def ejecutar(forzar: bool = False) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Descarga y cachea. Sin `forzar`, si el parquet existe no vuelve a bajar."""
    config.DIR_CRUDO.mkdir(parents=True, exist_ok=True)
    salidas = {}
    for nombre, descargar in (("vias", descargar_vias), ("anclas", descargar_anclas)):
        archivo = config.DIR_CRUDO / f"osm_{nombre}.parquet"
        if archivo.exists() and not forzar:
            log.info("%s ya está en disco (%s), no se vuelve a bajar.", nombre, archivo.name)
            salidas[nombre] = pl.read_parquet(archivo)
            continue
        df = descargar()
        df.write_parquet(archivo)
        log.info("%s: %s puntos", nombre, f"{len(df):,}")
        salidas[nombre] = df

    print(f"\n{'=' * 72}\n  Estructura urbana desde OpenStreetMap\n{'=' * 72}")
    with pl.Config(tbl_hide_dataframe_shape=True):
        print(f"\nRed vial: {len(salidas['vias']):,} tramos")
        print(salidas["vias"].group_by("subtipo").len().sort("len", descending=True))
        print(f"\nEquipamientos: {len(salidas['anclas']):,}")
        print(salidas["anclas"].group_by("tipo").len().sort("len", descending=True))
    return salidas["vias"], salidas["anclas"]
