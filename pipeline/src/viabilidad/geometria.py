"""Polígonos de manzana, simplificados, para dibujar el mapa.

El pipeline nunca necesitó geometría: la manzana sale embebida en el
`nro_catastral` y todo el análisis se hizo con centroides. Pero un score que
nadie puede mirar en un mapa es un número que nadie audita, así que para el
producto hacen falta los polígonos.

`Catastro/Catastro_capas_v2/FeatureServer/7` los publica, y su campo
`nomenclatura` ("15-06-007") es exactamente el id de manzana que usa el
pipeline, así que el join es directo y no hace falta ningún cruce espacial.

**La simplificación no es opcional.** Sin simplificar son 36,5 vértices por
manzana y 7.533 manzanas no las dibuja ningún navegador con fluidez. Se pide
simplificado del lado del servidor con `maxAllowableOffset`, que baja a ~7
vértices sin que se note: una manzana es casi un rectángulo.
"""

from __future__ import annotations

import json
import logging

import polars as pl
import requests

from . import config

log = logging.getLogger(__name__)

BASE = (
    "https://gis.cordoba.gob.ar/server/rest/services"
    "/Catastro/Catastro_capas_v2/FeatureServer/7/query"
)

# ~3 metros en grados. Una manzana es casi un rectángulo, así que a esta
# tolerancia el dibujo es indistinguible y el peso baja cinco veces.
TOLERANCIA_GRADOS = 0.00003
PAGINA = 2_000
DECIMALES = 5  # ~1 m; más decimales solo engordan el archivo

ARCHIVO = "manzanas_geo.json"


def descargar() -> dict[str, list]:
    """`{manzana: [[lon, lat], ...]}` con el anillo exterior de cada polígono."""
    poligonos: dict[str, list] = {}
    offset = 0
    while True:
        r = requests.get(
            BASE,
            params={
                "where": "1=1",
                "outFields": "nomenclatura",
                "returnGeometry": "true",
                "outSR": "4326",
                "maxAllowableOffset": str(TOLERANCIA_GRADOS),
                "orderByFields": "objectid ASC",
                "resultOffset": offset,
                "resultRecordCount": PAGINA,
                "f": "json",
            },
            timeout=180,
        )
        r.raise_for_status()
        datos = r.json()
        if "error" in datos:
            raise RuntimeError(f"El GIS respondió error: {datos['error']}")

        rasgos = datos.get("features", [])
        if not rasgos:
            break
        for f in rasgos:
            nombre = (f["attributes"].get("nomenclatura") or "").strip()
            anillos = f.get("geometry", {}).get("rings") or []
            if not nombre or not anillos:
                continue
            # Solo el anillo exterior: los huecos no cambian nada a esta escala
            # y duplicarían el peso.
            poligonos[nombre] = [
                [round(x, DECIMALES), round(y, DECIMALES)] for x, y in max(anillos, key=len)
            ]

        log.info("  %s manzanas", f"{len(poligonos):,}")
        if not datos.get("exceededTransferLimit"):
            break
        offset += len(rasgos)

    if not poligonos:
        raise ValueError("No se descargó ninguna manzana con geometría.")
    return poligonos


def ejecutar() -> dict[str, list]:
    log.info("Descargando polígonos de manzana...")
    poligonos = descargar()

    config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_PROCESADO / ARCHIVO
    salida.write_text(json.dumps(poligonos, separators=(",", ":")))

    vertices = sum(len(v) for v in poligonos.values())
    print(f"\n{'=' * 72}\n  Geometría de manzanas\n{'=' * 72}")
    print(
        f"\n{len(poligonos):,} manzanas | {vertices:,} vértices "
        f"({vertices / len(poligonos):.1f} por manzana)"
    )
    print(f"{salida.stat().st_size / 1e6:.1f} MB en {salida}")

    con_datos = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")["manzana"]
    hay = sum(1 for m in con_datos if m in poligonos)
    print(f"\nManzanas del pipeline con polígono: {hay:,} de {len(con_datos):,}")
    return poligonos
