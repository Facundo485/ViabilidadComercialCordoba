"""Configuración del pipeline: fuentes de datos y parámetros del dominio."""

import os
from pathlib import Path

# --- Fuente: GIS de la Municipalidad de Córdoba -----------------------------
# Ojo: el servicio se llama "ComerdioIndustria" (sic, falta la "c" de Comercio).
# Está mal escrito en el origen; no lo corrijas o deja de resolver.
GIS_BASE = (
    "https://gis.cordoba.gob.ar/server/rest/services"
    "/ComerdioIndustria/Hist%C3%B3rico_Habilitaciones/FeatureServer"
)

CAPA_PARCELAS = 0  # puntos, un registro por parcela con los conteos agregados
TABLA_HISTORIAL = 1  # un registro por trámite Y rubro: rubro, fechas, id_tramite

# El histórico declara `cuitempresa` y `razonsocial` pero las devuelve nulas en
# el 100% de las filas, igual que `vigente`. Sin titular no se pueden encadenar
# las renovaciones, que es lo único que distingue a un comercio que sobrevive
# de uno cuyo permiso simplemente venció.
#
# Este otro servicio del mismo GIS sí las trae pobladas: 71.287 registros, cero
# nulos, y su campo `id` matchea `id_tramite` del histórico en los 71.287. Es
# una fila por trámite, así que también es la unidad de conteo correcta.
GIS_BASE_VISTA = (
    "https://gis.cordoba.gob.ar/server/rest/services"
    "/ComerdioIndustria/Habilitaciones_Comerciales_Vista/FeatureServer"
)
CAPA_TRAMITES = 0  # una fila por trámite, con titular, barrio, CPC y superficies

# Campos de la vista que vale la pena guardar. El resto son de geocodificación
# (loc_name, score, status) o repiten lo que ya está en el histórico.
CAMPOS_TRAMITE = [
    "id",
    "nrocatastral",
    "cuitempresa",
    "barrio",
    "cpc",
    "riesgo",
    "superficietotal",
    "superficiecubierta",
    "superficiedeposito",
    # Dirección y punto del local. La dirección comercial es pública (está en el
    # GIS) y hace falta para poder cruzar contra fuentes externas; el punto es
    # del trámite, más fino que el centroide de la parcela (lon/lat salen de la
    # geometría, no de los campos `x`/`y`, que la capa expone vacíos).
    "calle",
    "numero",
    "domicilio_loc",
    # El nombre comercial del local. Es el cartel de la vereda, no un dato de
    # persona, y es lo único que permite distinguir "el local cambió de dueño"
    # de "el mismo negocio sigue con el permiso vencido" cuando se cruza contra
    # una fuente externa. Se compara localmente: no sale del pipeline.
    "nombrefantasia",
    "lon",
    "lat",
]

# El servidor declara maxRecordCount=2000 pero acepta hasta standardMaxRecordCount.
PAGE_SIZE = 32_000
PAGE_SIZE_FALLBACK = 2_000

# --- Datos personales -------------------------------------------------------
# `cuitempresa` identifica personas: en un monotributista el CUIT sale del DNI y
# la razón social suele ser su nombre. Para encadenar renovaciones alcanza con
# que el identificador sea estable, no hace falta que sea legible, así que al
# ingestar se reemplaza por un hash y `razonsocial` directamente no se guarda.
#
# Es seudonimización, no anonimización: el espacio de CUITs es chico y un hash
# con sal conocida se invierte por fuerza bruta. Lo que evita es que el número
# quede escrito en claro en los parquet. La protección real sigue siendo que
# `data/` no se versiona y que todo lo que se publica va agregado.
#
# La sal se puede fijar por entorno para que el hash no sea reproducible fuera
# de esta máquina; el default deja el pipeline corriendo de cero sin configurar.
SAL_CUIT = os.environ.get("VIABILIDAD_SAL_CUIT", "viabilidad-cordoba")
LARGO_HASH_CUIT = 8  # bytes, 16 hex. De sobra para 47k titulares sin colisiones.

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
# Todo cuelga de pipeline/, no de la raíz del repo.
RAIZ = Path(__file__).resolve().parents[2]
DIR_DATOS = RAIZ / "data"
DIR_CRUDO = DIR_DATOS / "crudo"
DIR_PROCESADO = DIR_DATOS / "procesado"

# Tablas de referencia chicas que sí se versionan: son el insumo para decidir
# el mapeo de rubros y conviene verlas en el diff cuando cambian.
DIR_REFERENCIA = RAIZ / "referencia"
