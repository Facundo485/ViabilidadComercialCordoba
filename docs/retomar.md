# Retomar — dónde quedó y qué hacer al abrir una sesión nueva

Hoja de ruta corta para no releer todo. El contexto del proyecto está en
`CLAUDE.md` y el detalle técnico del bloqueante en `docs/proximo-paso.md`.

**Última actualización:** commit `3806245`.

---

## Estado

```
Paso 1  [OK]        La tasa vieja medía la época, no la supervivencia. Confirmado.
Paso 2  [PENDIENTE] Código listo y testeado, falta correrlo con los datos reales.  <-- acá
Paso 3  [BLOQUEADO] Features. No empezar hasta que el Paso 2 dé bien.
```

Las dos ramas (`claude/great-sagan-qw0eso` y `claude/trusting-sagan-awshxl`)
están unificadas y apuntan al mismo commit. Da igual cuál se use.

---

## Lo primero que hay que hacer

```bash
cd ~/Git/React
git pull

cd pipeline && source .venv/bin/activate
pip install -e '.[dev]'          # se agregó lifelines como dependencia

python -m viabilidad diagnostico
python -m viabilidad supervivencia
```

No hace falta volver a correr `ingest`: el histórico ya está descargado en
`data/crudo/` (144.743 habilitaciones, corrida del 13/09). `data/` está
gitignoreado, así que si se trabaja desde otra máquina sí hay que rehacerlo.

---

## Lo que hay que mirar en la salida

### 1. Cuántos períodos tienen al menos una renovación

`supervivencia` imprime una línea así:

```
144.743 habilitaciones -> N períodos de actividad (M con al menos una renovación)
```

**Ese `M` decide el rumbo:**

| Si... | Significa | Qué sigue |
|---|---|---|
| `M` es grande (decenas de miles) | El municipio carga las renovaciones como habilitaciones nuevas, que es el supuesto del módulo | Las curvas sirven. Seguir con el Paso 3 (features) |
| `M` es casi cero | El supuesto es **falso**: las renovaciones se registran de otra forma | Frenar. Averiguar cómo se registra una renovación en el GIS antes de seguir |

Esto no se pudo verificar al escribir el módulo porque el entorno donde se
programó tiene bloqueado `gis.cordoba.gob.ar` por política de egress. Es la
incógnita principal.

### 2. El plazo otorgado

`plazos()` imprime media y desvío. Si el desvío es chico, confirma sobre datos
reales lo que hasta ahora solo se probó con sintéticos: que la duración de una
habilitación suelta es una constante administrativa y no dice nada del comercio.

Si el plazo resulta **variar mucho** (por rubro o por época), hay que revisar la
lógica de consolidación, no aplicarla de taquito.

### 3. El chequeo de dominio

El módulo lo imprime solo y lo marca `OK`, `EMPATE` o `AL REVÉS`:

```
Chequeo de dominio — supervivencia a 5 años:
  gastronomía XX%  vs  farmacia YY%  ->  ???
```

Gastronomía tiene que quedar **por debajo** de farmacia. Si da al revés o
empatado, el objetivo sigue midiendo otra cosa y el Paso 3 sigue bloqueado.

---

## Si los tres chequeos dan bien: Paso 3

Features sobre los datos ya descargados, sin fuentes nuevas:

- Competencia en radios de 100/300/500 m.
- Entropía de Shannon sobre rubros (qué tan diversa es la zona).
- Densidad comercial.
- **El entorno de las manzanas vecinas.** Este importa más de lo que parece: la
  mediana es de 3 habilitaciones por manzana y el 25% tuvo una sola en 12 años,
  así que en miles de manzanas no hay evidencia propia suficiente y el score
  tiene que apoyarse en el entorno.

Y los cuidados que ya están decididos en `CLAUDE.md`: validación espacial por
barrio (no aleatoria), validación temporal, y competencia en U invertida.

---

## Qué se hizo en la sesión anterior

| Commit | Qué |
|---|---|
| `7aebf7c` | Paso 1: `diagnostico.py`, confirma que la tasa reproducía el nomenclador |
| `3806245` | Paso 2: `supervivencia.py`, Kaplan-Meier sobre períodos de actividad |

**Paso 1 — qué se encontró.** La tasa `vigentes/total` por rubro no se *parece*
a la proporción de habilitaciones cargadas bajo el nomenclador nuevo: **es** esa
proporción, en 48 de 65 rubros. Un modelo de dos parámetros —el nomenclador
viejo no sobrevive nunca, el nuevo sobrevive ~0,66 sin importar el rubro—
explica el 87% de la varianza entre rubros. Es decir: la tabla de supervivencia
por rubro no contenía información sobre los rubros.

**Paso 2 — la corrección al plan.** La receta que traía `docs/proximo-paso.md`
(`duración = fechavencimientohab - fechahabaprobada`) reproducía el mismo bug
con mejor disfraz: esa resta es el plazo que otorgó el municipio, no la vida del
comercio. Lo que distingue al que sobrevive no es que su permiso venza —vence
siempre— sino **si lo renovó**. Por eso la unidad de análisis pasó a ser el
período de actividad de un titular en una dirección.

Hay un test que impide volver atrás:
`test_sin_consolidar_los_dos_rubros_se_ven_iguales`.

---

## Cosas que conviene no olvidar

- **Ante un resultado llamativo, buscar primero el artefacto.** Van tres veces
  que algo con pinta de hallazgo era un bug. La lección completa está al final
  de `docs/proximo-paso.md`.
- **Nunca rellenar la censura como cierre.** Convierte "no sé" en "cerró".
- **`cuitempresa` y `razonsocial` son datos personales.** Se usan para unir
  registros, nunca se muestran. Los CSV que se versionan son agregados.
- El entorno de Claude Code en la nube **no llega al GIS** (403 del proxy). Todo
  lo que necesite datos frescos hay que correrlo local.
