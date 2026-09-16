# Score de viabilidad comercial — Córdoba Capital

Dada una manzana y un rubro, estima la probabilidad de que un comercio sobreviva
ahí. Construido sobre el histórico de habilitaciones comerciales del municipio:
**71.287 trámites entre 2014 y 2026**, sobre 7.533 manzanas.

> De cada 10 comercios que abrieron en Córdoba desde 2014, **7 ya cerraron**.

**El proyecto está cerrado.** Llegó hasta un modelo que ordena razonablemente y
no alcanza para dar precisión por local. Lo que sigue documenta por qué, porque
el límite que encontré no es de este modelo: **es del dato**, y cualquiera que
intente esto con habilitaciones de otro municipio argentino se lo va a comer
igual. Eso me parece más útil de publicar que el score.

---

## El resultado, en una tabla

| | |
|---|---|
| AUC, validación temporal | **0,593** |
| Techo impuesto por la etiqueta | **0,608** |
| Exactitud de la etiqueta (contra Google Places, n=895) | 61,0% |
| Margen sobre el azar, capturado | 87% |

El modelo saca el 87% de lo que la variable objetivo permite sacar. **El cuello
de botella no son las variables: es que nadie registra los cierres.**

---

## Las cuatro cosas que vale la pena leer

### 1. El indicador que ya publicaba el municipio se cuenta a sí mismo

La Municipalidad publica, por parcela, habilitaciones vigentes sobre el total. Es
la línea base obvia, y mi primera comparación decía que yo empataba. Fui a ver
por qué.

En las manzanas con **una sola** habilitación —el 40% de la ciudad— ese
indicador coincide con el destino de ese único local el **95,9%** de las veces.
No lo está prediciendo: lo está incluyendo en su propio cálculo. Y a más de la
mitad de la ciudad le asigna 0% o 100%, veredictos categóricos sostenidos por
uno o dos locales.

Mi score no es más exacto. Es honesto sobre lo que no sabe, que en la mayor
parte de la ciudad es casi todo.

`python -m viabilidad diagnostico` reproduce la medición.

### 2. La variable objetivo es un proxy, y está medida, no asumida

**Nadie registra los cierres, y no es un olvido.** Un cierre es un no-evento:
nadie va a hacer el trámite de avisar que le fue mal. Revisé toda la fuente —los
campos `vigente`, `activa` y `tarjeta_activa` vienen nulos en el 100% de las
filas, y ninguno de los 183 datasets del portal abierto tiene bajas— y el campo
existe pero el trámite que lo llenaría no.

Así que lo único observable es **si el comercio renovó el permiso** a los 5
años. Para saber cuánto vale eso, tomé 1.498 locales y le pregunté a Google
Places qué opera hoy en esas direcciones:

| | |
|---|---|
| Exactitud del proxy | **61,0%** |
| Línea base (clase mayoritaria) | 55,3% |
| Odds ratio | 2,40 |
| Significación | p = 2,1e-10 |

Señal real —duplica largo las chances, y con n=895 no es azar— y ruidosa: uno de
cada tres casos utilizables va para el otro lado.

**Eso se convierte en un número duro.** Para un predictor binario,
AUC = (sensibilidad + especificidad)/2, y el AUC es simétrico entre las dos
variables: lo bien que mi etiqueta predice la verdad es lo mismo que lo bien que
la verdad predeciría mi etiqueta. Con sensibilidad 0,630 y especificidad 0,585,
**ningún modelo entrenado sobre esta etiqueta pasa de AUC 0,608.**

### 3. Etiquetar más no lo arregla — y eso también se mide

La respuesta intuitiva al punto anterior es etiquetar miles de locales a mano y
entrenar sobre verdad limpia. Antes de gastar meses, tracé la curva de
aprendizaje: de 200 a 350 etiquetas, **0,636 → 0,631**. Plana. El techo con
etiquetas perfectas queda en ~0,64.

Etiquetar compra **precisión de medición, no performance**. Hubiera sido el
error caro del proyecto, y costó una tarde evitarlo.

Durante varias semanas yo mismo venía diciendo que etiquetar era "la única
palanca". Lo era hasta que lo medí.

### 4. Los barrios con más bares son los de menor supervivencia

Esto salió de mirar el mapa y desconfiar, no de un test.

| Barrio | Bares | Sobreviven |
|---|---:|---:|
| Centro | 509 | **9,0%** |
| Nueva Córdoba | 355 | 10,4% |
| Güemes | 157 | 14,6% |
| Poeta Lugones | 43 | **25,6%** |

Un corredor gastronómico excelente rota más rápido: el alquiler y la competencia
se quedan con el margen. Lo que obliga a ser preciso sobre qué mide un score
así — **la probabilidad de que el negocio sobreviva, no la calidad de la
ubicación.** En gastronomía apuntan para lados opuestos.

`python -m viabilidad calibracion` contrasta lo predicho contra lo observado por
barrio: correlaciona 0,77 y acierta el promedio de ciudad, pero comprime hacia
la media. Probé corregirlo con la historia del rubro en el barrio: **+0,002 con
el signo inestable entre splits**, y solo el 15% de los locales tiene historia
previa. Con un techo de 0,61, un modelo que se jugara predicciones extremas
estaría sobreajustando. La compresión es honestidad, no error.

---

## Trampas que me costaron, documentadas para el próximo

**El escalón administrativo de los 5 años.** Casi todos los permisos duran ese
plazo exacto, así que la curva de supervivencia es plana y cae de golpe ahí:
S(4,99) = 0,97 y S(5,01) = 0,22. Evaluarla en el aniversario devuelve la
posición arbitraria dentro del salto — así reporté una supervivencia de ciudad
del 43% donde el número real es 21%. Los horizontes van **después** de cada
escalón, y hay un test que lo impide.

**El C-index no sirve acá.** El 55% de los períodos dura exactamente 5,0 años:
con más de la mitad de los pares empatados, un Cox da concordancia 0,507 aunque
tenga coeficientes significativos. Kaplan-Meier y Cox para entender direcciones;
un binario medido con AUC para predecir.

**La unidad no es la habilitación.** `vencimiento - alta` no mide la vida del
comercio sino el plazo que otorgó el municipio, que es ~constante. Lo que separa
al que sobrevive es si **renovó**, así que hay que encadenar los trámites
sucesivos de un mismo titular en una misma parcela.

**Y el titular no está en el histórico.** `cuitempresa` viene nula en el 100% de
las filas, así que la primera versión de la consolidación agrupaba contra una
columna vacía y daba cero renovaciones sin que nada fallara. Sale de otro
servicio del mismo GIS.

**Validación espacial y temporal no miden lo mismo.** El entorno aporta +0,072
de AUC en el corte espacial y **+0,006** en el temporal. En el espacial, train y
test comparten la época. El producto necesita la extrapolación temporal: alguien
parado frente a un local vacío pregunta por el futuro, no por otro barrio.
**Reportar siempre el número temporal; el espacial solo, engaña.**

**Nada del entorno puede mirar hacia adelante.** Un local que abrió en 2016 solo
puede ver el comercio que existía en 2016. Y cuidado con las features que
parecen del lugar y son del calendario: la antigüedad comercial de la zona
correlacionaba 0,986 con el año de alta, porque el histórico arranca en 2014 y
un local de ese año ve cero predecesores por construcción.

**La superficie es del negocio, no del lugar.** Promediarla por manzana hacía
que una manzana periférica con un galpón grande pareciera una zona comercial.
Lo encontró el dueño del dominio mirando el mapa.

**`\b` en los regex de rubro.** Sin él, `panaderia` matchea dentro de
"em**panaderia**s" y manda 2.896 bares al rubro equivocado. Hay un test que
recorre el nomenclador entero buscando reglas que matcheen a mitad de palabra;
así apareció que "cinemato**gráfica**s" caía en `fotocopias`.

**El offset radiométrico de Sentinel-2.** La colección cambió de calibración en
2022 (baseline 04.00, +1000). Sin corregirlo, la serie de densidad construida no
correlacionaba ni consigo misma entre años consecutivos: −0,09, −0,10, −0,23.
Corregido y ajustando la ventana estacional: 0,86, 0,86, 0,90.

**Desconfiar de un resultado uniforme.** Una tasa idéntica en las 76 categorías
no es un hallazgo, es un bug. El pipeline avisa por log cuando pasa, porque ya
produjo una tabla de resultados con ceros en todas las categorías sin que nada
fallara.

---

## Lo que se probó y no dio

Busqué predecir **zonas emergentes** —detectar crecimiento antes de que el
comercio llegue— con imágenes satelitales y con altura de edificios de Google
Open Buildings. Seis hipótesis, ninguna sobrevivió, y hay una explicación
mecanicista: **el comercio está en equilibrio con la forma construida.** La
altura creció 0,114 m en 7 años sobre el promedio de la ciudad. No hay una señal
de construcción que anticipe al comercio porque, a esta escala temporal, no hay
construcción suficiente.

---

## Datos personales

`cuitempresa` y `razonsocial` identifican personas: en un monotributista el CUIT
sale del DNI y la razón social suele ser su nombre.

El ingest reemplaza el CUIT por un hash antes de escribir nada a disco y no
descarga `razonsocial`. La sal es **aleatoria por instalación** y vive en
`data/`, que no se versiona: una sal fija en el código sería equivalente a no
tener sal, porque el espacio de CUITs es de ~10^8 por prefijo y se enumera en
minutos.

Aun así es **seudonimización, no anonimización**. La protección real es que
`data/` no se publica y que todo lo que sale agregado habla de manzanas y
rubros, nunca de titulares.

---

## Correrlo

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
python -m viabilidad todo
```

Toda la ingesta es reproducible desde cero: no hay descargas manuales. `data/`
no se versiona porque el pipeline la regenera.

| Comando | Qué hace |
|---|---|
| `mapeo` | Regenera la taxonomía de rubros desde las reglas |
| `ingest` | Descarga el histórico del GIS y hashea el CUIT |
| `diagnostico` | ¿La tasa publicada mide supervivencia o antigüedad? |
| `supervivencia` | Kaplan-Meier sobre períodos de actividad |
| `cohortes` | El mismo KM, estratificado por cohorte de alta |
| `muestra` / `places` | Calibra el proxy contra Google Places |
| `features` | Entorno comercial, medido a la fecha de alta |
| `modelo` | Validación espacial y temporal |
| `calibracion` | Lo predicho contra lo observado, por barrio |
| `valor` | ¿Conviene etiquetar más? (la curva de aprendizaje) |
| `score` | Genera el score por manzana y rubro |
| `mapa` | Arma el mapa navegable |

## Estructura

| | |
|---|---|
| `pipeline/` | Todo el procesamiento, como paquete Python instalable |
| `pipeline/referencia/mapeo_rubros.csv` | La taxonomía, versionada y editable a mano |
| `mapa/` | Visor Canvas 2D de las 19.600 manzanas |
| `CLAUDE.md` | Contexto y decisiones, en detalle |
| `docs/roadmap.md` | El plan original, por fases |

## Limitaciones a declarar junto a cualquier número

- **El modelo es predictivo, no causal.** Que una zona tenga cafés exitosos no
  prueba que un café nuevo vaya a funcionar.
- **Permiso vigente no es local abierto.** Es un proxy, el mejor disponible, y
  es el criterio del propio municipio. Su exactitud está medida: 61%.
- **Una habilitación de hace menos de 5 años no tuvo oportunidad de vencer.** Es
  censura a derecha, no éxito. Tratarla como éxito infla las zonas con aperturas
  recientes.
- **El score se presenta agregado** —manzana y rubro, donde el ruido promedia—
  porque la variable objetivo no sostiene precisión por local.

## Fuentes

Todo lo usado es público y sin trámite: el
[GIS de la Municipalidad de Córdoba](https://gis.cordoba.gob.ar/server/rest/services)
(habilitaciones 2014-2026 con alta, vencimiento, rubro y coordenadas), el portal
de Datos Abiertos, INDEC (censo 2022 por radio censal), OpenStreetMap y
Sentinel-2. Google Places se usó solo para calibrar el proxy, dentro del tier
gratuito.

Los pedidos de acceso a información pública que había preparado quedaron sin
efecto: los datos ya estaban abiertos.

## Licencia

MIT.
