# Próximo paso — la tasa de supervivencia está confundida con la antigüedad

**Estado:** Paso 1 hecho, hipótesis confirmada. El bloqueante sigue abierto: la
tasa cruda no se puede usar y todavía no está el análisis de supervivencia que
la reemplaza (Paso 2). No construir features hasta resolverlo.
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

## Paso 2 — reemplazar la tasa por análisis de supervivencia

No es un parche: es lo que el roadmap ya preveía en Fase 3.2. La pregunta deja
de ser *"¿sigue vigente hoy?"* —que premia al que abrió hace poco— y pasa a ser
*"¿qué probabilidad tiene de llegar a los 3 años?"*, comparable entre rubros y
entre épocas.

Con `lifelines`:

- **Duración:** `fechavencimientohab - fechahabaprobada` para las vencidas;
  `hoy - fechahabaprobada` para las que siguen vigentes.
- **Evento:** 1 si venció, 0 si sigue vigente (censurada a derecha).
- **Kaplan-Meier por rubro** para las curvas de supervivencia.
- **Métrica comparable:** supervivencia a 3 y a 5 años, no "tasa de vigentes".
- **Cox** después, para meter las variables explicativas.

Sanity check: la curva de gastronomía tiene que quedar **por debajo** de la de
farmacia. Si da al revés, el problema sigue ahí.

### Cuidados

- **Validación espacial, no aleatoria:** particionar por `barrio_identificado`.
  Un split aleatorio deja vecinos en train y test e infla las métricas.
- **Validación temporal:** entrenar con años previos a un corte, testear después.
- **Competencia en U invertida:** pocos competidores puede ser mercado
  inexistente; muchos, saturación; un nivel intermedio, aglomeración
  beneficiosa. No asumir monotonicidad.
- Revisar si una renovación figura como habilitación nueva. Si es así, un local
  de 20 años aparece como varios cortos y hay que consolidarlo por
  `cuitempresa` + `nro_catastral` antes de medir duraciones.

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

python -m viabilidad todo      # descarga, agrega y escribe los resúmenes
pytest
```

`data/` está gitignoreado; los resúmenes de `referencia/` y los `resumen_*.csv`
sí se versionan (son agregados, sin CUIT ni razón social).

## Lección de esta fase

Dos bugs seguidos produjeron tablas con pinta de resultado en vez de fallar:
`vigente` nulo leído como cierre, y ahora la antigüedad disfrazada de
supervivencia. **Ante un resultado llamativo, primero buscar el artefacto.** Un
95,6% de supervivencia en gastronomía es un bug, no un hallazgo.
