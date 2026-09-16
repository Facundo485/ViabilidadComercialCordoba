"""Tests del pipeline con el GIS mockeado.

La clave es que ejercitan `descargar_*` completas, no sus helpers sueltos: un
test que llamaba a los helpers por separado no vio que el join de rubros había
quedado después de un `return` y nunca se ejecutaba.
"""

from __future__ import annotations

import random

import polars as pl
import pytest

from viabilidad import arcgis, config, ingest, manzanas

RUBROS_REALES = [
    "Almacén de comestibles",
    "VENTA AL POR MENOR DE PRODUCTOS DE ALMACÉN Y DIETÉTICA",
    "Venta al por menor en farmacias de productos medicinales",
    "Bar, confiterías, pizzerías, lomiterías, empanaderías, parrilla",
    "Venta al por menor de pinturas, barnices, lacas, esmaltes",
    "VENTA AL POR MAYOR DE PRODUCTOS FARMACÉUTICOS",
    "Depósitos y almacenamientos en general, excepto alimentos",
]


def _falso_gis(
    monkeypatch, parcelas: list[dict], historial: list[dict], tramites: list[dict] | None = None
) -> None:
    """Mockea las tres capas. Hay que mirar la base y no solo el número de capa:
    las parcelas y los trámites son las dos capa 0 de servicios distintos."""

    def paginar(base, capa, **kw):
        if base == config.GIS_BASE_VISTA:
            return iter(tramites if tramites is not None else _tramites_de(historial))
        return iter(parcelas if capa == config.CAPA_PARCELAS else historial)

    monkeypatch.setattr(arcgis, "paginar", paginar)


def _tramites_de(historial: list[dict]) -> list[dict]:
    """Arma la vista de trámites a partir del histórico, un titular por trámite."""
    vistos: dict[int, dict] = {}
    for h in historial:
        vistos.setdefault(
            h["id_tramite"],
            {
                "id": h["id_tramite"],
                "nrocatastral": h["nro_catastral"],
                "cuitempresa": f"20{h['id_tramite']:09d}",
                "barrio": "AYACUCHO",
                "cpc": "CENTRO AMERICA",
            },
        )
    return list(vistos.values())


@pytest.fixture
def datos():
    random.seed(3)
    parcelas, historial = [], []
    for mz in range(1, 40):
        for p in range(1, random.randint(2, 6)):
            nro = f"01-01-{mz:03d}-{p:03d}"
            total = random.randint(1, 5)
            vig = random.randint(0, total)
            parcelas.append(
                {
                    "objectid": len(parcelas) + 1,
                    "nro_catastral": nro,
                    "hab_total": total,
                    "hab_vigentes": vig,
                    "hab_novigentes": total - vig,
                    "lon": -64.17 + random.random() / 100,
                    "lat": -31.37 - random.random() / 100,
                    "barrio_identificado": "AYACUCHO",
                    "cpc_identificado": "CENTRO AMERICA",
                }
            )
            for _ in range(total):
                historial.append(
                    {
                        "objectid": len(historial) + 1,
                        "id_tramite": len(historial) + 1,
                        "nro_catastral": nro,
                        "rubronombre": random.choice(RUBROS_REALES),
                        "vigente": random.randint(0, 1),
                        "fechahabaprobada": 1_600_000_000_000,
                        "fechavencimientohab": 1_700_000_000_000,
                    }
                )
    return parcelas, historial


def test_historial_trae_los_rubros_clasificados(monkeypatch, datos):
    """Regresión: el join contra el mapeo quedaba después de un return."""
    _falso_gis(monkeypatch, *datos)
    df = ingest.descargar_historial()

    assert {"nivel1", "nivel2", "manzana"} <= set(df.columns)
    assert df["nivel2"].null_count() == 0
    assert df.filter(pl.col("nivel2") != "otro").height > 0, "no clasificó nada"


def test_las_fechas_se_convierten(monkeypatch, datos):
    _falso_gis(monkeypatch, *datos)
    df = ingest.descargar_historial()
    assert isinstance(df.schema["fechahabaprobada"], pl.Datetime)
    assert df["fechahabaprobada"].dt.year().min() == 2020


def test_se_descartan_las_coordenadas_corruptas(monkeypatch, datos):
    """La capa declara un extent hasta lat 90: hay puntos fuera de Córdoba."""
    parcelas, historial = datos
    basura = dict(parcelas[0], objectid=99_999, nro_catastral="99-99-999-999", lat=89.9, lon=179.9)
    _falso_gis(monkeypatch, [*parcelas, basura], historial)

    df = ingest.descargar_parcelas()
    assert 99_999 not in df["objectid"].to_list()


def test_la_manzana_sale_del_nro_catastral(monkeypatch, datos):
    _falso_gis(monkeypatch, *datos)
    df = ingest.descargar_parcelas()
    assert df.filter(pl.col("nro_catastral") == "01-01-001-001")["manzana"][0] == "01-01-001"


def test_la_agregacion_no_pierde_habilitaciones(monkeypatch, datos):
    _falso_gis(monkeypatch, *datos)
    parcelas = ingest.descargar_parcelas()
    historial = ingest.descargar_historial()

    mz = manzanas.agregar(parcelas, historial)

    assert mz["hab_total"].sum() == parcelas["hab_total"].sum()
    assert mz["manzana"].n_unique() == len(mz)
    assert (mz["hab_total"] == mz["hab_vigentes"] + mz["hab_novigentes"]).all()


def test_la_vigencia_nula_se_deriva_de_la_fecha_de_vencimiento(monkeypatch, datos):
    """Regresión: `vigente` venía nulo del GIS y un fill_null(0) lo daba por cerrado.

    Es la variable objetivo, así que rellenarla con cero sesga todo el modelo.
    """
    parcelas, historial = datos
    futuro, pasado = 4_100_000_000_000, 1_600_000_000_000  # 2099 y 2020
    sin_vigente = [
        dict(h, vigente=None, fechavencimientohab=futuro if i % 2 else pasado)
        for i, h in enumerate(historial)
    ]
    _falso_gis(monkeypatch, parcelas, sin_vigente)

    df = ingest.descargar_historial()

    assert df["vigente"].sum() > 0, "no dedujo ninguna vigencia"
    assert df["vigente"].mean() == pytest.approx(0.5, abs=0.05)


def test_corta_si_no_queda_ninguna_vigente(monkeypatch, datos):
    parcelas, historial = datos
    muertas = [dict(h, vigente=None, fechavencimientohab=None) for h in historial]
    _falso_gis(monkeypatch, parcelas, muertas)

    with pytest.raises(ValueError, match="vigente"):
        ingest.descargar_historial()


def test_los_mayoristas_quedan_fuera_del_detalle(monkeypatch, datos):
    _falso_gis(monkeypatch, *datos)
    detalle = manzanas.por_rubro(ingest.descargar_historial())

    assert "industria y deposito" not in detalle["nivel1"].unique().to_list()
    assert detalle["tasa_supervivencia"].is_between(0, 1).all()


def test_el_suavizado_baja_las_tasas_perfectas_de_poco_volumen(monkeypatch, datos):
    _falso_gis(monkeypatch, *datos)
    detalle = manzanas.por_rubro(ingest.descargar_historial())

    perfectas = detalle.filter((pl.col("tasa_cruda") == 1.0) & (pl.col("total") <= 2))
    assert len(perfectas) > 0, "el fixture no generó el caso"
    assert (perfectas["tasa_supervivencia"] < 1.0).all()


def test_el_cuit_no_queda_en_el_parquet(monkeypatch, datos):
    """`cuitempresa` identifica personas: sale hasheado del ingest o no sale."""
    _falso_gis(monkeypatch, *datos)
    tramites = ingest.descargar_tramites()

    assert "cuitempresa" not in tramites.columns
    assert "razonsocial" not in tramites.columns
    assert tramites["titular"].null_count() == 0
    assert tramites["titular"].str.len_chars().max() == config.LARGO_HASH_CUIT * 2


def test_el_hash_del_titular_es_estable_y_distingue_titulares():
    """Para encadenar renovaciones alcanza con que sea estable y no colisione."""
    assert ingest.seudonimo("20123456789") == ingest.seudonimo("20123456789")
    assert ingest.seudonimo("20123456789") != ingest.seudonimo("20123456780")
    assert ingest.seudonimo(None) is None
    assert ingest.seudonimo("  ") is None


def test_el_historial_queda_con_titular(monkeypatch, datos):
    """Sin esto `supervivencia` consolida contra una columna vacía: es lo que pasó."""
    _falso_gis(monkeypatch, *datos)
    df = ingest.descargar_historial()

    assert df["titular"].null_count() == 0
    assert df["titular"].n_unique() > 1


def test_corta_si_la_vista_trae_el_titular_vacio(monkeypatch, datos):
    """Regresión: el histórico ya declara `cuitempresa` y la devuelve nula en el
    100% de las filas. Si la vista hiciera lo mismo, la consolidación daría cero
    renovaciones sin que nada fallara."""
    parcelas, historial = datos
    vacios = [dict(t, cuitempresa=None) for t in _tramites_de(historial)]
    _falso_gis(monkeypatch, parcelas, historial, tramites=vacios)

    with pytest.raises(ValueError, match="titular"):
        ingest.descargar_tramites()


def test_un_tramite_no_se_cuenta_dos_veces_en_el_mismo_rubro(monkeypatch, datos):
    """El nomenclador viejo y el CLANAE nuevo describen lo mismo: un trámite
    habilitado bajo ambos cae dos veces en el mismo nivel2 si no se deduplica."""
    parcelas, historial = datos
    manzana = historial[0]["nro_catastral"][:9]

    def total_almacen(filas):
        _falso_gis(monkeypatch, parcelas, filas)
        detalle = manzanas.por_rubro(ingest.descargar_historial())
        return detalle.filter((pl.col("manzana") == manzana) & (pl.col("nivel2") == "almacen"))[
            "total"
        ].sum()

    antes = total_almacen(historial)

    # Las dos entradas caen en nivel2 "almacen": una es del nomenclador viejo y
    # la otra del CLANAE nuevo. Son dos filas de un mismo trámite, así que el
    # rubro tiene que sumar uno solo, no dos.
    duplicado = dict(historial[0], objectid=999_999, rubronombre="Almacén de comestibles")
    gemelo = dict(duplicado, objectid=999_998, rubronombre="VENTA AL POR MENOR EN MINIMERCADOS")

    assert total_almacen([*historial, duplicado, gemelo]) == antes + 1


def test_la_sal_del_hash_no_esta_en_el_codigo(tmp_path, monkeypatch):
    """Una sal publicada es lo mismo que no tener sal: el CUIT se enumera."""
    monkeypatch.delenv("VIABILIDAD_SAL_CUIT", raising=False)
    monkeypatch.setattr(config, "ARCHIVO_SAL", tmp_path / ".sal")
    primera = config.sal_cuit()
    assert len(primera) >= 32
    # Estable entre corridas: si cambiara, los tramites de un mismo titular
    # dejarian de encadenarse y la supervivencia volveria a medir el plazo.
    assert config.sal_cuit() == primera

    otra = tmp_path / "otra" / ".sal"
    monkeypatch.setattr(config, "ARCHIVO_SAL", otra)
    assert config.sal_cuit() != primera
