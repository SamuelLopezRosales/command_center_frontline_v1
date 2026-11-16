# Revisión visual de la SPA contra los diseños (T-134)

Insumo del punto de control de la Fase 7. Las capturas están en `docs/capturas_spa/` (1440x900, stack local, Edge
con Playwright: `npm run e2e:capturas` en `frontend/`). Los diseños son `kiro_command_center_frontline_v1/disenos/png/`
(`01_login`, `cv1_01` a `cv1_10`). La comparación es a ojo. Los datos son ficticios; los campos de celular salen
enmascarados en gris y las columnas de celular de las tablas ya vienen enmascaradas por la API (`+52 •• •••• 5678`).
Las filas «Marcela WhatsappMWID…», «Carga1 Masiva…», etc. son datos que dejaron las pruebas E2E.

## Diferencias que se repiten en todas las pantallas

| Tema | Diseño | SPA | Clara / gusto |
| --- | --- | --- | --- |
| Logotipo | Imagen HONNE (isotipo + «DELIVERING TRUE VALUE» en el acceso) | Texto «H O N N E» | Clara: falta el activo gráfico |
| Enlaces con aspecto de botón (`Configurar campos`, `Ver historial`, `Abrir`, `Cancelar`, `Volver…`, `+ Nuevo colaborador`, `Editar`) | Texto sin subrayado | Subrayado de enlace por defecto en todos los `<a>` con clase de botón | Clara: falta `text-decoration: none` en los enlaces-botón |
| Tipografía de controles | Controles de 12 a 13 px, botones compactos | Botones, `select` e `input` más grandes (14 a 16 px) | Gusto, pero cambia el ritmo de las pantallas |
| Barra lateral | Dashboard, Colaboradores, Constancias, Notificaciones | Agrega Chat y Usuarios (sin diseño); el nombre del usuario sale como «Ana Ramírez (RH)» y se parte en dos líneas | Chat y Usuarios: falta diseño. Nombre con «(RH)»: dato del stack local |
| Cabecera de página | Título con subtítulo «Empresa · N activos · N registrados» y acciones arriba a la derecha | Título con subtítulo corto; las acciones se desbordan en varias pantallas (ver abajo) | Clara en Colaboradores |
| Tablas | Filas de 52 px, textos secundarios en gris | Filas más compactas, folios y nombres largos se parten en varias líneas | Clara en Historial y Detalle |

## Por pantalla

### 01 Acceso (`01_login` / `01_acceso.png`)
- Coincide: tarjeta blanca centrada, subtítulo «Inicia sesión para continuar», campos Usuario o correo y Contraseña, botón naranja, enlace «¿Olvidaste tu contraseña?».
- Difiere: el fondo es azul liso (el diseño usa trama de líneas y circuitos con el logotipo grande arriba a la izquierda); el logotipo de la tarjeta es texto; el campo de contraseña no muestra puntos de ejemplo; los enlaces van subrayados y azul por defecto; hay un enlace extra «Crear cuenta con invitación» (no está en el diseño; en local no funciona).
- Falta por diseño: ninguno para el acceso.

### 02 MFA (`02_mfa.png`)
- Sin PNG de diseño. Es la misma tarjeta con «Código de verificación» y «Verificar». Falta decidir el diseño del paso MFA, del enrolamiento con QR y de registro/recuperar.

### 03 Dashboard (`cv1_01` / `03_dashboard.png`)
- Coincide: cuatro tarjetas con icono de color, «Solicitudes recientes» y «Alertas» en dos columnas, tabla «Constancias recientes», botón «Ver historial», chips de estado.
- Difiere: el subtítulo no lleva la razón social («Bienvenido, David Bet · Grupo Industrial Norte S.A. de C.V.» en el diseño); el rótulo «CONSTANCIAS ESTE MES» se parte en dos líneas en la tarjeta; el botón «Revisar» de cada alerta es naranja en el diseño y aquí solo hay uno (solo hay una alerta en este stack); «Descargar» es un enlace subrayado y no azul en negritas; en el stack local todas las solicitudes salen «GENERADA» (chip verde distinto de ENTREGADA/EN PROCESO del diseño).
- Inconsistencia de datos: «En proceso = 6» con todas las solicitudes en GENERADA. Revisar la definición del contador.
- Inconsistencia entre pantallas: el dashboard ofrece «Descargar» en constancias PENDIENTE y el historial no.

### 04 Colaboradores, listado (`cv1_02` / `04_colaboradores_listado.png`)
- Coincide: tabla con las ocho columnas, chip de estatus, filtros de organización, planta y estatus, «Columnas (N de M)», paginación «Mostrando 1–10 de 19».
- Difiere: **la cabecera se desborda a 1440 px** (la captura de página completa mide 1452 px: el botón «Columnas (7 de 16)» y «+ Nuevo colaborador» sobrepasan el borde derecho); hay tres botones de cabecera en vez de dos («Carga masiva» y «Organizaciones y plantas»; son funciones reales sin lugar en el diseño); el filtro «Todos los tipos» es extra; el buscador no muestra el texto completo «Buscar por nombre o número de empleado»; la lista no viene ordenada por número de empleado (aquí sale por orden de alta o clave); el subtítulo es «19 colaboradores» sin razón social ni «N registrados».
- Es una diferencia clara por corregir: el desbordamiento horizontal.

### 05 Colaborador, formulario (`cv1_03` / `05_colaborador_formulario.png`)
- Coincide: dos secciones «Datos fijos del sistema» y «Campos adicionales», tres columnas, marcas «Sensible», casilla de consentimiento con su ayuda, migas de pan.
- Difiere: «Cancelar» y «Guardar colaborador» están **abajo** (en el diseño, arriba a la derecha); el campo Celular está enmascarado en la captura por la regla de privacidad; las listas muestran «Selecciona…» (en el diseño traen valores de ejemplo); los campos sin lista no muestran texto de ejemplo (ej. «11 dígitos» para NSS, «Ej. Ruta 7»); las etiquetas son más grandes y en negrita; aparece la ayuda «Se guarda cifrado.» bajo los sensibles (no está en el diseño); la casilla de consentimiento es la nativa, no la naranja del diseño.

### 06 Configuración de campos (`cv1_04` / `06_campos.png`)
- Coincide: pestañas Todos/Sugeridos/Personalizados con conteo, tabla Campo/Clave/Tipo/Oblig./Sensible/Estado, fila de «Campos fijos del sistema (11): no editables aquí», claves `{{…}}` en naranja, chips Sensible/Activo/Inactivo.
- Difiere: el diseño muestra primero los campos dinámicos y el panel «Editar campo» a la derecha; la captura es la pantalla inicial sin campo elegido, así que el panel no aparece (la selección sí existe: se probó en pruebas unitarias). Los 11 fijos ocupan casi toda la página (en el diseño solo se muestra el encabezado de grupo). La casilla de «Celular con WhatsApp» sale gris sólida, distinta de las demás casillas bloqueadas (posible defecto de estilo).
- Falta por diseño: ninguno.

### 07 Carga masiva (sin PNG de diseño) (`07_carga_masiva.png`)
- Pantalla sin diseño. Dos tarjetas (descargar plantilla, subir archivo) y tabla «Cargas anteriores». Usa el campo nativo de archivo del navegador. Pendiente de diseño.

### 08 Organizaciones y plantas (sin PNG de diseño) (`08_organizaciones.png`)
- Pantalla sin diseño. Pestañas Organizaciones/Plantas, tabla con clave, razón social, RFC, ciudad, logotipo y estado. Todas las organizaciones sembradas muestran «Sin logotipo».

### 09 Constancias, plantillas (`cv1_05` / `09_plantillas.png`)
- Coincide: título, subtítulo, pestañas «Plantillas (N)» e «Historial», tabla con Plantilla/Versión/Actualizada/Emitidas/Estado/Acciones, chip de versión azul, chip ACTIVA.
- Difiere: la fila es más baja y el nombre y la descripción quedan más juntos; «Editar» va subrayado y las acciones son azules (en el diseño «Eliminar» es rojo); aparece «Desactivar» (no está en el diseño); solo hay una plantilla en el stack.

### 10 Editor de plantilla (`cv1_06` / `10_editor_plantilla.png`)
- Coincide: tres columnas (variables, hoja, vista previa/validación/versiones), barra con B/I/U, tamaño, alineación y color, «Insertar logotipo», chips de variable en naranja y sensibles en rojo, «Guardar borrador» y «Publicar vN».
- Difiere: la barra del editor y la del encabezado son más grandes que en el diseño; falta la lista de variables del diseño agrupada con el mismo orden; la hoja del documento es más corta (el contenido de ejemplo es de dos líneas); la vista previa pide escribir el colaborador de prueba (en el diseño ya viene uno elegido) y tiene un botón «Ver vista previa» y el enlace «Validar», que no existen en el diseño (el diseño muestra el resultado de validación fijo); el diseño muestra tres versiones con «Restaurar» y una sola con ACTIVA en el stack.

### 11 Historial de constancias (`cv1_07` / `11_historial.png`)
- Coincide: filtros (buscador, fechas, plantilla, estado), tabla con folio, colaborador, plantilla, versión, fecha, canal y estado, chips.
- Difiere: los filtros de fecha están vacíos (el diseño trae el mes en curso); el folio se parte en dos líneas («CG-2026-» / «0006») y las fechas también; la columna «Acción» queda **vacía** para las constancias PENDIENTE (el diseño muestra «Descargar»; la lógica `accionesDe` lo oculta a propósito); el canal sale como «WHATSAPP» en mayúsculas.
- El diseño muestra «RH» como canal alterno; el stack local solo trae WhatsApp.

### 12 Verificación pública (sin PNG de diseño) (`12_verificacion_publica.png`)
- Sin diseño. Tarjeta centrada sobre fondo azul con nombre, folio, fecha de emisión y estado VIGENTE; el rótulo «Command Center» va en texto con interletraje muy abierto. Pendiente de diseño de marca.

### 13 Notificaciones, listado (`cv1_08` / `13_notificaciones_listado.png`)
- Coincide: cuatro indicadores, pestañas Envíos/Programadas/Borradores con conteo, tabla Envío/Audiencia/Plantilla/Destinatarios/Estado/Fecha/Acción, botones «Plantillas de mensaje» y «+ Nueva notificación».
- Difiere: los indicadores muestran 0/0%/0/0 porque en local no hay entrega (en el diseño 1,284 / 96 % / 71 % / 14); «Ver detalle» va subrayado; el estado sale ENVIANDO sin fecha porque no hay enviador. Los estados del diseño usan colores (COMPLETADO verde, CON FALLAS rojo): aquí solo se vio ENVIANDO.

### 14 Plantillas de mensaje (`14_plantillas_mensaje.png`)
- Sin diseño. Catálogo con estado en Meta (Aprobada, En revisión, Rechazada) y acciones. Pendiente de diseño.

### 15 Nueva notificación con embudo (`cv1_09` / `15_notificacion_nueva_embudo.png`)
- Coincide: «¿A quién le escribimos?» con los tres modos, constructor de criterios, «Resumen del envío» con las cuatro barras del embudo (Seleccionados, Con consentimiento, Estatus ACTIVO, Celular válido), aviso amarillo de excluidos, «Cuándo» (Enviar ahora/Programar), casilla de respaldo por correo, «Respuestas», vista previa tipo WhatsApp, botones «Guardar borrador» y «Enviar a N colaboradores».
- Difiere: hay un campo «Título del envío» arriba (el diseño no lo tiene; la API lo exige); las filas de criterio en el diseño llevan el conector «Y» entre filas y un criterio por línea; el diseño pone el botón «Revisar y enviar» y «Guardar borrador» arriba y abajo; el canal «Respuesta dentro de 24 h» del diseño no existe (decisión: solo plantillas aprobadas); la vista previa muestra «{{Nombre completo}}» sin resolver, el diseño la muestra con el nombre de ejemplo; las casillas y radios son los nativos del navegador (en el diseño van en naranja); el botón «Enviar a 13 colaboradores» se parte en dos líneas.

### 16 Detalle de envío (`cv1_10` / `16_detalle_envio.png`)
- Coincide: barras de «Resultado del envío», nota de excluidos, «Mensaje enviado» en burbuja, «Audiencia» con chips, «Línea de tiempo», tabla de destinatarios con celular enmascarado.
- Difiere: **la tabla de destinatarios se sale de la tarjeta por la derecha** (la columna Acción queda cortada: «sin consentimie…»); los nombres largos se parten en tres líneas; falta «Reintentar fallidos» y «Ver conversaciones» porque no hay fallidos ni respuestas en el stack; el mensaje enviado muestra la variable sin resolver «{{nombre_completo}}» (en el diseño «{{nombre}}» también aparece así, es coherente); el estado ENVIANDO es un chip junto a las migas, el diseño lo muestra en la barra de resultado.

### 17 Chat de RH (sin PNG de diseño) (`17_chat.png`)
- Sin diseño. Lista de conversaciones con ventana de 24 h y detalle con asignación y envío de plantilla. **Muestra el aviso «Pantalla pendiente de validación visual con Samuel.»** como banner azul (texto de desarrollo visible; retirar tras la validación).

### 18 a 20 Usuarios, invitación y bitácora (sin PNG de diseño)
- Sin diseño. Tabla de usuarios, cuadro «Invitación creada» (código visible una sola vez) y bitácora con filtros. Estilo coherente con el resto.

## Falta por falta de diseño

MFA y enrolamiento con QR, registro, recuperación de contraseña, carga masiva, organizaciones y plantas, verificación pública, plantillas de mensaje, chat, usuarios, invitación y bitácora no tienen PNG. Con la SPA actual el equipo de diseño puede partir de las capturas `02`, `07`, `08`, `12`, `14`, `17` a `20`.

## Diferencias claras, candidatas a corregir (no se corrigieron)

1. Enlaces con aspecto de botón subrayados en toda la SPA.
2. Desbordamiento horizontal de 12 px en el listado de colaboradores a 1440 px.
3. Tabla de destinatarios del detalle de envío fuera de la tarjeta.
4. Acciones del formulario de colaborador abajo y no arriba.
5. Historial: columna «Acción» vacía en PENDIENTE y folio en dos líneas.
6. Vista previa del mensaje con variables sin resolver y botón «Enviar a N colaboradores» que se parte.
7. Casillas y radios nativos (no naranjas) y casilla gris sólida en «Celular con WhatsApp».
8. Logotipo e imagen de fondo del acceso (requieren activos de marca).
9. Banner «Pantalla pendiente de validación visual con Samuel.» en el chat.
