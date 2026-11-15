// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/constancias/variables": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Variables disponibles para las plantillas (CON-15) */
        get: operations["listar_api_v1_constancias_variables_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/constancias/{constancia_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle de una constancia emitida (CON-16) */
        get: operations["detalle_api_v1_constancias__constancia_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/constancias/{constancia_id}/descarga": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** URL firmada de 24 horas para RH (CON-17) */
        post: operations["descarga_api_v1_constancias__constancia_id__descarga_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/constancias/{constancia_id}/reenviar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reenvía una constancia cuya entrega falló (CON-18) */
        post: operations["reenviar_api_v1_constancias__constancia_id__reenviar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado (CON-01) */
        get: operations["listar_api_v1_plantillas_get"];
        put?: never;
        /** Alta (CON-02) */
        post: operations["crear_api_v1_plantillas_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (CON-03) */
        get: operations["detalle_api_v1_plantillas__plantilla_id__get"];
        put?: never;
        post?: never;
        /** Eliminación lógica (CON-06) */
        delete: operations["eliminar_api_v1_plantillas__plantilla_id__delete"];
        options?: never;
        head?: never;
        /** Edición (CON-04) */
        patch: operations["actualizar_api_v1_plantillas__plantilla_id__patch"];
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/borrador": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Borrador (CON-07) */
        get: operations["obtener_api_v1_plantillas__plantilla_id__borrador_get"];
        /** Guarda el borrador (CON-08) */
        put: operations["guardar_api_v1_plantillas__plantilla_id__borrador_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/borrador/validar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Valida el borrador (CON-09) */
        post: operations["validar_api_v1_plantillas__plantilla_id__borrador_validar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/duplicar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Duplicado (CON-05) */
        post: operations["duplicar_api_v1_plantillas__plantilla_id__duplicar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/publicar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publica el borrador como una versión nueva (CON-10) */
        post: operations["publicar_api_v1_plantillas__plantilla_id__publicar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/versiones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Versiones publicadas (CON-11) */
        get: operations["listar_api_v1_plantillas__plantilla_id__versiones_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/versiones/{numero}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Una versión con su contenido (CON-12) */
        get: operations["detalle_api_v1_plantillas__plantilla_id__versiones__numero__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/versiones/{numero}/restaurar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restaura una versión como una versión nueva (CON-13) */
        post: operations["restaurar_api_v1_plantillas__plantilla_id__versiones__numero__restaurar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas/{plantilla_id}/vista-previa": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Vista previa con los datos de un colaborador (CON-14) */
        post: operations["vista_previa_api_v1_plantillas__plantilla_id__vista_previa_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/publico/verificar/{codigo}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Verifica una constancia por el código del QR (CON-19) */
        get: operations["verificar_api_v1_publico_verificar__codigo__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/d/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Página de descarga; no consume el enlace (CON-20) */
        get: operations["pagina_d__token__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/d/{token}/descargar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Consume el enlace y redirige al PDF firmado (CON-21) */
        post: operations["descargar_d__token__descargar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/plantillas/activas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Plantillas activas con versión publicada (INT-CON-01) */
        get: operations["disponibles_internal_plantillas_activas_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/plantillas/uso-de-variable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Plantillas que usan cada variable (INT-CON-06) */
        get: operations["uso_de_variable_internal_plantillas_uso_de_variable_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/solicitudes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Crea una solicitud de constancia (INT-CON-02) */
        post: operations["crear_internal_solicitudes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/solicitudes/{solicitud_id}/cancelar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancela una solicitud recibida (INT-CON-05) */
        post: operations["cancelar_internal_solicitudes__solicitud_id__cancelar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/solicitudes/{solicitud_id}/generar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Valida los datos y encola el PDF (INT-CON-04) */
        post: operations["generar_internal_solicitudes__solicitud_id__generar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/solicitudes/{solicitud_id}/plantilla": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fija la plantilla elegida (INT-CON-03) */
        post: operations["elegir_internal_solicitudes__solicitud_id__plantilla_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** BloqueLogotipo */
        BloqueLogotipo: {
            /**
             * Alineacion
             * @default izquierda
             * @enum {string}
             */
            alineacion: "izquierda" | "centro" | "derecha" | "justificado";
            /**
             * Ancho Cm
             * @default 5
             */
            ancho_cm: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            tipo: "logotipo";
        };
        /** BloqueParrafo */
        BloqueParrafo: {
            /**
             * Alineacion
             * @default izquierda
             * @enum {string}
             */
            alineacion: "izquierda" | "centro" | "derecha" | "justificado";
            /** Contenido */
            contenido?: (components["schemas"]["NodoTexto"] | components["schemas"]["NodoVariable"] | components["schemas"]["NodoSalto"])[];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            tipo: "parrafo";
        };
        /** BorradorGuardado */
        BorradorGuardado: {
            /**
             * Fecha Modificacion
             * Format: date-time
             */
            fecha_modificacion: string;
            /** Hash */
            hash: string;
        };
        /** BorradorLeido */
        BorradorLeido: {
            contenido: components["schemas"]["ContenidoPlantilla"];
            /**
             * Fecha Modificacion
             * Format: date-time
             */
            fecha_modificacion: string;
            /** Hash */
            hash: string;
        };
        /** ConstanciaDetalle */
        ConstanciaDetalle: {
            /** Colaborador Id */
            colaborador_id: number;
            /** Colaborador Nombre */
            colaborador_nombre: string;
            /** Estado Entrega */
            estado_entrega: string;
            /** Estado Vigencia */
            estado_vigencia: string;
            /** Fecha Entrega */
            fecha_entrega?: string | null;
            /**
             * Fecha Generacion
             * Format: date-time
             */
            fecha_generacion: string;
            /** Folio */
            folio: string;
            /** Id */
            id: number;
            /** Numero Empleado */
            numero_empleado: string;
            /** Plantilla Id */
            plantilla_id: number;
            /** Plantilla Nombre */
            plantilla_nombre: string;
            /** Solicitud Id */
            solicitud_id: number;
            /** Version */
            version: number;
        };
        /** ContenidoPlantilla */
        ContenidoPlantilla: {
            /** Bloques */
            bloques?: (components["schemas"]["BloqueLogotipo"] | components["schemas"]["BloqueParrafo"])[];
            /**
             * Esquema
             * @constant
             */
            esquema: 1;
            pagina?: components["schemas"]["Pagina"];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** Hallazgo */
        Hallazgo: {
            /** Codigo */
            codigo: string;
            /** Mensaje */
            mensaje: string;
            /** Total */
            total?: number | null;
            /** Variables */
            variables: string[];
        };
        /** Margenes */
        Margenes: {
            /**
             * Der
             * @default 2.5
             */
            der: number;
            /**
             * Inf
             * @default 2.5
             */
            inf: number;
            /**
             * Izq
             * @default 2.5
             */
            izq: number;
            /**
             * Sup
             * @default 2.5
             */
            sup: number;
        };
        /** NodoSalto */
        NodoSalto: {
            /**
             * Salto
             * @constant
             */
            salto: true;
        };
        /** NodoTexto */
        NodoTexto: {
            /** Color */
            color?: string | null;
            /** Cursiva */
            cursiva?: boolean | null;
            /** Negrita */
            negrita?: boolean | null;
            /** Subrayado */
            subrayado?: boolean | null;
            /** Tamano Pt */
            tamano_pt?: number | null;
            /** Texto */
            texto: string;
        };
        /** NodoVariable */
        NodoVariable: {
            /** Color */
            color?: string | null;
            /** Cursiva */
            cursiva?: boolean | null;
            /** Negrita */
            negrita?: boolean | null;
            /** Subrayado */
            subrayado?: boolean | null;
            /** Tamano Pt */
            tamano_pt?: number | null;
            /** Var */
            var: string;
        };
        /** Pagina */
        Pagina: {
            margenes_cm?: components["schemas"]["Margenes"];
            /**
             * Tamano
             * @default CARTA
             * @enum {string}
             */
            tamano: "CARTA" | "A4";
        };
        /** PlantillaActualizar */
        PlantillaActualizar: {
            /** Activa */
            activa?: boolean | null;
            /** Descripcion */
            descripcion?: string | null;
            /** Nombre */
            nombre?: string | null;
        };
        /** PlantillaCrear */
        PlantillaCrear: {
            /** Descripcion */
            descripcion?: string | null;
            /** Nombre */
            nombre: string;
        };
        /** PlantillaDisponible */
        PlantillaDisponible: {
            /** Descripcion */
            descripcion?: string | null;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
            /** Version */
            version: number;
        };
        /** PlantillaElegida */
        PlantillaElegida: {
            /** Plantilla Id */
            plantilla_id: number;
        };
        /** PlantillasDisponibles */
        PlantillasDisponibles: {
            /** Plantillas */
            plantillas: components["schemas"]["PlantillaDisponible"][];
        };
        /** PlantillasSalida */
        PlantillasSalida: {
            /** Items */
            items: components["schemas"]["cc_constancias__api__plantillas__Plantilla"][];
        };
        /** PublicarEntrada */
        PublicarEntrada: {
            /**
             * Confirmar Sensibles
             * @default false
             */
            confirmar_sensibles: boolean;
        };
        /** ResultadoValidacion */
        ResultadoValidacion: {
            /** Advertencias */
            advertencias: components["schemas"]["Hallazgo"][];
            /** Errores */
            errores: components["schemas"]["Hallazgo"][];
        };
        /** SolicitudEntrada */
        SolicitudEntrada: {
            /** Colaborador Id */
            colaborador_id: number;
            /** Colaborador Nombre */
            colaborador_nombre: string;
            /** Conversacion Id */
            conversacion_id?: number | null;
        };
        /** SolicitudSalida */
        SolicitudSalida: {
            /** Estado */
            estado: string;
            /**
             * Fecha Solicitud
             * Format: date-time
             */
            fecha_solicitud: string;
            /** Id */
            id: number;
            /** Version Plantilla Id */
            version_plantilla_id?: number | null;
        };
        /** UrlDescarga */
        UrlDescarga: {
            /**
             * Expira
             * Format: date-time
             */
            expira: string;
            /** Url */
            url: string;
        };
        /** Usos */
        Usos: {
            /** Usos */
            usos: {
                [key: string]: components["schemas"]["cc_constancias__api__internas__Usos__Plantilla"][];
            };
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** VariableDto */
        VariableDto: {
            /** Etiqueta */
            etiqueta: string;
            /**
             * Grupo
             * @enum {string}
             */
            grupo: "COLABORADOR" | "ORGANIZACION" | "SENSIBLES" | "SISTEMA";
            /** Nombre */
            nombre: string;
            /** Sensible */
            sensible: boolean;
        };
        /** VariablesSalida */
        VariablesSalida: {
            /** Items */
            items: components["schemas"]["VariableDto"][];
        };
        /** Verificacion */
        Verificacion: {
            /** Estado */
            estado: string;
            /**
             * Fecha Emision
             * Format: date-time
             */
            fecha_emision: string;
            /** Folio */
            folio: string;
            /** Nombre */
            nombre: string;
        };
        /** Version */
        Version: {
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Hash */
            hash: string;
            /** Numero */
            numero: number;
            /** Vigente */
            vigente: boolean;
        };
        /** VersionDetalle */
        VersionDetalle: {
            contenido: components["schemas"]["ContenidoPlantilla"];
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Hash */
            hash: string;
            /** Numero */
            numero: number;
            /** Vigente */
            vigente: boolean;
        };
        /** VersionesSalida */
        VersionesSalida: {
            /** Items */
            items: components["schemas"]["Version"][];
        };
        /**
         * VistaPreviaEntrada
         * @description Una de las dos fuentes: una ``version`` publicada o el borrador (``usar_borrador``).
         */
        VistaPreviaEntrada: {
            /** Colaborador Id */
            colaborador_id: number;
            /**
             * Usar Borrador
             * @default false
             */
            usar_borrador: boolean;
            /** Version */
            version?: number | null;
        };
        /** VistaPreviaSalida */
        VistaPreviaSalida: {
            /** Desconocidas */
            desconocidas: string[];
            /** Faltantes */
            faltantes: string[];
            /** Html */
            html: string;
        };
        /** Plantilla */
        cc_constancias__api__internas__Usos__Plantilla: {
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
        };
        /** Plantilla */
        cc_constancias__api__plantillas__Plantilla: {
            /** Activa */
            activa: boolean;
            /** Descripcion */
            descripcion: string | null;
            /** Emitidas */
            emitidas: number;
            /**
             * Estado
             * @enum {string}
             */
            estado: "ACTIVA" | "INACTIVA" | "BORRADOR";
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /**
             * Fecha Modificacion
             * Format: date-time
             */
            fecha_modificacion: string;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
            /** Tiene Borrador */
            tiene_borrador: boolean;
            /** Version */
            version: number | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    listar_api_v1_constancias_variables_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VariablesSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detalle_api_v1_constancias__constancia_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                constancia_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConstanciaDetalle"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    descarga_api_v1_constancias__constancia_id__descarga_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                constancia_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UrlDescarga"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reenviar_api_v1_constancias__constancia_id__reenviar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                constancia_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_api_v1_plantillas_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlantillasSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    crear_api_v1_plantillas_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlantillaCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["cc_constancias__api__plantillas__Plantilla"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detalle_api_v1_plantillas__plantilla_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["cc_constancias__api__plantillas__Plantilla"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    eliminar_api_v1_plantillas__plantilla_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    actualizar_api_v1_plantillas__plantilla_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlantillaActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["cc_constancias__api__plantillas__Plantilla"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    obtener_api_v1_plantillas__plantilla_id__borrador_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BorradorLeido"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    guardar_api_v1_plantillas__plantilla_id__borrador_put: {
        parameters: {
            query?: never;
            header?: {
                "if-match"?: string | null;
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContenidoPlantilla"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BorradorGuardado"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validar_api_v1_plantillas__plantilla_id__borrador_validar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResultadoValidacion"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    duplicar_api_v1_plantillas__plantilla_id__duplicar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["cc_constancias__api__plantillas__Plantilla"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publicar_api_v1_plantillas__plantilla_id__publicar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["PublicarEntrada"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Version"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_api_v1_plantillas__plantilla_id__versiones_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionesSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detalle_api_v1_plantillas__plantilla_id__versiones__numero__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
                numero: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionDetalle"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restaurar_api_v1_plantillas__plantilla_id__versiones__numero__restaurar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
                numero: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Version"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    vista_previa_api_v1_plantillas__plantilla_id__vista_previa_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                plantilla_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VistaPreviaEntrada"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VistaPreviaSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verificar_api_v1_publico_verificar__codigo__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                codigo: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Verificacion"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pagina_d__token__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/html": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    descargar_d__token__descargar_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            302: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disponibles_internal_plantillas_activas_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlantillasDisponibles"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    uso_de_variable_internal_plantillas_uso_de_variable_get: {
        parameters: {
            query: {
                variable: string[];
            };
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Usos"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    crear_internal_solicitudes_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SolicitudEntrada"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SolicitudSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancelar_internal_solicitudes__solicitud_id__cancelar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                solicitud_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SolicitudSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generar_internal_solicitudes__solicitud_id__generar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                solicitud_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    elegir_internal_solicitudes__solicitud_id__plantilla_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                solicitud_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlantillaElegida"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SolicitudSalida"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
