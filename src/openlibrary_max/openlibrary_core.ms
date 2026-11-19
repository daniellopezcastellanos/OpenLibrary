/*
    OpenLibrary - núcleo MaxScript
    Todo lo que toca la escena vive aquí. La interfaz (Python/Qt) solo llama a
    estas funciones globales con argumentos posicionales.

    olb_sceneEngine()                                  -> "corona" | "vray" | "other"
    olb_merge f name group layerMode objDups mtlDups lights cameras   -> #(nodes)
    olb_place nodes onSurface multi                    -> #(nodes colocados)
    olb_mergeProxy f name proxyDir mode engine layerMode mtlDups display -> #(nodes)
    olb_makePreview outFile size method margin elev azim fromView     -> true/false
    olb_sceneFiles()                                   -> #(rutas de assets de la escena)
    olb_setFileDir oldPath newDir                      -> true
*/

global olb_placeData
struct olb_PlaceStruct (nodes = #(), roots = #(), anchor = [0,0,0], onSurface = true, placed = false, clicked = false, midAbort = false, midWas = false)

-- ¿Está pulsada la rueda del ratón (botón central) ahora mismo?
global olb_ctlClass, olb_btnMiddle
fn olb_midDown =
(
    try
    (
        if olb_ctlClass == undefined do
        (
            olb_ctlClass = dotNetClass "System.Windows.Forms.Control"
            olb_btnMiddle = (dotNetClass "System.Windows.Forms.MouseButtons").Middle
        )
        dotNet.compareEnums olb_ctlClass.MouseButtons olb_btnMiddle
    )
    catch ( false )
)

-- ---------------------------------------------------------------------------
-- Utilidades
-- ---------------------------------------------------------------------------
fn olb_sceneEngine =
(
    local n = toLower ((classof renderers.current) as string)
    if matchPattern n pattern:"*corona*" then "corona"
    else if (matchPattern n pattern:"*v_ray*") or (matchPattern n pattern:"*vray*") then "vray"
    else if matchPattern n pattern:"*fstorm*" then "fstorm"
    else "other"
)

-- El puente se entera de los cambios por callbacks (y no preguntando cada segundo)
fn olb_stateChanged =
(
    try ( python.execute "import openlibrary_max.server as _ols\n_ols._refresh_state()" ) catch ()
)

fn olb_watchState enable =
(
    callbacks.removeScripts id:#OpenLibraryState
    if enable do
        for ev in #(#filePostOpen, #filePostSave, #systemPostNew, #systemPostReset, #postRendererChange, \
                    #selectionSetChanged) do
            callbacks.addScript ev "olb_stateChanged()" id:#OpenLibraryState
    ok
)

fn olb_safeName s =
(
    local bad = "\\/:*?\"<>| "
    local out = ""
    for i = 1 to s.count do
    (
        local c = s[i]
        out += (if (findString bad c) != undefined then "_" else c)
    )
    out
)

fn olb_roots nodes =
(
    for n in nodes where isValidNode n and (n.parent == undefined or (findItem nodes n.parent) == 0) collect n
)

fn olb_bbox nodes =
(
    local mn = [1e30, 1e30, 1e30]
    local mx = [-1e30, -1e30, -1e30]
    local any = false
    for n in nodes where isValidNode n and not (isGroupHead n) do
    (
        local a = n.min
        local b = n.max
        if a.x > b.x then continue   -- objetos sin geometría
        mn = [amin mn.x a.x, amin mn.y a.y, amin mn.z a.z]
        mx = [amax mx.x b.x, amax mx.y b.y, amax mx.z b.z]
        any = true
    )
    if not any then
    (
        mn = [0,0,0]
        mx = [0,0,0]
        for n in nodes where isValidNode n do ( mn = n.pos; mx = n.pos )
    )
    #(mn, mx)
)

fn olb_layerNames =
(
    for i = 0 to LayerManager.count - 1 collect (LayerManager.getLayer i).name
)

fn olb_cleanNewLayers before =
(
    -- borra capas vacías que trajo el merge
    local names = olb_layerNames()
    for n in names where (findItem before n) == 0 do
        try (LayerManager.deleteLayerByName n) catch ()
)

fn olb_assignLayer nodes layerMode assetName =
(
    local lay = undefined
    if layerMode == "asset" then
    (
        lay = LayerManager.getLayerFromName assetName
        if lay == undefined then lay = LayerManager.newLayerFromName assetName
    )
    else if layerMode == "current" then lay = LayerManager.current
    if lay != undefined then
        for n in nodes where isValidNode n do lay.addNode n
)

-- ---------------------------------------------------------------------------
-- Merge
-- ---------------------------------------------------------------------------
fn olb_merge f assetName doGroup layerMode objDups mtlDups lights cameras =
(
    if not (doesFileExist f) then return #()

    local objOpt = case objDups of
    (
        "merge":   #mergeDups
        "skip":    #skipDups
        "replace": #deleteOldDups
        "ask":     #promptDups
        default:   #autoRenameDups
    )
    local mtlOpt = case mtlDups of
    (
        "file":    #useMergedMtlDups
        "rename":  #renameMtlDups
        "ask":     #promptMtlDups
        default:   #useSceneMtlDups
    )

    local layersBefore = olb_layerNames()
    clearSelection()
    local ok = mergeMAXFile f objOpt mtlOpt #neverReparent #select #noRedraw quiet:true
    if not ok then return #()
    local nodes = selection as array

    -- Luces y cámaras
    if (not lights) or (not cameras) then
    (
        local del = #()
        for n in nodes where isValidNode n do
        (
            local sc = superclassof n
            if ((not lights) and sc == light) or ((not cameras) and sc == camera) then
            (
                append del n
                if (isProperty n #target) and n.target != undefined then append del n.target
            )
        )
        for d in del where isValidNode d do delete d
        nodes = for n in nodes where isValidNode n collect n
    )

    -- Capa
    olb_assignLayer nodes layerMode assetName

    -- Grupo
    if doGroup and nodes.count > 0 then
    (
        local tops = olb_roots nodes
        if tops.count > 0 then
        (
            local g = group tops name:(uniqueName (assetName + "_"))
            append nodes g
            olb_assignLayer #(g) layerMode assetName
        )
    )

    if layerMode != "file" then olb_cleanNewLayers layersBefore
    select nodes
    nodes
)

-- ---------------------------------------------------------------------------
-- Merge and Place: el modelo sigue al ratón y se apoya en las superficies.
--   Clic izquierdo  = soltar aquí (y, en modo múltiple, sigue con una instancia)
--   Rueda (pulsar)  = girar 90º en Z
--   Botón derecho   = terminar (igual que Esc)
--   Ctrl            = ignorar superficies, solo grid
-- ---------------------------------------------------------------------------
fn olb_surfacePoint =
(
    local best = undefined
    try
    (
        local r = mapScreenToWorldRay mouse.pos
        local hits = intersectRayScene r
        local bestD = 1e30
        for h in hits do
        (
            local nd = h[1]
            if (findItem olb_placeData.nodes nd) == 0 and not nd.isHidden then
            (
                local d = distance r.pos h[2].pos
                if d < bestD then ( bestD = d; best = h[2].pos )
            )
        )
    )
    catch ()
    best
)

fn olb_placeAt ir gridOnly =
(
    local pos = undefined
    if olb_placeData.onSurface and not gridOnly then pos = olb_surfacePoint()
    if pos == undefined and ir != undefined then pos = ir.pos
    if pos != undefined then
    (
        local delta = pos - olb_placeData.anchor
        for n in olb_placeData.roots where isValidNode n do n.pos += delta
        olb_placeData.anchor = pos
        olb_placeData.placed = true
        redrawViews()
    )
)

fn olb_rotateCurrent deg =
(
    local rot = eulerAngles 0 0 deg
    about olb_placeData.anchor
    (
        for n in olb_placeData.roots where isValidNode n do rotate n rot
    )
    redrawViews()
)

-- Al pulsar la rueda (solo al bajar, no mientras sigue pulsada): girar 90º
fn olb_checkMid =
(
    local down = olb_midDown()
    if down and not olb_placeData.midWas then olb_rotateCurrent 90.0
    olb_placeData.midWas = down
)

fn olb_trackCB msg ir obj faceNum shift ctrl alt =
(
    case msg of
    (
        #freeMove:   ( olb_checkMid(); olb_placeAt ir ctrl; #continue )
        #mouseMove:  ( olb_checkMid(); olb_placeAt ir ctrl; #continue )
        #mousePoint: ( olb_placeAt ir ctrl; olb_placeData.clicked = true; #stop )
        -- el botón derecho (o Esc) interrumpe; si fue la rueda, se gira y se sigue colocando
        #mouseAbort: ( olb_placeData.midAbort = olb_midDown() or olb_placeData.midWas; #abort )
        default:     #continue
    )
)

fn olb_cloneCurrent =
(
    local nn = #()
    try ( maxOps.cloneNodes olb_placeData.nodes cloneType:#instance newNodes:&nn ) catch ( nn = #() )
    nn
)

fn olb_place nodes onSurface multi =
(
    nodes = for n in nodes where isValidNode n collect n
    if nodes.count == 0 then return #()
    local bb = olb_bbox nodes
    local anchor = [(bb[1].x + bb[2].x) / 2.0, (bb[1].y + bb[2].y) / 2.0, bb[1].z]
    olb_placeData = olb_PlaceStruct nodes:nodes roots:(olb_roots nodes) anchor:anchor onSurface:onSurface
    local placedNodes = #()
    local done = false
    local quickAborts = 0
    local loops = 0
    pushPrompt ("OpenLibrary: clic = colocar" + (if multi then " y seguir con otra instancia" else "") + \
        " | rueda = girar 90º | botón derecho o Esc = terminar | Ctrl = solo grid")
    while not done do
    (
        loops += 1
        olb_placeData.clicked = false
        olb_placeData.midAbort = false
        local t0 = timeStamp()
        try ( mouseTrack trackCallback:olb_trackCB ) catch ()
        -- Si lo interrumpió la rueda, se gira y se sigue; el botón derecho, Esc o cualquier
        -- otra interrupción termina la colocación.
        local midClick = (olb_placeData.midAbort or olb_midDown()) and not keyboard.escPressed
        if olb_placeData.clicked then
        (
            quickAborts = 0
            join placedNodes olb_placeData.nodes
            if not multi then done = true
            else
            (
                local nn = olb_cloneCurrent()
                if nn.count == 0 then done = true
                else
                (
                    olb_placeData.nodes = nn
                    olb_placeData.roots = olb_roots nn
                )
            )
        )
        else if not midClick then done = true
        else
        (
            -- Si el giro no se hizo ya al bajar la rueda (callback), se hace ahora
            local already = olb_placeData.midWas
            -- Esperamos a que se suelte la rueda para no girar dos veces
            local w = 0
            while olb_midDown() and w < 100 do ( sleep 0.01; w += 1 )
            olb_placeData.midWas = false
            -- Seguro: si mouseTrack vuelve al instante una y otra vez, salimos
            if (timeStamp() - t0) < 40 then quickAborts += 1 else quickAborts = 0
            if quickAborts > 3 or loops > 10000 then done = true
            else if not already then olb_rotateCurrent 90.0
        )
    )
    popPrompt()
    if placedNodes.count > 0 then
    (
        -- La copia que quedaba flotando se borra
        local floating = for n in olb_placeData.nodes where isValidNode n and (findItem placedNodes n) == 0 collect n
        if floating.count > 0 then delete floating
    )
    else placedNodes = olb_placeData.nodes
    placedNodes = for n in placedNodes where isValidNode n collect n
    select placedNodes
    placedNodes
)

-- ---------------------------------------------------------------------------
-- Proxies (Corona .cgeo / V-Ray .vrmesh)
-- ---------------------------------------------------------------------------
fn olb_proxyExt engine = if engine == "vray" then ".vrmesh" else ".cgeo"

fn olb_writeRel fname rel =
(
    try
    (
        local fs = createFile (fname + ".olb")
        format "%" rel to:fs
        close fs
    )
    catch ()
)

fn olb_readRel fname =
(
    local rel = matrix3 1
    local side = fname + ".olb"
    if doesFileExist side then
    (
        try
        (
            local fs = openFile side
            local txt = readLine fs
            close fs
            local v = execute txt
            if classof v == Matrix3 then rel = v
        )
        catch ()
    )
    rel
)

fn olb_newProxyFromFile fname engine =
(
    local p = undefined
    if engine == "vray" then
    (
        try ( p = VRayProxy fileName:fname ) catch ( p = undefined )
    )
    else
    (
        try
        (
            p = CProxy()
            try ( p.filename = fname ) catch ( try ( p.cacheFilename = fname ) catch () )
        )
        catch ( p = undefined )
    )
    p
)

-- Exporta el nodo 'src' al archivo y devuelve el nodo proxy colocado.
fn olb_exportProxy src fname engine =
(
    local p = undefined
    if engine == "vray" then
    (
        local before = for o in objects where (classof o) == VRayProxy collect o
        try
        (
            vrayMeshExport meshFile:fname nodes:#(src) autoCreateProxies:true exportMultiple:false animation:off
        )
        catch ( format "OpenLibrary: error en vrayMeshExport: %\n" (getCurrentException()) )
        local after = for o in objects where (classof o) == VRayProxy and (findItem before o) == 0 collect o
        if after.count > 0 then p = after[1]
        else
        (
            p = olb_newProxyFromFile fname engine
            if p != undefined then p.transform = src.transform
        )
    )
    else
    (
        try
        (
            p = CProxy()
            CProxy.ProxyFp.fromScene p src fname
            p.transform = src.transform
        )
        catch
        (
            format "OpenLibrary: error creando CProxy: %\n" (getCurrentException())
            if p != undefined and isValidNode p then delete p
            p = undefined
        )
    )
    if p != undefined and isValidNode src then olb_writeRel fname (p.transform * (inverse src.transform))
    p
)

-- Malla temporal en espacio local con el pivote en la base del objeto
fn olb_bakeMesh n piv =
(
    local m = snapshotAsMesh n
    if piv == undefined then
        piv = [(n.min.x + n.max.x) / 2.0, (n.min.y + n.max.y) / 2.0, n.min.z]
    if m.numverts > 0 then meshop.moveVert m #{1..m.numverts} (-piv)
    local tmp = Editable_mesh()
    tmp.mesh = m
    tmp.transform = transMatrix piv
    tmp.material = n.material
    tmp.name = n.name
    tmp
)

-- Modo de visualización en viewport: "bbox" | "preview" | "full"
--   V-Ray (SDK pb2meshproxy.h): 0 caja, 1 preview, 2 punto, 3 preview caras, 4 malla completa
--   Corona: 0 caja sólida, 1 caja de alambre, 2 nube de puntos, 3 malla completa
fn olb_setProxyDisplay p engine mode =
(
    if p == undefined or not (isValidNode p) then return false
    local v
    if engine == "vray" then
    (
        v = case mode of ( "bbox": 0; "full": 4; default: 3 )
        try ( p.display = v; true ) catch ( false )
    )
    else
    (
        v = case mode of ( "bbox": 1; "full": 3; default: 2 )
        try ( p.previzType = v; true ) catch ( false )
    )
)

fn olb_isGeo n =
(
    isValidNode n and (superclassof n) == GeometryClass and (classof n) != TargetObject \
        and (canConvertTo n Editable_Mesh) and not (isGroupHead n)
)

fn olb_mergeProxy f assetName proxyDir mode engine layerMode mtlDups display =
(
    -- Proxy ya creado antes (en este u otro proyecto): se trae el .max pequeño
    -- con los proxies y sus materiales, sin volver a mergear el modelo pesado.
    local cacheMax = proxyDir + "\\proxies.max"
    if (doesFileExist (proxyDir + "\\done.olb")) and (doesFileExist cacheMax) then
    (
        local cached = olb_merge cacheMax assetName false layerMode "autorename" mtlDups false false
        if cached.count > 0 then
        (
            for n in cached do olb_setProxyDisplay n engine display
            return cached
        )
    )

    local nodes = olb_merge f assetName false "current" "autorename" mtlDups false false
    if nodes.count == 0 then return #()
    makeDir proxyDir all:true
    local reuse = doesFileExist (proxyDir + "\\done.olb")
    local ext = olb_proxyExt engine
    local geo = for n in nodes where olb_isGeo n collect n
    local result = #()
    local base = olb_safeName assetName

    -- Sources temporales en espacio limpio
    local sources = #()
    if mode == "single" and geo.count > 0 then
    (
        -- Pivote común en la base del conjunto
        local bb = olb_bbox geo
        local piv = [(bb[1].x + bb[2].x) / 2.0, (bb[1].y + bb[2].y) / 2.0, bb[1].z]
        local tgt = olb_bakeMesh geo[1] piv
        tgt.name = assetName
        for i = 2 to geo.count do
        (
            local t = olb_bakeMesh geo[i] piv
            try ( meshop.attach tgt t attachMat:#IDToMat condenseMat:true deleteSourceNode:true ) catch ( delete t )
        )
        sources = #(tgt)
    )
    else
    (
        sources = for g in geo collect olb_bakeMesh g undefined
    )

    -- Borramos lo mergeado original
    for n in nodes where isValidNode n and (isGroupMember n) do setGroupMember n false
    for n in nodes where isValidNode n do n.parent = undefined
    for n in nodes where isValidNode n do delete n

    for i = 1 to sources.count do
    (
        local src = sources[i]
        local fname = proxyDir + "\\" + base + (if sources.count > 1 then ("_" + (formattedPrint i format:"03d")) else "") + ext
        local p = undefined
        if reuse and (doesFileExist fname) then
        (
            p = olb_newProxyFromFile fname engine
            if p != undefined then p.transform = (olb_readRel fname) * src.transform
        )
        if p == undefined then p = olb_exportProxy src fname engine
        if p != undefined then
        (
            p.name = uniqueName (src.name + "_proxy")
            p.material = src.material
            olb_setProxyDisplay p engine display
            append result p
        )
        if isValidNode src then delete src
    )

    if result.count > 0 then
    (
        try ( saveNodes result cacheMax quiet:true ) catch ()
        try
        (
            local fs = createFile (proxyDir + "\\done.olb")
            format "%\n" f to:fs
            close fs
        ) catch ()
    )
    olb_assignLayer result layerMode assetName
    select result
    result
)

-- ---------------------------------------------------------------------------
-- Preview
--   Encuadre automático por bounding box (sirve igual para una silla que para
--   un edificio) o desde la vista activa.
-- ---------------------------------------------------------------------------
fn olb_fitCamera nodes fovDeg margin elev azim =
(
    local bb = olb_bbox nodes
    local c = (bb[1] + bb[2]) / 2.0
    elev = amax -85.0 (amin 85.0 elev)
    local dir = normalize [sin(azim) * cos(elev), -cos(azim) * cos(elev), sin(elev)]
    local xAx = normalize (cross [0,0,1] dir)
    local yAx = cross dir xAx
    local t = (tan (fovDeg / 2.0)) / margin
    local d = 0.0
    local a = bb[1]
    local b = bb[2]
    for cx in #(a.x, b.x) do for cy in #(a.y, b.y) do for cz in #(a.z, b.z) do
    (
        local v = [cx, cy, cz] - c
        local along = dot v dir
        local need = amax ((abs (dot v xAx)) / t + along) ((abs (dot v yAx)) / t + along)
        if need > d then d = need
    )
    if d < 1.0 then d = 1.0
    local pos = c + dir * d
    Freecamera name:(uniqueName "olb_previewCam") fov:fovDeg transform:(matrix3 xAx yAx dir pos) \
        nearclip:0.1 farclip:(d * 4.0)
)

fn olb_makePreview outFile size method margin elev azim fromView =
(
    local nodes = selection as array
    if nodes.count == 0 and not fromView then return false
    -- añade miembros de grupos seleccionados
    for n in (selection as array) where isGroupHead n do
        for ch in (n.children) where (findItem nodes ch) == 0 do append nodes ch

    local others = for o in objects where not o.isHidden and (findItem nodes o) == 0 \
        and (superclassof o) != light collect o
    local cam = undefined
    local ok = false
    local oldPass = undefined
    with redraw off
    (
        if nodes.count > 0 then hide others
    )
    try
    (
        local bmp = undefined
        if method == "viewport" then
        (
            local oldCam = viewport.getCamera()
            local oldTM = viewport.getTM()
            local oldType = viewport.getType()
            local w = gw.getWinSizeX()
            local h = gw.getWinSizeY()
            if not fromView then
            (
                -- fov horizontal tal que el recorte cuadrado central encuadre bien
                local vfov = 40.0
                local hfov = 2.0 * (atan ((tan (vfov / 2.0)) * (w as float) / (h as float)))
                cam = olb_fitCamera nodes vfov margin elev azim
                cam.fov = hfov
                viewport.setCamera cam
            )
            completeRedraw()
            local dib = gw.getViewportDib()
            local side = amin dib.width dib.height
            local sq = bitmap side side
            pasteBitmap dib sq (box2 ((dib.width - side) / 2) ((dib.height - side) / 2) side side) [0,0]
            bmp = bitmap size size
            copy sq bmp
            close sq
            close dib
            if not fromView then
            (
                if oldCam != undefined then viewport.setCamera oldCam
                else ( viewport.setType oldType; viewport.setTM oldTM )
            )
        )
        else
        (
            -- render con el motor activo, con límite de pasadas para que sea rápido
            if (olb_sceneEngine()) == "corona" then
            (
                try ( oldPass = renderers.current.progressive_passLimit; renderers.current.progressive_passLimit = 12 ) catch ()
            )
            if fromView then
                bmp = render outputSize:[size, size] vfb:false quiet:true
            else
            (
                cam = olb_fitCamera nodes 40.0 margin elev azim
                bmp = render camera:cam outputSize:[size, size] vfb:false quiet:true
            )
        )
        if bmp != undefined then
        (
            makeDir (getFilenamePath outFile) all:true
            bmp.filename = outFile
            save bmp
            close bmp
            ok = true
        )
    )
    catch ( format "OpenLibrary: error generando preview: %\n" (getCurrentException()) )

    if oldPass != undefined then try ( renderers.current.progressive_passLimit = oldPass ) catch ()
    if cam != undefined and isValidNode cam then delete cam
    with redraw off ( for o in others where isValidNode o do o.isHidden = false )
    redrawViews()
    ok
)

-- ---------------------------------------------------------------------------
-- Rutas de la escena (Asset Tracking)
-- ---------------------------------------------------------------------------
fn olb_sceneFiles =
(
    local fl = #()
    try ( ATSOps.Refresh(); ATSOps.GetFiles &fl ) catch ()
    fl
)

fn olb_setFileDir oldPath newDir =
(
    try
    (
        ATSOps.ClearSelection()
        ATSOps.SelectFiles #(oldPath)
        ATSOps.SetPathOnSelection newDir
        ATSOps.ClearSelection()
        true
    )
    catch ( false )
)

-- ---------------------------------------------------------------------------
-- Previews en lote (lo lanza la app con 3dsmaxbatch, sin tocar el Max del usuario)
--   jobsFile: una línea por asset "archivo.max<TAB>preview.jpg"
--   logFile:  se añade una línea "ok<TAB>n" o "fail<TAB>n" al acabar cada uno
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- Materiales y texturas (pestañas Materiales y Texturas de la app)
-- ---------------------------------------------------------------------------

-- (desde Python llegan doubles: «200.0d0» no se puede decodificar, por eso se pasa a float)
fn olb_cm v = ( units.decodeValue (((v as float) as string) + "cm") )

-- Medidas reales en un StandardUVGen (Bitmap de Max y VRayBitmap).
fn olb_realCoords c wCm hCm =
(
    -- (no tocar U_Tiling: con la escala real activada es el mismo valor que el ancho)
    try ( c.realWorldScale = true; c.realWorldWidth = olb_cm wCm; c.realWorldHeight = olb_cm hCm ) catch ()
)

-- Mapas que va creando olb_texNode para el material en curso (para enlazar sus medidas al final).
global olb_madeTex = #()

-- Nombres de material que ya hay en la escena, en el editor compacto y en las vistas de Slate (en minusculas).
fn olb_usedMatNames =
(
    local out = #()
    try ( for m in sceneMaterials do appendIfUnique out (toLower m.name) ) catch ()
    try ( for m in meditMaterials do appendIfUnique out (toLower m.name) ) catch ()
    try
    (
        for i = 1 to sme.GetNumViews() do
        (
            local v = sme.GetView i
            for j = 1 to v.GetNumNodes() do
                try ( local r = (v.GetNode j).reference; if superClassOf r == material do appendIfUnique out (toLower r.name) ) catch ()
        )
    )
    catch ()
    out
)

-- Material de la escena, del editor compacto o de Slate que se llama exactamente nm (sin mirar mayusculas).
fn olb_findMaterial nm =
(
    local hit = undefined
    local low = toLower nm
    try ( for m in sceneMaterials while hit == undefined where (toLower m.name) == low do hit = m ) catch ()
    if hit == undefined do
        try ( for m in meditMaterials while hit == undefined where (toLower m.name) == low do hit = m ) catch ()
    if hit == undefined do
    (
        try
        (
            for i = 1 to sme.GetNumViews() while hit == undefined do
            (
                local v = sme.GetView i
                for j = 1 to v.GetNumNodes() while hit == undefined do
                    try ( local r = (v.GetNode j).reference; if superClassOf r == material and (toLower r.name) == low do hit = r ) catch ()
            )
        )
        catch ()
    )
    hit
)

-- ¿Esta ya ese material (la misma instancia) en la escena, el editor compacto o Slate?
fn olb_matKnown m =
(
    local ok = false
    try ( for x in sceneMaterials while not ok where x == m do ok = true ) catch ()
    if not ok do try ( for x in meditMaterials while not ok where x == m do ok = true ) catch ()
    if not ok do
        try
        (
            for i = 1 to sme.GetNumViews() while not ok do
            (
                local v = sme.GetView i
                for j = 1 to v.GetNumNodes() while not ok do try ( ok = (v.GetNode j).reference == m ) catch ()
            )
        )
        catch ()
    ok
)

-- Si ya hay un material con ese nombre, el siguiente libre: «Nombre_01», «Nombre_02»...
fn olb_uniqueMatName nm =
(
    local used = olb_usedMatNames()
    if findItem used (toLower nm) == 0 then nm
    else
    (
        local i = 1
        local cand = nm + "_01"
        while findItem used (toLower cand) != 0 do
        (
            i += 1
            cand = nm + "_" + (formattedPrint i format:"02d")
        )
        cand
    )
)

-- Pone el mismo controlador a la propiedad de todos los mapas: al cambiar la medida en uno cambia en
-- todos (se conserva el valor que tenia el primero).
fn olb_shareCtrl owners prop ctrlClass =
(
    local c = undefined
    for o in owners do
    (
        try
        (
            local v = getProperty o prop
            if c == undefined then
            (
                c = ctrlClass()
                setPropertyController o prop c
                setProperty o prop v
            )
            else setPropertyController o prop c
        )
        catch ( format "OpenLibrary: no pude enlazar %: %\n" prop (getCurrentException()) )
    )
)

-- Enlaza las medidas reales (o el tamano del triplanar de V-Ray) de los mapas de un material.
fn olb_linkSizes texs =
(
    local corona = #()
    local coords = #()
    local vtri = #()
    for t in texs where t != undefined do
    (
        if CoronaBitmap != undefined and classOf t == CoronaBitmap then
            ( if t.realWorldScale do append corona t )
        else if VRayTriplanarTex != undefined and classOf t == VRayTriplanarTex then
            append vtri t
        else if hasProperty t #coords do
            try ( if t.coords.realWorldScale do append coords t.coords ) catch ()
    )
    if corona.count > 1 do olb_shareCtrl corona #uvwScale Bezier_Point3
    -- en un StandardUVGen el ancho y el alto reales son U_Tiling y V_Tiling
    if coords.count > 1 do ( olb_shareCtrl coords #U_Tiling Bezier_Float; olb_shareCtrl coords #V_Tiling Bezier_Float )
    if vtri.count > 1 do olb_shareCtrl vtri #size Bezier_Float
)

-- Mapa de imagen del motor pedido. role: "color" o "data" (sin gamma: normal, roughness...).
-- mapping "triplanar": proyeccion por las tres caras con baldosa de wCm centimetros.
-- mapping "realworld": la textura mide wCm x hCm (para un UVW Map con «Real-World Map Size»).
fn olb_texNode f engine role mapping wCm hCm =
(
    local t = undefined
    local nm = getFilenameFile f
    if engine == "corona" and CoronaBitmap != undefined then
    (
        t = CoronaBitmap filename:f
        t.name = nm
        if role != "color" do t.gamma = 1.0
        if mapping == "triplanar" do ( t.triplanarMapping = true; t.triplanarScale = olb_cm wCm )
        if mapping == "realworld" do ( t.realWorldScale = true; t.uvwScale = [olb_cm wCm, olb_cm hCm, 1] )
        append olb_madeTex t
    )
    else if engine == "vray" and VRayBitmap != undefined then
    (
        t = VRayBitmap HDRIMapName:f
        t.name = nm
        if role != "color" do t.color_space = 0
        if mapping == "realworld" do olb_realCoords t.coords wCm hCm
        if mapping == "triplanar" do
        (
            local tp = VRayTriplanarTex texture:t size:(olb_cm wCm)
            tp.name = nm + " triplanar"
            t = tp
        )
        append olb_madeTex t
    )
    else
    (
        t = Bitmaptexture fileName:f
        t.name = nm
        if role != "color" do try ( t.bitmap = openBitmap f gamma:1.0 ) catch ()
        if mapping == "realworld" do olb_realCoords t.coords wCm hCm
        append olb_madeTex t
    )
    t
)

-- Mete un mapa en el CoronaTriplanar compartido y devuelve la salida que hay que conectar al material
-- (la principal para el primero, «Additional Output N» para los demas). Sin triplanar, el mapa tal cual.
fn olb_triWire tri tex =
(
    if tri == undefined or tex == undefined then tex
    else
    (
        local idx = 1
        if tri.texmapX == undefined then tri.texmapX = tex
        else
        (
            tri.additionalOutputs = tri.additionalOutputs + 1
            tri.additionalTexmapX[tri.additionalOutputs] = tex
            idx = tri.additionalOutputs + 1
        )
        local o = MultiOutputChannelTexmapToTexmap sourceMap:tri outputChannelIndex:idx
        o
    )
)

fn olb_specFile keys vals ch =
(
    local i = findItem keys ch
    if i == 0 then undefined else vals[i]
)

-- Material PBR del motor pedido a partir de sus mapas.
-- spec: "canal=ruta|canal=ruta" con canales color, rough, gloss, refl, metal, normal, normaldx, bump,
-- disp, opacity, emission, transl. Devuelve el material (sin asignar a nada).
fn olb_pbrMaterial matName engine spec mapping wCm hCm useDisp =
(
    local keys = #()
    local vals = #()
    for part in (filterString spec "|") do
    (
        local p = findString part "="
        if p != undefined do ( append keys (substring part 1 (p - 1)); append vals (substring part (p + 1) -1) )
    )
    local fColor = olb_specFile keys vals "color"
    local fRough = olb_specFile keys vals "rough"
    local fGloss = olb_specFile keys vals "gloss"
    local fRefl = olb_specFile keys vals "refl"
    local fMetal = olb_specFile keys vals "metal"
    local fNormal = olb_specFile keys vals "normal"
    local flipG = false
    if fNormal == undefined do ( fNormal = olb_specFile keys vals "normaldx"; flipG = fNormal != undefined )
    local fBump = olb_specFile keys vals "bump"
    local fDisp = olb_specFile keys vals "disp"
    local fOpac = olb_specFile keys vals "opacity"
    local fEmit = olb_specFile keys vals "emission"
    local fTrans = olb_specFile keys vals "transl"
    local m = undefined
    matName = olb_uniqueMatName matName
    olb_madeTex = #()

    if engine == "corona" and CoronaPhysicalMtl != undefined then
    (
        m = CoronaPhysicalMtl name:matName
        -- triplanar: un solo CoronaTriplanar con todos los mapas (el color en la entrada principal y el
        -- resto en las salidas adicionales); cada canal del material se conecta a su salida
        local tri = undefined
        local cm = mapping
        if mapping == "triplanar" and CoronaTriplanar != undefined do
        (
            tri = CoronaTriplanar scale:(olb_cm wCm)
            tri.name = matName + " triplanar"
            cm = "uv"
        )
        if fColor != undefined do m.baseTexmap = olb_triWire tri (olb_texNode fColor engine "color" cm wCm hCm)
        if fRough != undefined then ( m.roughnessMode = 0; m.baseRoughnessTexmap = olb_triWire tri (olb_texNode fRough engine "data" cm wCm hCm) )
        else if fGloss != undefined do ( m.roughnessMode = 1; m.baseRoughnessTexmap = olb_triWire tri (olb_texNode fGloss engine "data" cm wCm hCm) )
        if fMetal != undefined do m.metalnessTexmap = olb_triWire tri (olb_texNode fMetal engine "data" cm wCm hCm)
        if fNormal != undefined then
        (
            local n = CoronaNormal normalMap:(olb_texNode fNormal engine "data" cm wCm hCm)
            n.name = matName + " normal"
            n.flipGreen = flipG
            if fBump != undefined do ( n.additionalBump = olb_triWire tri (olb_texNode fBump engine "data" cm wCm hCm); n.additionalBumpOn = true )
            m.baseBumpTexmap = olb_triWire tri n
        )
        else if fBump != undefined do m.baseBumpTexmap = olb_triWire tri (olb_texNode fBump engine "data" cm wCm hCm)
        if fDisp != undefined do
        (
            m.displacementTexmap = olb_triWire tri (olb_texNode fDisp engine "data" cm wCm hCm)
            m.displacementTexmapOn = useDisp
            m.displacementMinimum = 0
            m.displacementMaximum = olb_cm 1
        )
        if fOpac != undefined do m.opacityTexmap = olb_triWire tri (olb_texNode fOpac engine "data" cm wCm hCm)
        if fEmit != undefined do ( m.selfIllumTexmap = olb_triWire tri (olb_texNode fEmit engine "color" cm wCm hCm); m.selfIllumLevel = 1 )
        if fTrans != undefined do ( m.translucencyColorTexmap = olb_triWire tri (olb_texNode fTrans engine "color" cm wCm hCm); m.translucencyFraction = 0.5 )
    )
    else if engine == "vray" and VRayMtl != undefined then
    (
        m = VRayMtl name:matName
        if fColor != undefined do m.texmap_diffuse = olb_texNode fColor engine "color" mapping wCm hCm
        if fRough != undefined or fGloss != undefined or fMetal != undefined or fRefl != undefined do m.reflection = white
        if fRough != undefined then ( m.brdf_useRoughness = true; m.texmap_reflectionGlossiness = olb_texNode fRough engine "data" mapping wCm hCm )
        else if fGloss != undefined do ( m.brdf_useRoughness = false; m.texmap_reflectionGlossiness = olb_texNode fGloss engine "data" mapping wCm hCm )
        if fMetal != undefined then m.texmap_metalness = olb_texNode fMetal engine "data" mapping wCm hCm
        else if fRefl != undefined do m.texmap_reflection = olb_texNode fRefl engine "data" mapping wCm hCm
        if fNormal != undefined then
        (
            local n = VRayNormalMap normal_map:(olb_texNode fNormal engine "data" mapping wCm hCm)
            n.name = matName + " normal"
            n.flip_green = flipG
            if fBump != undefined do n.bump_map = olb_texNode fBump engine "data" mapping wCm hCm
            m.texmap_bump = n
            m.texmap_bump_multiplier = 100
        )
        else if fBump != undefined do m.texmap_bump = olb_texNode fBump engine "data" mapping wCm hCm
        if fDisp != undefined do ( m.texmap_displacement = olb_texNode fDisp engine "data" mapping wCm hCm; m.texmap_displacement_on = useDisp )
        if fOpac != undefined do m.texmap_opacity = olb_texNode fOpac engine "data" mapping wCm hCm
        if fEmit != undefined do m.texmap_self_illumination = olb_texNode fEmit engine "color" mapping wCm hCm
        if fTrans != undefined do m.texmap_translucent = olb_texNode fTrans engine "color" mapping wCm hCm
    )
    else
    (
        engine = "max"
        if mapping == "triplanar" do mapping = "uv"
        m = PhysicalMaterial name:matName
        if fColor != undefined do m.base_color_map = olb_texNode fColor engine "color" mapping wCm hCm
        if fRough != undefined then ( m.roughness_inv = false; m.roughness_map = olb_texNode fRough engine "data" mapping wCm hCm )
        else if fGloss != undefined do ( m.roughness_inv = true; m.roughness_map = olb_texNode fGloss engine "data" mapping wCm hCm )
        if fMetal != undefined do m.metalness_map = olb_texNode fMetal engine "data" mapping wCm hCm
        if fNormal != undefined then
        (
            local n = Normal_Bump normal_map:(olb_texNode fNormal engine "data" mapping wCm hCm)
            n.name = matName + " normal"
            n.flipgreen = flipG
            if fBump != undefined do n.bump_map = olb_texNode fBump engine "data" mapping wCm hCm
            m.bump_map = n
            m.bump_map_amt = 1.0
        )
        else if fBump != undefined do m.bump_map = olb_texNode fBump engine "data" mapping wCm hCm
        if fDisp != undefined do ( m.displacement_map = olb_texNode fDisp engine "data" mapping wCm hCm; m.displacement_map_on = useDisp )
        if fOpac != undefined do m.cutout_map = olb_texNode fOpac engine "data" mapping wCm hCm
    )
    olb_linkSizes olb_madeTex
    olb_madeTex = #()
    m
)

-- Lo que el puente ha visto bajo el raton al soltar (lo calcula ops.py con la ventana real):
-- olb_cursorKnown = true y olb_cursorHit = objeto o undefined.
global olb_cursorKnown = false
global olb_cursorHit = undefined

-- Objeto visible en el visor idx, en el pixel (x, y) de su ventana, o undefined. cw x ch es el tamano
-- de la ventana en pixeles de Windows: con la pantalla escalada (125 %, 150 %...) Max trabaja en
-- pixeles logicos, asi que se pasa a su escala con getViewSize.
fn olb_nodeAtView idx x y cw ch =
(
    local best = undefined
    try
    (
        if idx >= 1 and idx <= viewport.numViews and viewport.activeViewport != idx do viewport.activeViewport = idx
        local vs = getViewSize()
        if cw > 0 and ch > 0 do ( x = x * vs.x / cw; y = y * vs.y / ch )
        local r = mapScreenToWorldRay [x, y]
        local bestD = 1e30
        for h in (intersectRayScene r) do
        (
            local nd = h[1]
            if not nd.isHidden and not nd.isFrozen do
            (
                local d = distance r.pos h[2].pos
                if d < bestD do ( bestD = d; best = nd )
            )
        )
    )
    catch ( format "OpenLibrary: no pude mirar el visor %: %\n" idx (getCurrentException()) )
    best
)

-- Objeto visible que hay bajo el raton en el visor activo, o undefined.
fn olb_nodeUnderCursor =
(
    local best = undefined
    try
    (
        local mp = mouse.pos
        local vs = getViewSize()
        if mp.x >= 0 and mp.y >= 0 and mp.x <= vs.x and mp.y <= vs.y do
        (
            local r = mapScreenToWorldRay mp
            local bestD = 1e30
            for h in (intersectRayScene r) do
            (
                local nd = h[1]
                if not nd.isHidden and not nd.isFrozen do
                (
                    local d = distance r.pos h[2].pos
                    if d < bestD do ( bestD = d; best = nd )
                )
            )
        )
    )
    catch ()
    best
)

-- Pone materiales o mapas en la vista activa del editor Slate. Devuelve cuantos.
fn olb_toSlate items =
(
    local n = 0
    try
    (
        if not (sme.IsOpen()) do sme.Open()
        local v = undefined
        try ( v = sme.GetView sme.activeView ) catch ()
        if v == undefined do ( sme.CreateView "OpenLibrary"; v = sme.GetView (sme.GetNumViews()) )
        -- a la derecha de lo que ya hay en la vista (los mapas se colocan a la izquierda de su material)
        local x0 = 0
        local y0 = 0
        local first = true
        for i = 1 to v.GetNumNodes() do
        (
            local p = undefined
            try ( p = (v.GetNode i).position ) catch ()
            if p != undefined do
            (
                if first or p.x > x0 do x0 = p.x
                if first or p.y < y0 do y0 = p.y
                first = false
            )
        )
        if not first do x0 += 700
        local k = 0
        for it in items do
        (
            v.CreateNode it [x0 + (mod k 4) * 700, y0 + ((k / 4) as integer) * 500]
            k += 1
            n += 1
        )
        try ( v.SetSelectedNodes items ) catch ()
        try ( v.ZoomExtents type:#selected ) catch ()
        try ( sme.SetMtlInParamEditor items[items.count] ) catch ()
    )
    catch ( format "OpenLibrary: no pude usar el editor Slate: %\n" (getCurrentException()) )
    n
)

-- Pone materiales en Slate reutilizando los nodos que ya hay: si todos estan ya en una misma vista, se
-- cambia a esa vista y se seleccionan; si no, se anaden a la vista activa los que no esten en ella.
-- Devuelve cuantos se han puesto nuevos.
fn olb_slateShow mats =
(
    local added = 0
    try
    (
        if not (sme.IsOpen()) do sme.Open()
        local inView = #()          -- vista de cada material (0 = en ninguna)
        for m in mats do
        (
            local w = 0
            for i = 1 to sme.GetNumViews() while w == 0 do
            (
                local v = sme.GetView i
                for j = 1 to v.GetNumNodes() while w == 0 do try ( if (v.GetNode j).reference == m do w = i ) catch ()
            )
            append inView w
        )
        local same = inView.count > 0 and inView[1] > 0
        for w in inView where w != inView[1] do same = false
        if same then
            try ( sme.activeView = inView[1] ) catch ()
        else
        (
            local v = sme.GetView sme.activeView
            local missing = #()
            for k = 1 to mats.count where inView[k] != sme.activeView do append missing mats[k]
            if missing.count > 0 do added = olb_toSlate missing
        )
        local v = sme.GetView sme.activeView
        try ( v.SetSelectedNodes mats ) catch ()
        try ( v.ZoomExtents type:#selected ) catch ()
        try ( sme.SetMtlInParamEditor mats[mats.count] ) catch ()
    )
    catch ( format "OpenLibrary: no pude usar el editor Slate: %\n" (getCurrentException()) )
    added
)

-- Caja de mapeado en cada objeto. mode "box": caja de X x Y x Z cm (ancho, largo, alto).
-- mode "realworld": caja con «Real-World Map Size» (la medida la pone la textura).
fn olb_realUvw nodes mode xCm yCm zCm =
(
    for n in nodes do
    (
        try
        (
            local u = undefined
            for md in n.modifiers where md.name == "OpenLibrary UVW" do u = md
            if u == undefined do ( u = Uvwmap name:"OpenLibrary UVW"; addModifier n u )
            u.maptype = 4
            if mode == "realworld" then
                u.realWorldMapSize = true
            else
            (
                u.realWorldMapSize = false
                u.width = olb_cm xCm
                u.length = olb_cm yCm
                u.height = olb_cm zCm
            )
        )
        catch ()
    )
)

-- ¿Esta el raton encima del editor Slate abierto? (lo decide Max: su ventana puede estar acoplada)
fn olb_mouseOverSlate =
(
    local r = false
    try
    (
        if sme.IsOpen() do
        (
            local mf = sme.GetMainframe()
            if mf.visible do
            (
                local p = mouse.screenpos
                local a = mf.position
                local s = mf.size
                r = p.x >= a.x and p.y >= a.y and p.x <= a.x + s.x and p.y <= a.y + s.y
            )
        )
    )
    catch ()
    r
)

-- Si el editor Slate esta abierto, deja ahi tambien lo que se acaba de poner a los objetos.
fn olb_alsoSlate mats =
(
    local open = false
    try ( open = sme.IsOpen() ) catch ()
    if open then olb_toSlate mats else 0
)

-- Objetos destino: el de debajo del raton (con toda la seleccion si es parte de ella) o la seleccion.
fn olb_targetNodes target =
(
    local nodes = #()
    if target == "cursor" do
    (
        local hit = if olb_cursorKnown then olb_cursorHit else olb_nodeUnderCursor()
        olb_cursorKnown = false
        olb_cursorHit = undefined
        if hit != undefined do
            nodes = if hit.isSelected then (selection as array) else #(hit)
    )
    if target != "slate" and target != "plane" and nodes.count == 0 do nodes = selection as array
    nodes
)

-- Reparte materiales. target: "selection", "cursor" (encima de Slate: Slate; si no, el objeto bajo el
-- raton o la seleccion) o "slate". uvwMode "box" / "realworld" anade la caja de mapeado (X, Y, Z en cm).
-- Devuelve "objects|N|nombre", "slate|N|nombre" o "none|0|nombre".
fn olb_putMaterials mats target uvwMode xCm yCm zCm =
(
    local out = "none|0|"
    if mats.count > 0 do
    (
        -- (los nuevos, p. ej. de una biblioteca .mat: con nombre propio si ya hay uno igual en la escena;
        -- uno que ya estaba en la escena se queda como esta)
        for m in mats where not (olb_matKnown m) do try ( m.name = olb_uniqueMatName m.name ) catch ()
        local nodes = olb_targetNodes target
        if target == "slate" then
            out = "slate|" + ((olb_toSlate mats) as string) + "|" + mats[1].name
        else if nodes.count == 0 then
            out = "none|0|" + mats[1].name
        else
        (
            for n in nodes do try ( n.material = mats[1] ) catch ()
            if uvwMode == "box" or uvwMode == "realworld" do olb_realUvw nodes uvwMode xCm yCm zCm
            -- con el editor abierto, el material aparece tambien en su vista activa
            local w = if (olb_alsoSlate #(mats[1])) > 0 then "objects+slate" else "objects"
            out = w + "|" + (nodes.count as string) + "|" + mats[1].name
        )
    )
    out
)

-- ---------------------------------------------------------------------------
-- Interiores falsos (wParallax / ShadersBOX): un mapa OSL lee el EXR de la habitacion y va a la
-- autoiluminacion de un material negro; la vista previa (jpg) solo se ve en el visor.
-- sizeCode "S" / "M" / "L" (ancho de ventana); depthIdx -1 = la profundidad de las escenas de ejemplo.
-- ---------------------------------------------------------------------------
fn olb_interiorMaterial matName engine osl exr preview sizeCode depthIdx =
(
    matName = olb_uniqueMatName matName
    local o = OSLMap()
    o.OSLPath = osl
    o.OSLAutoUpdate = true
    o.name = matName + " OSL"
    try ( o.filename = exr ) catch ()
    local vals = #(0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0)
    local aIdx = case sizeCode of ( "M": 4; "L": 5; default: 1 )
    local dIdx = if depthIdx >= 0 then depthIdx else (if sizeCode == "S" then 3 else 5)
    -- wParallax_SMP / ADV usan desplegables (indices); jiWindowBox, valores
    if matchPattern (filenameFromPath osl) pattern:"wParallax*" then
        ( try ( o.roomDepth = dIdx; o.windowAspect = aIdx ) catch () )
    else
        ( try ( o.roomDepth = vals[dIdx + 1]; o.windowAspect = vals[aIdx + 1] ) catch () )
    local pv = undefined
    if preview != "" do ( pv = Bitmaptexture fileName:preview; pv.name = matName + " preview" )
    local m = undefined
    if engine == "corona" and CoronaPhysicalMtl != undefined then
    (
        m = CoronaPhysicalMtl name:matName
        m.baseColor = black
        m.selfIllumTexmap = o
        m.selfIllumLevel = 1.5
        if pv != undefined do ( m.baseTexmap = pv; m.baseTexmapOn = false )
    )
    else if engine == "vray" and VRayMtl != undefined then
    (
        m = VRayMtl name:matName
        m.diffuse = black
        m.texmap_self_illumination = o
        m.selfIllumination_multiplier = 1.5
        if pv != undefined do ( m.texmap_diffuse = pv; m.texmap_diffuse_on = false )
    )
    else
    (
        m = PhysicalMaterial name:matName
        m.base_color = black
        m.emit_color_map = o
        m.emission = 1.0
    )
    if pv != undefined do try ( showTextureMap m pv true ) catch ()
    m
)

-- Plano vertical de la ventana (como los de las escenas de ejemplo), apoyado donde esta el raton
-- en el plano de construccion o, si el raton no esta en un visor, en el origen.
fn olb_interiorPlane mat wCm hCm =
(
    local pt = [0, 0, 0]
    try
    (
        local mp = mouse.pos
        local vs = getViewSize()
        if mp.x >= 0 and mp.y >= 0 and mp.x <= vs.x and mp.y <= vs.y do pt = gw.getPointOnCP mp
    )
    catch ()
    local p = Plane length:(olb_cm hCm) width:(olb_cm wCm) lengthsegs:1 widthsegs:1
    p.rotation = quat 0.707107 0 0 0.707107
    p.pos = pt + [0, 0, (olb_cm hCm) / 2.0]
    p.name = uniqueName ("OL_" + mat.name + "_")
    p.material = mat
    select p
    p
)

-- target: "selection", "cursor", "slate" o "plane" (crea la ventana). Sin objetos destino crea el plano
-- salvo con "selection". Devuelve "objects|N|nombre", "plane|1|nombre", "slate|N|nombre" o "none|0|nombre".
fn olb_putInterior mat target wCm hCm =
(
    local nodes = olb_targetNodes target
    if target == "slate" then
        "slate|" + ((olb_toSlate #(mat)) as string) + "|" + mat.name
    else if nodes.count > 0 then
    (
        for n in nodes do try ( n.material = mat ) catch ()
        local w = if (olb_alsoSlate #(mat)) > 0 then "objects+slate" else "objects"
        w + "|" + (nodes.count as string) + "|" + mat.name
    )
    else if target == "selection" then
        "none|0|" + mat.name
    else
    (
        olb_interiorPlane mat wCm hCm
        "plane|1|" + mat.name
    )
)

-- Materiales de una biblioteca .mat (sin abrirla en el editor).
fn olb_matLibMaterials f =
(
    local out = #()
    try ( local lib = loadTempMaterialLibrary f; if lib != undefined do for m in lib do append out m ) catch ()
    out
)

-- Cambia o quita rutas de archivos externos dentro de varios .max SIN abrirlos.
-- jobsFile: una linea por cambio, "archivo.max <tab> ruta guardada <tab> ruta nueva" ("<quitar>" la vacia).
-- logFile: "ok <tab> n cambiadas <tab> archivo.max" o "fail <tab> 0 <tab> archivo.max" por cada .max.
fn olb_editFilePaths jobsFile logFile =
(
    local files = #()
    local edits = #()
    local jf = openFile jobsFile mode:"r"
    while not (eof jf) do
    (
        local parts = filterString (readLine jf) "\t"
        if parts.count == 3 do
        (
            local i = findItem files parts[1]
            if i == 0 do ( append files parts[1]; append edits #(); i = files.count )
            append edits[i] #(parts[2], (if parts[3] == "<quitar>" then "" else parts[3]))
        )
    )
    close jf
    local total = 0
    for i = 1 to files.count do
    (
        local n = 0
        local ok = false
        try
        (
            local meta = getMAXFileAssetMetadata files[i]
            if meta != undefined do
            (
                for a in meta do
                    for e in edits[i] where (stricmp (a.filename as string) e[1]) == 0 do
                    (
                        a.filename = e[2]
                        n += 1
                    )
                ok = if n > 0 then (setMAXFileAssetMetadata files[i] meta) else true
            )
        )
        catch ( format "OpenLibrary: error en %: %\n" files[i] (getCurrentException()) )
        local lf = openFile logFile mode:"a" encoding:#utf8
        if lf != undefined then
        (
            format "%\t%\t%\n" (if ok then "ok" else "fail") n files[i] to:lf
            close lf
        )
        if ok do total += n
    )
    total
)

-- Datos de la escena cargada para la ficha de la app, separados por tabuladores:
-- poligonos, vertices, objetos de geometria, desplazamiento (1/0), animacion (1/0), primer y ultimo fotograma.
fn olb_sceneStats =
(
    local polys = 0
    local verts = 0
    local nGeo = 0
    for o in geometry where not (isKindOf o TargetObject) do
    (
        nGeo += 1
        try ( local c = getPolygonCount o; polys += c[1]; verts += c[2] ) catch ()
    )
    -- desplazamiento: modificador o material con el mapa de desplazamiento encendido
    local disp = false
    for o in objects while not disp do
        for m in o.modifiers while not disp do
        (
            local cn = toLower ((classOf m) as string)
            if cn == "displace" or matchPattern cn pattern:"*displacement*" do disp = m.enabled
        )
    local checks = #(#("CoronaPhysicalMtl", #displacementTexmap, #displacementTexmapOn),
                     #("CoronaLegacyMtl", #texmapDisplace, #texmapOnDisplacement),
                     #("CoronaMtl", #texmapDisplace, #texmapOnDisplacement),
                     #("VRayMtl", #texmap_displacement, #texmap_displacement_on),
                     #("PhysicalMaterial", #displacement_map, #displacement_map_on))
    for c in checks while not disp do
    (
        local cls = execute c[1]
        if cls != undefined and cls != ok do
            try
            (
                for m in (getClassInstances cls) while not disp do
                    try ( if (getProperty m c[2]) != undefined and (getProperty m c[3]) == true do disp = true ) catch ()
            )
            catch ()
    )
    local anim = false
    for o in objects while not anim do try ( if o.isAnimated do anim = true ) catch ()
    local s = 0
    local e = 0
    try ( s = animationRange.start.frame as integer; e = animationRange.end.frame as integer ) catch ()
    (polys as string) + "\t" + (verts as string) + "\t" + (nGeo as string) + "\t" + \
        (if disp then "1" else "0") + "\t" + (if anim then "1" else "0") + "\t" + (s as string) + "\t" + (e as string)
)

-- Lee los datos de varios .max (uno por linea en jobsFile). En logFile: "ok<TAB>n<TAB>datos" o "fail<TAB>n".
fn olb_batchStats jobsFile logFile =
(
    local jobs = #()
    local jf = openFile jobsFile mode:"r"
    while not (eof jf) do
    (
        local l = readLine jf
        if l != "" do append jobs l
    )
    close jf
    local n = 0
    for f in jobs do
    (
        n += 1
        local st = undefined
        try ( if (loadMaxFile f quiet:true useFileUnits:true) do st = olb_sceneStats() )
        catch ( format "OpenLibrary: error en %: %\n" f (getCurrentException()) )
        local lf = openFile logFile mode:"a" encoding:#utf8
        if lf != undefined do
        (
            if st != undefined then format "ok\t%\t%\n" n st to:lf else format "fail\t%\n" n to:lf
            close lf
        )
    )
    n
)

fn olb_batchPreviews jobsFile logFile size margin elev azim =
(
    local jobs = #()
    local jf = openFile jobsFile mode:"r"
    while not (eof jf) do
    (
        local parts = filterString (readLine jf) "\t"
        if parts.count == 2 do append jobs parts
    )
    close jf
    local n = 0
    for j in jobs do
    (
        n += 1
        local ok = false
        local st = undefined
        try
        (
            if (loadMaxFile j[1] quiet:true useFileUnits:true) then
            (
                try ( st = olb_sceneStats() ) catch ()
                local nodes = for o in objects where not o.isHidden and (superclassof o) != light \
                    and (superclassof o) != camera collect o
                -- encuadre solo con la geometria (los ayudantes y splines agrandan la caja)
                local geo = for o in nodes where (superclassof o) == GeometryClass collect o
                if geo.count > 0 do nodes = geo
                if nodes.count > 0 then
                (
                    -- sin luces propias el asset saldría negro: luz uniforme del entorno
                    useEnvironmentMap = false
                    backgroundColor = color 228 228 228
                    select nodes
                    ok = olb_makePreview j[2] size "render" margin elev azim false
                )
            )
        )
        catch ( format "OpenLibrary: error en %: %\n" j[1] (getCurrentException()) )
        local lf = openFile logFile mode:"a" encoding:#utf8
        if lf != undefined then
        (
            if ok and st != undefined then format "ok\t%\t%\n" n st to:lf
            else format "%\t%\n" (if ok then "ok" else "fail") n to:lf
            close lf
        )
    )
    n
)

format "OpenLibrary: núcleo MaxScript cargado\n"
