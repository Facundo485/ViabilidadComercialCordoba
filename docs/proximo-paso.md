# Próximo paso — la tasa de supervivencia está confundida con la antigüedad

**Estado:** bloqueante abierto. No construir features hasta resolverlo.
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

## Paso 1 — confirmar la hipótesis

```bash
cd pipeline && source .venv/bin/activate
python -c "
import polars as pl
h = pl.read_parquet('data/crudo/historial.parquet')
r = (h.filter(pl.col('nivel2')!='otro')
      .group_by('nivel2')
      .agg(pl.len().alias('n'),
           pl.col('fechahabaprobada').dt.year().median().alias('anio_mediano'),
           pl.col('vigente').mean().round(3).alias('tasa'))
      .filter(pl.col('n')>=300).sort('tasa', descending=True))
print(r)
print('correlacion anio_mediano vs tasa:',
      round(r.select(pl.corr('anio_mediano','tasa')).item(), 3))
"
```

Una correlación alta (> 0,7) confirma que la tasa cruda mide antigüedad y no
sirve para comparar rubros entre sí.

Vale la pena mirar también si el nomenclador viejo y el nuevo se reparten por
época, cruzando `rubronombre` (si está en MAYÚSCULAS o no) contra el año.

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
