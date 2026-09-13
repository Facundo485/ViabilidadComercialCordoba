# Roadmap — Plataforma de Scoring de Localización Comercial

**Versión:** 1.0
**Ciudad piloto:** Buenos Aires (CABA) → Expansión a Córdoba
**Objetivo:** Predecir la probabilidad de éxito de un tipo de negocio en una ubicación determinada, a partir de datos abiertos, geoespaciales y satelitales.

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
- [ ] Crear repositorio en GitHub con estructura de proyecto profesional
- [ ] Configurar entorno: Python 3.11+, `venv` o `poetry`
- [ ] Instalar stack base: `pandas`, `geopandas`, `shapely`, `scikit-learn`, `xgboost`, `folium`, `rasterio`
- [ ] Configurar `pre-commit`, linting (`ruff`) y estructura de tests
- [ ] Crear README con planteo del problema y objetivos

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

### En paralelo (trámites que corren solos)
- [ ] Enviar pedido de acceso a información pública a la Municipalidad de Córdoba (habilitaciones comerciales con fecha de alta, baja, rubro y domicilio)
- [ ] Contactar a OpenDataCórdoba (comunidad local de datos abiertos)
- [ ] Escribir al EMFyC: `fiscalizacionycontrol@cordoba.gov.ar`
- [ ] Descargar y leer el informe del proyecto previo de CABA ("Historias con Datos")

**Entregable:** repositorio funcional + trámites iniciados.

---

## FASE 1 — Datos y exploración (Semanas 2-4)

**Objetivo:** entender qué hay realmente en los datos antes de modelar.

### 1.1 Ingesta
- [ ] Descargar habilitaciones aprobadas de CABA (2015-2026) desde BA Data
- [ ] Descargar datasets complementarios: comunas, barrios, usos del suelo, transporte
- [ ] Obtener datos del Censo INDEC 2022 por radio censal
- [ ] Descargar red vial y POIs desde OpenStreetMap (`osmnx`)
- [ ] Escribir scripts de descarga reproducibles (no descargas manuales)

### 1.2 Análisis exploratorio (EDA)
- [ ] Distribución de habilitaciones por año, barrio y rubro
- [ ] Calidad de geocodificación: ¿qué porcentaje tiene coordenadas usables?
- [ ] Detección de duplicados y registros inconsistentes
- [ ] Análisis de la estructura de rubros

### 1.3 El problema de los rubros (crítico)
El dataset de CABA usa 843 códigos entre 2015-2018 y 423 desde 2019, sin jerarquía y con múltiples rubros por local.

- [ ] Construir tabla de mapeo entre nomenclaturas antiguas y nuevas
- [ ] Definir taxonomía propia de 15-25 categorías operativas
- [ ] Definir criterio de rubro principal cuando hay varios
- [ ] Documentar todas las decisiones de mapeo

### 1.4 Definir la variable objetivo
Este es el punto que define si el proyecto es predictivo o descriptivo.

- [ ] Verificar si el dataset incluye estado, vencimiento o baja
- [ ] **Plan A:** usar fecha de baja directa si existe
- [ ] **Plan B:** inferir cierres comparando snapshots anuales (si un local desaparece del padrón, se asume baja)
- [ ] **Plan C:** cruzar con Google Places API (los locales cerrados quedan marcados)
- [ ] Documentar limitaciones de la definición elegida

**Entregable:** notebook de EDA + dataset limpio y geocodificado + variable objetivo definida.

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
- [ ] Mapa interactivo con **Leaflet** o **Mapbox**
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

## FASE 5 — Expansión a Córdoba (Semanas 16+)

Depende de la respuesta al pedido de información pública.

### Escenario A — Córdoba entrega los datos completos
- [ ] Adaptar el pipeline a la estructura de datos cordobesa
- [ ] Reentrenar el modelo
- [ ] Evaluar **transferibilidad:** ¿el modelo entrenado en CABA predice bien en Córdoba?

### Escenario B — Datos parciales o sin fechas de baja
- [ ] Aplicar inferencia por snapshots
- [ ] Complementar con Google Places
- [ ] Modelo descriptivo + predictivo parcial

### Escenario C — Sin acceso
- [ ] Construir dataset propio vía scraping de Google Places y portales inmobiliarios
- [ ] Modelo basado en proxies, con limitaciones documentadas

**Bonus:** si el modelo transfiere bien entre ciudades, eso es un argumento fuerte de escalabilidad — técnico y comercial.

---

## Stack tecnológico

| Capa | Herramientas |
|---|---|
| Datos | pandas, geopandas, osmnx, rasterio |
| Geoespacial | PostGIS, shapely, QGIS (exploración) |
| ML | scikit-learn, XGBoost, lifelines, SHAP |
| Satelital | Google Earth Engine, Sentinel Hub |
| Backend | FastAPI, PostgreSQL + PostGIS |
| Frontend | React + Leaflet / Mapbox |
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
| Habilitaciones Córdoba | Pedido de acceso a información pública / EMFyC |
| Google Places API | Cuenta de facturación (tier gratuito disponible) |
| Datos de tráfico histórico | TomTom / HERE (freemium) |

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
| No hay dato de cierres → sin variable objetivo | Planes B y C definidos en Fase 1.4; decidir temprano |
| Taxonomía de rubros inconsistente | Abordarlo en Fase 1, no dejarlo para el final |
| Geocodificación deficiente | Evaluar cobertura en EDA; usar geocoder propio si hace falta |
| Confundir correlación con causalidad | Documentar explícitamente; modelar no linealidad de la competencia |
| Alcance excesivo | Entregar por fases; cada una es autónoma y mostrable |
| Córdoba no responde | El proyecto ya funciona con CABA; Córdoba es expansión, no dependencia |

---

## Principios de ejecución

1. **Reproducibilidad antes que velocidad.** Todo script, nada manual.
2. **Documentar decisiones, no solo código.** El "por qué" vale más que el "qué" en un portfolio.
3. **Validación honesta.** Métricas infladas por mala validación se detectan en cualquier entrevista técnica.
4. **Publicar temprano y seguido.** Un proyecto visible a medias supera a uno perfecto sin terminar.
5. **Las limitaciones se declaran, no se esconden.** Reconocer lo que el modelo no puede hacer es señal de criterio.
