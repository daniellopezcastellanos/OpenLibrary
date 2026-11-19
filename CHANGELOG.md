# Changelog

Todos los cambios importantes de OpenLibrary se apuntan aquí.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versiones según
[Semantic Versioning](https://semver.org/lang/es/).

## [Sin publicar]

## [0.2.1] - 2026-11-19

### Añadido
- **Aviso del puente al abrir la app**: si un 3ds Max compatible no tiene el puente, o lo tiene de una versión anterior de OpenLibrary, sale un mensaje con un botón para instalarlo o actualizarlo ahí mismo (se conserva la barra que tuvieras). Para un Max en el que no lo quieras, «No volver a preguntar»; de los desactualizados se avisa siempre.

### Cambiado
- En el asistente de instalación, «Ahora no» ya no se salta el puente sin decir nada: avisa de que sin él no se puede arrastrar a la escena y ofrece instalarlo.

## [0.2.0] - 2026-11-19

Primera versión publicada, de prueba: OpenLibrary deja de vivir dentro de 3ds Max y pasa a ser una
app independiente, como Connecter o Cosmos Browser. Se descarga como `OpenLibrary-0.2.0-win64.zip`
desde la página de la release.

### Añadido
- **Estilo Open3D**: el aspecto de las otras apps de Open3D (OpenFarm, OpenRef, OpenScatter…): fondo cálido, esquinas rectas y pestañas, etiquetas y botones en monoespaciada y mayúsculas. Funciona en claro y en oscuro. El estilo de antes ya no está.
- **Caras, vértices, desplazamiento y animación** de cada modelo en su ficha. Se leen con un 3ds Max en segundo plano, sin tocar el tuyo: con el botón de la ficha o con clic derecho › «Leer caras, vértices y animación» (vale con varios), y solos al generar previews en lote. Si un .max deja a Max colgado al abrirlo, se salta y se sigue con el siguiente.
- **Material que ya está en la escena**: si sueltas un material sobre un objeto (o usas «Aplicar a la selección») y en la escena ya hay uno con ese nombre, la app pregunta si le pones el de la escena o metes uno nuevo («Nombre_01»). Si lo sueltas en el editor Slate, busca y selecciona el que ya había.
- **«Al Slate» con varios materiales**: mete todos los seleccionados, ordenados, cada uno con sus medidas y su mapeado (los que ya estaban, los selecciona).
- **Varios modelos a la vez**: si arrastras varios a Max (o usas el clic derecho), entran todos como Merge and Place, como proxy o en su posición original, según lo que elijas; con «Place» se coloca cada uno con su clic.
- **Espacio de trabajo al instalar**: es lo primero que pregunta el asistente, con la explicación. Si trabajáis varios, se elige la carpeta del NAS y la app crea dentro `_OpenLibrary` (con `workspace.json`, `medidas` y un LEEME). Lo que cambia uno lo ven los demás al momento: la app mira el archivo común cada 10 segundos (sin perder la carpeta ni la selección si solo cambian medidas o mapeado).
- **Mayús + clic en la flecha** de una carpeta del árbol: se cierran todas las carpetas.
- **Favoritos** en todas las pestañas (Modelos, Materiales, Texturas e Interiores): pulsa el corazón naranja de una tarjeta (o clic derecho › «Añadir a favoritos») y aparece en «Favoritos», arriba del árbol de carpetas. Cada persona tiene los suyos. En Ajustes › Libraries, la lista de carpetas de cada pestaña empieza por «Favoritos» y «Todos», con una casilla para enseñarlos o no en el árbol, y «Al abrir, mostrar» elige qué se ve al entrar: todos con los favoritos primero, solo los favoritos, o todos sin ordenar.
- **Medidas enlazadas en Real World**: todos los mapas de un material comparten la medida, así que si cambias el ancho o el alto en uno (el color, por ejemplo) cambia en la normal, el roughness y los demás. Vale en Corona, V-Ray y los mapas de Max, y también con el tamaño del triplanar de V-Ray.
- **Espacio de trabajo compartido** (Ajustes › Espacio de trabajo). Si trabajáis varios con la misma biblioteca, elegís todos la misma carpeta del NAS y compartís las pestañas y sus carpetas, las carpetas ocultas, los iconos de carpeta, las medidas y el mapeado de cada material, los ajustes de preview y las medidas de fabricante. Lo personal (ventana, tema, miniaturas, con qué 3ds Max conectas) sigue en cada equipo. Si dos personas guardan a la vez no se pisan (cada medida se junta por separado), la app trae los cambios de los compañeros al volver a ella, y sin conexión con el NAS se sigue trabajando con la última copia. Quien trabaja solo lo deja en «Solo en este equipo», como hasta ahora.
- Las **medidas de fabricante** (Poliigon, Superellipse…) se guardan en la carpeta del espacio de trabajo (`medidas\02_POLIIGON.json`…) en vez de dentro de las carpetas de la biblioteca. Un botón en Ajustes › Espacio de trabajo trae ahí las que ya estaban dentro.
- **Pestaña Materiales**: lee las carpetas de la pestaña y junta en un solo material los mapas que se llaman igual salvo el canal (`…_basecolor`, `…_normal`, `…_roughness`, `COL`/`NRM`/`GLOSS`/`DISP`…), con todas sus resoluciones. También enseña las bibliotecas `.mat`. No hay que preparar nada: vale con la carpeta tal como viene de Poliigon, Textures.com, Superellipse, MOTW, etc.
  - Cada material es una **bola** con el mapa de color (o la muestra del fabricante si viene una al lado), la **resolución** arriba y unas **insignias de colores** con los mapas que trae: `BC` color base / difuso, `Rg` roughness, `Gl` glossiness, `Mt` metalness, `Nr` normal, `Bm` bump, `DS` desplazamiento, `AO`, `Op` opacidad, `Em` emisión, `Tr` translucidez.
  - **Arrastra** el material sobre un objeto de 3ds Max para ponérselo, o sobre el editor **Slate** para dejarlo en la vista activa. «Aplicar a la selección» (o doble clic) y «Al Slate» hacen lo mismo con botón.
  - El material se crea para el motor de la escena (o el que elijas): `CoronaPhysicalMtl` con `CoronaBitmap`, `VRayMtl` con `VRayBitmap`, o Physical Material. Los mapas de datos entran sin gamma, la normal por su nodo de normal, y el desplazamiento conectado pero apagado salvo que marques «Desplazamiento».
  - **Resolución**: la más alta, la más baja o una concreta (si no existe, la más cercana).
  - **Medidas X · Y · Z en cm**: se sacan del nombre o de la carpeta («2.5x2.5 meters», «300x188cm», «_130cm»…). Si no vienen, las escribes con el material seleccionado y se quedan guardadas para ese material (el botón ↺ vuelve a las del nombre). Con clic derecho › «Usar estas medidas en toda la carpeta» se las pones de golpe a los de esa carpeta que no tienen.
  - **Mapeado por material**: **Real World** (la textura mide X × Y y el objeto recibe un UVW Map de caja con «Real-World Map Size»), **UVW Map** (caja de X × Y × Z), **Triplanar** (baldosa de X, sin UV; solo en texturas cuadradas) o **UV del objeto**. Lo que elijas se recuerda para ese material, como las medidas, y al arrastrarlo a Max se usa eso sin preguntar. Un material sin mapeado guardado va siempre con «UV del objeto». X, Y y Z se ven siempre; las que ese mapeado no usa salen apagadas.
  - **Cuadrada o rectangular**: arriba a la derecha de cada bola, un cuadrado blanco (textura cuadrada) o un rectángulo ámbar con la forma de la textura (más ancha o más alta). Se saca de las medidas reales o, si no hay, del tamaño en píxeles del mapa de color.
  - **Medidas de Poliigon y Superellipse** sacadas de sus webs y guardadas en un archivo `openlibrary_medidas.json` dentro de la carpeta de cada fabricante: la app las lee solas (y sirve para toda la gente que use esa biblioteca).
  - **Arrastrar y Slate**: soltar sobre el editor Slate deja el material solo ahí. Soltar sobre un objeto (o aplicarlo con el botón) se lo pone; si el editor Slate está abierto, aparece también en su vista activa, y si está cerrado no se abre. Si sueltas en el vacío del visor va a los objetos seleccionados.
  - Filtros «.mat» y «Con medidas», buscador y panel derecho con los mapas exactos que se cargarían.
- **Pestaña Interiores (wParallax)**: un tipo de pestaña nuevo para las habitaciones falsas de ventana de wParallax y ShadersBOX. Reconoce cada habitación por sus EXR, con día y noche, resoluciones y tamaño de ventana (S, M, L), y enseña la vista previa del pack (las de ShadersBOX no traen).
  - **Arrastra** una habitación sobre una ventana de 3ds Max (un plano o una caja) y entra montada como en las escenas de ejemplo: mapa OSL `wParallax_SMP.osl` leyendo el EXR, en la autoiluminación de un `CoronaPhysicalMtl` o `VRayMtl` negro, con la vista previa visible en el visor. Si sueltas en el vacío, crea el plano de la ventana con su tamaño (3,5 × 3,5 m, 7 × 3,5 m o 10,5 × 3,5 m) donde está el ratón.
  - Opciones: día o noche (también cambia la miniatura), resolución, motor y profundidad de la habitación. Botones «Aplicar a la selección», «Crear ventana» y «Al Slate».
  - Para usarla, en Ajustes › Libraries cambia el «Contenido» de la pestaña a «Interiores (wParallax)». Hay que actualizar el puente en Ajustes › Instalación y reiniciar 3ds Max.
- **Pestaña Texturas**: todas las imágenes sueltas de sus carpetas (suciedades, decals, máscaras…). Se arrastran una o varias al editor Slate y entran como mapas del motor elegido; sobre un objeto crean un material rápido. «Según el nombre» decide si se cargan como color o como datos sin gamma.
- En las dos pestañas valen las carpetas ocultas (`z-maps`…), el tamaño de miniatura, el modo claro y la búsqueda de cambios solo en las carpetas que han cambiado.
- **Quitar de golpe lo que sobra**: después de «Re-enlazar dentro de los .max», si entre lo que sigue perdido hay `.cube` (LUT), `.hdr` o texturas con «checker» en el nombre, pregunta si quitarlas de todos esos archivos a la vez. En «Archivos que faltan» hay un botón «Quitar .cube, .hdr y checker» que hace lo mismo para ese modelo.
- **Archivos que faltan**: la ficha del asset lista por su nombre todos los archivos externos que no se encuentran, y el botón «Ver archivos que faltan…» (también en el clic derecho) abre la lista en grande con la ruta donde debería estar cada uno. Seleccionas una o varias filas para re-enlazarlas a mano (un archivo, una carpeta, o buscar por nombre con subcarpetas) o quitarlas del `.max`, y «Guardar en el .max» lo escribe sin abrir el archivo: lo hace un 3ds Max en segundo plano, tarda medio minuto.
- **Catalogar** (botón ámbar, antes de Preview): abre la descarga de un modelo (`.zip`, `.rar`, `.7z`… o una carpeta ya descomprimida, también arrastrándola a la ventana) y la deja ordenada en la biblioteca.
  - Si tiene **contraseña**, la pide; si viene **en partes** (`.part1.rar`, `.7z.001`, `.r00`, `.z01`…), vale elegir cualquiera: busca las demás en la misma carpeta y avisa de las que falten.
  - Enseña todos los archivos sin carpetas, con miniatura, repartidos en tres listas que se corrigen arrastrando (o con clic derecho / Supr): **1 · Archivos .max**, **2 · Preview** y **3 · Texturas y otros**. Lo que se deje en «No se copia» se queda fuera.
  - Escribes el **nombre** y eliges la **carpeta de la biblioteca** en el árbol (con buscador y «Nueva carpeta…»). Se guarda `Carpeta\Nombre.max` y `Carpeta\Nombre.jpg` (el preview, con el mismo nombre para que salga de miniatura) y las texturas, con sus nombres originales, en `Carpeta\z-maps\Nombre\`. Con varias versiones: `Nombre_corona.max`, `Nombre_vray.max`.
  - Antes de guardar se ve dónde va a ir cada cosa y si ya existe algo con ese nombre. La carpeta `z-maps` queda oculta en el árbol automáticamente.
  - Para `.rar`, `.7z` con contraseña y archivos en partes hace falta tener instalado 7-Zip, NanaZip o WinRAR; los `.zip` normales se abren sin nada.
- **Ocultar carpetas del árbol**: clic derecho en una carpeta › «Ocultar esta carpeta» u «Ocultar todas las que se llamen …» (p. ej. todas las `z-maps` de golpe). «Ocultar carpetas por nombre…» deja escribir la lista a mano, con comodines (`z-*`). Lo oculto tampoco sale en la galería ni cuenta en los totales, y se recupera en «Carpetas ocultas». Se guarda en tus ajustes; en el disco no se toca nada.
- **App de escritorio OpenLibrary** (`OpenLibrary.exe`): navegar, buscar, ordenar pestañas y carpetas, ver previews, motor y avisos sin tener 3ds Max abierto. Tema oscuro, recuerda tamaño y posición, y si la abres dos veces se enfoca la que ya estaba abierta.
- **Puente con 3ds Max**: un script pequeño, sin ventanas ni menús, que arranca con Max y escucha solo en este equipo (puertos 47800-47809, uno por cada Max abierto). Solo acepta las órdenes de OpenLibrary.
- Se instala y se quita desde la app: Ajustes › **Instalación**, con la lista de versiones de Max del usuario y su estado.
- Arrastrar desde la app y soltar sobre la ventana de 3ds Max: la app detecta sobre qué Max se suelta y le manda el asset (Merge and Place, Merge as Proxy o en su posición original).
- Selector del 3ds Max de destino (si hay varios abiertos) con su motor y escena, y punto verde o gris de conexión.
- Botón 📌 para tener OpenLibrary siempre encima mientras arrastras a Max.
- **Asistente de instalación** la primera vez que abres la app: crea los accesos directos con el icono de OpenLibrary (menú Inicio y escritorio), conecta tu 3ds Max y, si quieres, añade una barra «OpenLibrary» con su botón dentro de Max. Explica cómo anclarla a la barra de tareas de Windows (Windows no deja que un programa se ancle solo). Todo se puede repetir o cambiar en Ajustes › Instalación.
- Barra opcional en 3ds Max con el botón de OpenLibrary: aparece al abrir Max, se puede mover y acoplar como cualquier otra. También sigue la macro en Customize UI › Toolbars › categoría "OpenLibrary".
- **Interfaz nueva**, más moderna: cabecera con las pestañas como pastillas y el buscador, barra lateral de carpetas con iconos, tarjetas de miniatura redondeadas con el nombre y el motor debajo, cuadrícula que llena todo el ancho, barra de información en tarjeta y barra de estado con el tamaño de miniatura y la conexión con Max. Tema oscuro con acento ámbar, también en Ajustes y en la barra de título de Windows.
- **Galería de modelos**: las miniaturas mandan y llenan la fila entera, sin texto debajo; el nombre aparece al pasar el ratón o al seleccionar. Insignias de motor arriba a la izquierda y aviso ⚠ arriba a la derecha. Con el botón «Nombres» vuelves a las tarjetas con nombre y motor.
- **Ficha del asset** en un panel a la derecha (sustituye a la barra de información de abajo): preview grande, ruta, versiones con tamaño y fecha, archivos externos, estado del proxy y botones «Usar en la escena», «Como proxy» y «Sin colocar».
- **Vista rápida**: Espacio (o clic en la preview de la ficha) enseña la imagen en grande; con las flechas o la rueda pasas al asset anterior o siguiente. Intro abre el menú de Merge.
- **Filtros rápidos** sobre la galería: Todos / Corona / V-Ray / Motor de la escena, «Con avisos» y «Sin preview». Orden por nombre o por más recientes.
- Entrada «Todos» arriba del árbol de carpetas.
- **Modo claro y modo oscuro**: botón de sol/luna en la cabecera; se recuerda entre sesiones.
- **Doble clic** en un modelo abre su preview en grande (igual que Espacio).
- Botón **Abrir en 3ds Max** en la ficha del asset: abre el `.max` para editarlo (si Max tiene cambios sin guardar, pregunta antes). Debajo quedan «Colocar», «Proxy» y «Original» para meterlo en la escena.
- **Previews en lote, en segundo plano**: Preview › «De los seleccionados» o «De todos los que no tienen preview aquí». Lo hace un 3ds Max aparte, sin ventana, que no toca tu escena; barra de progreso y «Cancelar» en la barra de estado.
- Re-enlazar › «Dentro de todos los .max de esta vista», además del seleccionado y de la escena, con progreso y un resumen al acabar.
- **Colores e iconos de carpeta**: clic derecho en una carpeta › Color (paleta de 9) o Icono (árbol, planta, sofá, silla, mesa, cama, lámpara, edificio, puerta, vehículo, personas, baño, cocina, decoración, texturas…). Si no eliges icono, se pone solo según el nombre de la carpeta. Se guarda en tus ajustes.
- El motor de cada asset se ve como una **etiqueta con el logo** de Corona, V-Ray o FStorm; la versión que no es del motor de la escena sale apagada.
- **FStorm** se reconoce como motor: se detecta al leer el `.max`, vale el sufijo `_fstorm` en el nombre del archivo y tiene su filtro en la galería. (El proxy sigue siendo solo para Corona y V-Ray.)
- Icono de app (`openlibrary.ico`) para el `.exe`, la ventana, la barra de tareas y los accesos directos.
- Todo lo de Max (importar, colocar, preview, re-enlazar, añadir) se hace en segundo plano: la app no se congela mientras colocas en Max.
- Si no hay Max conectado, "Abrir .max" abre el archivo con Windows.
- Pestañas en el navegador: **Modelos**, **Materiales** y **Texturas** por defecto. En Ajustes › Libraries se crean, renombran, ordenan y quitan, y cada una tiene sus carpetas. Materiales y Texturas muestran "próximamente".
- Índice guardado en disco: la biblioteca se lee entera una sola vez. Al abrir se muestra al instante lo último leído y en segundo plano solo se vuelven a listar las carpetas que han cambiado. Botón ⟳ para "Buscar cambios" o "Leer todo de nuevo".
- Merge and Place en cadena: cada clic deja una instancia y sigues colocando otra. Pulsando la rueda del ratón gira 90º en Z, y con el botón derecho o Esc terminas. Funciona igual con proxies. Se puede desactivar en Ajustes.
- Opción "Preguntar cada vez" para objetos y materiales duplicados.
- Ajuste de visualización del proxy en el viewport: caja, vista previa o malla completa (Corona y V-Ray).
- Aviso amarillo ⚠ en la preview cuando un asset tiene texturas o archivos externos fuera de su ruta. Se revisa en segundo plano leyendo el propio `.max` y el tooltip dice cuáles.
- Barra de información del asset (botón ⓘ abajo): versiones con tamaño y fecha, archivos externos, preview y si su proxy ya está creado.
- Icono propio (estantería con libros y un baúl) e iconos para Preview, Re-enlazar, Añadir, Ajustes, Buscar cambios y Siempre encima.
- `CHANGELOG.md`, `LICENSE` (MIT), `CLAUDE.md`, `.gitignore` y `requirements-dev.txt`.

### Cambiado
- **Doble clic** en un modelo, material, textura o interior: la preview en grande (también con Espacio). Para aplicar, Enter o los botones.
- La cabecera ya no lleva logo ni nombre, y el buscador va centrado en el ancho de la ventana en todas las pestañas.
- «Catalogar» y «Crear ventana» van en el color de la app.
- **Colocar modelos**: ahora se gira 90º pulsando la **rueda** del ratón, y el **botón derecho** deja de colocar (como Esc).
- **Sin lista de 3ds Max abiertos** en la barra de abajo: los assets van solos al Max que está por encima de los demás (el último que usaste) o al que tiene el ratón encima. Abajo se ve a cuál, sin cortarse.
- El **botón de OpenLibrary dentro de Max** trae la app delante de todo si ya estaba abierta (aunque la abrieras desde otro sitio) y la abre si no.
- El icono nuevo sale también en la barra de tareas, los accesos directos y el botón de la barra de 3ds Max (la app avisa a Windows para que olvide el viejo), y en «Todos» del árbol.
- **Icono nuevo** en el lenguaje de las apps Open3D: azulejo oscuro con los libros de la estantería en ámbar.
- **Previews más rápidos al hacer scroll**: se cargan primero las que estás viendo, las de las pantallas siguientes se piden por adelantado, y leer los `.max` (motor y archivos externos) ya no las frena. Además, pintar la cuadrícula ya no toca el NAS.
- En Ajustes › Libraries, los iconos de «Favoritos» y «Todos» van al tamaño del texto.
- Si vuelves a meter un material que ya está en la escena (o en el editor de materiales), el nuevo se llama «Nombre_01», «Nombre_02»…, así no hay dos materiales con el mismo nombre aunque los cambies un poco. Pasa igual con los de las bibliotecas `.mat` y los interiores.
- **Abrir en 3ds Max** abre el `.max` en un 3ds Max nuevo (de la misma versión que el conectado, si la hay) y no toca los que tengas abiertos. Abrirlo en el Max conectado, en lugar de su escena, sigue en el clic derecho.
- La cabecera ya no lleva el icono ni el nombre «OpenLibrary» junto a las pestañas; la versión pasa a la esquina inferior izquierda, en la barra de estado.
- Los ajustes se guardan con más cuidado: si hay dos OpenLibrary abiertas, la que tiene los ajustes viejos ya no pisa las bibliotecas que cambiaste en la otra, y se conserva una copia del guardado anterior (`settings.json.bak`) por si el archivo se estropea.
- El proyecto pasa a llamarse **OpenLibrary**. Ajustes, miniaturas e índice en `%LOCALAPPDATA%\OpenLibrary`. Las bibliotecas ya configuradas en la versión anterior se conservan en la pestaña Modelos.
- Merge as Proxy reutiliza el proxy si ya se creó antes (en este u otro proyecto): trae un `.max` pequeño con los proxies y sus materiales, sin volver a mergear el modelo pesado. Solo se crea uno nuevo si el `.max` del asset ha cambiado.
- `build.py` genera ahora la app (`dist/OpenLibrary/OpenLibrary.exe` y un `.zip`) con PyInstaller, con el icono de la app dentro del `.exe`.

### Corregido
- **Cambiar de pestaña ya no vuelve a montarlo todo.** Al volver a Modelos, el árbol y la galería siguen como los dejaste (con 30.000 modelos pasaba de unos 6 segundos a una décima). Elegir el icono de cada carpeta y mirar si cada modelo es favorito ya no se repite en cada cambio, y cambiar de pestaña ya no escribe en el archivo común del NAS si no ha cambiado nada común.
- Si una pestaña estaba buscando cambios en sus carpetas y te ibas a otra del mismo tipo (p. ej. de Materiales a Texturas), esa búsqueda se cortaba y la próxima vez empezaba de cero. Ahora cada pestaña termina la suya en segundo plano, y la barra de estado solo cuenta la de la pestaña que estás viendo.
- La barra de tareas de Windows seguía enseñando el icono viejo: los accesos directos (también el anclado a la barra) apuntan ahora a una copia del icono que cambia de nombre cuando cambia el icono, así Windows no puede tirar del viejo de su caché.
- El botón de OpenLibrary dentro de Max no abría nada cuando el puente se había instalado desde otro sitio: ahora apunta a `OpenLibrary.exe`, y la app lo vuelve a apuntar sola cada vez que se abre.
- Posible causa del aviso de MAXScript «unknown error ... garbage collection» al abrir el editor de materiales: el puente podía dejar restos de una orden de Max que se liberaban fuera del hilo de Max. Ahora se limpian en el hilo de Max al acabar cada orden, y el puente ya no pregunta a Max por la escena cada segundo y medio: se entera por los avisos de Max (abrir, guardar, cambio de motor o de selección).
- Las medidas y el mapeado que guardas para cada material ya no dependen de cómo se abra la biblioteca: valen igual con `B:\` que con `\\BETA-SERVER\...` (se guardan respecto a la carpeta de la pestaña; las que ya tenías se pasan solas al guardarlas de nuevo).
- Ajustes › Instalación avisa cuando el puente instalado en un 3ds Max es anterior al de la app («desactualizado: pulsa Instalar y reinicia Max»), y la barra de estado lo dice al conectar con ese Max.
- Si 3ds Max no contesta al crear un material (por ejemplo, porque tiene una ventana abierta esperando respuesta), la app deja de esperar a los dos minutos y explica por qué, en vez de quedarse con la barra girando.
- Los materiales que se llevan al editor Slate se colocan a la derecha de lo que ya hay en la vista y la vista se encuadra en ellos, en vez de irse cada vez más lejos.
- **Los materiales en Real World o triplanar no se ponían** (ni arrastrando ni con el botón) y no salía ningún aviso. Las medidas llegaban a Max en un formato que no sabía leer, y el puente se tragaba el error. Ahora funcionan, y si una orden falla en Max la app enseña el motivo en vez de quedarse sin hacer nada (vale para todas las órdenes: colocar modelos, proxies, materiales…).
- **Triplanar en Corona montado como se hace a mano**: un solo mapa CoronaTriplanar con el color en la entrada principal y roughness, metalness, normal, desplazamiento… en sus salidas adicionales, cada una conectada a su canal del material. Antes cada mapa llevaba su propio triplanar.
- Con varios 3ds Max abiertos, soltar sobre uno recién abierto que la app aún no tenía en su lista no hacía nada: ahora lo busca en ese momento.
- **Arrastrar un material, una textura o una habitación sobre un objeto de 3ds Max no se lo ponía.** Max buscaba el objeto en el visor activo y no en el visor donde se soltaba, y con la pantalla escalada (125 %, 150 %…) el punto salía desplazado. Ahora el puente mira qué visor hay de verdad bajo el ratón y convierte la posición a la escala de Max. Hace falta actualizar el puente (Ajustes › Instalación) y reiniciar 3ds Max; la app avisa si el de Max es anterior.
- Materiales de Superellipse cuyo nombre acaba en «Metal» (casi toda la carpeta Metal) salían con la bola dibujada en vez de su vista previa.
- Materiales de Poliigon antiguos (carpeta «Bricks 001» con la muestra «Bricks_001.jpg» al lado) salían con la bola dibujada en vez de su vista previa.
- Las imágenes PNG con fondo transparente salían sobre negro en las miniaturas; ahora sobre gris.
- El árbol de carpetas no enseñaba las flechas para desplegar subcarpetas. Ahora se ven, un clic en la carpeta la despliega y las carpetas abiertas siguen abiertas después de buscar cambios.
- Los botones Preview y Re-enlazar parecían no hacer nada: ahora abren siempre su menú, avisan al momento si falta algo (objetos sin seleccionar en Max, Max ocupado) y la barra de estado enseña que Max está trabajando.
- Una carpeta que solo tiene subcarpetas ya no sale vacía con «Incluir subcarpetas» desmarcado: enseña lo que hay dentro.

### Eliminado
- «Añadir selección» (guardar lo seleccionado en 3ds Max como un asset nuevo de la biblioteca): ya no tenía botón y se ha quitado del todo, también del puente.
- El panel acoplable dentro de 3ds Max, su menú y su barra de herramientas.
- El instalador `.mzp`: el puente se instala desde la app.

## [0.1.0] - 2026-11-11

Primera versión interna (no se publicó): solo modelos 3D. Aún no se ha probado dentro de 3ds Max.

### Añadido
- **Catalogar** (botón ámbar, antes de Preview): abre la descarga de un modelo (`.zip`, `.rar`, `.7z`… o una carpeta ya descomprimida, también arrastrándola a la ventana) y la deja ordenada en la biblioteca.
  - Si tiene **contraseña**, la pide; si viene **en partes** (`.part1.rar`, `.7z.001`, `.r00`, `.z01`…), vale elegir cualquiera: busca las demás en la misma carpeta y avisa de las que falten.
  - Enseña todos los archivos sin carpetas, con miniatura, repartidos en tres listas que se corrigen arrastrando (o con clic derecho / Supr): **1 · Archivos .max**, **2 · Preview** y **3 · Texturas y otros**. Lo que se deje en «No se copia» se queda fuera.
  - Escribes el **nombre** y eliges la **carpeta de la biblioteca** en el árbol (con buscador y «Nueva carpeta…»). Se guarda `Carpeta\Nombre.max` y `Carpeta\Nombre.jpg` (el preview, con el mismo nombre para que salga de miniatura) y las texturas, con sus nombres originales, en `Carpeta\z-maps\Nombre\`. Con varias versiones: `Nombre_corona.max`, `Nombre_vray.max`.
  - Antes de guardar se ve dónde va a ir cada cosa y si ya existe algo con ese nombre. La carpeta `z-maps` queda oculta en el árbol automáticamente.
  - Para `.rar`, `.7z` con contraseña y archivos en partes hace falta tener instalado 7-Zip, NanaZip o WinRAR; los `.zip` normales se abren sin nada.
- Panel acoplable en 3ds Max 2026+ (PySide6) que se instala arrastrando un `.mzp`, con menú **OpenLibrary** y macro en la categoría "OpenLibrary".
- Ajustes › Libraries: añadir, renombrar, cambiar carpeta, quitar y ordenar bibliotecas. Los ajustes son de cada usuario (`%LOCALAPPDATA%\OpenLibrary`).
- Navegador con árbol de carpetas (y nº de assets), miniaturas con caché local, buscador, opción de subcarpetas y deslizador de tamaño.
- Icono de motor en cada preview (Corona, V-Ray u otro), que sale atenuado si no es el motor de la escena.
- Motor detectado por el sufijo del archivo (`_corona`, `_vray`…) o leyendo las clases del `.max` sin abrirlo.
- Al importar entra la versión del motor de la escena, o se pregunta cuál usar si no la hay.
- Merge and Place (el modelo sigue al ratón sobre superficies, Ctrl = solo grid) y Merge as Proxy (CProxy / VRayProxy, todo en uno o uno por objeto, con caché en `_proxies`).
- Preview con encuadre automático por bounding box o desde la vista activa, por render o captura de viewport.
- Re-enlazar texturas perdidas en la escena o dentro de los `.max` de la biblioteca.
- Ajustes de importación: grupo, capa, duplicados de objetos y materiales, luces, cámaras, proxy y carpetas de texturas.
- Botón Añadir: guarda la selección como asset nuevo con su preview.
- `build.py` para generar el `.mzp` y tests de indexado, detección de motor y ajustes.

[Sin publicar]: https://github.com/daniellopezcastellanos/OpenLibrary/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/daniellopezcastellanos/OpenLibrary/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/daniellopezcastellanos/OpenLibrary/releases/tag/v0.2.0
