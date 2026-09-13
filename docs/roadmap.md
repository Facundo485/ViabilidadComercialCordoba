# Roadmap — Plataforma de Scoring de Localización Comercial

**Versión:** 2.0
**Ciudad piloto:** Córdoba Capital → Expansión a Buenos Aires (CABA)
**Objetivo:** Predecir la probabilidad de éxito de un tipo de negocio en una ubicación determinada, a partir de datos abiertos, geoespaciales y satelitales.

---

## Qué cambió en la v2

El orden de ciudades se invirtió. La v1 ponía a CABA de piloto y a Córdoba en
Fase 5, condicionada a un pedido de acceso a información pública.

Córdoba publica el histórico de habilitaciones sin trámite, con fecha de alta,
vencimiento, rubro y coordenadas: 144.743 registros entre 2014 y 2026. Eso
resuelve la variable objetivo, que era el riesgo que podía convertir el proyecto
en descriptivo, y lo resuelve por el Plan A. En CABA sigue sin confirmarse.

Consecuencias sobre el plan original:

- **Fase 0:** los tres trámites (información pública, EMFyC, OpenDataCórdoba)
  quedan sin efecto.
- **Fase 1:** cerrada. Ingesta, taxonomía de rubros y variable objetivo resueltas.
- **Fase 5:** pasa a ser CABA, como prueba de transferibilidad entre ciudades.

El detalle de las fuentes y de cómo se define la supervivencia está en
`CLAUDE.md`.

---

## Resumen del proyecto

Plataforma que asigna un **score de viabilidad comercial** a cualquier ubicación urbana, respondiendo dos preguntas:

1. ¿Qué tan probable es que un negocio de rubro X funcione en esta ubicación?
2. Dado un local vacío, ¿qué tipo de negocio tiene mayor probabilidad de éxito?

**Diferencial:** a diferencia de los mapas descriptivos existentes, el modelo es **predictivo** y el pipeline es **automatizado y sostenible** en el tiempo.

---

## FASE 0 — Fundaciones (Semana 1)

**Objetivo:** dejar todo listo para trabajar sin fricción.

### Tareas
- [x] Crear repositorio en GitHub con estructura de proyecto profesional
- [x] Configurar entorno: Python 3.11+, `venv`
- [x] Instalar stack base (`polars` en vez de `pandas`; ver `CLAUDE.md`)
- [x] Estructura de tests
- [ ] Configurar `pre-commit` y linting (`ruff`)
- [x] Crear README con planteo del problema y objetivos

### Estructura sugerida del repositorio
```
site-score/
├── data/
│   ├── raw/            # Descargas originales (no versionar)
│   ├── interim/        # Datos en proceso
│   └── processed/      # Datasets finales
├── notebooks/          # Exploración
├── src/
│   ├── ingest/         # Descarga de fuentes
│   ├── features/       # Ingeniería de variables
│   ├── models/         # Entrenamiento y evaluación
│   └── viz/            # Mapas y visualizaciones
├── tests/
├── docs/
└── README.md
```

### Trámites — sin efecto
Los datos de Córdoba estaban abiertos en el GIS municipal. No hizo falta ningún
pedido de acceso a información pública ni contactar al EMFyC.

- [ ] Revisar el **Localizador de Oportunidades Comerciales** del municipio
  (`cordoba.gob.ar/loc-filtros-consultados/`): es un buscador con filtros sobre
  los mismos datos, sin modelo predictivo. Sirve para delimitar el diferencial.

**Entregable:** repositorio funcional + trámites iniciados.

---

## FASE 1 — Datos y exploración ✅ COMPLETA

### 1.1 Ingesta
- [x] Descargar el histórico de habilitaciones del GIS de Córdoba (2014-2026)
- [x] Scripts de descarga reproducibles, con paginación y reintentos
- [x] Limpieza por bounding box (la capa declara un extent hasta lat 90)
- [ ] Datasets complementarios del portal: manzanas, barrios, zonificación, POIs
- [ ] Censo INDEC 2022 por radio censal
- [ ] Red vial y POIs de OpenStreetMap (`osmnx`)

### 1.2 Análisis exploratorio
- [x] Distribución por año, barrio y rubro
- [x] Geocodificación: el GIS viene en WGS84 nativo, sin geocoding
- [x] Estructura de rubros

### 1.3 El problema de los rubros ✅
1377 valores, dos nomencladores mezclados. Resuelto: 76 rubros de nivel 2 en 12
grupos de nivel 1, 93,4% de cobertura, en `referencia/mapeo_rubros.csv`.

En Córdoba cada local tiene un rubro, así que no hizo falta un criterio de rubro
principal. En CABA sí va a hacer falta.

### 1.4 La variable objetivo ✅
Resuelta por el **Plan A**: `fechahabaprobada` y `fechavencimientohab` por
habilitación. La derivación está validada de forma cruzada contra los conteos
precalculados de la capa 0 (33,1% vs ~33%). Detalle y limitaciones en
`CLAUDE.md`.

### Números de la corrida
| | |
|---|---|
| Habilitaciones | 144.743 |
| Manzanas | 7.533 |
| Supervivencia de la ciudad | 33,1% |
| Mediana por manzana | 3 (máximo 657) |

**Entregable:** ✅ pipeline reproducible, dataset limpio y geocodificado,
variable objetivo definida y validada.

---

## FASE 2 — Ingeniería de variables (Semanas 5-7)

**Objetivo:** construir las features que alimentan el modelo.

### Variables por categoría

**Demográficas**
- Población por radio censal (INDEC 2022)
- Densidad poblacional desagregada a nivel manzana
- Nivel socioeconómico (NBI, nivel educativo, tipo de vivienda)
- Estructura etaria

**Competencia y complementariedad**
- Cantidad de locales del mismo rubro en radios de 100m, 300m y 500m
- Cantidad de locales de rubros complementarios
- Índice de diversidad comercial (entropía de Shannon sobre rubros)
- Antigüedad promedio de los comercios vecinos

**Accesibilidad**
- Distancia a la parada de transporte público más cercana
- Cantidad de líneas de transporte en radio de 500m
- Centralidad de la calle en la red vial (betweenness con `osmnx`)
- Índice de caminabilidad

**Contexto urbano**
- Zonificación y uso del suelo permitido
- Distancia a atractores (universidades, hospitales, shoppings, estaciones)
- Superficie del local

**Temporales**
- Año de habilitación
- Tendencia del rubro en la zona (crecimiento o retracción)

### Capa satelital (diferencial técnico)
- [ ] Descargar footprints de edificios (Google Open Buildings / Microsoft Building Footprints)
- [ ] Implementar **dasymetric mapping**: desagregar población censal a nivel manzana usando footprints y altura estimada
- [ ] Detección de cambio: comparar imágenes Sentinel-2 de distintos años para identificar zonas en crecimiento
- [ ] NDVI como proxy socioeconómico
- [ ] Luces nocturnas (VIIRS) como proxy de actividad nocturna

**Entregable:** dataset de features documentado, con diccionario de variables.

---

## FASE 3 — Modelado (Semanas 8-11)

### 3.1 Baseline
- [ ] Modelo trivial (predecir la clase mayoritaria) como piso de comparación
- [ ] Regresión logística simple

### 3.2 Modelos principales
- [ ] **XGBoost / LightGBM** para clasificación de supervivencia
- [ ] **Análisis de supervivencia** (Cox, Kaplan-Meier) — más adecuado que clasificación binaria, porque maneja datos censurados (locales que siguen abiertos hoy)
- [ ] **Clustering (K-means, HDBSCAN)** para tipologías de zona comercial

### 3.3 Validación (hacerlo bien acá importa)
- [ ] **Validación espacial:** partición por barrios, no aleatoria. El split aleatorio infla las métricas porque hay autocorrelación espacial
- [ ] **Validación temporal:** entrenar con datos previos a un año de corte, testear con posteriores
- [ ] Métricas: AUC-ROC, precision/recall, calibración de probabilidades
- [ ] Curva de calibración (que un 70% predicho signifique realmente 70%)

### 3.4 Interpretabilidad
- [ ] SHAP values para explicar cada predicción individual
- [ ] Importancia global de variables
- [ ] Convertir explicaciones a lenguaje natural para el usuario final

### 3.5 El problema de la causalidad (documentar honestamente)
Que una zona tenga muchos cafés exitosos no implica que un café nuevo vaya a funcionar. Hay que distinguir:
- **Aglomeración beneficiosa** (clusters que atraen demanda)
- **Saturación competitiva** (mercado ya cubierto)

- [ ] Modelar la relación como no lineal (curva en U invertida sobre densidad de competencia)
- [ ] Documentar la limitación explícitamente en el proyecto

**Entregable:** modelo entrenado, validado y documentado con métricas honestas.

---

## FASE 4 — Producto (Semanas 12-15)

### 4.1 API
- [ ] Backend con **FastAPI**
- [ ] Endpoint: dado (lat, lon, rubro) → score + explicación
- [ ] Endpoint: dado (lat, lon) → ranking de rubros recomendados
- [ ] Base de datos **PostgreSQL + PostGIS** para consultas espaciales
- [ ] Documentación automática (OpenAPI)

### 4.2 Frontend
- [ ] Mapa interactivo con **MapLibre GL** (WebGL: son 7.533 polígonos)
- [ ] Selector de ubicación (click en mapa o búsqueda de dirección)
- [ ] Selector de rubro
- [ ] Panel de resultados: score, factores que lo suben, factores que lo bajan
- [ ] Capas visualizables: densidad, competencia, transporte

### 4.3 Automatización (el diferencial de sostenibilidad)
- [ ] Pipeline con **GitHub Actions** o **Prefect** que revise periódicamente si hay datos nuevos
- [ ] Reentrenamiento programado
- [ ] Tests de calidad de datos (Great Expectations o similar)
- [ ] Monitoreo de drift del modelo

### 4.4 Deploy
- [ ] Dockerizar la aplicación
- [ ] Deploy en Railway, Render o Fly.io (opciones de bajo costo)
- [ ] Dominio propio

**Entregable:** aplicación web funcionando y accesible públicamente.

---

## FASE 5 — Expansión a CABA (Semanas 16+)

La pregunta abierta en CABA es la misma que Córdoba ya resolvió: si el dataset
de habilitaciones trae estado, vencimiento o fecha de baja.

- [ ] Verificar la variable objetivo en BA Data
- [ ] **Plan B si no hay baja directa:** inferir cierres comparando snapshots anuales
- [ ] **Plan C:** cruzar con Google Places API
- [ ] Señal complementaria: inspecciones de la AGC prueban que un local seguía
  operativo en una fecha dada
- [ ] Resolver la taxonomía de CABA: 843 códigos entre 2015-2018, 423 desde
  2019, y varios rubros por local
- [ ] Adaptar el pipeline y reentrenar
- [ ] Evaluar **transferibilidad:** ¿el modelo entrenado en Córdoba predice bien
  en CABA?

Otra ciudad a considerar: **Posadas** publica renovaciones de habilitación, que
son prueba directa de supervivencia, geolocalizadas y con actualización diaria.
Es el dato más limpio de los tres.

**Bonus:** si el modelo transfiere bien entre ciudades, eso es un argumento
fuerte de escalabilidad — técnico y comercial.

---

## Stack tecnológico

| Capa | Herramientas |
|---|---|
| Datos | **polars**, geopandas, osmnx, rasterio |
| Geoespacial | PostGIS, shapely, QGIS (exploración) |
| ML | scikit-learn, XGBoost, lifelines, SHAP |
| Satelital | Google Earth Engine, Sentinel Hub |
| Backend | FastAPI, PostgreSQL + PostGIS |
| Frontend | React + MapLibre GL |
| Orquestación | Prefect o GitHub Actions |
| Deploy | Docker + Railway / Render |

---

## Fuentes de datos

### Disponibles sin trámite
| Fuente | Contenido |
|---|---|
| BA Data | Habilitaciones aprobadas CABA 2015-2026, inspecciones, +400 datasets (CC BY 4.0) |
| INDEC | Censo 2022 por radio censal |
| OpenStreetMap | Red vial, POIs, footprints |
| Google Open Buildings | Footprints de edificios detectados por IA |
| Copernicus / Sentinel-2 | Imágenes satelitales gratuitas |
| Meta/CIESIN HRSL | Densidad poblacional 30x30m (estático, sin actualizar desde 2024) |
| VIIRS | Luces nocturnas |
| Datos Abiertos Córdoba | Barrios, catastro, planeamiento urbano, seguridad vial |

### Requieren gestión
| Fuente | Vía |
|---|---|
| Google Places API | Cuenta de facturación (tier gratuito disponible) |
| Tráfico en tiempo real | TomTom Traffic Flow: 2500 req/día gratis, sin tarjeta |

---

## Hitos de portfolio

No esperar a terminar todo para mostrar el trabajo. Cada fase produce algo publicable:

| Momento | Qué mostrar |
|---|---|
| Fin Fase 1 | Post técnico sobre el EDA y el problema de taxonomía de rubros |
| Fin Fase 2 | Artículo sobre dasymetric mapping con datos argentinos |
| Fin Fase 3 | Post sobre validación espacial y por qué el split aleatorio engaña |
| Fin Fase 4 | Demo pública + video corto + post de lanzamiento |

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| ~~No hay dato de cierres~~ | Resuelto en Córdoba por Plan A. Sigue abierto para CABA (Fase 5) |
| ~~Taxonomía de rubros inconsistente~~ | Resuelto en Córdoba: 1377 → 76 → 12. Sigue abierto para CABA |
| ~~Geocodificación deficiente~~ | El GIS de Córdoba viene georreferenciado en WGS84 |
| Confundir correlación con causalidad | Documentar explícitamente; modelar no linealidad de la competencia |
| Alcance excesivo | Entregar por fases; cada una es autónoma y mostrable |
| ~~Córdoba no responde~~ | Resuelto: los datos estaban abiertos, sin trámite |

---

## Principios de ejecución

1. **Reproducibilidad antes que velocidad.** Todo script, nada manual.
2. **Documentar decisiones, no solo código.** El "por qué" vale más que el "qué" en un portfolio.
3. **Validación honesta.** Métricas infladas por mala validación se detectan en cualquier entrevista técnica.
4. **Publicar temprano y seguido.** Un proyecto visible a medias supera a uno perfecto sin terminar.
5. **Las limitaciones se declaran, no se esconden.** Reconocer lo que el modelo no puede hacer es señal de criterio.
