"""Tabla de reglas que agrupa los 1377 valores de `rubronombre` en dos niveles.

Estas reglas son el *generador* del mapeo, no la fuente de verdad: producen
`referencia/mapeo_rubros.csv`, que se versiona y se puede corregir a mano. El
pipeline lee el CSV, no este módulo, para que ajustar una clasificación no
requiera tocar código.

Se evalúan en orden y gana la primera que matchea, así que lo específico va
antes que lo general (`productos de confitería` es venta de golosinas y tiene
que resolverse antes que `confitería`, que es un café).
"""

from __future__ import annotations

# (nivel2, nivel1, incluye, excluye)
Regla = tuple[str, str, str, str]

MAYORISTA = "industria y deposito"
GASTRO = "gastronomia"
ALIM = "alimentos"
INDUM = "indumentaria"
SALUD = "salud"
HOGAR = "hogar y construccion"
AUTO = "automotor"
SERVP = "servicios personales"
SERVPR = "servicios profesionales"
ESPAR = "esparcimiento"
EDU = "educacion"
GENERAL = "comercio general"

REGLAS: list[Regla] = [
    # --- No son comercios a la calle. Van primero para que no contaminen nada.
    ("mayorista", MAYORISTA, r"por mayor|mayorista", ""),
    ("fabricacion", MAYORISTA, r"fabricacion|elaboracion de|industrializacion", r"elaboracion propia"),
    ("deposito", MAYORISTA, r"deposito|almacenamiento", ""),

    # --- Gastronomía
    ("panaderia", GASTRO, r"panaderia|panificadora|reposteria|horneado de pan|\bpan y productos", ""),
    ("heladeria", GASTRO, r"heladeria|expendio de helados|\bhelados\b", ""),
    ("golosinas", ALIM, r"bombones|golosinas|carameleria|galletiteria|productos de confiteria", ""),
    ("bar_restaurante", GASTRO,
     r"\bbar\b|\bbares\b|restaurant|cantina|parrilla|pizzeria|lomiteria|trattoria"
     r"|empanaderia|expendio de comidas|servicio de mesa|cerveceria|pub\b", ""),
    ("cafeteria", GASTRO, r"cafeteria|\bcafes?\b|confiteria|salon de te|casa de te", ""),
    ("comida_para_llevar", GASTRO,
     r"preparacion de comidas|venta para llevar|sandwicheria|rotiseria|comidas rapidas", ""),
    ("expendio_bebidas", GASTRO, r"expendio de bebidas", ""),

    # --- Alimentos (venta minorista)
    ("carniceria", ALIM, r"carniceria|carnes rojas|\bcarnes\b|carne envasada|chacinados", ""),
    ("polleria", ALIM, r"polleria|carne de aves|aves evisceradas|productos de granja", ""),
    ("verduleria", ALIM, r"verduleria|fruteria|frutas, legumbres|hortalizas", ""),
    ("fiambreria", ALIM, r"fiambreria|fiambres|embutidos", ""),
    ("pescaderia", ALIM, r"pescaderia|pescados|mariscos", ""),
    ("lacteos", ALIM, r"lacteos|\bleche\b|quesos", ""),
    ("dietetica", ALIM, r"dieteticos|dietetica|herboristeria|suplementos", ""),
    ("bebidas", ALIM, r"bebidas|vinoteca|vineria|cerveza", ""),
    ("almacen", ALIM, r"almacen|minimercado|autoservicio|supermercado|comestibles", ""),
    ("forrajeria", ALIM, r"forrajes|alimento balanceado|animales domesticos|productos veterinarios|mascotas|para animales", ""),
    ("alimentos_otros", ALIM, r"productos alimenticios|\balimentos\b|pastas frescas", ""),

    # --- Indumentaria
    ("ropa_infantil", INDUM, r"bebes y ninos|para bebes|infantil", ""),
    ("lenceria", INDUM, r"lenceria|ropa interior|\bmedias\b|prendas para dormir", ""),
    ("calzado", INDUM, r"calzado|zapateria|zapatilleria", ""),
    ("marroquineria", INDUM, r"marroquineria|carteras|paraguas|talabarteria", ""),
    ("indumentaria_deportiva", INDUM, r"indumentaria deportiva", ""),
    ("bijouterie", INDUM, r"bijouterie|fantasia|plateria|alhajas|orfebreria|joyeria|relojeria|\bjoyas\b|\brelojes\b", ""),
    ("merceria", INDUM, r"merceria|materiales textiles|\btextiles\b|\btelas\b", ""),
    ("ropa", INDUM, r"prendas de vestir|prendas y accesorios|indumentaria|\bropa\b|boutique", ""),

    # --- Salud
    ("farmacia", SALUD, r"farmacia|productos farmaceuticos|medicamentos de uso humano", r"veterinari|asesoramiento"),
    ("perfumeria", SALUD, r"perfumeria|cosmetica|cosmeticos|\btocador\b", ""),
    ("optica", SALUD, r"\boptica\b|articulos de optica", ""),
    ("ortopedia", SALUD, r"ortopedi|articulos medicos|instrumental medico", ""),
    ("veterinaria", SALUD, r"servicios medicos para animales|veterinari", ""),
    ("consultorio", SALUD, r"atencion ambulatoria|consultorio|servicios medicos|salud humana|servicios de tratamiento|odontolog|kinesiolog|psicolog", ""),
    ("laboratorio_analisis", SALUD, r"analisis clinicos|laboratorio", ""),

    # --- Hogar y construcción
    ("ferreteria", HOGAR, r"ferreteria|materiales electricos|herramientas", ""),
    ("pinturería", HOGAR, r"pinturer|\bpinturas\b|barnices", ""),
    ("construccion", HOGAR, r"materiales de construccion|\bsanitarios\b|corralon|\bgriferia\b", ""),
    ("muebleria", HOGAR, r"muebleria|\bmuebles\b|mimbre|colchones|almohadas", ""),
    ("bazar", HOGAR, r"bazar|menaje|\bvajilla\b", ""),
    ("limpieza", HOGAR, r"insumos de limpieza|productos de limpieza|articulos.*limpieza", ""),
    ("electrodomesticos", HOGAR, r"electrodomesticos|artefactos para el hogar|aparatos de uso domestico", ""),
    ("articulos_hogar", HOGAR, r"articulos del hogar|articulos para el hogar|decoracion|blanco\b|cortinas|alfombras", ""),
    ("vivero", HOGAR, r"vivero|plantas|semillas|jardineria", ""),

    # --- Automotor
    ("repuestos", AUTO, r"repuestos|partes, piezas|accesorios para vehiculos|\bneumaticos\b|\bcubiertas\b|lubricantes", ""),
    ("taller_mecanico", AUTO, r"reparacion de automotores|mecanica integral|taller|chapa y pintura|\blubricentro\b", ""),
    ("venta_vehiculos", AUTO, r"venta de automotores|concesionari|\bmotocicletas\b|bicicleteria|\bbicicletas\b", ""),
    ("estacion_servicio", AUTO, r"estacion de servicio|expendio de combustible|\bgnc\b|playa de estacionamiento|lavadero de auto", ""),

    # --- Servicios personales
    ("peluqueria", SERVP, r"peluqueria", ""),
    ("belleza", SERVP, r"tratamiento de belleza|manicur|depilacion|\bspa\b|\bestetica\b", ""),
    ("gimnasio", SERVP, r"gimnasio|\bnatatorio\b|actividad fisica|acondicionamiento fisico", ""),
    ("lavanderia", SERVP, r"lavanderia|tintoreria", ""),
    ("reparaciones", SERVP, r"reparacion de aparatos|reparacion de calzado|cerrajeria|\brelojero\b", ""),
    ("fotocopias", SERVP, r"fotocopiado|preparacion de documentos|\bimprenta\b|grafica", ""),
    ("locutorio", SERVP, r"cabinas telefonicas|locutorio|ciber", ""),

    # --- Servicios profesionales
    ("inmobiliaria", SERVPR, r"inmobiliari|locacion de bienes inmuebles|administracion, alquiler", ""),
    ("oficina", SERVPR, r"oficina administrativa|gestion administrativa|servicios empresariales|\bestudio\b|desarrollo de software|servicios prestados a las empresas|profesionales organizados", ""),
    ("cobranzas", SERVPR, r"cobranzas|agencias de cobro|crediticia|\bfinanciera\b|\bcambio\b|prestamos|\bbancos?\b", ""),
    ("intermediarios", SERVPR, r"intermediarios|consignatarios|comisionistas", ""),
    ("turismo", SERVPR, r"agencias de turismo|agencias de viajes|\bturismo\b|\bhotel\b|hospedaje|\bhosteria\b", ""),
    ("seguros", SERVPR, r"\bseguros\b|productor asesor", ""),
    ("transporte", SERVPR, r"transporte|\bremis\b|\bmensajeria\b|\bflete\b|\bdelivery\b|reparto a domicilio", ""),

    # --- Esparcimiento
    ("juegos_azar", ESPAR, r"quiniela|loteria|\bbingo\b|quini|juegos de azar|apuestas", ""),
    ("jugueteria", ESPAR, r"jugueteria|\bjuguetes\b|cotillon|juegos de mesa", ""),
    ("espectaculos", ESPAR, r"instalaciones deportivas|\bcine\b|\bteatro\b|\bboliche\b|salon de fiestas|espectaculo|\bcanchas?\b", ""),
    ("deportes", ESPAR, r"articulos deportivos|\bpesca\b|\bcaza\b|camping", ""),

    # --- Educación
    ("educacion", EDU, r"\bensenanza\b|\binstituto\b|\bcolegio\b|\bjardin de infantes\b|\bguarderia\b|\bcapacitacion\b", ""),

    # --- Comercio general (minorista que no entra en los grupos temáticos)
    ("kiosco", GENERAL, r"kiosco|quiosco|polirrubro|polirubro|drugstore", ""),
    ("libreria", GENERAL, r"libreria|papeleria|\blibros\b|materiales de embalaje|\bcarton\b", ""),
    ("regaleria", GENERAL, r"regaleria|articulos para regalos|\bsouvenir\b|\bartesania", ""),
    ("tecnologia", GENERAL, r"telefonia|celulares|computacion|informatic|perifericos|\belectronica\b", ""),
    ("fotografia", GENERAL, r"fotografia|\bfotografico\b", ""),
    ("tabaqueria", GENERAL, r"\btabaco\b|cigarrillo", ""),
    ("usados", GENERAL, r"\busados\b|antiguedades|feria americana", ""),
    ("comercio_otros", GENERAL, r"articulos nuevos|articulos varios|no especializados|otras actividades", ""),
]

# nivel2 -> nivel1, derivado de la tabla para no repetirlo en el CSV a mano.
NIVEL1_DE: dict[str, str] = {n2: n1 for n2, n1, _, _ in REGLAS}
