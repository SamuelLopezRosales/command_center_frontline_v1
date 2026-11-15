// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/bitacora": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Consulta de la bitácora (DSH-05) */
        get: operations["consultar_api_v1_bitacora_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/constancias/historial": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Historial de constancias (DSH-11) */
        get: operations["historial_api_v1_constancias_historial_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dashboard/alertas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Alertas (DSH-04) */
        get: operations["alertas_api_v1_dashboard_alertas_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dashboard/constancias-recientes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Constancias recientes (DSH-03) */
        get: operations["constancias_recientes_api_v1_dashboard_constancias_recientes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dashboard/resumen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Indicadores (DSH-01) */
        get: operations["resumen_api_v1_dashboard_resumen_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/dashboard/solicitudes-recientes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Solicitudes recientes (DSH-02) */
        get: operations["solicitudes_recientes_api_v1_dashboard_solicitudes_recientes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/sesion/iniciar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Registra el inicio de sesión (DSH-06) */
        post: operations["iniciar_api_v1_sesion_iniciar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usuarios": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Usuarios de la empresa (DSH-08) */
        get: operations["listar_api_v1_usuarios_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usuarios/invitaciones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Crea una invitación de registro; el código se muestra una sola vez (DSH-10) */
        post: operations["invitar_api_v1_usuarios_invitaciones_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usuarios/yo": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Usuario actual (DSH-07) */
        get: operations["yo_api_v1_usuarios_yo_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/usuarios/{usuario_id}/desactivar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Desactiva un usuario y cierra sus sesiones (DSH-09) */
        post: operations["desactivar_api_v1_usuarios__usuario_id__desactivar_post"];
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
        /** Alerta */
        Alerta: {
            /** Detalle */
            detalle: string;
            /** Enlace */
            enlace: string;
            /**
             * Tipo
             * @enum {string}
             */
            tipo: "SIN_CONSENTIMIENTO" | "CONSTANCIA_FALLIDA" | "CONSTANCIA_PENDIENTE" | "CAMPO_VACIO_EN_PLANTILLA";
            /** Titulo */
            titulo: string;
            /** Total */
            total: number;
        };
        /** BitacoraSalida */
        BitacoraSalida: {
            /** Items */
            items: components["schemas"]["RegistroBitacora"][];
            /** Siguiente */
            siguiente: string | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HistorialSalida */
        HistorialSalida: {
            /** Items */
            items: components["schemas"]["ItemHistorial"][];
            /** Siguiente */
            siguiente: string | null;
        };
        /** InvitacionEntrada */
        InvitacionEntrada: {
            /** Correo Destino */
            correo_destino?: string | null;
        };
        /** InvitacionSalida */
        InvitacionSalida: {
            /** Codigo */
            codigo: string;
            /**
             * Fecha Expira
             * Format: date-time
             */
            fecha_expira: string;
            /** Id */
            id: number;
        };
        /** ItemConstancia */
        ItemConstancia: {
            /** Colaborador Nombre */
            colaborador_nombre: string;
            /** Estado Entrega */
            estado_entrega: string;
            /**
             * Fecha
             * Format: date-time
             */
            fecha: string;
            /** Folio */
            folio: string;
            /** Id */
            id: number;
            /** Plantilla Nombre */
            plantilla_nombre: string;
            /** Version */
            version: number;
        };
        /** ItemHistorial */
        ItemHistorial: {
            /** Canal */
            canal: string;
            /** Colaborador Nombre */
            colaborador_nombre: string;
            /** Estado Entrega */
            estado_entrega: string;
            /**
             * Fecha
             * Format: date-time
             */
            fecha: string;
            /** Folio */
            folio: string;
            /** Id */
            id: number;
            /** Plantilla Nombre */
            plantilla_nombre: string;
            /** Version */
            version: number;
        };
        /** ItemSolicitud */
        ItemSolicitud: {
            /** Colaborador Nombre */
            colaborador_nombre: string;
            /** Estado */
            estado: string;
            /** Id */
            id: number;
            /** Plantilla Nombre */
            plantilla_nombre: string | null;
            /** Version */
            version: number | null;
        };
        /** RegistroBitacora */
        RegistroBitacora: {
            /** Accion */
            accion: string;
            /** Colaborador Id */
            colaborador_id: number | null;
            /** Detalle */
            detalle: {
                [key: string]: unknown;
            };
            /** Entidad */
            entidad: string;
            /** Entidad Id */
            entidad_id: number | null;
            /**
             * Fecha Hora
             * Format: date-time
             */
            fecha_hora: string;
            /** Id */
            id: number;
            /** Ip */
            ip: string | null;
            /** Origen */
            origen: string;
            /** Usuario Id */
            usuario_id: number | null;
            /** Usuario Nombre */
            usuario_nombre: string | null;
        };
        /** ResumenDashboard */
        ResumenDashboard: {
            /** Colaboradores Activos */
            colaboradores_activos: number;
            /** Constancias Mes */
            constancias_mes: number;
            /** Plantillas Activas */
            plantillas_activas: number;
            /** Solicitudes En Proceso */
            solicitudes_en_proceso: number;
            /** Vacio */
            vacio: boolean;
        };
        /** UsuarioItem */
        UsuarioItem: {
            /** Activo */
            activo: boolean;
            /** Correo */
            correo: string;
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
            /** Rol */
            rol: string;
            /** Ultima Actividad */
            ultima_actividad: string | null;
        };
        /** UsuarioYo */
        UsuarioYo: {
            /** Correo */
            correo: string;
            /** Empresa Id */
            empresa_id: number;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
            /** Permisos */
            permisos: string[];
            /** Rol */
            rol: string;
        };
        /** UsuariosSalida */
        UsuariosSalida: {
            /** Items */
            items: components["schemas"]["UsuarioItem"][];
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
    consultar_api_v1_bitacora_get: {
        parameters: {
            query?: {
                desde?: string | null;
                hasta?: string | null;
                usuario_id?: number | null;
                colaborador_id?: number | null;
                accion?: string | null;
                orden?: "asc" | "desc";
                cursor?: string | null;
                limite?: number;
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
                    "application/json": components["schemas"]["BitacoraSalida"];
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
    historial_api_v1_constancias_historial_get: {
        parameters: {
            query?: {
                desde?: string | null;
                hasta?: string | null;
                plantilla_id?: number | null;
                colaborador_id?: number | null;
                estado?: ("PENDIENTE" | "ENTREGADA" | "FALLIDA") | null;
                q?: string | null;
                cursor?: string | null;
                limite?: number;
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
                    "application/json": components["schemas"]["HistorialSalida"];
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
    alertas_api_v1_dashboard_alertas_get: {
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
                    "application/json": components["schemas"]["Alerta"][];
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
    constancias_recientes_api_v1_dashboard_constancias_recientes_get: {
        parameters: {
            query?: {
                limite?: number;
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
                    "application/json": components["schemas"]["ItemConstancia"][];
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
    resumen_api_v1_dashboard_resumen_get: {
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
                    "application/json": components["schemas"]["ResumenDashboard"];
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
    solicitudes_recientes_api_v1_dashboard_solicitudes_recientes_get: {
        parameters: {
            query?: {
                limite?: number;
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
                    "application/json": components["schemas"]["ItemSolicitud"][];
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
    iniciar_api_v1_sesion_iniciar_post: {
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
    listar_api_v1_usuarios_get: {
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
                    "application/json": components["schemas"]["UsuariosSalida"];
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
    invitar_api_v1_usuarios_invitaciones_post: {
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
                "application/json": components["schemas"]["InvitacionEntrada"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InvitacionSalida"];
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
    yo_api_v1_usuarios_yo_get: {
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
                    "application/json": components["schemas"]["UsuarioYo"];
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
    desactivar_api_v1_usuarios__usuario_id__desactivar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                usuario_id: number;
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
}
