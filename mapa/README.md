# Mapa de viabilidad

`index.html` es la página del score. No trae los datos: los espera en un
`datos.js` al lado, que define `window.DATOS`.

Para regenerarlo desde cero:

```bash
cd ../pipeline && source .venv/bin/activate
python -m viabilidad ingest      # histórico + vista de trámites
python -m viabilidad poblacion   # socioeconómico por barrio
python -m viabilidad features    # entorno a la fecha de alta
python -m viabilidad geometria   # polígonos de manzana simplificados
python -m viabilidad score       # el score por manzana y rubro
python -m viabilidad mapa        # arma data/procesado/datos.js
cp data/procesado/datos.js ../mapa/
```

`datos.js` pesa ~2,2 MB y sale de `data/`, que está gitignoreado, así que no se
versiona: se regenera.

## Por qué no hay mapa base

La página se publica como artifact y ahí la política de contenido bloquea los
pedidos a servidores de tiles. No es una limitación real: los 6.892 polígonos de
manzana dibujan la ciudad solos, y las calles aparecen como espacio negativo.

## Qué muestra y qué no

El score es la probabilidad de que un comercio de ese rubro abierto hoy en esa
manzana pase su primer vencimiento, a los 5,5 años. Está agregado a manzana y
rubro a propósito: el objetivo tiene 61% de exactitud medida y eso pone un techo
de AUC 0,608, así que no sostiene un veredicto por dirección. Las limitaciones
van escritas en el pie de la propia página, no en un documento aparte.
