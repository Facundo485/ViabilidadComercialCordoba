Unas semanas construyendo un score de viabilidad comercial para Córdoba: dada una manzana y un rubro, qué probabilidad hay de que el negocio sobreviva.

Lo cierro con un modelo que anda apenas. Publico igual, porque el límite que encontré no es de mi modelo: es del dato.

**Medí contra lo que ya existía, antes de festejar.** La Municipalidad publica un indicador por parcela: habilitaciones vigentes sobre el total. Mi comparación decía que empataba, así que fui a ver por qué. En las manzanas con una sola habilitación —el 40% de la ciudad— ese indicador coincide con el destino de ese único local el 95,9% de las veces. No lo predice: se cuenta a sí mismo.

**Después medí mi propia variable objetivo.** Nadie registra los cierres: un cierre es un no-evento, nadie avisa. Lo único observable es si el comercio renovó el permiso a los 5 años. Tomé 1.500 locales y le pregunté a Google Places qué opera hoy en esas direcciones: el proxy acierta el 61%.

Eso se vuelve un número duro. Con esa sensibilidad y especificidad, ningún modelo entrenado sobre esta etiqueta pasa de 0,608 de AUC. El mío va 0,593: el 87% del margen disponible.

**Y medí si la solución obvia servía.** Etiquetar a mano parecía el camino. Tracé la curva de aprendizaje antes de encararlo: de 200 a 350 etiquetas, 0,636 → 0,631. Plana. Etiquetar compra precisión de medición, no performance. Era el error caro, y costó una tarde evitarlo.

Lo mejor salió de mirar el mapa y desconfiar: **los barrios con más bares son los de menor supervivencia individual.** Centro tiene 509 y sobrevive el 9%. Poeta Lugones tiene 43 y sobrevive el 25,6%. Un corredor gastronómico excelente rota más rápido: el alquiler y la competencia se quedan con el margen. Se ve en la segunda imagen, con el centro pintado en frío.

Lo que obliga a ser preciso sobre qué mide un score así: si el negocio sobrevive, no si la ubicación es buena. En gastronomía apuntan para lados opuestos.

No sigo con esto. Pero prefiero un mapa que no miente sobre su incertidumbre a un número lindo que nadie auditó — y el techo va a estar ahí para cualquiera que lo intente con habilitaciones de otro municipio.

Mapa navegable y código, en el primer comentario 👇
