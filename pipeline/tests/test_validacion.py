"""Tests de la muestra para calibrar el proxy de cierre contra Places.

Lo que se protege acá es sobre todo **qué sale del repo**: la muestra se manda a
un servicio externo, así que una columna de más no es un detalle de formato.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest

from tests.test_supervivencia import HOY, PLAZO, habilitaciones
from viabilidad import config, validacion


@pytest.fixture
def preparado(monkeypatch):
    """Histórico sintético con su tabla de trámites, como la deja el ingest.

    Los `vivos` abrieron hace dos años y renovaron: siguen con permiso. Los
    `muertos` abrieron hace ocho y no renovaron: el permiso caducó hace tres.
    """
    vivos = habilitaciones(
        nivel2="r", nivel1="g", n=40, renovaciones=1, alta=HOY - PLAZO, cuit_base=1
    )
    muertos = habilitaciones(
        nivel2="r",
        nivel1="g",
        n=40,
        renovaciones=0,
        alta=HOY - PLAZO - timedelta(days=3 * 365),
        cuit_base=2,
    )
    h = pl.DataFrame(vivos + muertos)
    tramites = (
        h.select("id_tramite")
        .unique()
        .with_columns(
            pl.format("CALLE {} 100", pl.col("id_tramite")).alias("domicilio_loc"),
            pl.lit(-64.18).alias("lon"),
            pl.lit(-31.42).alias("lat"),
            pl.lit("CENTRO").alias("barrio"),
            pl.format("NEGOCIO {}", pl.col("id_tramite")).alias("nombrefantasia"),
            pl.lit("hash-del-titular").alias("titular"),
        )
    )
    monkeypatch.setattr(validacion.supervivencia, "_historial", lambda: h)
    monkeypatch.setattr(validacion, "_tramites", lambda: tramites)
    return h


def test_la_muestra_no_lleva_el_titular(preparado):
    """Es dato personal y no hace falta para calibrar el proxy: no se manda."""
    m = validacion.muestra(n=20, hoy=HOY)

    assert "titular" not in m.columns
    assert "hash-del-titular" not in m.write_csv()


def test_una_direccion_aparece_una_sola_vez(preparado):
    """Con dos locales en la misma dirección no se sabe por cuál responde Places."""
    m = validacion.muestra(n=40, hoy=HOY)

    assert m["domicilio_loc"].n_unique() == len(m)


def test_las_dos_clases_estan_representadas(preparado):
    """Medir solo los cierres no dice nada sobre los falsos negativos."""
    m = validacion.muestra(n=40, hoy=HOY)

    assert set(m["estado_predicho"].unique()) == {"abierto", "cerrado"}


def test_el_que_todavia_tiene_permiso_se_predice_abierto(preparado):
    p = validacion.preparar(hoy=HOY)

    vigentes = p.filter(pl.col("evento") == 0)
    assert not vigentes.is_empty()
    assert (vigentes["estado_predicho"] == "abierto").all()


def test_los_cierres_viejos_quedan_fuera(preparado):
    """Un cierre de hace muchos años ya no figura: preguntarlo mide la memoria
    de Google, no nuestro proxy."""
    viejos = validacion.preparar(hoy=HOY).filter(
        (pl.col("estado_predicho") == "cerrado")
        & (pl.col("fin_cobertura").dt.year() < validacion.ANIO_CIERRE_MIN)
    )
    m = validacion.muestra(n=40, hoy=HOY)

    cerrados = m.filter(pl.col("estado_predicho") == "cerrado")
    assert not cerrados.is_empty()
    assert cerrados["fin_cobertura"].dt.year().min() >= validacion.ANIO_CIERRE_MIN
    assert set(viejos["ultimo_tramite"]).isdisjoint(set(cerrados["ultimo_tramite"]))


def test_corta_si_los_tramites_son_de_antes_de_la_direccion(monkeypatch, tmp_path):
    """Regresión: con el parquet viejo el join dejaba la dirección toda nula y
    la muestra salía vacía en silencio."""
    (tmp_path / "tramites.parquet").write_bytes(b"")
    pl.DataFrame({"id_tramite": [1], "titular": ["x"]}).write_parquet(tmp_path / "tramites.parquet")
    monkeypatch.setattr(config, "DIR_CRUDO", tmp_path)

    with pytest.raises(ValueError, match="dirección"):
        validacion._tramites()


def test_los_locales_sin_nombre_de_fantasia_quedan_fuera(preparado, monkeypatch):
    """Sin nombre no hay con qué desempatar si el negocio que Places encuentra es
    el nuestro o el que lo reemplazó, así que la consulta se paga y no informa.
    Medido: las 22 primeras sin nombre salieron todas `sin_dato`."""
    tramites = validacion._tramites().with_columns(
        # % 3 y no % 2: los períodos que renovaron ocupan dos trámites seguidos,
        # así que con paridad todos los "abierto" caerían del mismo lado y el
        # test mediría eso en vez del filtro.
        pl.when(pl.col("id_tramite") % 3 == 0)
        .then(pl.lit(""))
        .otherwise(pl.col("nombrefantasia"))
        .alias("nombrefantasia")
    )
    monkeypatch.setattr(validacion, "_tramites", lambda: tramites)

    m = validacion.muestra(n=40, hoy=HOY)

    assert not m.is_empty()
    assert set(m["estado_predicho"].unique()) == {"abierto", "cerrado"}
    assert (m["nombrefantasia"].str.strip_chars() != "").all()
