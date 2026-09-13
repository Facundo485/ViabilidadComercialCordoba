"""Tests del Paso 2: supervivencia sobre períodos de actividad consolidados.

Los datos sintéticos imitan la estructura real del GIS —plazos de 5 años fijos y
renovaciones cargadas como habilitaciones nuevas— porque es justamente esa
estructura la que hace que la receta ingenua mida el calendario en vez del
comercio.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from viabilidad import supervivencia

HOY = datetime(2026, 9, 1)
PLAZO = timedelta(days=int(5 * supervivencia.DIAS_ANIO))


def habilitaciones(
    *, nivel2: str, nivel1: str, n: int, renovaciones: int, alta: datetime, cuit_base: int
) -> list[dict]:
    """Genera `n` comercios que renuevan `renovaciones` veces, con plazo fijo.

    Cada renovación es una fila más, como las carga el municipio: encadenarlas
    es trabajo de `consolidar()`.
    """
    filas = []
    for i in range(n):
        inicio = alta
        for _ in range(renovaciones + 1):
            filas.append(
                {
                    "objectid": len(filas) + 1 + cuit_base * 10_000,
                    "nro_catastral": f"01-01-{cuit_base:03d}-{i:03d}",
                    "cuitempresa": f"20{cuit_base:03d}{i:05d}9",
                    "fechahabaprobada": inicio,
                    "fechavencimientohab": inicio + PLAZO,
                    "nivel2": nivel2,
                    "nivel1": nivel1,
                    "manzana": f"01-01-{cuit_base:03d}",
                }
            )
            inicio = inicio + PLAZO
    return filas


@pytest.fixture
def mercado():
    """Dos rubros con la misma época de alta pero vidas muy distintas.

    `duradero` renueva tres veces (≈20 años de actividad) y `efimero` no renueva
    nunca (≈5 años). Las altas son las mismas, así que nada los distingue salvo
    la supervivencia real.
    """
    alta = HOY - timedelta(days=int(21 * supervivencia.DIAS_ANIO))
    return pl.DataFrame(
        habilitaciones(
            nivel2="duradero", nivel1="grupo_a", n=150, renovaciones=3, alta=alta, cuit_base=1
        )
        + habilitaciones(
            nivel2="efimero", nivel1="grupo_b", n=150, renovaciones=0, alta=alta, cuit_base=2
        )
    )


def test_detecta_que_el_plazo_es_constante(mercado):
    """El supuesto que justifica todo el módulo se mide, no se asume."""
    p = supervivencia.plazos(mercado)

    assert p["media"][0] == pytest.approx(5.0, abs=0.05)
    assert p["desvio"][0] < 0.01, "con plazo fijo el desvío tiene que ser ~0"


def test_las_renovaciones_se_encadenan_en_un_solo_periodo(mercado):
    """Sin esto, un local de 20 años cuenta como cuatro de 5 y la duración
    medida termina siendo el plazo del permiso."""
    spells = supervivencia.consolidar(mercado)

    duraderos = spells.filter(pl.col("nivel2") == "duradero")
    assert len(duraderos) == 150, "cuatro habilitaciones encadenadas son un período"
    assert (duraderos["habilitaciones"] == 4).all()

    efimeros = spells.filter(pl.col("nivel2") == "efimero")
    assert len(efimeros) == 150
    assert (efimeros["habilitaciones"] == 1).all()


def test_un_hueco_largo_corta_el_periodo():
    """Irse y volver años después no es una renovación: son dos comercios."""
    alta = HOY - timedelta(days=int(20 * supervivencia.DIAS_ANIO))
    filas = habilitaciones(
        nivel2="r", nivel1="g", n=1, renovaciones=0, alta=alta, cuit_base=1
    ) + habilitaciones(
        nivel2="r",
        nivel1="g",
        n=1,
        renovaciones=0,
        alta=alta + PLAZO + timedelta(days=supervivencia.HUECO_DIAS + 30),
        cuit_base=1,
    )
    spells = supervivencia.consolidar(pl.DataFrame(filas))

    assert len(spells) == 2, "el hueco tendría que haber abierto un período nuevo"


def test_el_que_sigue_con_permiso_se_censura_no_se_cuenta_como_cierre():
    """Regresión conceptual: la censura nunca se rellena como cierre.

    Ya pasó con `vigente` nulo leído como cero y produjo una tabla de ceros sin
    que nada fallara.
    """
    alta = HOY - timedelta(days=int(2 * supervivencia.DIAS_ANIO))
    d = supervivencia.duraciones(
        supervivencia.consolidar(
            pl.DataFrame(
                habilitaciones(nivel2="r", nivel1="g", n=1, renovaciones=0, alta=alta, cuit_base=1)
            )
        ),
        hoy=HOY,
    )

    assert d["evento"][0] == 0, "tiene permiso vigente: es censura, no cierre"
    assert d["duracion"][0] == pytest.approx(2.0, abs=0.05)


def test_un_vencimiento_muy_reciente_no_se_da_por_cerrado():
    """Las renovaciones fuera de término existen; darlas por cierre las inventa."""
    alta = HOY - PLAZO - timedelta(days=30)  # venció hace un mes
    d = supervivencia.duraciones(
        supervivencia.consolidar(
            pl.DataFrame(
                habilitaciones(nivel2="r", nivel1="g", n=1, renovaciones=0, alta=alta, cuit_base=1)
            )
        ),
        hoy=HOY,
    )

    assert d["evento"][0] == 0, "dentro del período de gracia todavía no se sabe"


def test_kaplan_meier_distingue_los_dos_rubros(mercado):
    """Lo que la tasa cruda no podía hacer: ordenar rubros por vida real."""
    km = supervivencia.kaplan_meier(
        supervivencia.duraciones(supervivencia.consolidar(mercado), hoy=HOY), "nivel2"
    )
    s5 = dict(zip(km["nivel2"], km["s5"], strict=True))
    mediana = dict(zip(km["nivel2"], km["mediana_anios"], strict=True))

    assert s5["duradero"] > s5["efimero"], "el rubro que renueva tiene que sobrevivir más"
    assert mediana["duradero"] > mediana["efimero"]
    assert mediana["efimero"] == pytest.approx(5.0, abs=0.5)


def test_sin_consolidar_los_dos_rubros_se_ven_iguales(mercado):
    """El test que justifica el módulo.

    Midiendo habilitación por habilitación —la receta literal del doc— los dos
    rubros dan la misma duración, porque lo que se mide es el plazo del permiso
    y no la vida del comercio. Si este test empieza a fallar, es que alguien
    sacó la consolidación.
    """
    sin_consolidar = mercado.with_columns(
        pl.col("fechahabaprobada").alias("inicio"),
        pl.col("fechavencimientohab").alias("fin_cobertura"),
    )
    km = supervivencia.kaplan_meier(supervivencia.duraciones(sin_consolidar, hoy=HOY), "nivel2")
    mediana = dict(zip(km["nivel2"], km["mediana_anios"], strict=True))

    assert mediana["duradero"] == pytest.approx(mediana["efimero"], abs=0.1), (
        "sin consolidar, ambos rubros miden el plazo del permiso y son indistinguibles"
    )
