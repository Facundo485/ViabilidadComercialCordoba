"""Configuración del pipeline: fuentes de datos y parámetros del dominio."""

from pathlib import Path

# --- Fuente: GIS de la Municipalidad de Córdoba -----------------------------
# Ojo: el servicio se llama "ComerdioIndustria" (sic, falta la "c" de Comercio).
# Está mal escrito en el origen; no lo corrijas o deja de resolver.
GIS_BASE = (
    "https://gis.cordoba.gob.ar/server/rest/services"
    "/ComerdioIndustria/Hist%C3%B3rico_Habilitaciones/FeatureServer"
)

CAPA_PARCELAS = 0  # puntos, un registro por parcela con los conteos agregados
TABLA_HISTORIAL = 1  # un registro por habilitación: rubro, fechas, titular

# El servidor declara maxRecordCount=2000 pero acepta hasta standardMaxRecordCount.
PAGE_SIZE = 32_000
PAGE_SIZE_FALLBACK = 2_000

# --- Limpieza ---------------------------------------------------------------
# La capa declara un extent de -180/180/90: hay puntos con coordenadas corruptas.
# Todo lo que caiga afuera de este bbox se descarta al ingestar.
BBOX_CORDOBA = {"lon_min": -64.35, "lon_max": -64.05, "lat_min": -31.55, "lat_max": -31.25}

# --- Dominio ----------------------------------------------------------------
# Los primeros tres segmentos de nro_catastral ("01-01-001-007") son la manzana.
LARGO_ID_MANZANA = 9

# El campo `rubronombre` mezcla dos nomencladores: el municipal viejo (Título,
# con acentos) y el CLANAE/CIIU nuevo (MAYÚSCULAS). El mismo concepto aparece en
# ambos, más variantes con doble espacio. Por eso todo se compara normalizado:
# minúsculas, sin acentos, espacios colapsados.

# Se descartan antes de clasificar: no son comercios a la calle y contaminarían
# el modelo (un distribuidor mayorista de medicamentos no es una farmacia).
EXCLUSIONES = r"por mayor|mayorista|fabricacion|reparacion|\bdeposito"

# Rubros del MVP. Se evalúan en orden y gana el primero que matchea, así que los
# específicos van antes que los amplios. Los patrones son regex sobre el nombre
# normalizado; \b evita falsos positivos por substring (sin él "bar" matchea
# "barnices" y una pinturería termina clasificada como cafetería).
RUBROS = {
    "farmacia": {
        "incluye": r"farmacia|productos farmaceuticos|medicamentos de uso humano",
        "excluye": r"veterinari|asesoramiento|laboratorio",
    },
    "kiosco": {
        "incluye": r"kiosco|quiosco|polirrubro|drugstore",
    },
    "ferreteria": {
        "incluye": (
            r"ferreteria|pinturer|\bpinturas\b|\bsanitarios\b"
            r"|materiales de construccion|herramientas|materiales electricos"
        ),
    },
    "indumentaria": {
        "incluye": (
            r"prendas de vestir|prendas y accesorios|indumentaria|calzado"
            r"|zapateria|zapatilleria|marroquineria|\bropa\b|boutique|lenceria"
        ),
    },
    "cafeteria": {
        "incluye": (
            r"\bbar\b|\bbares\b|cafeteria|\bcafes?\b|confiteria|restaurant"
            r"|cantina|pizzeria|heladeria|cerveceria|lomiteria|empanaderia|parrilla"
            r"|expendio de comidas|expendio de bebidas|preparacion de comidas"
            r"|salon de te|casa de te"
        ),
        # "productos de confitería" es venta de golosinas, no una confitería.
        "excluye": r"productos de confiteria|articulos para bar",
    },
}

# Para normalizar: polars no trae unicodedata, se hace con un mapa de reemplazo.
ACENTOS = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}

# --- Salidas ----------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[3]
DIR_DATOS = RAIZ / "data"
DIR_CRUDO = DIR_DATOS / "crudo"
DIR_PROCESADO = DIR_DATOS / "procesado"

# Tablas de referencia chicas que sí se versionan: son el insumo para decidir
# el mapeo de RUBROS y conviene verlas en el diff cuando cambian.
DIR_REFERENCIA = Path(__file__).resolve().parents[2] / "referencia"
