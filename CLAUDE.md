# CLAUDE.md — Contexto del proyecto

## Qué es este proyecto

Plataforma que asigna un **score de viabilidad comercial** a ubicaciones urbanas. Responde dos preguntas:

1. ¿Qué tan probable es que un negocio de rubro X sobreviva en esta ubicación?
2. Dado un local vacío, ¿qué rubro tiene mayor probabilidad de éxito ahí?

**Ciudad piloto:** Buenos Aires (CABA). **Expansión prevista:** Córdoba, Argentina.

El roadmap completo está en `docs/roadmap.md`. Leerlo antes de proponer cambios de alcance.

---

## Historia de decisiones (importante — no revertir sin discutir)

**La idea original era un mapa de tráfico y densidad de personas en tiempo real.** Se descartó el tiempo real por restricciones de datos reales:

- Los satélites de observación terrestre están en órbita LEO, no geoestacionaria. Sentinel-2 pasa por un mismo punto cada ~5 días, con resolución de 10m. No sirve para observar tráfico ni personas en vivo.
- La densidad poblacional en tiempo real solo se consigue vía datos agregados de operadoras móviles: caro e inaccesible sin tracción comercial previa.

**El pivot a scoring de localización comercial resolvió el problema:** un negocio se instala una vez y permanece años, así que lo relevante son patrones históricos, no el instante actual. Esos datos sí están disponibles y son gratuitos.

**Consecuencia:** el satélite pasa de ser el núcleo del producto a ser una capa de refinamiento (desagregación de densidad poblacional y detección de crecimiento urbano). No proponer volver al tiempo real.

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

## El problema abierto más importante

**Definir la variable objetivo (supervivencia) depende de conseguir datos de cierres.**

El dataset de CABA publica habilitaciones *otorgadas*. Falta confirmar si incluye estado, vencimiento o fecha de baja.

Planes en orden de preferencia:

- **Plan A:** campo de baja directo en el dataset, si existe.
- **Plan B:** inferir cierres comparando snapshots anuales — si un local desaparece del padrón, se asume baja.
- **Plan C:** cruzar con Google Places API (los locales cerrados quedan marcados como permanentemente cerrados).

Señal complementaria: el dataset de **inspecciones de la AGC** prueba que un local seguía operativo en una fecha dada.

**Esto debe resolverse en las primeras semanas.** Si no hay dato de cierres por ninguna vía, el proyecto cambia de naturaleza (pasa de predictivo a descriptivo) y hay que replantear.

---

## Segundo problema conocido: taxonomía de rubros

El dataset de CABA usa **843 códigos de rubro entre 2015-2018** y **423 desde 2019**, sin jerarquía clara, y cada local puede estar habilitado bajo varios rubros simultáneamente.

Tareas:
- Construir tabla de mapeo entre nomenclatura antigua y nueva.
- Definir taxonomía propia de 15-25 categorías operativas.
- Definir criterio de rubro principal cuando hay múltiples.
- Documentar todas las decisiones de mapeo en `docs/rubros.md`.

No dejar esto para el final: condiciona todo el modelado.

---

## Fuentes de datos

### Disponibles sin trámite
| Fuente | Contenido | URL |
|---|---|---|
| BA Data — Habilitaciones | Habilitaciones CABA 2015-2026, CSV/XLSX | data.buenosaires.gob.ar/dataset/habilitaciones-aprobadas |
| BA Data — Inspecciones | Inspecciones AGC (señal de operatividad) | data.buenosaires.gob.ar |
| Posadas | Habilitaciones con altas, renovaciones y cambios de rubro, geolocalizado, actualización diaria | Portal de datos abiertos de Posadas |
| INDEC | Censo 2022 por radio censal | indec.gob.ar |
| OpenStreetMap | Red vial, POIs, footprints (vía `osmnx`) | — |
| Google Open Buildings | Footprints de edificios detectados por IA | — |
| Copernicus / Sentinel-2 | Imágenes satelitales gratuitas | — |
| Meta/CIESIN HRSL | Densidad poblacional 30x30m (estático, sin actualizar desde 2024) | — |
| VIIRS | Luces nocturnas (proxy de actividad nocturna) | — |
| Datos Abiertos Córdoba | Barrios, catastro, planeamiento, seguridad vial | gobiernoabierto.cordoba.gob.ar |

Nota sobre Posadas: publica renovaciones, que son prueba directa de supervivencia. Puede convenir prototipar el método de análisis de supervivencia ahí (dato más limpio) y aplicar a CABA por volumen.

### Requieren gestión
- Habilitaciones de Córdoba: pedido de acceso a información pública / EMFyC (`fiscalizacionycontrol@cordoba.gov.ar`).
- Google Places API: cuenta de facturación, tier gratuito disponible.

---

## Stack

| Capa | Herramientas |
|---|---|
| Datos | pandas, geopandas, osmnx, rasterio |
| Geoespacial | PostGIS, shapely |
| ML | scikit-learn, XGBoost, lifelines, SHAP |
| Satelital | Google Earth Engine, Sentinel Hub |
| Backend | FastAPI, PostgreSQL + PostGIS |
| Frontend | React + Leaflet / Mapbox |
| Orquestación | Prefect o GitHub Actions |
| Deploy | Docker + Railway / Render |

Python 3.11+.

---

## Estructura del repositorio

```
site-score/
├── data/
│   ├── raw/            # Descargas originales (gitignored)
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
│   ├── roadmap.md
│   └── rubros.md
└── CLAUDE.md
```

---

## Convenciones

- **Toda ingesta debe ser un script reproducible.** Nada de descargas manuales: el pipeline tiene que poder correr de cero.
- **No versionar `data/raw/`.** Los scripts regeneran las descargas.
- Linting con `ruff`, `pre-commit` configurado.
- Tests para las transformaciones de datos, no solo para el modelo.
- Documentar decisiones, no solo código. El razonamiento detrás de cada elección vale tanto como la implementación.
- Declarar limitaciones explícitamente. Nunca presentar métricas sin explicar cómo se validaron.

---

## Estado actual

Fase 0 — sin iniciar. Arrancar por:
1. Inicializar repositorio y entorno.
2. Descargar el dataset de CABA y revisar el diccionario de datos para resolver la pregunta de la variable objetivo.
