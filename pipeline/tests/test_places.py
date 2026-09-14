"""Tests del clasificador de respuestas de Places.

Todos los casos salieron de respuestas reales de las primeras 60 consultas.
El clasificador es lo que convierte "hay un negocio acá" en "nuestro local
sobrevivió o no", así que un error suyo no rompe nada: sesga la calibración.
"""

from __future__ import annotations

import pytest

from viabilidad import places


@pytest.mark.parametrize(
    ("nuestro", "de_places"),
    [
        ("Gold Body", "Goldbody Supplements"),  # el mismo, pegado
        ("AL BUCHE", "BUCHEANDO"),  # el mismo, derivado
        ("Eric", "Drugstore Eric"),  # el mismo, con el rubro adelante
        ("MUNDO ALIMENTOS", "Mundo Alimento"),  # singular/plural
        ("MERCADO URBANO", "Mercado urbano"),  # mayúsculas
        ("PIDE SUSHI S.A.S.", "Pide Sushi Bar"),  # forma societaria de más
    ],
)
def test_reconoce_el_mismo_negocio_escrito_distinto(nuestro, de_places):
    assert places.mismo_negocio(nuestro, de_places) is True


@pytest.mark.parametrize(
    ("nuestro", "de_places"),
    [
        ("Súper Argenchino", "Alfa y omega carnes"),
        ("la esquina de la vinotinto", "Aware - Espacio Terapéutico"),
        ("Super Matanza", "Supermercado José Hernández"),
    ],
)
def test_reconoce_que_el_local_cambio_de_dueno(nuestro, de_places):
    assert places.mismo_negocio(nuestro, de_places) is False


def test_sin_nombre_no_decide():
    """La ausencia de nombre es no saber, no es un cierre."""
    assert places.mismo_negocio("", "Kiosco Tito") is None
    assert places.mismo_negocio("Kiosco Tito", None) is None


@pytest.mark.parametrize(
    "nombre",
    [
        "Manuel Cardeñosa 4513 Loc 2",
        'San Lorenzo 437 " Torre Da\'Vinci"',
        "Buenos Aires 478, nueva cordoba",
        None,
    ],
)
def test_una_direccion_no_es_un_negocio(nombre):
    """Regresión: cuando no hay comercio indexado, Text Search contesta igual con
    el resultado geocodificado y su `displayName` es la dirección. Leerlo como el
    nombre de un negocio inventaba un `otro_negocio`, que es justo el caso que
    decide si el proxy acertó."""
    assert places.es_direccion(nombre) is True


@pytest.mark.parametrize("nombre", ["Drugstore Eric", "Mercado urbano", "Kiosco 24"])
def test_un_nombre_comercial_no_se_confunde_con_una_direccion(nombre):
    assert places.es_direccion(nombre) is False


def test_el_permanentemente_cerrado_se_lee_como_cierre():
    respuesta = {
        "places": [
            {
                "displayName": {"text": "Kiosco Tito"},
                "businessStatus": "CLOSED_PERMANENTLY",
            }
        ]
    }
    assert (
        places._interpretar(respuesta, {"nombrefantasia": "Kiosco Tito"})["observado"] == "cerrado"
    )


def test_sin_resultados_es_sin_dato_y_no_un_cierre():
    """El error de siempre en este proyecto: convertir "no sé" en "cerró"."""
    assert places._interpretar({}, {"nombrefantasia": "X"})["observado"] == "sin_dato"
    assert places._interpretar({"places": []}, {"nombrefantasia": "X"})["observado"] == "sin_dato"
