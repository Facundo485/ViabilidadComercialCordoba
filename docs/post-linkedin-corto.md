Pasé unos meses construyendo un score de viabilidad comercial para Córdoba: dada una manzana y un rubro, qué probabilidad hay de que el negocio sobreviva.

Lo cierro con un modelo que anda apenas. Publico igual, porque lo que encontré no es un límite de mi modelo: es del dato.

**Medí contra lo que ya existía, antes de festejar.** La Municipalidad publica un indicador por parcela: habilitaciones vigentes sobre el total. Mi primera comparación decía que yo empataba, así que fui a ver por qué.

En las manzanas con una sola habilitación —el 40% de la ciudad— ese indicador coincide con el destino de ese único local el 95,9% de las veces. No lo está prediciendo: se está contando a sí mismo.

**Después medí mi propia variable objetivo.** Nadie registra los cierres; un cierre es un no-evento, nadie va a avisar. Lo único observable es si el comercio renovó el permiso a los 5 años. Tomé 1.500 locales y le pregunté a Google Places qué opera hoy en esas direcciones: el proxy acierta el 61%.

Eso se convierte en un número duro. Con esa sensibilidad y especificidad, ningún modelo entrenado sobre esta etiqueta puede pasar de 0,608 de AUC. El mío va 0,593: el 87% del margen disponible.

**Y medí si la solución obvia servía.** Etiquetar miles de locales a mano parecía el camino. Antes de gastar meses, tracé la curva de aprendizaje: de 200 a 350 etiquetas, 0,636 → 0,631. Plana. Etiquetar compra precisión de medición, no performance. Hubiera sido el error caro del proyecto y costó una tarde evitarlo.

Lo mejor que encontré, igual, salió de mirar el mapa y desconfiar: **los barrios con más bares son los de menor supervivencia individual.** Centro tiene 509 bares y sobrevive el 9%. Poeta Lugones tiene 43 y sobrevive el 25,6%. Un corredor gastronómico excelente rota más rápido, porque el alquiler y la competencia se quedan con el margen.

Lo que obliga a ser preciso sobre qué mide un score así: la probabilidad de que el negocio sobreviva, no la calidad de la ubicación. En gastronomía apuntan para lados opuestos.

No sigo con esto. Pero prefiero un mapa que no miente sobre su incertidumbre a un número lindo que nadie auditó — y si alguien intenta lo mismo con datos de habilitaciones de cualquier municipio argentino, el techo lo va a encontrar igual. Mejor saberlo antes.

Código y metodología, abiertos 👇
