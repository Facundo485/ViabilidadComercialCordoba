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


# Las coordenadas se guardan como enteros delta, no como texto decimal.
#
# Escritas en claro, "[-64.19142,-31.36512]" son 20 caracteres por vértice, y
# son 130.264 vértices: el archivo daba 5,1 MB y en red celular tardaba casi
# veinte segundos en cargar. Guardadas como diferencias contra el vértice
# anterior, cada una entra en dos o tres dígitos, porque una manzana mide
# decenas de metros.
#
# El cliente las reconstruye al cargar. Es la única complejidad que se le suma a
# la página, y compra que el mapa abra en un teléfono.
ESCALA = 100_000  # 1e-5 grados, ~1 m


def _codificar(anillo: list, origen: tuple[float, float]) -> list[int]:
    """Anillo a enteros: primer vértice absoluto contra el origen, resto deltas."""
    salida: list[int] = []
    px = py = 0
    for lon, lat in anillo:
        x = round((lon - origen[0]) * ESCALA)
        y = round((lat - origen[1]) * ESCALA)
        salida.append(x - px)
        salida.append(y - py)
        px, py = x, y
    return salida


def construir() -> dict:
    geo = json.loads((config.DIR_PROCESADO / geometria.ARCHIVO).read_text())
    s = pl.read_parquet(config.DIR_PROCESADO / score.ARCHIVO)
    manzanas = pl.read_parquet(config.DIR_PROCESADO / "manzanas.parquet")

    rubros = sorted(s["rubro"].unique().to_list())
    ancho = s.pivot("rubro", index="manzana", values="score")
    ancho = ancho.join(manzanas.select("manzana", "barrio", "hab_total"), on="manzana", how="left")

    origen = (config.BBOX_CORDOBA["lon_min"], config.BBOX_CORDOBA["lat_min"])

    # Se emiten **todas** las manzanas de la ciudad, no solo las que tienen
    # score. Son 19.600 contra 6.892: mostrando nada más las que tienen historia
    # comercial, Córdoba parece un archipiélago y los huecos se leen como error
    # del mapa. Y la ausencia también informa — una manzana sin ninguna
    # habilitación en doce años está diciendo algo.
    con_score = {f["manzana"]: f for f in ancho.iter_rows(named=True)}
    filas = []
    for manzana, anillo in geo.items():
        if not anillo or len(anillo) < 4:
            continue
        fila = con_score.get(manzana)
        if fila is None:
            filas.append([manzana, None, 0, None, _codificar(anillo, origen)])
        else:
            filas.append(
                [
                    manzana,
                    fila["barrio"],
                    int(fila["hab_total"] or 0),
                    # Enteros por mil: más precisión de la que el modelo tiene.
                    [round((fila[r] or 0) * 1000) for r in rubros],
                    _codificar(anillo, origen),
                ]
            )

    if not filas:
        raise ValueError("Ninguna manzana quedó con geometría.")
    return {
        "origen": list(origen),
        "escala": ESCALA,
        "rubros": rubros,
        "manzanas": filas,
    }


def ejecutar() -> dict:
    datos = construir()
    salida = config.DIR_PROCESADO / ARCHIVO
    salida.write_text("window.DATOS=" + json.dumps(datos, separators=(",", ":")) + ";")

    print(f"\n{'=' * 72}\n  Datos del mapa\n{'=' * 72}")
    con = sum(1 for f in datos["manzanas"] if f[3] is not None)
    print(
        f"\n{len(datos['manzanas']):,} manzanas dibujadas | "
        f"{con:,} con score | {len(datos['rubros'])} rubros"
    )
    print(f"{salida.stat().st_size / 1e6:.2f} MB en {salida}")
    return datos
