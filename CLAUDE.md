# CLAUDE.md — Contexto del proyecto

> **¿Sesión nueva? Empezá por [`docs/retomar.md`](docs/retomar.md):** dice en
> qué paso está el proyecto, qué comando correr y qué mirar en la salida.

## Qué es este proyecto

Plataforma que asigna un **score de viabilidad comercial** a ubicaciones urbanas. Responde dos preguntas:

1. ¿Qué tan probable es que un negocio de rubro X sobreviva en esta ubicación?
2. Dado un local vacío, ¿qué rubro tiene mayor probabilidad de éxito ahí?

**Ciudad piloto:** Córdoba Capital. **Expansión prevista:** Buenos Aires (CABA).

El roadmap completo está en `docs/roadmap.md`. Leerlo antes de proponer cambios de alcance.

---

## Historia de decisiones (importante — no revertir sin discutir)

**La idea original era un mapa de tráfico y densidad de personas en tiempo real.** Se descartó el tiempo real por restricciones de datos reales:

- Los satélites de observación terrestre están en órbita LEO, no geoestacionaria. Sentinel-2 pasa por un mismo punto cada ~5 días, con resolución de 10m. No sirve para observar tráfico ni personas en vivo.
- La densidad poblacional en tiempo real solo se consigue vía datos agregados de operadoras móviles: caro e inaccesible sin tracción comercial previa.

**El pivot a scoring de localización comercial resolvió el problema:** un negocio se instala una vez y permanece años, así que lo relevante son patrones históricos, no el instante actual. Esos datos sí están disponibles y son gratuitos.

**Consecuencia:** el satélite pasa de ser el núcleo del producto a ser una capa de refinamiento (desagregación de densidad poblacional y detección de crecimiento urbano). No proponer volver al tiempo real.

**La ciudad piloto pasó de CABA a Córdoba.** El roadmap original ponía a CABA
primero y a Córdoba en Fase 5, condicionada a un pedido de acceso a información
pública. Se invirtió al encontrar que Córdoba publica las habilitaciones con
fecha de alta, vencimiento, rubro y coordenadas, sin trámite (ver más abajo).
Eso resuelve hoy la variable objetivo, que en CABA sigue sin confirmarse. CABA
pasa a ser la prueba de transferibilidad entre ciudades.

Razón secundaria pero real: el autor vive en Córdoba y puede validar el score
contra su propio conocimiento de la ciudad. Un score sin nadie que pueda mirar
el mapa y decir "esa esquina no da" es un número que nadie audita.

---

## Decisiones técnicas críticas

### 1. Validación espacial, no aleatoria
Los locales vecinos están espacialmente autocorrelacionados. Un split aleatorio deja vecinos en train y test simultáneamente, inflando las métricas de forma engañosa.

**Regla:** particionar por barrio/comuna. Además, validación temporal (entrenar con años anteriores a un corte, testear con posteriores).

### 2. Análisis de supervivencia, no clasificación binaria
Un local abierto hace 6 meses que sigue activo no es "éxito" ni "fracaso" — es un **dato censurado a la derecha**.

**Regla:** usar Kaplan-Meier y modelos de Cox (`lifelines`) como enfoque principal. XGBoost puede complementar, pero no debe ser el único modelo: no maneja censura correctamente.

### 3. La competencia no es lineal
Pocos competidores puede indicar mercado inexistente; muchos, saturación; un nivel intermedio suele reflejar aglomeración beneficiosa (clusters que atraen demanda).

**Regla:** modelar la densidad de competencia esperando una relación en U invertida. No asumir monotonicidad.

### 4. Causalidad
El modelo es **predictivo, no causal**. Que una zona tenga cafés exitosos no prueba que un café nuevo vaya a funcionar. Documentar esta limitación explícitamente en el README y en la salida del producto.

---

## La variable objetivo (resuelto)

Era el problema abierto que definía si el proyecto podía ser predictivo. **Está
resuelto, y por el Plan A.**

El GIS de la Municipalidad de Córdoba publica un `FeatureServer` de ArcGIS con
el histórico completo de habilitaciones, sin trámite:

```
https://gis.cordoba.gob.ar/server/rest/services/ComerdioIndustria/Histórico_Habilitaciones/FeatureServer
```

(El nombre del servicio está mal escrito en el origen: `ComerdioIndustria`. No
corregirlo.)

| Capa | Contenido |
|---|---|
| `0` — Habilitaciones Históricas | Un punto por parcela, con `hab_total`, `hab_vigentes`, `hab_novigentes`. WGS84 nativo |
| `1` — Historial Habilitaciones | Un registro por **trámite y rubro**: `rubronombre`, `fechahabaprobada`, `fechavencimientohab`, `id_tramite` |

Se unen por `nro_catastral`. Cobertura: **2014-01-02 a 2026-09-02**, 144.743
filas sobre 7.533 manzanas. La capa se recarga completa y está al día.

**Las filas no son habilitaciones.** Son **71.287 trámites**: un trámite habilita
varios rubros a la vez (media 2,03, máximo 73) y aparece una vez por cada uno.
La unidad de conteo es `id_tramite`. Los conteos de la Fase 1 estaban inflados
al doble por no haber chequeado esto.

**`cuitempresa` y `razonsocial` vienen nulas en el 100% de las filas** de la
tabla 1, igual que `vigente`: el schema las declara y nadie las popula. Sin
titular no se pueden encadenar renovaciones, que es lo único que distingue a un
comercio que sobrevive. El titular sale de otro servicio del mismo GIS:

```
https://gis.cordoba.gob.ar/server/rest/services/ComerdioIndustria/Habilitaciones_Comerciales_Vista/FeatureServer
```

Su capa `0` es una fila por trámite, con `cuitempresa` poblada (cero nulos,
46.767 titulares), y su campo `id` matchea `id_tramite` del histórico en los
71.287. Trae además `barrio`, `cpc`, `riesgo` y las superficies. El ingest la
baja y hashea el CUIT antes de escribirlo.

**Cómo se define la supervivencia.** La columna `vigente` de la tabla 1 viene
nula en el 100% de las filas: el schema la declara pero nadie la popula. Se
deriva de `fechavencimientohab`: el permiso sigue vigente si todavía no venció.

Esa derivación está validada de forma cruzada. La capa 0 reporta una tasa de
supervivencia de ciudad de 33,1% con sus propios conteos precalculados; la
derivación desde las fechas de la tabla 1, sin mirar esos conteos, da ~33%. Dos
fuentes independientes, el mismo número.

**El municipio no registra los cierres, y no es un olvido.** Un cierre es un
no-evento: nadie va a avisar que cerró. Se revisó toda la fuente y no hay dónde
buscarlos — `activa` y `tarjeta_activa` de la vista vienen nulas en el 100%,
`idtipotramite` es la categoría de riesgo y no alta/baja, `status` es del
geocodificador, el servicio de evolución solo cuenta altas, y ninguno de los 183
datasets del portal abierto tiene bajas ni ceses. Por eso `vigente` está sin
poblar: el campo existe, el trámite que lo llenaría no.

Tampoco alcanza con mirar quién habilitó después en la misma dirección: de
37.146 sucesiones de titular en una parcela, 32.325 se solapan más de seis meses
(son locales que conviven, no un relevo). Afinando a calle y altura, o a
superficie, quedan menos todavía.

La consecuencia es que el evento observable sigue siendo **si renovó**. Su
calidad **está medida**, no asumida: `validacion.py` arma la muestra y
`places.py` la consulta contra Google Places, que sí publica `businessStatus`
por local.

**Resultado de la calibración** (1.498 locales, 895 con dato utilizable):

| | |
|---|---|
| Exactitud del proxy | **61,0%** |
| Línea base (predecir siempre la clase mayoritaria) | 55,3% |
| Odds ratio | 2,40 |
| Significación | p = 2,1e-10 |

**El proxy tiene señal real pero es ruidoso.** Predecir "cerró" duplica largo
las chances de que en esa dirección hoy opere otro negocio, y eso no es azar con
n=895. Pero está lejos de ser un objetivo limpio: uno de cada tres casos
utilizables va para el otro lado.

Es un **piso**, no la calidad verdadera, porque la medición arrastra error
propio: un local puede cambiar de nombre sin cerrar, el nombre de fantasía del
GIS puede estar viejo, y Places no indexa todo (603 de 1.498 quedaron sin dato).

**Qué implica para el producto.** El modelo tiene techo: no se puede prometer
precisión por local que el objetivo no sostiene. El score se presenta agregado
—manzana y rubro, donde el ruido promedia— y la limitación se declara junto al
número. Esto no invalida el enfoque: el permiso sigue siendo el mejor proxy
disponible y es el criterio del propio municipio.

**Limitaciones a declarar en el producto:**

- Permiso vigente no es lo mismo que local abierto. Alguien puede cerrar sin dar
  de baja, o seguir operando con el permiso vencido. Es un proxy, el mejor
  disponible, consistente con el criterio del propio municipio.
- Los permisos duran ~5 años. Una habilitación aprobada hace menos de eso
  todavía no tuvo oportunidad de vencer: es censura a derecha, no éxito. Tratarla
  como éxito infla las zonas con aperturas recientes.
- Nunca rellenar la vigencia nula con cero. Convierte "no sé" en "cerró" y sesga
  el modelo hacia abajo. Ya pasó una vez y produjo una tabla de resultados con
  ceros en las 76 categorías sin que nada fallara.

**Datos personales.** `cuitempresa` y `razonsocial` identifican personas: en un
monotributista el CUIT sale del DNI y la razón social suele ser su nombre. El
ingest reemplaza el CUIT por un hash (`titular`) antes de escribir nada a disco
y no descarga `razonsocial`. Es seudonimización, no anonimización —el espacio de
CUITs es chico— así que la protección real sigue siendo que `data/` no se
versiona y que todo lo que se publica va agregado: el mapa habla de manzanas y
rubros, nunca de titulares.

## Taxonomía de rubros (resuelto para Córdoba)

`rubronombre` trae **1377 valores distintos**: dos nomencladores mezclados, el
municipal viejo (Título, con acentos) y el CLANAE/CIIU nuevo (MAYÚSCULAS), con
variantes del mismo concepto que a veces solo difieren en un espacio doble.

Se agrupan en dos niveles: **75 rubros de nivel 2** dentro de **12 grupos de
nivel 1**, que cubren el 93,3% de las habilitaciones. 71 de los 75 superan las
200 habilitaciones, que es del orden de los 100 cierres que necesita un modelo
con ~10 variables.

**Las reglas son el lugar donde se corrige, no el CSV.** El CSV sigue siendo lo
que lee el pipeline, pero los errores que aparecieron eran sistemáticos —un
regex sin `\b` afecta a todas las variantes de una entrada— y editar filas
sueltas los deja volver en la próxima regeneración. `test_rubros.py` fija cada
cadena que rompió, y tiene además un test general que recorre el nomenclador
entero buscando reglas que matcheen a mitad de palabra: así apareció que
"cinemato**gráfica**s" caía en `fotocopias`.

El nivel 2 es donde se modela cuando hay volumen; el nivel 1 es el respaldo para
los rubros chicos, que heredan el comportamiento de su grupo en vez de quedarse
sin modelo.

| Archivo | Rol |
|---|---|
| `pipeline/src/viabilidad/rubros.py` | Las reglas que generan el mapeo |
| `pipeline/referencia/mapeo_rubros.csv` | **La fuente de verdad**, versionada y editable a mano |

El pipeline lee el CSV, no las reglas: corregir una clasificación es editar una
fila y el diff muestra qué cambió. `python -m viabilidad mapeo` lo regenera
desde las reglas y pisa las ediciones manuales.

Todo lo que cae en `industria y deposito` (mayoristas, fábricas, depósitos)
queda fuera del análisis: no son comercios a la calle.

Comparar contra la nomenclatura de CABA cuando se aborde esa ciudad: usa 843
códigos entre 2015-2018 y 423 desde 2019. Ahí cada local puede estar habilitado
bajo varios rubros a la vez — y en Córdoba también, contra lo que se creía: son
2,03 rubros por trámite en promedio.

## Fuentes de datos

### Disponibles sin trámite
| Fuente | Contenido | Acceso |
|---|---|---|
| **GIS Córdoba — Habilitaciones** | Histórico 2014-2026 con alta, vencimiento, rubro y coordenadas | `gis.cordoba.gob.ar/server/rest/services` (ArcGIS REST) |
| Datos Abiertos Córdoba | Barrios, catastro, manzanas, planeamiento urbano, escuelas, salud, CPC, espacios verdes | `gobiernoabierto.cordoba.gob.ar/api/datos-abiertos` |
| INDEC | Censo 2022 por radio censal | `geonode.indec.gob.ar` |
| OpenStreetMap | Red vial, POIs, footprints (vía `osmnx`) | — |
| ohsome (HeiGIT) | Historial de OSM: cuántos comercios había en una zona año a año | `api.ohsome.org` |
| Google Open Buildings | Footprints de edificios detectados por IA | — |
| Copernicus / Sentinel-2 | Imágenes satelitales gratuitas, archivo desde 2015 | STAC |
| VIIRS | Luces nocturnas (proxy de actividad nocturna) | — |
| BA Data | Habilitaciones CABA, inspecciones AGC | `data.buenosaires.gob.ar` |

El portal de Córdoba expone una API REST propia además de la web:
`/api/datos-abiertos/dato?size=200` lista los 183 datasets, y
`/dato/<id>/version-dato` las versiones descargables de cada uno. El campo
`periodicidad` dice cuáles se mantienen al día. Los archivos del portal para
habilitaciones están congelados en 2023; el GIS no. Usar el GIS.

Datasets del portal ya identificados como útiles: `125` manzanas catastrales
(tiempo real), `164` catastro (parcelas, tiempo real), `3011` planeamiento
urbano (zonificación), `118` barrios, `261` escuelas, `3` centros de salud,
`2993` CPC, `117` espacios verdes, `3323` puntos de wifi, `124` líneas férreas.

**La zonificación es un filtro duro, no una variable.** Hay zonas donde no se
puede habilitar un comercio: un score alto ahí no vale nada porque el municipio
no otorga el permiso. Aplicarla antes de scorear.

### Requieren gestión
| Fuente | Vía |
|---|---|
| Google Places API | Cuenta de facturación (tier gratuito). **Vuelve a hacer falta**, en otro rol: no como variable objetivo sino para *calibrar* el proxy de renovación. `businessStatus` es la única señal de cierre directa y por local que existe. Ver `validacion.py` |
| Tráfico en tiempo real | TomTom Traffic Flow: 2500 requests/día gratis, sin tarjeta. Devuelve `currentSpeed` y `freeFlowSpeed` por segmento |

Los pedidos de acceso a información pública a la Municipalidad de Córdoba y al
EMFyC quedaron sin efecto: los datos estaban abiertos.

## Stack

| Capa | Herramientas |
|---|---|
| Datos | **polars**, geopandas, osmnx, rasterio |
| Geoespacial | PostGIS, shapely |
| ML | scikit-learn, XGBoost, lifelines, SHAP |
| Satelital | Google Earth Engine, Sentinel Hub |
| Backend | FastAPI, PostgreSQL + PostGIS |
| Frontend | React + MapLibre GL |
| Orquestación | Prefect o GitHub Actions |
| Deploy | Docker + Railway / Render |

Python 3.11+.

**polars en vez de pandas** para las transformaciones tabulares: los CSV de
habilitaciones son cientos de miles de filas y polars las procesa varias veces
más rápido y con menos memoria. geopandas sigue para lo geoespacial.

**MapLibre GL en vez de Leaflet**: son 7.533 manzanas como polígonos y Leaflet
no las dibuja con fluidez; MapLibre usa WebGL. Simplificar las geometrías antes
de servirlas — sin simplificar son varios MB y matan el navegador.

---

## Estructura del repositorio

```
React/
├── CLAUDE.md
├── docs/
│   ├── retomar.md         # por dónde seguir (leer primero)
│   ├── proximo-paso.md    # el bloqueante de la variable objetivo, en detalle
│   └── roadmap.md
└── pipeline/
    ├── pyproject.toml
    ├── referencia/            # tablas chicas, versionadas
    │   ├── rubros.csv         # nomenclador crudo del GIS
    │   └── mapeo_rubros.csv   # fuente de verdad del agrupamiento
    ├── data/                  # gitignored, lo regenera el pipeline
    │   ├── crudo/
    │   └── procesado/
    ├── src/viabilidad/
    │   ├── arcgis.py          # cliente paginado del FeatureServer
    │   ├── config.py          # fuentes, rutas, parámetros
    │   ├── rubros.py          # reglas de agrupamiento
    │   ├── mapeo.py           # genera mapeo_rubros.csv
    │   ├── ingest.py          # descarga, limpia y hashea el CUIT
    │   ├── manzanas.py        # agrega a manzana (su tasa_supervivencia está viciada)
    │   ├── resumen.py         # CSV agregados para revisar o commitear
    │   ├── diagnostico.py     # chequea que la tasa no mida antigüedad
    │   ├── supervivencia.py   # Kaplan-Meier sobre períodos de actividad
    │   ├── cohortes.py        # el mismo KM estratificado por cohorte de alta
    │   ├── validacion.py      # muestra para calibrar el proxy contra Places
    │   └── cli.py
    └── tests/
```

Difiere de la estructura genérica que proponía el roadmap (`src/ingest`,
`src/features`, `data/raw|interim|processed`). Se mantiene esta: los módulos
están separados por etapa igual, con nombres del dominio y en español como el
resto del proyecto. Cuando aparezcan las features y el modelo van como
`features.py` y `modelo.py` en el mismo paquete.

`pipeline/` queda como un proyecto Python instalable aparte, para que el backend
y el frontend puedan sumarse como carpetas hermanas sin mezclarse.

Comandos:

```
python -m viabilidad {rubros|mapeo|ingest|manzanas|resumen|todo}
python -m viabilidad diagnostico     # ¿la tasa mide el nomenclador? (no necesita red)
python -m viabilidad supervivencia   # Kaplan-Meier por rubro (necesita ingest previo)
python -m viabilidad cohortes        # Paso 2b: estratificado por cohorte de alta
python -m viabilidad muestra         # muestra para calibrar el proxy contra Places
```

## Convenciones

- **Toda ingesta debe ser un script reproducible.** Nada de descargas manuales: el pipeline tiene que poder correr de cero.
- **No versionar `data/raw/`.** Los scripts regeneran las descargas.
- Linting y formato con `ruff`; `pre-commit` corre ruff, chequeos de archivos y
  los tests en cada commit. Instalarlo una vez: `pre-commit install`.
- Tests para las transformaciones de datos, no solo para el modelo.
- **Los tests ejercitan las funciones de ingesta enteras, con el GIS mockeado,
  no sus helpers sueltos.** Un test por helper prueba que la pieza anda, no que
  esté enchufada: así pasó desapercibido que el join de rubros había quedado
  después de un `return` y nunca se ejecutaba.
- **Desconfiar de un resultado uniforme.** Una tasa idéntica en las 76
  categorías no es un hallazgo, es un bug. El pipeline avisa por log cuando pasa.
- Documentar decisiones, no solo código. El razonamiento detrás de cada elección vale tanto como la implementación.
- Declarar limitaciones explícitamente. Nunca presentar métricas sin explicar cómo se validaron.

---

## Estado actual

**Fase 1 cerrada.** El pipeline descarga el histórico completo del GIS, lo
limpia, lo agrupa por rubro y lo agrega a nivel manzana.

| | |
|---|---|
| Trámites | 71.287 (2014-2026), en 144.743 filas trámite x rubro |
| Manzanas | 7.533 |
| Supervivencia de la ciudad | 33,1% |
| Rubros | 1377 → 76 de nivel 2 → 12 de nivel 1 |

Hallazgos que condicionan el modelado:

- **De cada 10 comercios que abrieron en Córdoba desde 2014, 7 ya cerraron.** Ese
  33,1% es la referencia contra la que se compara cualquier manzana.
- **La distribución está muy sesgada:** mediana de 3 habilitaciones por manzana,
  máximo 657, y el 25% de las manzanas tuvo una sola en 12 años. En miles de
  manzanas no hay evidencia propia suficiente, así que el score va a tener que
  apoyarse en el entorno (las manzanas vecinas) y no solo en lo ocurrido dentro
  de la cuadra.
- Por eso la tasa se suaviza hacia el promedio **del propio rubro**, no hacia el
  global: una farmacia y un bar no tienen la misma expectativa de vida.
- **La manzana no necesita join espacial.** Está embebida en `nro_catastral`:
  `01-01-001-007` → manzana `01-01-001` (distrito-zona-manzana-parcela).

**Bloqueante abierto antes de la Fase 2:** la tasa `vigentes/total` mide
antigüedad, no supervivencia. Los permisos duran ~5 años, así que una
habilitación reciente figura vigente por construcción; y como los dos
nomencladores se usaron en épocas distintas, el rubro queda correlacionado con
el año. Resultado: gastronomía da 95,6% de supervivencia y regalería 0%.

**Medido, ya no es sospecha.** `python -m viabilidad diagnostico` cruza la tasa
de cada rubro contra la proporción de sus habilitaciones cargadas bajo el
nomenclador nuevo: Pearson 0,716 sobre 65 rubros, y en 48 de ellos la tasa no
se parece a esa proporción, *es* esa proporción. Un modelo de dos parámetros
—el nomenclador viejo no sobrevive nunca, el nuevo sobrevive ~0,66 sin importar
el rubro— explica el 87% de la varianza entre rubros. La tabla de supervivencia
por rubro no contiene información sobre los rubros.

**El bloqueante está cerrado.** `supervivencia.py` consolida renovaciones y hace
Kaplan-Meier con `lifelines`; `cohortes.py` lo estratifica por cohorte de alta.
El chequeo de dominio pasa (gastronomía 17,7% contra farmacia 24,0% a 5,5 años)
y, sobre todo, **el orden de los rubros se sostiene entre cohortes
independientes**: rho de Spearman 0,59 a 0,76 entre pares de cohortes, 0,68 de
promedio. Dentro de una cohorte la época está fija, así que esa estabilidad es
la evidencia de que hay un efecto de rubro real y no un artefacto de calendario.

**Nunca evaluar la supervivencia a los 5 años exactos.** Casi todos los permisos
duran ese plazo, así que la curva es plana y cae de golpe ahí: S(4,99)=0,97 y
S(5,01)=0,22. `predict(5.0)` devuelve la posición arbitraria dentro del salto,
no una supervivencia — depende de cuántos vencimientos cayeron unos días antes o
después del aniversario. Así se reportó una supervivencia de ciudad del 43%
donde el número real es 21%. Los horizontes van **después** de cada escalón
(`HORIZONTES = (5.5, 10.5)`), y hay un test que lo impide
(`test_el_horizonte_no_cae_adentro_del_escalon_administrativo`). El de 3 años
que pedía el roadmap no distingue nada: antes del primer vencimiento S(3)=1.

**La feature de rubro es `efecto`, no `s5_5`.** Está en `efecto_rubro.csv`: los
puntos de supervivencia de cada rubro por encima de la ciudad **de su misma
cohorte**. El `s5_5` crudo mezcla el rubro con su época; el `efecto` no. Sigue
correlacionando 0,51 con el año mediano del rubro, pero eso ya no implica
confusión —la estabilidad entre cohortes la descarta— sino la asociación
esperable entre un rubro en crecimiento y un rubro que sobrevive. Cuantificarla
requiere el Cox con el año como covariable, que va junto con las features.

**La unidad de análisis no es la habilitación: es el período de actividad.** La
resta `fechavencimientohab - fechahabaprobada` no mide la vida del comercio sino
el plazo que otorgó el municipio, que es ~constante. Medida así, una habilitación
vencida dura ~5 años por definición administrativa y Kaplan-Meier vuelve a medir
época. Lo que separa al que sobrevive es **si renovó**, así que hay que encadenar
los trámites sucesivos de un mismo `titular` en un mismo `nro_catastral`. No
revertir a medir habilitaciones sueltas: hay un test que lo impide
(`test_sin_consolidar_los_dos_rubros_se_ven_iguales`).

**El titular no está en el histórico.** `cuitempresa` viene nula en el 100% de
las filas, así que la primera versión de la consolidación agrupaba contra una
columna vacía y daba cero renovaciones sin que nada fallara. Sale de la vista de
trámites (ver "La variable objetivo") y llega hasheado. Si el ingest se saltea
esa capa, el Paso 2 vuelve a medir el plazo del permiso.

El detalle, el diagnóstico y los pasos están en **`docs/proximo-paso.md`**.
