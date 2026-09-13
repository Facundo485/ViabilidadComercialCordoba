# Próximo paso — la tasa de supervivencia está confundida con la antigüedad

**Estado:** Paso 1 cerrado. Paso 2 corrido sobre datos reales y **a medias**: la
consolidación de renovaciones ya funciona y el chequeo de dominio da OK, pero la
época sigue explicando buena parte de la tabla por rubro (ver "Paso 2b"). No
construir features hasta cerrar eso.
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

## Paso 2 — reemplazar la tasa por análisis de supervivencia (corrido, a medias)

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

    spell  = trámites sucesivos de (titular, nro_catastral) sin un hueco
             mayor a un año entre el vencimiento de uno y el alta del
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

### Estado — corrido sobre datos reales el 13/09

La primera corrida real dio **cero renovaciones**, exactamente cero:

```
144.743 habilitaciones -> 144.743 períodos de actividad (0 con al menos una renovación).
```

No era que el municipio no registrara las renovaciones. Era que la clave de
consolidación, `cuitempresa`, **viene nula en el 100% de las filas** del
histórico, igual que `vigente`. El schema la declara y nadie la popula. Como las
filas sin CUIT quedan cada una como su propio spell, el resultado no podía ser
otro. Verificado contra el GIS en vivo, no solo contra el parquet.

**El destrabe.** Otro servicio del mismo GIS sí la trae poblada:

```
ComerdioIndustria/Habilitaciones_Comerciales_Vista/FeatureServer/0
```

71.287 filas, cero nulos en `cuitempresa`, 46.767 titulares distintos, y su
campo `id` matchea `id_tramite` del histórico en los 71.287. `ingest` la baja,
hashea el CUIT (blake2b con sal, ver `config.SAL_CUIT`) y lo adjunta como
`titular`. El número no queda escrito en claro en ningún parquet y
`razonsocial` ni se descarga. Es seudonimización, no anonimización: el espacio
de CUITs es chico y un hash con sal conocida se invierte por fuerza bruta. La
protección real sigue siendo que `data/` no se versiona.

**El error de conteo que apareció de paso.** Las 144.743 filas del histórico no
son 144.743 habilitaciones: son **71.287 trámites**. Un trámite habilita varios
rubros a la vez (media 2,03, máximo 73) y aparece una vez por cada uno. Todos
los conteos anteriores estaban inflados al doble. La unidad es `id_tramite`, y
`por_tramite()` colapsa el histórico antes de consolidar.

Esto además contradice lo que decía `CLAUDE.md` sobre que en Córdoba un local no
está habilitado bajo varios rubros a la vez. Sí lo está, igual que en CABA.

**Cómo quedó la corrida con el titular real:**

```
144.743 filas -> 71.287 trámites -> 62.560 períodos de actividad
                                    7.075 con al menos una renovación (11,3%)
Plazo otorgado: 4,83 +/- 0,76 años (mediana 5,00)
Chequeo de dominio: gastronomía 40,3% vs farmacia 43,5% -> OK
```

Los tres chequeos que pedía este documento dan bien.

### Paso 2b — por qué esto todavía no cierra el bloqueante

Pasar el chequeo de dominio no es lo mismo que haber sacado el artefacto.

| Señal | Valor | Lectura |
|---|---|---|
| Renovaciones | 11,3% de los spells | Hay señal, pero el 89% sigue terminando en el escalón administrativo de los 5 años |
| `mediana_anios` | 4,999316 en los 76 rubros | Sigue siendo el plazo del permiso. **No leerla como resultado** |
| `s5` vs año mediano del rubro | Pearson 0,71 | La época sigue explicando buena parte de la tabla. Antes era 0,92 |
| Ídem, restringido a altas ≤2019 | Pearson 0,58 | Baja, pero no desaparece |
| `bar_restaurante` en esa cohorte | s5 = 95,3% con 215 spells | El outlier imposible del Paso 1, más chico. Sigue siendo un artefacto |

Lo que hay que hacer, en orden:

1. **Entender el 95% de `bar_restaurante`.** La sospecha: es un rubro que solo
   existe en el nomenclador nuevo, así que todos sus spells son recientes y
   quedan censurados. Si es eso, el problema no es Kaplan-Meier sino que hay
   rubros sin cohortes viejas, y compararlos contra los que sí las tienen es
   comparar épocas.
2. **Estratificar por cohorte de alta** — una curva por rubro y año de alta — en
   vez de mezclar doce años de altas en una sola curva. Si el orden entre rubros
   se mantiene dentro de cada cohorte, la señal es real.
3. **Ajustar por época explícitamente**, con el año de alta como covariable en
   un Cox, en lugar de confiar en que la censura lo resuelva sola.

Criterio de cierre: la correlación entre `s5` y el año mediano del rubro tiene
que bajar a algo explicable por el negocio y no por el calendario. Con 0,58 no.

### Los tests

Cubierto por 14 tests entre `test_supervivencia.py` y `test_pipeline.py`. Los
que fijan las decisiones:

- `test_sin_consolidar_los_dos_rubros_se_ven_iguales`: construye dos rubros con
  vidas de 20 y 5 años y verifica que, medidos trámite por trámite, den la misma
  mediana. Si alguien saca la consolidación, falla.
- `test_corta_si_la_vista_trae_el_titular_vacio`: el modo de falla que ya se dio
  dos veces con esta fuente. Si la vista empezara a devolver el CUIT nulo, el
  ingest corta en vez de producir curvas planas en silencio.
- `test_el_cuit_no_queda_en_el_parquet`: el dato personal sale hasheado o no
  sale.
- `test_un_tramite_no_se_cuenta_dos_veces_en_el_mismo_rubro`: el nomenclador
  viejo y el CLANAE nuevo describen lo mismo, y un trámite habilitado bajo ambos
  caía dos veces en el mismo nivel2.

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

Cuatro veces seguidas, lo que parecía un resultado era un artefacto: `vigente`
nulo leído como cierre, la antigüedad disfrazada de supervivencia, la receta del
Paso 2 que iba a medir el plazo del permiso creyendo medir la vida del comercio,
y la consolidación que devolvía cero renovaciones porque consolidaba contra una
columna vacía. **Ante un resultado llamativo, primero buscar el artefacto.** Un 95,6%
de supervivencia en gastronomía es un bug, no un hallazgo.

La tercera agrega algo a la lección: el artefacto no estaba en el código sino en
el plan, y venía envuelto en una herramienta correcta. Usar `lifelines` no
protege de medir la variable equivocada. **Antes de aplicar un método, medir el
supuesto que lo habilita** — que es para lo que existe `plazos()`.

La cuarta agrega otra: **esta fuente declara columnas que no popula.** Pasó con
`vigente` y con `cuitempresa`, las dos veces con la variable objetivo de por
medio. Que el schema tenga el campo no quiere decir que tenga el dato: mirar el
`null_count` antes de construir algo encima, y hacer que el pipeline corte solo
cuando una columna clave venga vacía.

Y una quinta, más chica pero cara: **confirmar de qué es una fila antes de
contarla.** Durante toda la Fase 1 se reportaron 144.743 habilitaciones donde
había 71.287 trámites, porque nadie chequeó si `id_tramite` se repetía.
