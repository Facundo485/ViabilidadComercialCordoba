# Retomar — dónde quedó y qué hacer al abrir una sesión nueva

Hoja de ruta corta para no releer todo. El contexto del proyecto está en
`CLAUDE.md` y el detalle técnico del bloqueante en `docs/proximo-paso.md`.

**Última actualización:** corrida del 13/09 con la vista de trámites.

---

## Estado

```
Paso 1  [OK]         La tasa vieja medía la época, no la supervivencia. Confirmado.
Paso 2  [A MEDIAS]   Ya hay renovaciones y el chequeo de dominio da OK, pero la
                     época sigue explicando buena parte de la tabla.          <-- acá
Paso 3  [BLOQUEADO]  Features. No empezar hasta cerrar lo de arriba.
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
Chequeo de dominio: gastronomía 40,3% vs farmacia 43,5% -> OK
```

Los tres chequeos de la sesión anterior dan bien. **Pero el bloqueante no está
cerrado**, y conviene ser explícito sobre por qué:

| Señal | Valor | Lectura |
|---|---|---|
| Renovaciones | 11,3% de los spells | Hay señal, pero el 89% sigue terminando en el escalón administrativo de los 5 años |
| `mediana_anios` | 4,999316 en los 76 rubros | La mediana sigue siendo el plazo del permiso: **no leerla como resultado** |
| `s5` vs año mediano del rubro | Pearson 0,71 | La época sigue explicando buena parte de la tabla (antes era 0,92) |
| Ídem, en cohortes de alta ≤2019 | Pearson 0,58 | Baja, pero no desaparece |
| `bar_restaurante` en la cohorte | s5 = 95,3% con 215 spells | El mismo outlier imposible del Paso 1, más chico. Es un artefacto |

O sea: el chequeo de dominio pasó, pero pasar un chequeo no es lo mismo que
haber sacado el artefacto. Lo de siempre en este proyecto — ante un resultado
llamativo, buscar primero el artefacto.

---

## Hallazgo del 13/09: el outlier era taxonomía, no censura

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

**Arreglar el mapeo es probablemente la mitad del Paso 2b**, y se hace editando
`referencia/mapeo_rubros.csv` fila por fila, que es para lo que existe ese CSV.

---

## Lo que sigue (Paso 2b)

1. **Arreglar el mapeo de rubros** (ver la sección de arriba). Empezar por
   sacar la gastronomía vieja de `panaderia` y unirla con `bar_restaurante`, y
   por los 13 rubros segregados por nomenclador. Después volver a medir la
   correlación con la época: si baja mucho, el resto del Paso 2b es más chico
   de lo que parece.
2. **Medir `s5` dentro de cohortes de alta fijas** (una curva por rubro y año de
   alta) en vez de mezclar doce años de altas en una sola curva. Si el orden
   entre rubros se mantiene dentro de cada cohorte, la señal es real.
3. **Ajustar por época explícitamente** —el año de alta como covariable en un
   Cox— en lugar de esperar que la censura lo resuelva sola.
4. Recién con eso, el Paso 3.

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
