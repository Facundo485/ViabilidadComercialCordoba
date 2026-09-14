"""Arma los datos que consume el mapa: geometría + score, en un solo archivo.

El mapa es el punto donde el proyecto deja de ser una tabla y pasa a ser algo
que alguien puede mirar y auditar. Por eso el criterio acá es que **todo lo que
el mapa muestra tenga respaldo en el pipeline**: el score sale de `score.py`, la
geometría de `geometria.py`, y la base de comparación del mismo entrenamiento.

Sale un `.js` y no un `.json` a propósito: la página se publica como artifact y
ahí `fetch` a archivos sueltos puede estar bloqueado, mientras que un `<script>`
del mismo origen carga siempre. El archivo define `window.DATOS`.

El peso importa: son 7.500 polígonos. Las coordenadas van a 5 decimales (~1 m) y
los scores como enteros de 0 a 1000, que es más precisión de la que el modelo
tiene para dar.
"""

from __future__ import annotations

import json
import logging

import polars as pl

from . import config, geometria, score

log = logging.getLogger(__name__)

ARCHIVO = "datos.js"


def construir() -> dict:
    geo = json.loads((config.DIR_PROCESADO / geometria.ARCHIVO).read_text())
    s = pl.read_parquet(config.DIR_PROCESADO / score.ARCHIVO)
    manzanas = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")

    rubros = sorted(s["rubro"].unique().to_list())
    ancho = s.pivot("rubro", index="manzana", values="score")
    ancho = ancho.join(manzanas.select("manzana", "barrio", "hab_total"), on="manzana", how="left")

    # Se dibujan **todas** las manzanas de la ciudad, no solo las que tienen
    # score. Son 19.600 contra 6.892: si se muestran nada más las que tienen
    # historia comercial, Córdoba parece un archipiélago y los huecos se leen
    # como error del mapa. Y la ausencia también informa — una manzana sin
    # ninguna habilitación en doce años está diciendo algo.
    con_score = {f["manzana"]: f for f in ancho.iter_rows(named=True)}
    rasgos = []
    for manzana, anillo in geo.items():
        if not anillo or len(anillo) < 4:
            continue
        propiedades = {"m": manzana}
        fila = con_score.get(manzana)
        if fila is not None:
            propiedades["b"] = fila["barrio"]
            propiedades["n"] = int(fila["hab_total"] or 0)
            # Los scores van como array indexado por rubro, no como claves con
            # nombre: repetir "bar_restaurante" 6.892 veces pesaba un megabyte
            # entero. Y como enteros por mil, que es más precisión de la que el
            # modelo tiene para dar.
            propiedades["s"] = [round((fila[r] or 0) * 1000) for r in rubros]
        rasgos.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [anillo]},
                "properties": propiedades,
            }
        )

    if not rasgos:
        raise ValueError("Ninguna manzana quedó con geometría y score a la vez.")

    return {
        "rubros": rubros,
        "manzanas": {"type": "FeatureCollection", "features": rasgos},
    }


def ejecutar() -> dict:
    datos = construir()
    salida = config.DIR_PROCESADO / ARCHIVO
    salida.write_text("window.DATOS=" + json.dumps(datos, separators=(",", ":")) + ";")

    print(f"\n{'=' * 72}\n  Datos del mapa\n{'=' * 72}")
    con = sum(1 for f in datos["manzanas"]["features"] if "s" in f["properties"])
    print(
        f"\n{len(datos['manzanas']['features']):,} manzanas dibujadas | "
        f"{con:,} con score | {len(datos['rubros'])} rubros"
    )
    print(f"{salida.stat().st_size / 1e6:.2f} MB en {salida}")
    return datos
