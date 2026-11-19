macroScript OpenLibrary
    category:"OpenLibrary"
    buttonText:"OpenLibrary"
    toolTip:"Abrir la app OpenLibrary"
(
    on execute do
    (
        python.execute "import openlibrary_max\nopenlibrary_max.launch_app()"
    )
)
