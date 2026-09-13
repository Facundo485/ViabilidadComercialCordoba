"""Tests del diagnóstico de la variable objetivo.

Ejercitan `nomenclador()` entera contra tablas fabricadas, no sus helpers: lo
que importa es que la detección del nomenclador quede efectivamente enchufada
al cruce contra la tasa, que es donde el bug anterior se escondió.
"""

from __future__ import annotations

import polars as pl
import pytest

from viabilidad import config, diagnostico, mapeo

# Nombres reales del GIS. Los de MAYÚSCULAS son CLANAE/CIIU (nomenclador nuevo)
# y los de Título, el municipal viejo. Ojo con el acento en mayúscula de
# "FARMACÉUTICOS": es el caso que un chequeo ingenuo de acentos clasificaría mal.
NUEVOS = [
    "VENTA AL POR MENOR DE PRODUCTOS DE ALMACÉN Y DIETÉTICA",
    "VENTA AL POR MAYOR DE PRODUCTOS FARMACÉUTICOS",
    "OTRAS ACTIVIDADES N.C.P.",
]
VIEJOS = [
    "Almacén de comestibles",
    "Bar, confiterías, pizzerías, lomiterías, empanaderías, parrilla",
]


@pytest.fixture
def tablas(tmp_path, monkeypatch):
    """Arma un referencia/mapeo_rubros.csv y un resumen_rubros.csv mínimos.

    `solo_nuevo` viene entero del nomenclador nuevo y `solo_viejo` entero del
    viejo; `mezclado` va mitad y mitad. `chico` y `otro` existen para comprobar
    que el filtro los deja afuera.
    """
    referencia = tmp_path / "referencia"
    referencia.mkdir()
    monkeypatch.setattr(config, "RAIZ", tmp_path)
    monkeypatch.setattr(config, "DIR_REFERENCIA", referencia)
    monkeypatch.setattr(config, "DIR_CRUDO", tmp_path / "crudo")

    filas = []
    for nivel2, n_nuevo, n_viejo in [
        ("solo_nuevo", 1000, 0),
        ("mezclado", 500, 500),
        ("solo_viejo", 0, 1000),
        ("chico", 50, 50),
        ("otro", 1000, 1000),
    ]:
        if n_nuevo:
            filas.append({"rubronombre": NUEVOS[0], "n": n_nuevo, "nivel2": nivel2})
        if n_viejo:
            filas.append({"rubronombre": VIEJOS[0], "n": n_viejo, "nivel2": nivel2})
    pl.DataFrame(filas).with_columns(pl.lit("grupo").alias("nivel1")).write_csv(
        referencia / mapeo.ARCHIVO
    )

    pl.DataFrame(
        {
            "nivel2": ["solo_nuevo", "mezclado", "solo_viejo", "chico", "otro"],
            "nivel1": ["grupo"] * 5,
            "habilitaciones": [1000, 1000, 1000, 100, 2000],
            "vigentes": [664, 332, 0, 50, 700],
            "tasa": [0.664, 0.332, 0.0, 0.5, 0.35],
        }
    ).write_csv(tmp_path / diagnostico.ARCHIVO_RESUMEN)
    return tmp_path


def test_separa_los_dos_nomencladores(tablas):
    """Las MAYÚSCULAS acentuadas del CLANAE cuentan como nomenclador nuevo."""
    df = diagnostico.nomenclador()
    frac = dict(zip(df["nivel2"], df["frac_nuevo"], strict=True))

    assert frac["solo_nuevo"] == 1.0
    assert frac["solo_viejo"] == 0.0
    assert frac["mezclado"] == pytest.approx(0.5)


def test_deja_afuera_lo_que_no_se_puede_comparar(tablas):
    """Los rubros chicos se mueven por ruido y `otro` promedia cosas distintas."""
    nivel2 = diagnostico.nomenclador()["nivel2"].to_list()

    assert "chico" not in nivel2, "no aplicó el umbral de habilitaciones"
    assert "otro" not in nivel2, "el cajón de no clasificados no se puede comparar"
    assert {"solo_nuevo", "mezclado", "solo_viejo"} == set(nivel2)


def test_el_ajuste_recupera_la_supervivencia_del_nomenclador_nuevo(tablas):
    """Con tasa = 0,664 * frac_nuevo exacta, el ajuste tiene que devolver eso."""
    pendiente, r2 = diagnostico.ajuste_por_el_origen(diagnostico.nomenclador())

    assert pendiente == pytest.approx(0.664, abs=1e-3)
    assert r2 == pytest.approx(1.0, abs=1e-6)


def test_el_cruce_contra_el_anio_se_omite_sin_el_historico(tablas):
    """Sin ingest previo el diagnóstico igual corre: la otra vía no necesita red."""
    assert diagnostico.epoca() is None


def test_falla_claro_si_falta_el_resumen(tablas):
    (tablas / diagnostico.ARCHIVO_RESUMEN).unlink()

    with pytest.raises(FileNotFoundError, match="viabilidad resumen"):
        diagnostico.nomenclador()
