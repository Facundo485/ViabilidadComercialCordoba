"""Consulta Google Places para calibrar el proxy de cierre.

`validacion.py` arma la muestra; esto la consulta y compara. La pregunta que se
responde es **qué tan bien "no renovó el permiso" predice "el local cerró"**,
que hasta acá era un supuesto sin medir.

**Places no responde esa pregunta directamente.** Responde "¿hay un negocio en
esta dirección hoy?". Un `OPERATIONAL` sobre un local que nosotros dimos por
cerrado tiene dos lecturas opuestas: el local cambió de dueño y ahora hay otro
negocio —nuestro proxy acertó— o el mismo negocio sigue operando con el permiso
vencido —nuestro proxy erró—. El desempate es el nombre: se compara el que
devuelve Places contra el `nombrefantasia` que el GIS tiene para ese trámite.

De ahí salen cuatro estados observados:

    sigue_el_mismo   opera y el nombre coincide con el nuestro
    otro_negocio     opera pero con otro nombre: el local se dio vuelta
    cerrado          Places lo marca CLOSED_PERMANENTLY
    sin_dato         no hay nada en esa dirección, o no tenemos nombre
                     para desempatar. **No es un cierre**: es no saber

Dos cuidados de costo, porque esto se factura por llamada:

- Cada respuesta se cachea en disco por trámite. Volver a correr no vuelve a
  facturar, y se puede cortar y retomar.
- `consultar(n=...)` limita cuántas se piden. Conviene arrancar con 200 y mirar
  la salida antes de pagar la muestra entera.

La clave se lee de `pipeline/.env` y no se escribe en ningún log.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import unicodedata
from pathlib import Path

import polars as pl
import requests

from . import config, validacion

log = logging.getLogger(__name__)

URL = "https://places.googleapis.com/v1/places:searchText"
VARIABLE_CLAVE = "GOOGLE_PLACES_API_KEY"

# Solo estos campos. El field mask determina el SKU que se factura, así que
# pedir de más cuesta plata sin agregar nada: businessStatus ya obliga al tier
# Pro, y displayName y formattedAddress viajan en el mismo tier.
CAMPOS = "places.displayName,places.businessStatus,places.formattedAddress"

# Caja de ~70 m alrededor del punto del trámite. `locationRestriction` en Text
# Search solo acepta rectángulo (el círculo es de `locationBias`, que sugiere en
# vez de restringir). Sin esta caja la búsqueda por dirección devuelve negocios
# parecidos a cuadras de distancia: pedirle "9 de Julio 1333" sin restringir
# devuelve farmacias de otras tres calles.
GRADOS_LAT = 0.00063
GRADOS_LON = 0.00074

TIMEOUT = 30
PAUSA = 0.06  # ~16 req/s, muy por debajo de cualquier límite de la API
REINTENTOS = 3

SEMILLA_ORDEN = 11
ARCHIVO_CACHE = "places_cache.jsonl"
ARCHIVO_RESULTADO = "places_resultado.csv"

# Palabras que aparecen en cualquier cartel y no identifican a nadie.
# Dos nombres cuyas palabras largas comparten este prefijo se toman por el
# mismo local ("goldbody"/"gold", "buche"/"bucheando").
LARGO_PREFIJO = 5

GENERICAS = {
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "y",
    "sa",
    "srl",
    "s",
    "a",
    "r",
    "l",
    "casa",
    "centro",
    "local",
    "comercial",
    "don",
    "dona",
    "san",
    "santa",
    # Genéricas del rubro: aparecen en un cartel de cada tres y harían pasar por
    # el mismo negocio a "Super Matanza" y "Supermercado José Hernández".
    "super",
    "supermercado",
    "mercado",
    "minimercado",
    "market",
    "mini",
    "kiosco",
    "quiosco",
    "almacen",
    "despensa",
    "autoservicio",
    "tienda",
}


def _clave() -> str:
    if clave := os.environ.get(VARIABLE_CLAVE):
        return clave
    archivo = config.RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            if linea.startswith(f"{VARIABLE_CLAVE}=") and (valor := linea.split("=", 1)[1].strip()):
                return valor
    raise RuntimeError(
        f"Falta {VARIABLE_CLAVE}. Ponela en {archivo} (ese archivo está gitignoreado):\n"
        f'  read -s -p "API key: " K && echo "{VARIABLE_CLAVE}=$K" >> {archivo} && unset K'
    )


def _plano(texto: str | None) -> str:
    """Minúsculas y sin acentos."""
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _normalizar(texto: str | None) -> set[str]:
    """Palabras significativas de un nombre comercial, para poder compararlo."""
    return {p for p in re.split(r"[^a-z0-9]+", _plano(texto)) if len(p) > 2 and p not in GENERICAS}


def es_direccion(nombre: str | None) -> bool:
    """¿Places devolvió una dirección en vez del nombre de un negocio?

    Cuando en el punto no hay ningún comercio indexado, Text Search igual
    contesta con el resultado geocodificado y su `displayName` es la dirección:
    "Manuel Cardeñosa 4513 Loc 2", "Buenos Aires 478, nueva cordoba". Leerlo
    como el nombre de un negocio lo convertía en un `otro_negocio` inventado, que
    es justo el caso que decide si nuestro proxy acertó. Es no saber.
    """
    if not nombre:
        return True
    # Una altura de calle en Córdoba son 3 a 5 dígitos. Se exige ese largo para
    # no confundir un nombre comercial que lleva un número corto ("Kiosco 24").
    return bool(re.search(r"\b\d{3,5}\b", nombre))


def _pegar(texto: str | None) -> str:
    """El nombre entero sin espacios ni signos, conservando el orden."""
    return (
        "".join(sorted(_normalizar(texto), key=lambda p: 0))
        if False
        else "".join(re.findall(r"[a-z0-9]+", _plano(texto)))
    )


def mismo_negocio(nuestro: str | None, de_places: str | None) -> bool | None:
    """¿Los dos nombres son del mismo local? `None` si no se puede decidir.

    Los carteles se escriben distinto en cada registro, así que la comparación
    es tolerante a propósito. Con igualdad exacta no coincidiría casi nunca, y
    con tokens sueltos se escapan casos obvios:

        "Gold Body"  vs "Goldbody Supplements"   -> el mismo, pegado
        "AL BUCHE"   vs "BUCHEANDO"              -> el mismo, derivado
        "Eric"       vs "Drugstore Eric"         -> el mismo, con rubro adelante

    Se acepta si comparten una palabra distintiva, si una cadena entera está
    contenida en la otra al sacarle los espacios, o si dos palabras largas
    comparten prefijo.
    """
    a, b = _normalizar(nuestro), _normalizar(de_places)
    if not a or not b:
        return None
    if a & b:
        return True

    # Sobre el texto entero y en su orden original: "gold body" se pega como
    # "goldbody" y aparece dentro de "goldbodysupplements". Ordenar las palabras
    # rompería justamente ese caso.
    pegado_a, pegado_b = _pegar(nuestro), _pegar(de_places)
    if pegado_a and pegado_b and (pegado_a in pegado_b or pegado_b in pegado_a):
        return True

    return any(
        x[:LARGO_PREFIJO] == y[:LARGO_PREFIJO]
        for x in a
        for y in b
        if len(x) >= LARGO_PREFIJO and len(y) >= LARGO_PREFIJO
    )


def _consultar_una(sesion: requests.Session, clave: str, fila: dict) -> dict:
    """Una llamada a Text Search, restringida al rectángulo de la dirección."""
    cuerpo = {
        "textQuery": f"{fila['domicilio_loc'].strip()}, Córdoba, Argentina",
        "languageCode": "es",
        "maxResultCount": 5,
        "locationRestriction": {
            "rectangle": {
                "low": {
                    "latitude": fila["lat"] - GRADOS_LAT,
                    "longitude": fila["lon"] - GRADOS_LON,
                },
                "high": {
                    "latitude": fila["lat"] + GRADOS_LAT,
                    "longitude": fila["lon"] + GRADOS_LON,
                },
            }
        },
    }
    cabeceras = {
        "X-Goog-Api-Key": clave,
        "X-Goog-FieldMask": CAMPOS,
        "Content-Type": "application/json",
    }

    for intento in range(REINTENTOS):
        r = sesion.post(URL, json=cuerpo, headers=cabeceras, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            espera = 2 ** (intento + 1)
            log.warning("Places respondió %s; reintento en %ss", r.status_code, espera)
            time.sleep(espera)
            continue
        # 400/403 no se arreglan reintentando: la clave, la facturación o el
        # cuerpo están mal, y seguir solo gasta llamadas.
        raise RuntimeError(f"Places devolvió {r.status_code}: {r.text[:300]}")
    raise RuntimeError("Places no respondió después de los reintentos.")


def _interpretar(respuesta: dict, fila: dict) -> dict:
    """Traduce la respuesta al estado observado del local.

    Se miran **todos** los lugares devueltos, no solo el primero. En una misma
    dirección conviven varios comercios —galerías, edificios, esquinas— y Places
    ordena por prominencia: el primero puede ser el colegio o la playa de
    estacionamiento del edificio mientras nuestro kiosco es el cuarto. Mirar
    solo el primero contaba esos casos como "otro negocio", que es exactamente
    el error que haría parecer peor al proxy de lo que es.
    """
    lugares = respuesta.get("places") or []
    if not lugares:
        return {"observado": "sin_dato", "detalle": "sin resultados en la dirección"}

    nuestro = fila.get("nombrefantasia")
    candidatos = [
        ((lugar.get("displayName") or {}).get("text"), lugar.get("businessStatus"))
        for lugar in lugares
    ]

    # Si alguno de los lugares de la dirección es el nuestro, esa es la respuesta,
    # esté donde esté en el ranking.
    for nombre, estado in candidatos:
        if mismo_negocio(nuestro, nombre):
            return {
                "observado": "cerrado" if estado == "CLOSED_PERMANENTLY" else "sigue_el_mismo",
                "nombre_places": nombre,
                "detalle": estado or "",
            }

    # Ninguno es el nuestro. El primero decide si sabemos algo o no.
    nombre, estado = candidatos[0]
    if estado == "CLOSED_PERMANENTLY":
        return {"observado": "cerrado", "nombre_places": nombre, "detalle": estado}
    if es_direccion(nombre):
        return {
            "observado": "sin_dato",
            "nombre_places": nombre,
            "detalle": "Places devolvió una dirección, no un negocio",
        }
    if mismo_negocio(nuestro, nombre) is None:
        return {
            "observado": "sin_dato",
            "nombre_places": nombre,
            "detalle": "opera, pero sin nombre para desempatar",
        }
    return {"observado": "otro_negocio", "nombre_places": nombre, "detalle": estado or ""}


def _cache() -> tuple[Path, dict[int, dict]]:
    ruta = config.DIR_PROCESADO / ARCHIVO_CACHE
    guardado: dict[int, dict] = {}
    if ruta.exists():
        for linea in ruta.read_text().splitlines():
            if linea.strip():
                fila = json.loads(linea)
                guardado[fila["ultimo_tramite"]] = fila["respuesta"]
    return ruta, guardado


def consultar(n: int | None = None) -> pl.DataFrame:
    """Consulta la muestra y devuelve el estado observado de cada local.

    Lo ya consultado sale del cache y no se vuelve a facturar.
    """
    archivo = config.DIR_PROCESADO / validacion.ARCHIVO
    if not archivo.exists():
        raise FileNotFoundError(f"Falta {archivo}. Corré `python -m viabilidad muestra`.")
    muestra = pl.read_csv(archivo)

    ruta_cache, guardado = _cache()
    pendientes = [f for f in muestra.to_dicts() if f["ultimo_tramite"] not in guardado]
    # La muestra viene ordenada por estado y grupo, así que cortar por `n` sobre
    # ese orden traería una sola clase y la corrida parcial no diría nada.
    # Barajado con semilla fija para que retomar siga el mismo orden.
    random.Random(SEMILLA_ORDEN).shuffle(pendientes)
    if n is not None:
        pendientes = pendientes[:n]

    log.info(
        "%s en cache, %s a consultar (de %s en la muestra)",
        f"{len(guardado):,}",
        f"{len(pendientes):,}",
        f"{len(muestra):,}",
    )

    if pendientes:
        clave = _clave()
        config.DIR_PROCESADO.mkdir(parents=True, exist_ok=True)
        with requests.Session() as sesion, ruta_cache.open("a") as salida:
            for i, fila in enumerate(pendientes, 1):
                respuesta = _consultar_una(sesion, clave, fila)
                salida.write(
                    json.dumps(
                        {"ultimo_tramite": fila["ultimo_tramite"], "respuesta": respuesta},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                salida.flush()  # cortar a mitad no pierde lo ya pagado
                guardado[fila["ultimo_tramite"]] = respuesta
                if i % 50 == 0:
                    log.info("  %s/%s consultadas", i, len(pendientes))
                time.sleep(PAUSA)

    # Se interpreta acá y no al consultar: el cache guarda la respuesta cruda,
    # así que corregir el clasificador —que ya hizo falta tres veces— no cuesta
    # una llamada más.
    observadas = pl.DataFrame(
        [
            {
                "ultimo_tramite": f["ultimo_tramite"],
                **_interpretar(guardado[f["ultimo_tramite"]], f),
            }
            for f in muestra.to_dicts()
            if f["ultimo_tramite"] in guardado
        ]
    )
    return muestra.join(observadas, on="ultimo_tramite", how="inner")


# Plaza San Martín. Sirve para partir la ciudad en anillos sin traer geometría.
CENTRO = (-64.1810, -31.4167)
KM_POR_GRADO_LON = 88.5
KM_POR_GRADO_LAT = 111.3


def estructura_espacial(r: pl.DataFrame) -> pl.DataFrame:
    """¿El proxy falla más en unas zonas que en otras? Es el chequeo que decide.

    Que el objetivo sea ruidoso no impide modelar: un error de medición repartido
    parejo atenúa los efectos estimados hacia cero, o sea cuesta potencia, no
    validez. Y potencia sobra con 62.560 períodos.

    Lo que sí rompería un score de localización es que el error esté **ligado al
    lugar**. Si el permiso vencido sin cerrar fuera más común en la periferia,
    el mapa mediría formalidad administrativa y no supervivencia comercial, y
    toda zona informal saldría mal puntuada por un artefacto.

    Ojo con no confundirlo con la cobertura de Places, que sí varía con la
    distancia: eso limita dónde podemos *verificar*, no dónde el proxy acierta.
    """
    con_km = r.with_columns(
        (
            ((pl.col("lon") - CENTRO[0]) * KM_POR_GRADO_LON) ** 2
            + ((pl.col("lat") - CENTRO[1]) * KM_POR_GRADO_LAT) ** 2
        )
        .sqrt()
        .alias("km_al_centro")
    )
    util = con_km.filter(pl.col("observado") != "sin_dato").with_columns(
        (
            ((pl.col("estado_predicho") == "cerrado") & (pl.col("observado") != "sigue_el_mismo"))
            | ((pl.col("estado_predicho") == "abierto") & (pl.col("observado") == "sigue_el_mismo"))
        )
        .cast(pl.Int8)
        .alias("acierto")
    )
    anillos = util.with_columns(
        pl.col("km_al_centro").qcut(4, labels=["0 centro", "1", "2", "3 periferia"]).alias("anillo")
    )
    return (
        anillos.group_by("anillo")
        .agg(
            pl.len().alias("n"),
            pl.col("km_al_centro").median().round(1).alias("km_mediana"),
            pl.col("acierto").mean().round(3).alias("exactitud"),
        )
        .sort("anillo")
    )


def calibrar(r: pl.DataFrame) -> pl.DataFrame:
    """Matriz de confusión: lo que predecimos contra lo que se observa.

    `sin_dato` queda aparte y no se cuenta como acierto ni como error. Meterlo
    de un lado sería el mismo error que rellenar la censura como cierre.
    """
    return (
        r.group_by("estado_predicho", "observado")
        .len()
        .pivot("observado", index="estado_predicho", values="len")
        .fill_null(0)
        .sort("estado_predicho")
    )


def techo_auc(r: pl.DataFrame) -> dict[str, float]:
    """El AUC máximo que cualquier modelo puede sacar contra nuestra etiqueta.

    La etiqueta que el modelo aprende no es la verdad: es un proxy con error
    medido. Eso pone un techo que ninguna feature puede romper, y saberlo cambia
    qué conviene hacer después — si estamos lejos del techo falta señal, y si
    estamos cerca lo que falta es un objetivo mejor, no más variables.

    El cálculo sale de la tabla de calibración. Para un predictor binario,
    AUC = (sensibilidad + especificidad) / 2, y el AUC es simétrico entre las
    dos variables: **lo bien que nuestra etiqueta predice la verdad es lo mismo
    que lo bien que la verdad predeciría nuestra etiqueta**. O sea que un modelo
    capaz de adivinar el desenlace real, medido contra nuestra etiqueta, no
    pasaría de ese número.

    Tres salvedades, porque el número es fuerte y conviene no sobrevenderlo:

    - Toma a Places como verdad, y Places tiene su propio error.
    - La etiqueta de la calibración (el permiso venció sin renovar) no es
      idéntica a la del modelo (duró más que el primer vencimiento), aunque
      están muy pegadas.
    - Es el techo para predecir **la etiqueta ruidosa**. La capacidad real del
      modelo sobre el desenlace verdadero es probablemente mayor, pero con este
      objetivo no hay forma de medir cuánto.
    """
    util = r.filter(pl.col("observado") != "sin_dato").with_columns(
        (pl.col("observado") == "sigue_el_mismo").alias("_verdad"),
        (pl.col("estado_predicho") == "abierto").alias("_etiqueta"),
    )
    a = util.filter(pl.col("_etiqueta") & pl.col("_verdad")).height
    b = util.filter(pl.col("_etiqueta") & ~pl.col("_verdad")).height
    c = util.filter(~pl.col("_etiqueta") & pl.col("_verdad")).height
    d = util.filter(~pl.col("_etiqueta") & ~pl.col("_verdad")).height
    if not (a + c) or not (b + d):
        raise ValueError("Falta una de las dos clases observadas; no hay techo que estimar.")

    sensibilidad = a / (a + c)
    especificidad = d / (b + d)
    return {
        "sensibilidad": sensibilidad,
        "especificidad": especificidad,
        "techo_auc": (sensibilidad + especificidad) / 2,
    }


def ejecutar(n: int | None = None) -> pl.DataFrame:
    r = consultar(n=n)
    print(f"\n{'=' * 72}\n  Calibración del proxy contra Google Places\n{'=' * 72}")
    print(f"\n{len(r):,} locales consultados.\n")

    with pl.Config(tbl_hide_dataframe_shape=True, fmt_str_lengths=20):
        print(calibrar(r))

    util = r.filter(pl.col("observado") != "sin_dato")
    if util.is_empty():
        log.error("Ninguna consulta pudo desempatarse: no hay nada que calibrar todavía.")
        return r

    cerrados = util.filter(pl.col("estado_predicho") == "cerrado")
    abiertos = util.filter(pl.col("estado_predicho") == "abierto")
    print(f"\nDe {len(util):,} con dato utilizable ({len(r) - len(util):,} sin dato):")
    if not cerrados.is_empty():
        ok = cerrados.filter(pl.col("observado").is_in(["cerrado", "otro_negocio"])).height
        print(
            f"  predichos CERRADOS: {ok:,}/{len(cerrados):,} confirmados ({ok / len(cerrados):.1%})"
        )
    if not abiertos.is_empty():
        ok = abiertos.filter(pl.col("observado") == "sigue_el_mismo").height
        print(
            f"  predichos ABIERTOS: {ok:,}/{len(abiertos):,} confirmados ({ok / len(abiertos):.1%})"
        )

    anillos = estructura_espacial(r)
    print("\n¿El proxy falla más en unas zonas que en otras?")
    with pl.Config(tbl_hide_dataframe_shape=True):
        print(anillos)
    brecha = anillos["exactitud"].max() - anillos["exactitud"].min()
    if brecha > 0.15:
        log.error(
            "La exactitud del proxy varía %.0f puntos entre el centro y la periferia. "
            "El objetivo está ligado al lugar: un score de localización construido "
            "sobre esto mide formalidad administrativa, no supervivencia.",
            brecha * 100,
        )
    else:
        print(
            f"  Brecha centro-periferia: {brecha:.1%}. El error del objetivo no está\n"
            "  ligado al lugar, así que atenúa los efectos espaciales pero no los sesga."
        )

    techo = techo_auc(r)
    print(
        f"\nTecho de AUC que impone el ruido del objetivo: {techo['techo_auc']:.3f}\n"
        f"  (sensibilidad {techo['sensibilidad']:.3f}, "
        f"especificidad {techo['especificidad']:.3f})\n"
        "  Un modelo que adivinara el desenlace real no sacaría más que eso\n"
        "  medido contra nuestra etiqueta. No es una meta: es el límite."
    )

    salida = config.DIR_PROCESADO / ARCHIVO_RESULTADO
    r.write_csv(salida)
    print(f"\nEscrito en {salida}")
    return r
