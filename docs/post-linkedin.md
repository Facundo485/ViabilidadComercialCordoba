Pasé unos meses construyendo un score de viabilidad comercial para Córdoba: dada una manzana y un rubro, qué probabilidad hay de que el negocio sobreviva.

Lo termino con un modelo que anda apenas, y con tres cosas que aprendí que valen más que el modelo.

**1. Medí contra lo que ya existía, antes de festejar.**

La Municipalidad publica un indicador por parcela: habilitaciones vigentes sobre el total. Mi primera comparación decía que yo empataba. Fui a ver por qué.

En las manzanas con una sola habilitación —el 40% de la ciudad— ese indicador coincide con el destino de ese único local el 95,9% de las veces. No lo está prediciendo: **se está contando a sí mismo.** Y a más de la mitad de la ciudad le da 0% o 100%, veredictos extremos apoyados en uno o dos locales.

Mi score no es más exacto. Es honesto sobre lo que no sabe.

**2. Mi variable objetivo es un proxy, y lo medí en vez de asumirlo.**

Nadie registra los cierres. Un cierre es un no-evento: nadie va a avisar. Lo único observable es si el comercio renovó el permiso a los 5 años.

Así que tomé 1.500 locales y fui a preguntarle a Google Places qué hay hoy en esas direcciones. El proxy acierta el 61% de las veces. Real —duplica largo las chances, p = 2e-10— y ruidoso: uno de cada tres casos va para el otro lado.

Eso se puede convertir en un número duro. Con esa sensibilidad y especificidad, **ningún modelo entrenado sobre esta etiqueta puede pasar de 0,608 de AUC.** El mío va 0,593 en validación temporal: el 87% del margen disponible.

El cuello de botella no eran mis variables. Era el dato.

**3. Cuando eso no me gustó, medí si etiquetar más lo arreglaba. No lo arregla.**

La respuesta intuitiva era etiquetar miles de locales a mano y entrenar sobre verdad limpia. Antes de gastar meses en eso, tracé la curva de aprendizaje: de 200 a 350 etiquetas, 0,636 → 0,631. Plana. El techo con etiquetas perfectas queda en ~0,64.

Etiquetar compra **precisión de medición, no performance.** Hubiera sido el error caro, y lo evité midiendo algo que tardó una tarde.

---

Dos bugs que encontró el dueño del dominio mirando el mapa, no los tests:

"¿Por qué zonas alejadas del centro puntúan alto en indumentaria?" Estaba promediando la superficie de los locales por manzana. La superficie es un atributo **del negocio**, no del lugar: una manzana periférica con un galpón grande parecía una zona comercial.

"En Güemes y Nueva Córdoba hay muchos bares y el mapa los pone tres puntos abajo." También cierto. Y al ir a mirar apareció lo más interesante que encontré en todo el proyecto: **los barrios con más bares son los de menor supervivencia individual.** Centro tiene 509 bares y sobrevive el 9%. Poeta Lugones tiene 43 y sobrevive el 25,6%.

Un corredor gastronómico excelente rota más rápido, porque el alquiler y la competencia se quedan con el margen. Lo que obliga a ser preciso sobre qué mide un score así: **la probabilidad de que el negocio sobreviva, no la calidad de la ubicación.** En gastronomía apuntan para lados opuestos.

---

Otras cosas que dejé documentadas porque me costaron: casi todos los permisos duran 5 años exactos, así que la curva de supervivencia tiene un escalón ahí —S(4,99)=0,97, S(5,01)=0,22— y evaluarla en el aniversario me hizo reportar 43% donde el número real era 21%. Las imágenes de Sentinel-2 cambiaron de calibración en 2022 y sin corregir ese offset la serie temporal de densidad construida no correlacionaba ni consigo misma. Un `\b` faltante en un regex mandó 2.896 bares al rubro "panadería", porque "empanaderías" contiene "panadería".

No voy a seguir con esto. Lo que tengo es un mapa que ordena bien y no miente sobre su incertidumbre, sobre un dato que no da para más.

Pero prefiero eso a un número lindo que nadie auditó. Y publicar el techo que encontré me parece más útil que publicar el modelo: si alguien intenta esto con datos de habilitaciones de cualquier municipio argentino, el límite lo va a encontrar igual. Mejor saberlo antes.

Código y metodología, abiertos. Si trabajás con datos públicos municipales y te topaste con lo mismo, escribime.
