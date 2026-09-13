# Próximo paso — la tasa de supervivencia está confundida con la antigüedad

**Estado:** Pasos 1 y 2 hechos. La hipótesis quedó confirmada y el análisis de
supervivencia está implementado y testeado, pero **todavía no corrió sobre los
datos reales**: falta validarlo con el histórico descargado (ver "Estado" en el
Paso 2). No construir features hasta ver esa salida.
**Contexto general:** `CLAUDE.md`. **Plan por fases:** `docs/roadmap.md`.

---

## Qué pasa

El pipeline corre entero y produce, por manzana y por rubro, una tasa
`vigentes / total`. Esa tasa **no mide supervivencia**: mide qué tan recientes
son las habilitaciones de ese rubro.

Resultados de la última corrida (133.379 habilitaciones, tasa global 31,8%):

| nivel2 | habilitaciones | tasa |
|---|---|---|
| `bar_restaurante` | 1.781 | **95,6%** |
| `electrodomesticos` | 352 | 83,2% |
| `dietetica` | 5.051 | 61,6% |
| ... | | |
| `almacen` | 6.467 | 9,0% |
| `cafeteria` | 324 | **2,5%** |
| `intermediarios` | 479 | **0,0%** |
| `regaleria` | 1.527 | **0,0%** |

Tres cosas imposibles:

1. Los bares son el rubro de mayor mortalidad que existe. 95,6% no ocurre.
2. `bar_restaurante` y `cafeteria` son el mismo negocio. No pueden dar 95,6% y
   2,5%.
3. Cero sobrevivientes de 1.527 regalerías no es un fenómeno, es un artefacto.

## Por qué pasa

La vigencia se deriva de `fechavencimientohab > hoy`, y los permisos duran ~5
años. Entonces una habilitación aprobada hace menos de 5 años figura como
vigente **por construcción, no por mérito**: todavía no tuvo oportunidad de
vencer.

`rubronombre` mezcla dos nomencladores: el municipal viejo (Título, con acentos)
y el CLANAE/CIIU (MAYÚSCULAS). Si cada uno se usó en una época distinta, el
rubro queda correlacionado con el año de habilitación, y la tasa termina
midiendo el nomenclador en vez del negocio.

Encaja con el patrón observado: `cafeteria` matchea sobre todo nombres viejos
(`"Bar, confiterías, pizzerías..."`) y `bar_restaurante` sobre nombres nuevos
(`"SERVICIOS DE RESTAURANTES Y CANTINAS..."`).

Es la trampa que `CLAUDE.md` ya documentaba en "La variable objetivo": *"Los
permisos duran ~5 años. Una habilitación aprobada hace menos de eso todavía no
tuvo oportunidad de vencer: es censura a derecha, no éxito."*

---

## Paso 1 — confirmar la hipótesis (hecho: confirmada)

```bash
cd pipeline && source .venv/bin/activate
python -m viabilidad diagnostico
```

El chequeo quedó como módulo (`pipeline/src/viabilidad/diagnostico.py`) en vez
de un `python -c` suelto: es el tipo de comprobación que hay que repetir cada
vez que se toca el mapeo de rubros o la derivación de la vigencia.

Corre por dos vías independientes. La del **nomenclador** usa solo tablas
versionadas (`referencia/mapeo_rubros.csv` y `resumen_rubros.csv`), así que no
necesita red ni haber descargado el GIS. La del **año** necesita
`data/crudo/historial.parquet` y se omite sola, con un aviso, si no está.

### Resultado

Confirmada, y por un margen mayor al esperado. Sobre los 65 rubros de nivel 2
con 300 habilitaciones o más:

| | |
|---|---|
| Correlación `frac_nuevo` vs `tasa` | **Pearson 0,716 · Spearman 0,758** |
| Rubros con \|tasa − frac_nuevo\| < 0,10 | **48 de 65** |
| Ajuste `tasa = p · frac_nuevo` | p = 0,664, **R² = 0,869** |

`frac_nuevo` es la proporción de habilitaciones del rubro cargadas bajo el
nomenclador CLANAE/CIIU (MAYÚSCULAS). La correlación supera el umbral de 0,7
que fijaba este documento, pero el hallazgo fuerte es otro: **para dos tercios
de los rubros la tasa no se parece a `frac_nuevo`, es `frac_nuevo`.**

| nivel2 | habilitaciones | tasa | frac_nuevo |
|---|---|---|---|
| `bar_restaurante` | 1.781 | 95,6% | 98,9% |
| `electrodomesticos` | 352 | 83,2% | 100% |
| `transporte` | 947 | 15,6% | 15,7% |
| `belleza` | 520 | 5,8% | 6,0% |
| `locutorio` | 360 | 3,1% | 3,6% |
| `cafeteria` | 324 | 2,5% | 2,5% |
| `regaleria` | 1.527 | 0,0% | 0,0% |
| `intermediarios` | 479 | 0,0% | 0,0% |

El ajuste por el origen dice qué está pasando, y es un modelo falsable: una
habilitación del nomenclador viejo **no sobrevive nunca** (tasa 0 en los dos
rubros que son 100% viejos), y una del nuevo sobrevive con probabilidad ~0,66
**sin importar el rubro**. Con esos dos números y nada más se explica el 87% de
la varianza entre rubros. Es decir: la tabla de supervivencia por rubro no
contiene información sobre los rubros.

Eso también responde el misterio de `bar_restaurante` (95,6%) contra
`cafeteria` (2,5%), que son el mismo negocio: uno matchea nombres nuevos y el
otro nombres viejos. No son dos mercados distintos, son dos épocas de carga.

Los 17 rubros que se apartan del patrón son los que tienen algo que decir
—`forrajeria` (100% nuevo, tasa 22,7%), `oficina`, `peluqueria`,
`taller_mecanico`, `heladeria`—, y son justamente los que la tasa cruda
ordena mal.

### Lo que queda pendiente de este paso

El cruce contra el **año mediano** de habilitación no se pudo correr: el
entorno de esta sesión tiene bloqueado `gis.cordoba.gob.ar` por política de
egress (403 al CONNECT del proxy), así que no hay forma de regenerar
`data/crudo/historial.parquet`, que está gitignoreado. El código está escrito y
cubierto por tests; corre solo con hacer `python -m viabilidad ingest` desde una
red que llegue al GIS.

No es un bloqueante para el Paso 2. La vía del nomenclador ya confirma que la
tasa no sirve para comparar rubros, y el nomenclador es un marcador de época:
el cruce contra el año mediría lo mismo con otro reloj.

## Paso 2 — reemplazar la tasa por análisis de supervivencia (implementado)

```bash
cd pipeline && source .venv/bin/activate
python -m viabilidad supervivencia
```

No es un parche: es lo que el roadmap ya preveía en Fase 3.2. La pregunta deja
de ser *"¿sigue vigente hoy?"* —que premia al que abrió hace poco— y pasa a ser
*"¿qué probabilidad tiene de llegar a los 3 años?"*, comparable entre rubros y
entre épocas.

### Corrección: la receta de este documento estaba mal

Como estaba escrita acá, la construcción era:

    duración = fechavencimientohab - fechahabaprobada   (para las vencidas)
    evento   = 1 si venció

**Tomada literal, reproduce el bug del Paso 1 en forma más sofisticada.** Esa
resta no es la vida del comercio: es el plazo que el municipio otorgó. Si los
permisos duran ~5 años, toda habilitación vencida dura ~5 años por definición
administrativa, y toda vigente dura menos porque todavía no llegó. Kaplan-Meier
sobre eso da una curva plana con un escalón a los 5 años, y lo único que separa
a un rubro de otro vuelve a ser qué proporción de sus registros es reciente.
Época disfrazada de supervivencia, otra vez, pero ahora con `lifelines` adelante
dándole aire de rigor.

Lo que distingue a un comercio que sobrevive no es que su permiso venza —vence
siempre— sino **si lo renovó**. Así que la unidad de análisis no es la
habilitación sino el **período de actividad** de un titular en una dirección,
que puede encadenar varias:

    spell  = habilitaciones sucesivas de (cuitempresa, nro_catastral) sin un
             hueco mayor a un año entre el vencimiento de una y el alta de la
             siguiente
    cierre = la cobertura caducó y nadie renovó
    censura = todavía tiene permiso vigente

El documento traía esto como una advertencia menor al final del Paso 2
("revisar si una renovación figura como habilitación nueva"). No es menor: es
la diferencia entre medir el negocio y medir el calendario.

### Qué hace el módulo

`pipeline/src/viabilidad/supervivencia.py`:

| Función | Rol |
|---|---|
| `plazos()` | Mide el supuesto antes de usarlo: ¿el plazo otorgado es constante? |
| `consolidar()` | Encadena renovaciones en períodos de actividad |
| `duraciones()` | Duración y evento, con censura a derecha explícita |
| `kaplan_meier()` | Curvas por nivel1 y nivel2, con supervivencia a 3 y 5 años |

Dos cuidados que no estaban en el plan y que el código aplica:

- **Período de gracia.** Un permiso vencido hace un mes todavía puede renovarse
  fuera de término. Darlo por cerrado inventa cierres, y los inventa justo entre
  los más recientes, que es exactamente el sesgo que se está tratando de sacar.
  Dentro del año de gracia se censura.
- **Huecos.** Un titular que se va y vuelve tres años después no renovó: son dos
  comercios. Un hueco mayor a un año abre un período nuevo.

### Estado

Implementado y cubierto por 7 tests, **pero sin correr sobre los datos reales**:
en esta sesión `gis.cordoba.gob.ar` está bloqueado por política de egress, así
que no hay `data/crudo/historial.parquet`.

Los tests corren sobre datos sintéticos que imitan la estructura real (plazos de
5 años fijos, renovaciones como filas nuevas). Uno de ellos,
`test_sin_consolidar_los_dos_rubros_se_ven_iguales`, es el que fija la
corrección: construye dos rubros con vidas de 20 y 5 años y verifica que, medidos
habilitación por habilitación, den la misma mediana. Si alguien saca la
consolidación, ese test falla.

**Lo que hay que mirar al correrlo con datos reales**, en este orden:

1. `plazos()`: si el desvío es chico, el diagnóstico de arriba queda confirmado
   sobre los datos y no solo sobre los sintéticos. Si el plazo resulta variar
   mucho por rubro, hay que revisar esta lógica, no aplicarla de taquito.
2. Cuántos períodos quedan con al menos una renovación. Si son casi cero, el
   supuesto de que las renovaciones se cargan como altas nuevas es falso y hay
   que averiguar cómo se registra realmente una renovación antes de seguir.
3. El chequeo de dominio: gastronomía tiene que quedar **por debajo** de
   farmacia. El módulo lo imprime y lo marca. Si da al revés o empatado, el
   objetivo sigue midiendo otra cosa y el Paso 3 sigue bloqueado.

### Lo que falta

- **Cox** con las variables explicativas, una vez que existan las features.
- **Validación espacial**, particionando por `barrio_identificado`: un split
  aleatorio deja vecinos en train y test e infla las métricas.
- **Validación temporal**: entrenar con años previos a un corte, testear después.
- **Competencia en U invertida**: pocos competidores puede ser mercado
  inexistente; muchos, saturación; un nivel intermedio, aglomeración
  beneficiosa. No asumir monotonicidad.

## Paso 3 — recién ahí, las features

Sobre los datos ya descargados, sin fuentes nuevas: competencia en radios de
100/300/500m, entropía de Shannon sobre rubros, densidad comercial, y el entorno
de las manzanas vecinas.

Ese último importa: la mediana es de 3 habilitaciones por manzana y el 25% tuvo
una sola en 12 años, así que en miles de manzanas no hay evidencia propia
suficiente y el score tiene que apoyarse en el entorno.

---

## Cómo correr lo que ya hay

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cd .. && pre-commit install && cd pipeline

python -m viabilidad todo            # descarga, agrega y escribe los resúmenes
python -m viabilidad diagnostico     # Paso 1: ¿la tasa mide el nomenclador?
python -m viabilidad supervivencia   # Paso 2: Kaplan-Meier por rubro
pytest
```

`diagnostico` corre sin haber descargado nada (se apoya en tablas versionadas) y
amplía el análisis si encuentra el histórico. `supervivencia` sí necesita
`ingest` previo.

`data/` está gitignoreado; los resúmenes de `referencia/` y los `resumen_*.csv`
sí se versionan (son agregados, sin CUIT ni razón social).

## Lección de esta fase

Tres veces seguidas, lo que parecía un resultado era un artefacto: `vigente`
nulo leído como cierre, la antigüedad disfrazada de supervivencia, y la receta
del Paso 2 que iba a medir el plazo del permiso creyendo medir la vida del
comercio. **Ante un resultado llamativo, primero buscar el artefacto.** Un 95,6%
de supervivencia en gastronomía es un bug, no un hallazgo.

La tercera agrega algo a la lección: el artefacto no estaba en el código sino en
el plan, y venía envuelto en una herramienta correcta. Usar `lifelines` no
protege de medir la variable equivocada. **Antes de aplicar un método, medir el
supuesto que lo habilita** — que es para lo que existe `plazos()`.
