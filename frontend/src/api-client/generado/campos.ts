// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/campos": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado de campos (CAM-01) */
        get: operations["listar_api_v1_campos_get"];
        put?: never;
        /** Alta (CAM-02) */
        post: operations["crear_api_v1_campos_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campos/orden": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Reordenamiento (CAM-06) */
        put: operations["ordenar_api_v1_campos_orden_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campos/{campo_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (CAM-03) */
        get: operations["detalle_api_v1_campos__campo_id__get"];
        put?: never;
        post?: never;
        /** Eliminación lógica (CAM-05) */
        delete: operations["eliminar_api_v1_campos__campo_id__delete"];
        options?: never;
        head?: never;
        /** Edición (CAM-04) */
        patch: operations["actualizar_api_v1_campos__campo_id__patch"];
        trace?: never;
    };
    "/api/v1/campos/{campo_id}/opciones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Opciones (CAM-07) */
        get: operations["listar_api_v1_campos__campo_id__opciones_get"];
        put?: never;
        /** Alta de opción (CAM-08) */
        post: operations["crear_api_v1_campos__campo_id__opciones_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/campos/{campo_id}/opciones/{opcion_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Edición o desactivación de una opción (CAM-09) */
        patch: operations["actualizar_api_v1_campos__campo_id__opciones__opcion_id__patch"];
        trace?: never;
    };
    "/internal/campos": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Definiciones de campos con sus opciones (INT-CAM-01)
         * @description Por defecto solo los campos activos. Con ``incluir_inactivos`` también los desactivados
         *     no eliminados, que conservan sus valores y siguen resolviendo variables ya publicadas.
         */
        get: operations["definiciones_internal_campos_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/empresas/{empresa_id}/campos-sugeridos": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Siembra el catálogo de campos sugeridos (INT-CAM-02)
         * @description Idempotente: lo ya existente no se duplica. La empresa de la ruta debe ser la del
         *     encabezado ``X-Empresa-Id`` (la que fija RLS).
         */
        post: operations["sembrar_internal_empresas__empresa_id__campos_sugeridos_post"];
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
        /**
         * CampoActualizar
         * @description Parcial. El código interno no está: no cambia nunca (CC-REQ-046).
         */
        CampoActualizar: {
            /** Activo */
            activo?: boolean | null;
            /** Clave */
            clave?: string | null;
            /**
             * Confirmar
             * @default false
             */
            confirmar: boolean;
            /** Es Sensible */
            es_sensible?: boolean | null;
            /** Formato Validacion */
            formato_validacion?: string | null;
            /** Nombre Campo */
            nombre_campo?: string | null;
            /** Obligatorio */
            obligatorio?: boolean | null;
            /** Tipo Dato */
            tipo_dato?: ("TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO") | null;
        };
        /** CampoCrear */
        CampoCrear: {
            /** Clave */
            clave: string;
            /**
             * Es Sensible
             * @default false
             */
            es_sensible: boolean;
            /** Formato Validacion */
            formato_validacion?: string | null;
            /** Nombre Campo */
            nombre_campo: string;
            /**
             * Obligatorio
             * @default false
             */
            obligatorio: boolean;
            /** Orden */
            orden?: number | null;
            /**
             * Tipo Dato
             * @enum {string}
             */
            tipo_dato: "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
        };
        /** CampoDto */
        CampoDto: {
            /** Activo */
            activo: boolean;
            /** Clave */
            clave: string;
            /** Codigo Interno */
            codigo_interno: string;
            /** Es Sensible */
            es_sensible: boolean;
            /** Es Sugerido */
            es_sugerido: boolean;
            /** Formato Validacion */
            formato_validacion: string | null;
            /** Id */
            id: number;
            /** Nombre Campo */
            nombre_campo: string;
            /** Obligatorio */
            obligatorio: boolean;
            /** Opciones */
            opciones?: components["schemas"]["OpcionDto"][] | null;
            /** Orden */
            orden: number;
            /**
             * Tipo Dato
             * @enum {string}
             */
            tipo_dato: "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
            /** Usada En Plantillas */
            usada_en_plantillas?: number | null;
        };
        /** CampoFijoDto */
        CampoFijoDto: {
            /** Clave */
            clave: string;
            /** Nombre */
            nombre: string;
            /** Obligatorio */
            obligatorio: boolean;
            /**
             * Tipo Dato
             * @enum {string}
             */
            tipo_dato: "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
        };
        /** Definicion */
        Definicion: {
            /** Activo */
            activo: boolean;
            /** Clave */
            clave: string;
            /** Codigo Interno */
            codigo_interno: string;
            /** Es Sensible */
            es_sensible: boolean;
            /** Es Sugerido */
            es_sugerido: boolean;
            /** Formato Validacion */
            formato_validacion: string | null;
            /** Id */
            id: number;
            /** Nombre Campo */
            nombre_campo: string;
            /** Obligatorio */
            obligatorio: boolean;
            /**
             * Opciones
             * @default []
             */
            opciones: components["schemas"]["OpcionDto"][];
            /** Orden */
            orden: number;
            /**
             * Tipo Dato
             * @enum {string}
             */
            tipo_dato: "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
            /** Usada En Plantillas */
            usada_en_plantillas?: number | null;
        };
        /** Definiciones */
        Definiciones: {
            /** Campos */
            campos: components["schemas"]["Definicion"][];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** ListadoCampos */
        ListadoCampos: {
            /** Dinamicos */
            dinamicos: components["schemas"]["CampoDto"][];
            /** Fijos */
            fijos: components["schemas"]["CampoFijoDto"][];
        };
        /**
         * OpcionActualizar
         * @description El ``valor`` no está: no cambia (enviarlo da 422 ``CAMPO_NO_PERMITIDO``).
         */
        OpcionActualizar: {
            /** Activo */
            activo?: boolean | null;
            /** Descripcion */
            descripcion?: string | null;
            /** Etiqueta */
            etiqueta?: string | null;
            /** Orden */
            orden?: number | null;
        };
        /** OpcionCrear */
        OpcionCrear: {
            /** Descripcion */
            descripcion?: string | null;
            /** Etiqueta */
            etiqueta: string;
            /** Orden */
            orden?: number | null;
            /** Valor */
            valor: string;
        };
        /** OpcionDto */
        OpcionDto: {
            /** Activo */
            activo: boolean;
            /** Descripcion */
            descripcion: string | null;
            /** Etiqueta */
            etiqueta: string;
            /** Id */
            id: number;
            /** Orden */
            orden: number;
            /** Valor */
            valor: string;
        };
        /** OpcionesSalida */
        OpcionesSalida: {
            /** Items */
            items: components["schemas"]["OpcionDto"][];
        };
        /** OrdenItem */
        OrdenItem: {
            /** Id */
            id: number;
            /** Orden */
            orden: number;
        };
        /** Sembrado */
        Sembrado: {
            /** Creados */
            creados: number;
            /** Existentes */
            existentes: number;
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
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    listar_api_v1_campos_get: {
        parameters: {
            query?: {
                estado?: "todos" | "activos" | "inactivos";
                tipo?: "todos" | "sugeridos" | "personalizados";
            };
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
                    "application/json": components["schemas"]["ListadoCampos"];
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
    crear_api_v1_campos_post: {
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
                "application/json": components["schemas"]["CampoCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CampoDto"];
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
    ordenar_api_v1_campos_orden_put: {
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
                "application/json": components["schemas"]["OrdenItem"][];
            };
        };
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
    detalle_api_v1_campos__campo_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
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
                    "application/json": components["schemas"]["CampoDto"];
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
    eliminar_api_v1_campos__campo_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
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
    actualizar_api_v1_campos__campo_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CampoActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CampoDto"];
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
    listar_api_v1_campos__campo_id__opciones_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
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
                    "application/json": components["schemas"]["OpcionesSalida"];
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
    crear_api_v1_campos__campo_id__opciones_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OpcionCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OpcionDto"];
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
    actualizar_api_v1_campos__campo_id__opciones__opcion_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                campo_id: number;
                opcion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OpcionActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OpcionDto"];
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
    definiciones_internal_campos_get: {
        parameters: {
            query?: {
                incluir_inactivos?: boolean;
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
                    "application/json": components["schemas"]["Definiciones"];
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
    sembrar_internal_empresas__empresa_id__campos_sugeridos_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                empresa_id: number;
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
                    "application/json": components["schemas"]["Sembrado"];
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
