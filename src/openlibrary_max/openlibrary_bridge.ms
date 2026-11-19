-- OpenLibrary: conecta este 3ds Max con la app OpenLibrary.
-- Lo copia la app en scripts\startup. No añade menús ni ventanas: solo un
-- botón opcional (Customize UI > Toolbars > categoría "OpenLibrary") para abrir la app.
(
    local root = (getDir #userScripts) + "\\OpenLibrary"
    try
    (
        python.execute ("import sys\nr = r'" + root + "'\nif r not in sys.path: sys.path.insert(0, r)\nimport openlibrary_max\nopenlibrary_max.start()")
    )
    catch ( format "OpenLibrary: no se pudo arrancar el puente: %\n" (getCurrentException()) )
    try ( fileIn (root + "\\openlibrary_max\\openlibrary_launch.mcr") ) catch ()
)
