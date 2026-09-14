"""Tests de las reglas que agrupan el nomenclador.

Cada caso es una cadena real del GIS, copiada tal cual. Son casi todos de
regresión: el agrupamiento se veía sano en el agregado y estaba mandando miles
de habilitaciones al rubro equivocado, así que lo que se fija acá es el
resultado sobre las cadenas que efectivamente rompieron.
"""

from __future__ import annotations

import polars as pl
import pytest

from viabilidad import mapeo

CASOS = [
    # El bug que partió la gastronomía en dos por época: sin `\b`, el regex de
    # "panaderia" matcheaba adentro de "e-m-panaderías" y se llevaba las 2.896
    # habilitaciones del nomenclador viejo.
    (
        "Bar, confiterías, pizzerías, lomiterías, empanaderías, parrilla, trattoría, "
        "confiterías y restaurantes con una superficie habilitada hasta 100 m2.-",
        "bar_restaurante",
    ),
    ("Venta al por menor de panificadoras y panaderías", "panaderia"),
    ("VENTA AL POR MENOR DE PAN Y PRODUCTOS DE PANADERÍA", "panaderia"),
    # Un hotel que nombra su restaurante no es un restaurante.
    ("SERVICIOS DE ALOJAMIENTO EN HOTELES, HOSTERÍAS Y RESIDENCIALES SIMILARES", "turismo"),
    # ...pero un geriátrico tampoco es turismo aunque dé alojamiento.
    ("SERVICIOS DE ATENCIÓN A ANCIANOS CON ALOJAMIENTO", "otro"),
    # Vender café en grano es un almacén; tostarlo, industria. Ninguno es un bar.
    ("Venta al por menor de café, te, yerba mate y especias", "alimentos_otros"),
    ("Tostado, torrado y molienda de café", "fabricacion"),
    ("Venta al por menor de masas y demás productos de pastelerías. Confiterías", "panaderia"),
    # La veterinaria es un servicio médico, no un local de venta de forraje.
    ("SERVICIOS MÉDICOS PARA ANIMALES (VETERINARIA)", "veterinaria"),
    ("SERVICIOS VETERINARIOS", "veterinaria"),
    (
        "VENTA AL POR MENOR DE PRODUCTOS VETERINARIOS, ANIMALES DOMÉSTICOS Y ALIMENTO BALANCEADO",
        "forrajeria",
    ),
    # "rodados infantiles" son bicicletas, no ropa de nene.
    (
        "Venta al por menor de bicicletas y rodados infantiles, sus repuestos y accesorios",
        "venta_vehiculos",
    ),
    ("Venta al por menor de indumentaria para bebes y niños", "ropa_infantil"),
    # El CLANAE llama al almacén de toda la vida "productos de almacén y
    # dietética": es el mismo negocio que el "Almacén de comestibles" viejo, y
    # separarlos parte el rubro en dos mitades que no se solapan en el tiempo.
    ("VENTA AL POR MENOR DE PRODUCTOS DE ALMACÉN Y DIETÉTICA", "almacen"),
    ("Almacén de comestibles", "almacen"),
    ("Venta al por menor de productos dietéticos.", "dietetica"),
    ("Venta al por menor de herboristería", "dietetica"),
    # Una cancha de paddle y un salón de fiestas no tienen la misma vida útil.
    ("EXPLOTACIÓN DE INSTALACIONES DEPORTIVAS, EXCEPTO CLUBES", "instalaciones_deportivas"),
]


def _clasificar(nombre: str) -> str:
    df = pl.DataFrame({"rubronombre": [nombre]})
    return df.select(mapeo.clasificar(mapeo.normalizar()).alias("n2"))["n2"][0]


@pytest.mark.parametrize(("nombre", "esperado"), CASOS)
def test_clasifica_las_cadenas_reales(nombre: str, esperado: str):
    assert _clasificar(nombre) == esperado


def test_ninguna_regla_matchea_a_mitad_de_palabra():
    """El detector general del bug de `empanaderías`.

    Un regex sin `\\b` que cae adentro de otra palabra clasifica por accidente.
    Los plurales no cuentan: ahí la palabra es la misma, solo cambia el final.
    """
    import re

    from viabilidad import config, rubros

    df = pl.read_csv(config.DIR_REFERENCIA / "rubros.csv").with_columns(
        mapeo.normalizar().alias("k")
    )
    compiladas = [
        (n2, re.compile(inc), re.compile(exc) if exc else None) for n2, _, inc, exc in rubros.REGLAS
    ]

    culpables = []
    for nombre, k in df.select("rubronombre", "k").iter_rows():
        for nivel2, incluir, excluir in compiladas:
            if excluir and excluir.search(k):
                continue
            if not (m := incluir.search(k)):
                continue
            arranca_a_mitad = m.start() > 0 and k[m.start() - 1].isalpha()
            if arranca_a_mitad:
                culpables.append((nivel2, m.group(0), nombre))
            break

    assert not culpables, f"reglas que matchean a mitad de palabra: {culpables[:5]}"
