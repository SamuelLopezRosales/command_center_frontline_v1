// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/audiencias": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado de audiencias (NOT-01) */
        get: operations["listar_api_v1_audiencias_get"];
        put?: never;
        /** Alta (NOT-02) */
        post: operations["crear_api_v1_audiencias_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audiencias/previsualizar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Conteo de la audiencia sin guardarla (NOT-06) */
        post: operations["previsualizar_api_v1_audiencias_previsualizar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audiencias/{audiencia_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (NOT-03) */
        get: operations["detalle_api_v1_audiencias__audiencia_id__get"];
        put?: never;
        post?: never;
        /** Desactivación (NOT-05) */
        delete: operations["desactivar_api_v1_audiencias__audiencia_id__delete"];
        options?: never;
        head?: never;
        /** Edición (NOT-04) */
        patch: operations["actualizar_api_v1_audiencias__audiencia_id__patch"];
        trace?: never;
    };
    "/api/v1/notificaciones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado por pestañas (NOT-14) */
        get: operations["listar_api_v1_notificaciones_get"];
        put?: never;
        /** Alta (NOT-15) */
        post: operations["crear_api_v1_notificaciones_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/indicadores": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Indicadores del mes (NOT-24) */
        get: operations["indicadores_api_v1_notificaciones_indicadores_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (NOT-16) */
        get: operations["detalle_api_v1_notificaciones__notificacion_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Edición (NOT-17) */
        patch: operations["actualizar_api_v1_notificaciones__notificacion_id__patch"];
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/cancelar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancelar un borrador o una programada (NOT-20) */
        post: operations["cancelar_api_v1_notificaciones__notificacion_id__cancelar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/confirmar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirmar: enviar ahora o programar (NOT-19) */
        post: operations["confirmar_api_v1_notificaciones__notificacion_id__confirmar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/destinatarios": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Destinatarios con celular enmascarado (NOT-21) */
        get: operations["destinatarios_api_v1_notificaciones__notificacion_id__destinatarios_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/duplicar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Duplicar como borrador (NOT-23) */
        post: operations["duplicar_api_v1_notificaciones__notificacion_id__duplicar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/reintentar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reintentar los destinatarios fallidos (NOT-22) */
        post: operations["reintentar_api_v1_notificaciones__notificacion_id__reintentar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/notificaciones/{notificacion_id}/revisar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revisión de la audiencia y embudo (NOT-18) */
        post: operations["revisar_api_v1_notificaciones__notificacion_id__revisar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas-mensaje": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado de plantillas (NOT-07) */
        get: operations["listar_api_v1_plantillas_mensaje_get"];
        put?: never;
        /** Alta (NOT-08) */
        post: operations["crear_api_v1_plantillas_mensaje_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas-mensaje/{plantilla_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (NOT-09) */
        get: operations["detalle_api_v1_plantillas_mensaje__plantilla_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Edición (NOT-10) */
        patch: operations["actualizar_api_v1_plantillas_mensaje__plantilla_id__patch"];
        trace?: never;
    };
    "/api/v1/plantillas-mensaje/{plantilla_id}/duplicar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Duplicar como borrador (NOT-12) */
        post: operations["duplicar_api_v1_plantillas_mensaje__plantilla_id__duplicar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas-mensaje/{plantilla_id}/enviar-revision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Envío a revisión de Meta (NOT-11) */
        post: operations["enviar_revision_api_v1_plantillas_mensaje__plantilla_id__enviar_revision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantillas-mensaje/{plantilla_id}/sincronizar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Sincronizar el estado con Meta (NOT-13) */
        post: operations["sincronizar_api_v1_plantillas_mensaje__plantilla_id__sincronizar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/plantillas-mensaje/{plantilla_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * INT-NOT-01
         * @description La plantilla de mensaje de la empresa: el chat de RH (WAP-04) la usa para exigir que esté
         *     APROBADA y para armar el texto. Solo lectura; sin datos personales.
         */
        get: operations["plantilla_internal_plantillas_mensaje__plantilla_id__get"];
        put?: never;
        post?: never;
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
        /** AudienciaActualizar */
        AudienciaActualizar: {
            /** Activa */
            activa?: boolean | null;
            /** Criterios */
            criterios?: {
                [key: string]: unknown;
            } | null;
            /** Nombre */
            nombre?: string | null;
        };
        /** AudienciaCrear */
        AudienciaCrear: {
            /** Criterios */
            criterios: {
                [key: string]: unknown;
            };
            /** Nombre */
            nombre: string;
        };
        /** AudienciaDto */
        AudienciaDto: {
            /** Activa */
            activa: boolean;
            /** Creada Por Usuario Id */
            creada_por_usuario_id: number;
            /** Criterios */
            criterios: {
                [key: string]: unknown;
            };
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
        };
        /** Cancelar */
        Cancelar: {
            /** Motivo */
            motivo?: string | null;
        };
        /** Confirmar */
        Confirmar: {
            /**
             * Confirmar Fuera Horario
             * @default false
             */
            confirmar_fuera_horario: boolean;
            /**
             * Modo Envio
             * @enum {string}
             */
            modo_envio: "AHORA" | "PROGRAMAR";
            /** Programada Para */
            programada_para?: string | null;
            /** Respaldo Correo */
            respaldo_correo?: boolean | null;
        };
        /** Contadores */
        Contadores: {
            /** Entregados */
            entregados: number;
            /** Enviados */
            enviados: number;
            /** Excluidos */
            excluidos: number;
            /** Fallidos */
            fallidos: number;
            /** Leidos */
            leidos: number;
            /** Respondieron */
            respondieron: number;
            /** Seleccionados */
            seleccionados: number;
            /** Validos */
            validos: number;
        };
        /** ConteoPestanas */
        ConteoPestanas: {
            /** Borradores */
            borradores: number;
            /** Envios */
            envios: number;
            /** Programadas */
            programadas: number;
        };
        /** DestinatarioDto */
        DestinatarioDto: {
            /** Canal Usado */
            canal_usado: string | null;
            /** Celular Enmascarado */
            celular_enmascarado: string | null;
            /** Colaborador Id */
            colaborador_id: number;
            /** Conversacion Id */
            conversacion_id: number | null;
            /**
             * Estado
             * @enum {string}
             */
            estado: "PENDIENTE" | "EXCLUIDO" | "ENVIADO" | "ENTREGADO" | "LEIDO" | "RESPONDIO" | "FALLIDO";
            /**
             * Fecha Estado
             * Format: date-time
             */
            fecha_estado: string;
            /** Id */
            id: number;
            /** Intentos */
            intentos: number;
            /** Motivo Exclusion */
            motivo_exclusion: string | null;
            /** Motivo Fallo */
            motivo_fallo: string | null;
            /** Nombre */
            nombre: string;
            /** Planta */
            planta: string | null;
        };
        /** EmbudoDto */
        EmbudoDto: {
            /** Activos */
            activos: number;
            /** Celular Valido */
            celular_valido: number;
            /** Con Consentimiento */
            con_consentimiento: number;
            /** Seleccionados */
            seleccionados: number;
        };
        /** ExcluidosPorMotivo */
        ExcluidosPorMotivo: {
            /** Estatus Baja */
            ESTATUS_BAJA: number;
            /** Sin Celular Valido */
            SIN_CELULAR_VALIDO: number;
            /** Sin Consentimiento */
            SIN_CONSENTIMIENTO: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HitoLineaTiempo */
        HitoLineaTiempo: {
            /**
             * En
             * Format: date-time
             */
            en: string;
            /**
             * Evento
             * @enum {string}
             */
            evento: "CREADA" | "REVISADA" | "CONFIRMADA" | "PROGRAMADA_PARA" | "ENVIADA";
        };
        /** Indicadores */
        Indicadores: {
            conteos: components["schemas"]["ConteoPestanas"];
            /** Entregadas */
            entregadas: number;
            /** Enviadas */
            enviadas: number;
            /** Fallidas */
            fallidas: number;
            /** Leidas */
            leidas: number;
            /** Mes */
            mes: string;
            /** Porcentaje Entregadas */
            porcentaje_entregadas: number;
            /** Porcentaje Leidas */
            porcentaje_leidas: number;
        };
        /** NotificacionActualizar */
        NotificacionActualizar: {
            /** Audiencia Id */
            audiencia_id?: number | null;
            /** Colaborador Id */
            colaborador_id?: number | null;
            /** Criterios */
            criterios?: {
                [key: string]: unknown;
            } | null;
            /** Modo */
            modo?: ("CRITERIOS" | "INDIVIDUAL" | "GRUPO") | null;
            /** Plantilla Mensaje Id */
            plantilla_mensaje_id?: number | null;
            /** Respaldo Correo */
            respaldo_correo?: boolean | null;
            /** Titulo */
            titulo?: string | null;
            /** Variables */
            variables?: {
                [key: string]: components["schemas"]["VariableAsignada"];
            } | null;
            /** Zona Horaria */
            zona_horaria?: string | null;
        };
        /** NotificacionCrear */
        NotificacionCrear: {
            /** Audiencia Id */
            audiencia_id?: number | null;
            /** Colaborador Id */
            colaborador_id?: number | null;
            /** Criterios */
            criterios?: {
                [key: string]: unknown;
            } | null;
            /**
             * Modo
             * @enum {string}
             */
            modo: "CRITERIOS" | "INDIVIDUAL" | "GRUPO";
            /** Plantilla Mensaje Id */
            plantilla_mensaje_id: number;
            /**
             * Respaldo Correo
             * @default false
             */
            respaldo_correo: boolean;
            /** Titulo */
            titulo: string;
            /**
             * Variables
             * @default {}
             */
            variables: {
                [key: string]: components["schemas"]["VariableAsignada"];
            };
            /** Zona Horaria */
            zona_horaria?: string | null;
        };
        /** NotificacionDto */
        NotificacionDto: {
            /** Audiencia Id */
            audiencia_id: number | null;
            /** Audiencia Nombre */
            audiencia_nombre: string | null;
            /**
             * Canal
             * @default PLANTILLA_META
             * @constant
             */
            canal: "PLANTILLA_META";
            /** Colaborador Id */
            colaborador_id: number | null;
            /** Confirmada En */
            confirmada_en: string | null;
            /** Confirmada Fuera Horario */
            confirmada_fuera_horario: boolean;
            /** Confirmada Por Usuario Id */
            confirmada_por_usuario_id: number | null;
            contadores: components["schemas"]["Contadores"];
            /** Criterios */
            criterios: {
                [key: string]: unknown;
            } | null;
            /**
             * Estado
             * @enum {string}
             */
            estado: "BORRADOR" | "PROGRAMADA" | "ENVIANDO" | "COMPLETADA" | "CON_FALLAS" | "CANCELADA";
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Fecha Envio */
            fecha_envio: string | null;
            /** Id */
            id: number;
            /** Linea De Tiempo */
            linea_de_tiempo: components["schemas"]["HitoLineaTiempo"][];
            /**
             * Modo
             * @enum {string}
             */
            modo: "CRITERIOS" | "INDIVIDUAL" | "GRUPO";
            /** Modo Envio */
            modo_envio: ("AHORA" | "PROGRAMAR") | null;
            /** Motivo Cancelacion */
            motivo_cancelacion: string | null;
            plantilla: components["schemas"]["PlantillaResumen"] | null;
            /** Programada Para */
            programada_para: string | null;
            /** Respaldo Correo */
            respaldo_correo: boolean;
            /** Revisada En */
            revisada_en: string | null;
            /** Titulo */
            titulo: string;
            /** Usuario Id */
            usuario_id: number;
            /** Variables */
            variables: {
                [key: string]: unknown;
            };
            /** Vista Previa */
            vista_previa: string | null;
            /** Zona Horaria */
            zona_horaria: string;
        };
        /** PaginaAudiencias */
        PaginaAudiencias: {
            /** Items */
            items: components["schemas"]["AudienciaDto"][];
            /** Siguiente */
            siguiente?: string | null;
        };
        /** PaginaDestinatarios */
        PaginaDestinatarios: {
            /** Items */
            items: components["schemas"]["DestinatarioDto"][];
            /** Siguiente */
            siguiente?: string | null;
        };
        /** PaginaNotificaciones */
        PaginaNotificaciones: {
            conteos: components["schemas"]["ConteoPestanas"];
            /** Items */
            items: components["schemas"]["NotificacionDto"][];
            /** Siguiente */
            siguiente?: string | null;
        };
        /** PaginaPlantillas */
        PaginaPlantillas: {
            /** Items */
            items: components["schemas"]["PlantillaDto"][];
            /** Siguiente */
            siguiente?: string | null;
        };
        /** PlantillaActualizar */
        PlantillaActualizar: {
            /** Categoria */
            categoria?: ("UTILITY" | "MARKETING" | "AUTHENTICATION") | null;
            /** Ejemplos */
            ejemplos?: string[] | null;
            /** Idioma */
            idioma?: string | null;
            /** Nombre */
            nombre?: string | null;
            /** Texto Con Variables */
            texto_con_variables?: string | null;
        };
        /** PlantillaCrear */
        PlantillaCrear: {
            /**
             * Categoria
             * @enum {string}
             */
            categoria: "UTILITY" | "MARKETING" | "AUTHENTICATION";
            /**
             * Ejemplos
             * @default []
             */
            ejemplos: string[];
            /**
             * Idioma
             * @default es_MX
             */
            idioma: string;
            /** Nombre */
            nombre: string;
            /** Texto Con Variables */
            texto_con_variables: string;
        };
        /** PlantillaDto */
        PlantillaDto: {
            /** Cantidad Variables */
            cantidad_variables: number;
            /**
             * Categoria
             * @enum {string}
             */
            categoria: "UTILITY" | "MARKETING" | "AUTHENTICATION";
            /** Creada Por Usuario Id */
            creada_por_usuario_id: number;
            /** Ejemplos */
            ejemplos: string[];
            /**
             * Estado Meta
             * @enum {string}
             */
            estado_meta: "BORRADOR" | "EN_REVISION" | "APROBADA" | "RECHAZADA";
            /**
             * Fecha Creacion
             * Format: date-time
             */
            fecha_creacion: string;
            /** Id */
            id: number;
            /** Id Plantilla Meta */
            id_plantilla_meta: string | null;
            /** Idioma */
            idioma: string;
            /** Motivo Rechazo */
            motivo_rechazo: string | null;
            /** Nombre */
            nombre: string;
            /** Texto Con Variables */
            texto_con_variables: string;
        };
        /** PlantillaInterna */
        PlantillaInterna: {
            /** Estado Meta */
            estado_meta: string;
            /** Id */
            id: number;
            /** Idioma */
            idioma: string;
            /** Nombre */
            nombre: string;
            /** Texto Con Variables */
            texto_con_variables: string;
        };
        /** PlantillaResumen */
        PlantillaResumen: {
            /** Estado Meta */
            estado_meta: string;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
        };
        /** Previsualizar */
        Previsualizar: {
            /** Criterios */
            criterios: {
                [key: string]: unknown;
            };
        };
        /** Reintentar */
        Reintentar: {
            /**
             * Confirmar Fuera Horario
             * @default false
             */
            confirmar_fuera_horario: boolean;
        };
        /** Revision */
        Revision: {
            embudo: components["schemas"]["EmbudoDto"];
            excluidos_por_motivo: components["schemas"]["ExcluidosPorMotivo"];
            /**
             * Revisada En
             * Format: date-time
             */
            revisada_en: string;
            /** Total Excluidos */
            total_excluidos: number;
            /** Total Seleccionados */
            total_seleccionados: number;
        };
        /** Total */
        Total: {
            /** Total */
            total: number;
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
        /** VariableAsignada */
        VariableAsignada: {
            /** Campo */
            campo?: string | null;
            /**
             * Origen
             * @enum {string}
             */
            origen: "COLABORADOR" | "FIJO";
            /** Valor */
            valor?: string | null;
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
    listar_api_v1_audiencias_get: {
        parameters: {
            query?: {
                estado?: "activas" | "inactivas" | "todas";
                cursor?: string | null;
                limite?: number | null;
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
                    "application/json": components["schemas"]["PaginaAudiencias"];
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
    crear_api_v1_audiencias_post: {
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
                "application/json": components["schemas"]["AudienciaCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AudienciaDto"];
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
    previsualizar_api_v1_audiencias_previsualizar_post: {
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
                "application/json": components["schemas"]["Previsualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Total"];
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
    detalle_api_v1_audiencias__audiencia_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                audiencia_id: number;
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
                    "application/json": components["schemas"]["AudienciaDto"];
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
    desactivar_api_v1_audiencias__audiencia_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                audiencia_id: number;
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
    actualizar_api_v1_audiencias__audiencia_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                audiencia_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AudienciaActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AudienciaDto"];
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
    listar_api_v1_notificaciones_get: {
        parameters: {
            query?: {
                pestana?: "envios" | "programadas" | "borradores";
                estado?: ("BORRADOR" | "PROGRAMADA" | "ENVIANDO" | "COMPLETADA" | "CON_FALLAS" | "CANCELADA") | null;
                cursor?: string | null;
                limite?: number | null;
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
                    "application/json": components["schemas"]["PaginaNotificaciones"];
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
    crear_api_v1_notificaciones_post: {
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
                "application/json": components["schemas"]["NotificacionCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionDto"];
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
    indicadores_api_v1_notificaciones_indicadores_get: {
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
                    "application/json": components["schemas"]["Indicadores"];
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
    detalle_api_v1_notificaciones__notificacion_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
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
                    "application/json": components["schemas"]["NotificacionDto"];
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
    actualizar_api_v1_notificaciones__notificacion_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotificacionActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionDto"];
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
    cancelar_api_v1_notificaciones__notificacion_id__cancelar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["Cancelar"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionDto"];
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
    confirmar_api_v1_notificaciones__notificacion_id__confirmar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Confirmar"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionDto"];
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
    destinatarios_api_v1_notificaciones__notificacion_id__destinatarios_get: {
        parameters: {
            query?: {
                estado?: ("PENDIENTE" | "EXCLUIDO" | "ENVIADO" | "ENTREGADO" | "LEIDO" | "RESPONDIO" | "FALLIDO") | null;
                cursor?: string | null;
                limite?: number | null;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
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
                    "application/json": components["schemas"]["PaginaDestinatarios"];
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
    duplicar_api_v1_notificaciones__notificacion_id__duplicar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
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
                    "application/json": components["schemas"]["NotificacionDto"];
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
    reintentar_api_v1_notificaciones__notificacion_id__reintentar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["Reintentar"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionDto"];
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
    revisar_api_v1_notificaciones__notificacion_id__revisar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notificacion_id: number;
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
                    "application/json": components["schemas"]["Revision"];
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
    listar_api_v1_plantillas_mensaje_get: {
        parameters: {
            query?: {
                estado?: ("BORRADOR" | "EN_REVISION" | "APROBADA" | "RECHAZADA") | null;
                cursor?: string | null;
                limite?: number | null;
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
                    "application/json": components["schemas"]["PaginaPlantillas"];
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
    crear_api_v1_plantillas_mensaje_post: {
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
                    "application/json": components["schemas"]["PlantillaDto"];
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
    detalle_api_v1_plantillas_mensaje__plantilla_id__get: {
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
                    "application/json": components["schemas"]["PlantillaDto"];
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
    actualizar_api_v1_plantillas_mensaje__plantilla_id__patch: {
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
                    "application/json": components["schemas"]["PlantillaDto"];
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
    duplicar_api_v1_plantillas_mensaje__plantilla_id__duplicar_post: {
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
                    "application/json": components["schemas"]["PlantillaDto"];
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
    enviar_revision_api_v1_plantillas_mensaje__plantilla_id__enviar_revision_post: {
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
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlantillaDto"];
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
    sincronizar_api_v1_plantillas_mensaje__plantilla_id__sincronizar_post: {
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
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlantillaDto"];
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
    plantilla_internal_plantillas_mensaje__plantilla_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
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
                    "application/json": components["schemas"]["PlantillaInterna"];
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
