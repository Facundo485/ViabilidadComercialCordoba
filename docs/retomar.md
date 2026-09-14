# Retomar — dónde quedó y qué hacer al abrir una sesión nueva

Hoja de ruta corta para no releer todo. El contexto del proyecto está en
`CLAUDE.md` y el detalle técnico del bloqueante en `docs/proximo-paso.md`.

**Última actualización:** corrida del 13/09 con la vista de trámites.

---

## Estado

```
Paso 1  [OK]         La tasa vieja medía la época, no la supervivencia. Confirmado.
Paso 2  [OK]         Renovaciones encadenadas con el titular de la vista.
Paso 2b [OK]         Estratificado por cohorte: el efecto de rubro existe y es
                     estable entre cohortes independientes (rho 0,68).
Paso 3  [A MEDIAS]   Features hechas. El entorno separa lugares dentro de un
                     período (AUC 0,60 -> 0,66) pero casi no predice hacia
                     adelante (+0,006). Ver abajo.                           <-- acá
Places  [OK]         Proxy calibrado: 61,0% de exactitud contra 55,3% de base.
                     Tiene señal real, pero es ruidoso. Ver abajo.
```

---

## Lo primero que hay que hacer

```bash
cd ~/Git/React/pipeline && source .venv/bin/activate
pip install -e '.[dev]'

python -m viabilidad ingest          # ahora baja también la vista de trámites
python -m viabilidad supervivencia
python -m viabilidad muestra         # muestra para calibrar contra Places
```

**El `ingest` hay que rehacerlo sí o sí** si el `data/crudo/` es de antes del
13/09: el histórico viejo no tiene la columna `titular` y `supervivencia` corta
con un error que lo dice.

---

## Qué se destrabó y cómo

El Paso 2 daba **cero renovaciones**, o sea la consolidación no consolidaba
nada. La causa: el histórico declara `cuitempresa` y la devuelve **nula en el
100% de las filas**, igual que `vigente`. Sin titular no hay forma de saber si
una habilitación nueva es un comercio nuevo o la renovación del de al lado, así
que cada trámite quedaba como su propio período de 5 años.

Hay otro servicio del mismo GIS que sí la trae poblada:

```
ComerdioIndustria/Habilitaciones_Comerciales_Vista/FeatureServer/0
```

71.287 filas, cero nulos en `cuitempresa`, 46.767 titulares distintos, y su
campo `id` matchea `id_tramite` del histórico en los 71.287. El ingest la baja,
hashea el CUIT y lo adjunta como `titular`. El número nunca queda escrito en
claro en los parquet (ver la nota de `config.SAL_CUIT`: es seudonimización, no
anonimización).

De paso apareció un error de conteo que venía de antes: **las 144.743 filas del
histórico no son 144.743 habilitaciones, son 71.287 trámites.** Un trámite
habilita varios rubros a la vez (media 2,03, máximo 73) y aparece una vez por
cada uno. La unidad de conteo es `id_tramite`.

---

## Cómo quedó la corrida

```
144.743 filas -> 71.287 trámites -> 62.560 períodos de actividad
                                    7.075 con al menos una renovación (11,3%)
Plazo otorgado: 4,83 +/- 0,76 años (mediana 5,00)
Chequeo de dominio: gastronomía 17,7% vs farmacia 24,0% -> OK
```

El 11,3% de renovaciones es poco: el otro 89% termina en el escalón
administrativo de los 5 años. Por eso `mediana_anios` da 4,999 en todos los
rubros —es el plazo del permiso, no la vida del comercio— y **no hay que leerla
como resultado**. Lo que sí se lee es `s5_5`: haber pasado el primer
vencimiento.

> Las cifras de `s5` que traía antes esta sección (gastronomía 40,3%, farmacia
> 43,5%, correlaciones de 0,71) estaban mal: el horizonte caía adentro del
> escalón. Ver "Paso 2b" más abajo.

---

## Arreglado: el outlier era taxonomía, no censura

`bar_restaurante` daba 95% porque **su gemelo viejo está clasificado como
panadería**. El nomenclador municipal mete toda la gastronomía en una entrada
—"Bar, confiterías, pizzerías, lomiterías, empanaderías, parrilla, trattoria…"—
y `mapeo_rubros.csv` la manda a `panaderia`: son 2.896 habilitaciones, el 47%
de ese rubro. Como el CLANAE nuevo sí tiene `bar_restaurante`, el rubro quedó
partido en dos por época, y la supervivencia de cada mitad es la de su época.

`cafeteria` tampoco es cafetería: sus entradas top son "venta de masas y
productos de pastelería" y "venta de café, té y yerba mate" — un negocio de
granos, no un bar.

**Hay 13 de 73 rubros que existen bajo un solo nomenclador** (<5% o >95% de
filas en el nuevo). Esos son, por construcción, rubros que codifican época:

```
solo viejo:  intermediarios, regaleria, cafeteria, locutorio
solo nuevo:  comercio_otros, espectaculos, bar_restaurante, electrodomesticos,
             fiambreria, veterinaria, ortopedia, forrajeria, optica
```

Otros errores vistos de paso: `forrajeria` contiene "SERVICIOS MÉDICOS PARA
ANIMALES (VETERINARIA)" (355) mientras `veterinaria` existe aparte con 235; y
`espectaculos` es en realidad instalaciones deportivas (canchas de paddle,
tenis, fútbol).

**Arreglado en las reglas de `rubros.py`, no a mano en el CSV:** los errores
eran sistemáticos (un regex sin `\b` afecta a todas las variantes), así que
editar filas sueltas los habría dejado volver en la próxima regeneración.

Se movieron **4.063 habilitaciones en 26 entradas**:

```
2896  panaderia      -> bar_restaurante    (el \b de "empanaderías")
 355  forrajeria     -> veterinaria        (servicio médico, no venta de forraje)
 203  espectaculos   -> instalaciones_deportivas
 189  ropa_infantil  -> venta_vehiculos    ("rodados infantiles" son bicicletas)
 324  cafeteria      -> panaderia / alimentos_otros / fabricacion
  91  bar_rest/otro  -> turismo            (hoteles que nombran su restaurante)
```

Y uno que encontró el test general, no yo: "cinemato**gráfica**s" caía en
`fotocopias` por el regex `grafica` sin `\b`.

`cafeteria` quedó en **cero**: nunca fue una categoría real, era contenido mal
ruteado. `espectaculos` quedó en 4 — el 98% de ese rubro eran canchas de paddle
y fútbol.

**Qué mejoró, medido:**

| | antes | después |
|---|---|---|
| rubros segregados por nomenclador | 13 de 73 | **11 de 72** |
| `bar_restaurante` | 1.598 spells, outlier imposible | **4.088 spells, adentro de gastronomía** |

El outlier desapareció y el chequeo de dominio pasa por la razón correcta, con
`bar_restaurante` dentro de gastronomía y con volumen real.

Hubo un segundo caso idéntico, que apareció recién al estratificar por cohorte:
el CLANAE nuevo llama al almacén de toda la vida **"venta al por menor de
productos de almacén y dietética"**, y esas 3.310 habilitaciones caían en
`dietetica` mientras el "Almacén de comestibles" viejo caía en `almacen`. El
mismo rubro partido en dos por época. Al ordenar la regla de `almacen` antes que
la de `dietetica`: almacen 6.467 -> 9.777, dietetica 5.051 -> 1.741.

---

## Paso 2b: el resultado, y un bug que invalidó los números anteriores

**Primero la corrección.** Todos los `s5` que figuraban antes en este documento
y en los commits hasta `855e8c8` estaban mal. El horizonte de 5 años caía
**justo adentro del escalón administrativo**: como casi todos los permisos duran
exactamente 5 años, la curva es plana y se desploma en ese punto —S(4,99)=0,97 y
S(5,01)=0,22 sobre los datos reales— así que `predict(5.0)` no devolvía una
supervivencia sino la posición arbitraria dentro del salto, que depende de
cuántos vencimientos cayeron unos días antes o después del aniversario exacto.

Así salía una "supervivencia de la ciudad a 5 años" del 43% donde el número
real, apenas pasado el escalón, es 21%. Y explicaba la línea base delirante de
la primera corrida por cohortes: 52%, 16% y 47% en cohortes consecutivas.

Los horizontes ahora van **después** de cada escalón: `HORIZONTES = (5.5, 10.5)`,
o sea "sobrevivió a la primera renovación" y "a la segunda". El de 3 años que
pedía el roadmap no sirve acá: antes del primer vencimiento S(3)=1 para todos
los rubros. `test_el_horizonte_no_cae_adentro_del_escalon_administrativo` mueve
el vencimiento unos días y verifica que el resultado no se mueva.

**El resultado del Paso 2b.** Estratificando por cohorte de alta, cada rubro se
compara contra la ciudad de su misma cohorte:

```
Supervivencia de la ciudad a 5,5 años     Estabilidad del orden entre cohortes
  2014-2015   12.755 spells   14,0%         2014-15 vs 2016-17   rho 0,70
  2016-2017   14.298 spells   11,3%         2014-15 vs 2018-19   rho 0,59
  2018-2019   11.404 spells   14,3%         2016-17 vs 2018-19   rho 0,76
```

**Ese rho de 0,68 promedio es el resultado que destraba la fase.** Las cohortes
son muestras independientes —locales distintos, años distintos— y dentro de cada
una la época está fija. Si el orden de los rubros fuera un artefacto de época,
cada cohorte ordenaría distinto. Ordenan parecido, así que **hay un efecto de
rubro real que extraer**, que es lo que no se podía afirmar hasta ahora.

**Una advertencia honesta:** el `efecto` todavía correlaciona 0,51 con el año
mediano del rubro. Pero eso ya no implica confusión: la estabilidad entre
cohortes descarta que el orden *sea* la época, y una asociación entre "rubro en
crecimiento" y "rubro que sobrevive" es esperable y probablemente real. Para
cuantificarlo hace falta el Cox con el año como covariable, que va con las
features.

`python -m viabilidad cohortes` deja `efecto_rubro.csv` y
`supervivencia_cohortes.csv`. **El `efecto` es la feature de rubro que hay que
usar en el modelo, no el `s5_5` crudo**: el crudo mezcla el rubro con su época.

---

## Lo que sigue

1. **El Cox con el año de alta como covariable**, junto con las features. Es lo
   que va a separar cuánto del efecto de rubro es el rubro y cuánto es que el
   rubro viene creciendo.
2. **Los 11 rubros que siguen existiendo bajo un solo nomenclador.** Algunos no
   tienen arreglo —el nomenclador viejo simplemente no tenía el concepto— pero
   conviene revisarlos uno por uno antes de meterlos al modelo.
3. El Paso 3, que ya no está bloqueado.

**En paralelo, la calibración contra Places.** `python -m viabilidad muestra`
deja 1.500 locales en `data/procesado/muestra_places.csv`, mitad predichos
cerrados y mitad abiertos, estratificados por grupo de rubro, con dirección y
coordenadas y **sin titular**. Falta la clave de API: va en `pipeline/.env`
como `GOOGLE_PLACES_API_KEY` (ya está gitignoreado). El script que consulta
Places se escribe cuando exista la clave, para poder probarlo de verdad en vez
de entregarlo a ciegas.

Lo que va a dar: de los que llamamos cerrados, cuántos Places confirma
`CLOSED_PERMANENTLY`, y de los que llamamos abiertos, cuántos `OPERATIONAL`.
Eso convierte el proxy de supuesto en número medido.

Un criterio de cierre concreto: la correlación entre `s5` y el año mediano del
rubro tiene que bajar a algo que se pueda explicar por el negocio y no por el
calendario. Con 0,58 todavía no.

---

## La calibración contra Places (hecha)

`python -m viabilidad muestra` arma la muestra y `python -m viabilidad places`
la consulta. Son ~1.500 llamadas, una sola vez, contra una cuota gratis de 5.000
por mes del SKU Text Search Pro: **costo cero**. Las respuestas crudas se
cachean en `data/procesado/places_cache.jsonl`, así que volver a correrlo no
vuelve a facturar y corregir el clasificador es gratis.

```
                 sin_dato   sigue_el_mismo   otro_negocio
predicho abierto    271          312             166
predicho cerrado    332          183             234

exactitud 61,0% | línea base 55,3% | odds ratio 2,40 | p=2,1e-10 | n=895
```

**El proxy tiene señal pero es ruidoso.** Uno de cada tres casos utilizables va
para el otro lado. Y es un piso, no la calidad real: un local puede cambiar de
nombre sin cerrar, el nombre de fantasía del GIS puede estar viejo, y Places no
indexa todo (603 de 1.498 sin dato).

Tres cosas que costó descubrir y conviene no repetir:

- **Places responde "¿hay un negocio acá?", no "¿sobrevivió el nuestro?".** Un
  `OPERATIONAL` sobre un local que dimos por cerrado es ambiguo: puede ser el
  sucesor (acertamos) o el mismo con el permiso vencido (erramos). El desempate
  es comparar el nombre contra `nombrefantasia`, que se hace localmente.
- **Hay que mirar todos los lugares devueltos, no el primero.** Places ordena
  por prominencia, y en una galería el primero es el edificio o el colegio
  mientras nuestro kiosco es el cuarto. Arreglarlo movió la exactitud de 58,4%
  a 61,0% sin una llamada más.
- **Sin nombre de fantasía la consulta no puede aportar nada**, así que esos
  locales quedan fuera de la muestra. Las primeras 22 que se consultaron sin
  nombre dieron `sin_dato` las 22: son llamadas que se pagan y no informan.

**Qué implica.** El modelo tiene techo. El score va agregado a manzana y rubro,
donde el ruido promedia, y la limitación se declara junto al número.

---

## Paso 3: las features del entorno, y el resultado que gobierna todo

`python -m viabilidad features` calcula, para cada período, qué había alrededor
**el día que abrió**: densidad comercial y competencia del mismo rubro a 100,
300 y 500 m, entropía de Shannon sobre los rubros vecinos, historial de cierres
de la zona y antigüedad comercial. 62.556 períodos en 20 segundos.

**La regla que ordena el módulo es que nada mire hacia adelante.** Un local que
abrió en 2016 solo ve el entorno de 2016. Hay tests que lo fijan; es el modo de
falla que mejoraría las métricas y arruinaría el producto.

Dos features salieron midiendo el calendario y hubo que corregirlas:
`antiguedad_zona_anios` correlacionaba **0,986** con el año de alta y
`cierres_previos_zona` **0,925**. No describían la zona sino la ventana de
observación: el histórico arranca en 2014, así que un local de ese año ve cero
predecesores terminados por construcción. Se arreglaron restándoles la media de
su cohorte de alta, que es donde sí hay señal de lugar.

### El modelo es binario, no de duración

El 55% de los períodos dura exactamente 5,0 años. Con más de la mitad de los
pares empatados, el C-index de un Cox no puede discriminar: dio **0,507** aunque
los coeficientes fueran significativos. Lo que separa a un comercio de otro es
binario —renovó o no—, así que se modela así y se mide con AUC.

El Cox igual sirvió para ver direcciones, y dos features salieron significativas
y en el sentido esperado: más cierres previos en la zona que el promedio de su
cohorte sube el riesgo (HR 1,66, p=0,004) y más antigüedad comercial lo baja
(p=0,0002). Densidad, competencia y entropía no dieron significativas.

### Los dos números, y por qué hay que reportar el peor

`python -m viabilidad modelo`:

```
ESPACIAL (barrios no vistos, mismo período)   solo rubro  ->  rubro+entorno
  5 splits                                      0,595          0,669   (+0,072)

TEMPORAL (altas posteriores, el uso real)     solo rubro  ->  rubro+entorno
  train<=2016, test 2017-2021                   0,582          0,592
  train<=2017, test 2018-2021                   0,571          0,573
  train<=2018, test 2019-2021                   0,560          0,565   (+0,006)
```

**El entorno separa lugares dentro de un período, pero no predice hacia
adelante.** En el corte espacial train y test comparten la época, así que el
modelo se apoya en regularidades de ese período que no son estables. No es fuga
de la variable objetivo, pero es optimismo: reportar solo el 0,669 sería vender
una capacidad que el modelo no tiene.

Y el producto necesita justamente la extrapolación temporal: alguien parado hoy
frente a un local vacío pregunta por el futuro, no por otro barrio.

### Qué sigue, entonces

1. **Sumar features estructurales**, que es lo que falta y lo que debería
   transferir mejor en el tiempo: zonificación (dataset `3011`), población por
   radio censal (INDEC 2022), red vial y POIs (OSM). Las que tenemos hoy salen
   todas del mismo churn comercial, que es justamente lo que cambia de período
   a período.
2. **Revisar el techo.** El objetivo tiene 61% de exactitud medida; parte de
   este 0,57 es ruido del target y no falta de señal. Conviene estimar cuánto.
3. No tocar el corte temporal para que dé mejor. Es el número honesto.

---

## Si se llega al Paso 3

Features sobre los datos ya descargados, sin fuentes nuevas:

- Competencia en radios de 100/300/500 m.
- Entropía de Shannon sobre rubros (qué tan diversa es la zona).
- Densidad comercial.
- **El entorno de las manzanas vecinas.** Este importa más de lo que parece: la
  mediana es de 3 habilitaciones por manzana y el 25% tuvo una sola en 12 años,
  así que en miles de manzanas no hay evidencia propia suficiente y el score
  tiene que apoyarse en el entorno.

La vista de trámites además trae gratis cosas que sirven acá: `barrio`, `cpc`,
`riesgo` y las superficies (total, cubierta, depósito).

Y los cuidados ya decididos en `CLAUDE.md`: validación espacial por barrio (no
aleatoria), validación temporal, y competencia en U invertida.

---

## Cosas que conviene no olvidar

- **Ante un resultado llamativo, buscar primero el artefacto.** Van cuatro veces
  que algo con pinta de hallazgo era un bug. La lista está al final de
  `docs/proximo-paso.md`.
- **Esta fuente declara columnas que no popula.** Pasó con `vigente` y con
  `cuitempresa`. Que el schema tenga el campo no quiere decir que tenga el dato:
  chequear el `null_count` antes de construir algo encima.
- **Nunca rellenar la censura como cierre.** Convierte "no sé" en "cerró".
- **El CUIT es dato personal y sale hasheado del ingest.** `razonsocial` ni se
  descarga. Los CSV que se versionan son agregados.
- El entorno de Claude Code en la nube **no llega al GIS** (403 del proxy). Todo
  lo que necesite datos frescos hay que correrlo local.
