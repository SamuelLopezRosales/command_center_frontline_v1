// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/conversaciones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Conversaciones del chat (WAP-01) */
        get: operations["listar_api_v1_conversaciones_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversaciones/{conversacion_id}/asignacion": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Asigna la conversación a una persona de RH (WAP-05) */
        put: operations["asignar_api_v1_conversaciones__conversacion_id__asignacion_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversaciones/{conversacion_id}/mensajes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Mensajes de una conversación, del más reciente al más antiguo (WAP-02) */
        get: operations["listar_mensajes_api_v1_conversaciones__conversacion_id__mensajes_get"];
        put?: never;
        /** Envía texto libre con la ventana de 24 horas abierta (WAP-03) */
        post: operations["enviar_texto_api_v1_conversaciones__conversacion_id__mensajes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversaciones/{conversacion_id}/mensajes/plantilla": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Envía una plantilla aprobada, con la ventana abierta o cerrada (WAP-04) */
        post: operations["enviar_plantilla_api_v1_conversaciones__conversacion_id__mensajes_plantilla_post"];
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
        /** ConversacionItem */
        ConversacionItem: {
            /** Asignada A Usuario Id */
            asignada_a_usuario_id?: number | null;
            /** Colaborador Id */
            colaborador_id: number;
            /** Colaborador Nombre */
            colaborador_nombre?: string | null;
            /**
             * Estado
             * @enum {string}
             */
            estado: "VERIFICANDO" | "ACTIVA" | "BLOQUEADA" | "CERRADA";
            /** Fecha Asignacion */
            fecha_asignacion?: string | null;
            /**
             * Fecha Ultimo Mensaje
             * Format: date-time
             */
            fecha_ultimo_mensaje: string;
            /** Id */
            id: number;
            /**
             * Origen
             * @enum {string}
             */
            origen: "CONSTANCIA" | "NOTIFICACION";
            /** Ultima Notificacion Id */
            ultima_notificacion_id?: number | null;
            /** Ultimo Mensaje Entrante At */
            ultimo_mensaje_entrante_at?: string | null;
            /** Ventana Abierta */
            ventana_abierta: boolean;
            /** Verificada */
            verificada: boolean;
        };
        /** EntradaAsignacion */
        EntradaAsignacion: {
            /** Usuario Id */
            usuario_id: number;
        };
        /** EntradaPlantilla */
        EntradaPlantilla: {
            /** Plantilla Mensaje Id */
            plantilla_mensaje_id: number;
            /**
             * Variables
             * @description Variables numeradas, en orden.
             */
            variables?: string[];
            /**
             * Variables Nombradas
             * @description Valor por nombre de variable, si la plantilla usa variables con nombre.
             */
            variables_nombradas?: {
                [key: string]: string;
            } | null;
        };
        /** EntradaTexto */
        EntradaTexto: {
            /** Texto */
            texto: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** Mensaje */
        Mensaje: {
            /** Contenido */
            contenido?: string | null;
            /**
             * Direccion
             * @enum {string}
             */
            direccion: "ENTRANTE" | "SALIENTE";
            /** Enviado Por Usuario Id */
            enviado_por_usuario_id?: number | null;
            /** Error Codigo */
            error_codigo?: string | null;
            /** Estado */
            estado: string;
            /**
             * Fecha Hora
             * Format: date-time
             */
            fecha_hora: string;
            /** Id */
            id: number;
            /** Origen Tipo */
            origen_tipo: string;
            /** Plantilla */
            plantilla?: string | null;
            /**
             * Tipo
             * @enum {string}
             */
            tipo: "TEXTO" | "PLANTILLA" | "INTERACTIVO";
        };
        /** MensajeEncolado */
        MensajeEncolado: {
            /** Mensaje Id */
            mensaje_id: number;
        };
        /** PaginaConversaciones */
        PaginaConversaciones: {
            /** Items */
            items: components["schemas"]["ConversacionItem"][];
            /** Siguiente */
            siguiente?: string | null;
        };
        /** PaginaMensajes */
        PaginaMensajes: {
            /** Items */
            items: components["schemas"]["Mensaje"][];
            /** Siguiente */
            siguiente?: string | null;
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
    listar_api_v1_conversaciones_get: {
        parameters: {
            query?: {
                notificacion_id?: number | null;
                asignada_a?: number | null;
                estado?: ("VERIFICANDO" | "ACTIVA" | "BLOQUEADA" | "CERRADA") | null;
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
                    "application/json": components["schemas"]["PaginaConversaciones"];
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
    asignar_api_v1_conversaciones__conversacion_id__asignacion_put: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                conversacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EntradaAsignacion"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversacionItem"];
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
    listar_mensajes_api_v1_conversaciones__conversacion_id__mensajes_get: {
        parameters: {
            query?: {
                cursor?: string | null;
                limite?: number | null;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                conversacion_id: number;
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
                    "application/json": components["schemas"]["PaginaMensajes"];
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
    enviar_texto_api_v1_conversaciones__conversacion_id__mensajes_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                conversacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EntradaTexto"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MensajeEncolado"];
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
    enviar_plantilla_api_v1_conversaciones__conversacion_id__mensajes_plantilla_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                conversacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EntradaPlantilla"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MensajeEncolado"];
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
