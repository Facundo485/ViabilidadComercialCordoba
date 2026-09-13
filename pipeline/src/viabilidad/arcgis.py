"""Cliente mínimo para consultar un ArcGIS FeatureServer con paginación."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

log = logging.getLogger(__name__)

TIMEOUT = 60
REINTENTOS = 4


def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET con reintentos y backoff exponencial (2s, 4s, 8s, 16s)."""
    ultimo_error: Exception | None = None
    for intento in range(REINTENTOS):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            datos = r.json()
            # ArcGIS devuelve 200 con un cuerpo {"error": {...}} cuando falla.
            if "error" in datos:
                raise RuntimeError(f"ArcGIS respondió error: {datos['error']}")
            return datos
        except Exception as exc:
            ultimo_error = exc
            espera = 2 ** (intento + 1)
            log.warning("Fallo la consulta (%s). Reintento en %ss", exc, espera)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo consultar {url}") from ultimo_error


def contar(base: str, capa: int, where: str = "1=1") -> int:
    """Cantidad de registros que matchean `where`, sin traerlos."""
    datos = _get(
        f"{base}/{capa}/query",
        {"f": "json", "where": where, "returnCountOnly": "true"},
    )
    return int(datos["count"])


def paginar(
    base: str,
    capa: int,
    *,
    where: str = "1=1",
    con_geometria: bool = False,
    page_size: int = 32_000,
) -> Iterator[dict[str, Any]]:
    """Itera todos los registros de una capa/tabla, página por página.

    Se ordena por objectid para que la paginación sea estable: sin `orderByFields`
    el servidor no garantiza el orden entre requests y podrías perder o duplicar
    filas al avanzar el offset.
    """
    offset = 0
    while True:
        datos = _get(
            f"{base}/{capa}/query",
            {
                "f": "json",
                "where": where,
                "outFields": "*",
                "returnGeometry": "true" if con_geometria else "false",
                "outSR": 4326,
                "orderByFields": "objectid ASC",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            },
        )
        features = datos.get("features", [])
        if not features:
            return

        for f in features:
            fila = dict(f["attributes"])
            if con_geometria and (geom := f.get("geometry")):
                fila["lon"] = geom.get("x")
                fila["lat"] = geom.get("y")
            yield fila

        log.info("  %s registros descargados", offset + len(features))

        # Sin el flag, la última página vino incompleta y ya no queda nada.
        if not datos.get("exceededTransferLimit"):
            return
        offset += len(features)


def rubros_con_conteo(base: str, capa: int) -> list[dict[str, Any]]:
    """Agrega del lado del servidor: cada rubro con su cantidad, sin bajar filas."""
    datos = _get(
        f"{base}/{capa}/query",
        {
            "f": "json",
            "where": "1=1",
            "groupByFieldsForStatistics": "rubronombre",
            "outStatistics": (
                '[{"statisticType":"count","onStatisticField":"objectid",'
                '"outStatisticFieldName":"n"}]'
            ),
            "orderByFields": "n DESC",
        },
    )
    return [f["attributes"] for f in datos.get("features", [])]
