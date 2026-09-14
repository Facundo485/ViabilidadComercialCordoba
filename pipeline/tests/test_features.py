"""Tests de las features del entorno.

Lo que se protege acá es que **nada mire hacia adelante**. Es el modo de falla
que arruinaría el modelo sin romper nada: las métricas darían mejores y el score
no serviría para alguien parado hoy frente a un local vacío.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from viabilidad import features

HOY = datetime(2026, 9, 1)


def _local(idx: int, alta: datetime, anios: float, rubro: str, lon: float, lat: float) -> dict:
    return {
        "ultimo_tramite": idx,
        "manzana": "01-01-001",
        "barrio": "CENTRO",
        "superficietotal": 50.0,
        "inicio": alta,
        "fin_cobertura": alta + timedelta(days=int(anios * features.DIAS_ANIO)),
        "duracion": anios,
        "evento": 1,
        "nivel2": [rubro],
        "nivel1": ["g"],
        "rubro_principal": rubro,
        "lon": lon,
        "lat": lat,
    }


def _vecinos_a(metros: float) -> float:
    """Desplazamiento en grados de longitud equivalente a `metros` en Córdoba."""
    import math

    return metros / (features.METROS_POR_GRADO * math.cos(math.radians(-31.42)))


def test_no_cuenta_vecinos_que_abrieron_despues():
    """El corazón del módulo. Un local de 2016 no puede ver el comercio que
    abrió en 2022: contarlo mete el futuro adentro de la variable explicativa."""
    base = datetime(2016, 1, 1)
    d = pl.DataFrame(
        [
            _local(1, base, 5, "kiosco", -64.18, -31.42),
            # Pegado, pero abre seis años después: no existe todavía.
            _local(2, base + timedelta(days=6 * 365), 5, "kiosco", -64.18 + _vecinos_a(40), -31.42),
        ]
    )
    f = features.calcular(d)
    del_viejo = f.filter(pl.col("ultimo_tramite") == 1)

    assert del_viejo["densidad_100"][0] == 0, "contó un vecino que todavía no existía"
    assert del_viejo["competencia_100"][0] == 0


def test_no_cuenta_vecinos_que_ya_habian_cerrado():
    """Un permiso vencido hace años no es competencia presente."""
    base = datetime(2020, 1, 1)
    d = pl.DataFrame(
        [
            _local(1, base, 5, "kiosco", -64.18, -31.42),
            _local(2, datetime(2010, 1, 1), 2, "kiosco", -64.18 + _vecinos_a(40), -31.42),
        ]
    )
    f = features.calcular(d).filter(pl.col("ultimo_tramite") == 1)

    assert f["densidad_100"][0] == 0, "contó un vecino cuyo permiso ya había vencido"


def test_cuenta_al_vecino_activo_y_lo_ubica_en_el_radio_correcto():
    base = datetime(2018, 1, 1)
    d = pl.DataFrame(
        [
            _local(1, base + timedelta(days=365), 5, "kiosco", -64.18, -31.42),
            _local(2, base, 8, "kiosco", -64.18 + _vecinos_a(50), -31.42),  # a 50 m
            _local(3, base, 8, "farmacia", -64.18 + _vecinos_a(250), -31.42),  # a 250 m
        ]
    )
    f = features.calcular(d).filter(pl.col("ultimo_tramite") == 1)

    assert f["densidad_100"][0] == 1
    assert f["densidad_300"][0] == 2
    assert f["competencia_100"][0] == 1, "el de 50 m es del mismo rubro"
    assert f["competencia_300"][0] == 1, "el de 250 m es de otro rubro, no compite"


def test_un_local_no_se_cuenta_a_si_mismo():
    d = pl.DataFrame([_local(1, datetime(2018, 1, 1), 5, "kiosco", -64.18, -31.42)])
    f = features.calcular(d)

    assert f["densidad_100"][0] == 0
    assert f["competencia_100"][0] == 0


def test_la_entropia_distingue_una_zona_diversa_de_una_uniforme():
    """Veinte kioscos y veinte rubros distintos tienen la misma densidad y no son
    el mismo lugar."""
    base = datetime(2018, 1, 1)
    despues = base + timedelta(days=365)

    def zona(rubros, offset):
        filas = [_local(999, despues, 5, "objetivo", -64.18 + offset, -31.42)]
        filas += [
            _local(i, base, 8, r, -64.18 + offset + _vecinos_a(30 + i), -31.42)
            for i, r in enumerate(rubros, start=1)
        ]
        return filas

    uniforme = features.calcular(pl.DataFrame(zona(["kiosco"] * 8, 0)))
    diversa = features.calcular(pl.DataFrame(zona([f"r{i}" for i in range(8)], 0)))

    e_uniforme = uniforme.filter(pl.col("ultimo_tramite") == 999)["entropia_rubros"][0]
    e_diversa = diversa.filter(pl.col("ultimo_tramite") == 999)["entropia_rubros"][0]
    assert e_diversa > e_uniforme
    assert e_uniforme == 0.0, "un solo rubro no tiene diversidad"


def test_sin_vecinos_previos_queda_nulo_y_no_cero():
    """ "No había nada antes" es no saber, no es una zona con cero cierres."""
    d = pl.DataFrame([_local(1, datetime(2014, 1, 1), 5, "kiosco", -64.18, -31.42)])
    f = features.calcular(d)

    assert f["cierres_previos_zona_rel"][0] is None
    assert f["antiguedad_zona_anios_rel"][0] is None
