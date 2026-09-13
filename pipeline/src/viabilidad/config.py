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
# ambos, más variantes con doble espacio. Las reglas que los agrupan están en
# rubros.py y el resultado en referencia/mapeo_rubros.csv.

# Para normalizar: polars no trae unicodedata, se hace con un mapa de reemplazo.
ACENTOS = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}

# --- Salidas ----------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[3]
DIR_DATOS = RAIZ / "data"
DIR_CRUDO = DIR_DATOS / "crudo"
DIR_PROCESADO = DIR_DATOS / "procesado"

# Tablas de referencia chicas que sí se versionan: son el insumo para decidir
# el mapeo de rubros y conviene verlas en el diff cuando cambian.
DIR_REFERENCIA = Path(__file__).resolve().parents[2] / "referencia"
