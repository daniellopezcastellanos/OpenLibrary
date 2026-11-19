# OpenLibrary

Biblioteca de modelos 3D para 3ds Max 2025+ (Corona / V-Ray), como app independiente al estilo de
Connecter o Cosmos Browser: navegas, buscas y organizas sin tener Max abierto, y arrastras los assets
a la escena cuando lo está. Es solo código, sin APIs ni IA: la carpeta de la biblioteca es la única
fuente de verdad.

## Cómo funciona

```
 OpenLibrary.exe  ──(127.0.0.1:47800-47809)──►  puente dentro de 3ds Max  ──►  escena
 navegar, buscar,                                (sin ventanas ni menús)        merge, place,
 previews, avisos                                arranca con Max                proxy, render
```

- **La app** lee las carpetas, guarda un índice en disco, saca el motor y las texturas de cada `.max`
  sin abrirlo y enseña las previews. No necesita Max.
- **El puente** es un script de arranque de Max que escucha solo en este equipo. Recibe órdenes como
  "mergea este archivo con estas opciones" y las ejecuta con MaxScript. Uno por cada Max abierto.
- **Arrastrar:** al soltar un asset sobre la ventana de Max, la app mira de qué proceso es esa
  ventana y le manda la orden a su puente.

## Usar

Desde el código (hace falta Python 3.10+ con PySide6):

```
pip install -r requirements-dev.txt
python run_openlibrary.py
```

Empaquetado: `python build.py` genera `dist/OpenLibrary/OpenLibrary.exe` y un `.zip`.

La primera vez que la abres sale un asistente: accesos directos (menú Inicio / escritorio), puente en tu 3ds Max y, si quieres, una barra con el botón de OpenLibrary dentro de Max. Para la barra de tareas de Windows: clic derecho en el icono de OpenLibrary abierta › *Anclar a la barra de tareas*. Todo esto se puede repetir en **⚙ › Instalación**. Después reinicia Max. El punto de
abajo se pone verde cuando hay conexión.

Ajustes, miniaturas e índice: `%LOCALAPPDATA%\OpenLibrary`.

## Cómo organizar la biblioteca

```
Biblioteca/
  Sillas/
    Eames_corona.max      ← versión Corona   (sufijos: _corona _cr _vray _vr _v-ray)
    Eames_vray.max        ← versión V-Ray
    Eames.jpg             ← preview (o .png, Eames_preview.jpg, previews/Eames.jpg)
    Tulip.max             ← sin sufijo: el motor se lee del propio .max
    maps/                 ← texturas (aquí se busca al re-enlazar)
    _proxies/             ← lo crea "Merge as Proxy" (no se indexa)
```

## Qué hace

| Función | Sin Max | Cómo |
|---|---|---|
| Pestañas | ✔ | Modelos, Materiales y Texturas por defecto; en ⚙ › Libraries se crean, renombran, ordenan y quitan, cada una con sus carpetas |
| Materiales | ✔ (aplicar: con Max) | agrupa los mapas PBR de cada carpeta en un material con su resolución, insignias de mapas y tamaño real; se arrastra a un objeto o al editor Slate y se crea para Corona, V-Ray o Physical |
| Interiores | ✔ (aplicar: con Max) | habitaciones wParallax / ShadersBOX: se arrastran a una ventana o crean el plano, con el OSL ya montado |
| Texturas | ✔ (aplicar: con Max) | imágenes sueltas que se arrastran a Slate como mapas, o a un objeto como material rápido |
| Navegador | ✔ | árbol con nº de assets, miniaturas en caché, buscador y tamaño de miniatura |
| Rápido al abrir | ✔ | índice en disco: se muestra al instante y solo se releen las carpetas que han cambiado |
| Icono de motor | ✔ | C naranja = Corona, V azul = V-Ray, ? = otro; el que no es el de la escena sale atenuado |
| Aviso ⚠ | ✔ | triángulo amarillo si el asset tiene texturas o archivos externos fuera de su ruta |
| Barra de info | ✔ | botón ⓘ: versiones, tamaño, fecha, archivos externos y si el proxy ya está creado |
| Merge and Place | Max | arrastra a Max (uno o varios a la vez; doble clic = preview en grande). Clic = instancia y sigues, rueda = girar 90º, botón derecho o Esc = terminar, Ctrl = solo grid |
| Merge as Proxy | Max | CProxy `.cgeo` o VRayProxy `.vrmesh`, todo en uno o por objeto, vista de caja, preview o malla; si ya existe se reutiliza al instante |
| Preview | Max | encuadre automático por bounding box o desde tu vista; render corto o captura de viewport |
| Re-enlazar | Max | en la escena o dentro de los `.max` de la biblioteca sin abrirlos |

## Estructura

- `src/openlibrary/`: la app (Python + PySide6)
  - `library.py` índice con caché · `maxfile.py` lee motor y rutas del `.max` (formato OLE)
  - `maxlink.py` cliente del puente · `bridge_install.py` instala el puente en cada Max
  - `proxies.py` dónde va cada proxy · `ui_browser.py`, `ui_settings.py`, `app.py` interfaz
- `src/openlibrary_max/`: el puente que corre dentro de Max
  - `server.py` socket local · `ops.py` operaciones · `openlibrary_core.ms` MaxScript
  - `openlibrary_bridge.ms` script de arranque · `openlibrary_launch.mcr` botón para abrir la app
- `run_openlibrary.py`, `build.py`, `tests/`

## Pendiente de probar con 3ds Max

Lo que no necesita Max tiene tests, también el cliente del puente contra un Max simulado y la
instalación en carpetas simuladas. Falta probar con Max de verdad:
- que el puente arranque con Max y la app lo vea (punto verde)
- soltar sobre la ventana de Max: que detecte el proceso y que Max pase al frente para colocar
- colocar en cadena: la rueda gira (se mira al moverse y al interrumpirse mouseTrack) y el botón derecho o Esc terminan
- `CProxy.ProxyFp.fromScene`, la posición del proxy, `vrayMeshExport` y el valor de `previzType` de cada modo de vista
- el render de la preview con Corona (límite de pasadas `progressive_passLimit`)
