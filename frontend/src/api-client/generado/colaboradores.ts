// Generado por scripts/generar-api.mjs. No editar.
export interface paths {
    "/api/v1/cargas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Historial de cargas (COL-19) */
        get: operations["listar_api_v1_cargas_get"];
        put?: never;
        /** Inicia una carga (COL-17) */
        post: operations["iniciar_api_v1_cargas_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/cargas/plantilla": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Plantilla de Excel con los campos activos (COL-16) */
        get: operations["plantilla_api_v1_cargas_plantilla_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/cargas/{carga_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Resumen y filas de una carga (COL-20) */
        get: operations["detalle_api_v1_cargas__carga_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/cargas/{carga_id}/cancelar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancela una carga (COL-22) */
        post: operations["cancelar_api_v1_cargas__carga_id__cancelar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/cargas/{carga_id}/confirmar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirma el archivo subido y lo encola (COL-18) */
        post: operations["confirmar_api_v1_cargas__carga_id__confirmar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/cargas/{carga_id}/errores": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reporte de errores en CSV (COL-21) */
        get: operations["errores_api_v1_cargas__carga_id__errores_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/colaboradores": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listado (COL-01) */
        get: operations["listar_api_v1_colaboradores_get"];
        put?: never;
        /** Alta (COL-02) */
        post: operations["crear_api_v1_colaboradores_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/colaboradores/{colaborador_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Detalle (COL-03) */
        get: operations["detalle_api_v1_colaboradores__colaborador_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Edición con If-Match (COL-04) */
        patch: operations["actualizar_api_v1_colaboradores__colaborador_id__patch"];
        trace?: never;
    };
    "/api/v1/colaboradores/{colaborador_id}/baja": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Baja (COL-05) */
        post: operations["baja_api_v1_colaboradores__colaborador_id__baja_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/colaboradores/{colaborador_id}/consentimiento": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Consentimiento de WhatsApp (COL-07) */
        put: operations["consentimiento_api_v1_colaboradores__colaborador_id__consentimiento_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/colaboradores/{colaborador_id}/reactivar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reactivación (COL-06) */
        post: operations["reactivar_api_v1_colaboradores__colaborador_id__reactivar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizaciones": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Organizaciones (COL-08) */
        get: operations["listar_api_v1_organizaciones_get"];
        put?: never;
        /** Crea una organización (COL-09) */
        post: operations["crear_api_v1_organizaciones_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizaciones/{organizacion_id}": {
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
        /** Actualiza o desactiva una organización (COL-10) */
        patch: operations["actualizar_api_v1_organizaciones__organizacion_id__patch"];
        trace?: never;
    };
    "/api/v1/organizaciones/{organizacion_id}/logotipo": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** URL firmada para subir el logotipo (COL-11) */
        post: operations["solicitar_logotipo_api_v1_organizaciones__organizacion_id__logotipo_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizaciones/{organizacion_id}/logotipo/confirmar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verifica el logotipo subido y lo asigna (COL-12) */
        post: operations["confirmar_logotipo_api_v1_organizaciones__organizacion_id__logotipo_confirmar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Plantas (COL-13) */
        get: operations["listar_api_v1_plantas_get"];
        put?: never;
        /** Crea una planta (COL-14) */
        post: operations["crear_api_v1_plantas_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plantas/{planta_id}": {
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
        /** Actualiza o desactiva una planta (COL-15) */
        patch: operations["actualizar_api_v1_plantas__planta_id__patch"];
        trace?: never;
    };
    "/internal/campos/{campo_id}/uso": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** INT-COL-10 */
        get: operations["uso_de_campo_internal_campos__campo_id__uso_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/buscar-por-celular": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-01 */
        post: operations["buscar_por_celular_internal_colaboradores_buscar_por_celular_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/contactos:resolver": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-05 */
        post: operations["resolver_contactos_internal_colaboradores_contactos_resolver_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/faltantes:contar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-09 */
        post: operations["faltantes_contar_internal_colaboradores_faltantes_contar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/{colaborador_id}/datos-constancia": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-04 */
        post: operations["datos_constancia_internal_colaboradores__colaborador_id__datos_constancia_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/{colaborador_id}/desafio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-02 */
        post: operations["desafio_internal_colaboradores__colaborador_id__desafio_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/{colaborador_id}/resumen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** INT-COL-07 */
        get: operations["resumen_internal_colaboradores__colaborador_id__resumen_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/colaboradores/{colaborador_id}/verificar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** INT-COL-03 */
        post: operations["verificar_internal_colaboradores__colaborador_id__verificar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/organizaciones/{organizacion_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** INT-COL-08 */
        get: operations["organizacion_internal_organizaciones__organizacion_id__get"];
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
        /** Baja */
        Baja: {
            /**
             * Fecha Baja
             * Format: date
             */
            fecha_baja: string;
        };
        /** BuscarCelular */
        BuscarCelular: {
            /** Celular */
            celular: string;
        };
        /** Busqueda */
        Busqueda: {
            /** Celular Hash */
            celular_hash: string;
            /** Colaborador Id */
            colaborador_id?: number | null;
            /** Consentimiento Vigente */
            consentimiento_vigente?: boolean | null;
            /** Elegible */
            elegible?: boolean | null;
            /** Encontrado */
            encontrado: boolean;
            /** Estatus */
            estatus?: string | null;
            /** Motivo */
            motivo?: string | null;
        };
        /** Carga */
        Carga: {
            /** Confirmada */
            confirmada: boolean;
            /**
             * Estado
             * @enum {string}
             */
            estado: "EN_PROCESO" | "TERMINADA" | "CANCELADA";
            /**
             * Fecha Carga
             * Format: date-time
             */
            fecha_carga: string;
            /** Fecha Fin */
            fecha_fin: string | null;
            /** Filas Error */
            filas_error: number;
            /** Filas Ok */
            filas_ok: number;
            /** Id */
            id: number;
            /** Motivo Cierre */
            motivo_cierre: string | null;
            /** Nombre Archivo */
            nombre_archivo: string;
            /** Total Filas */
            total_filas: number | null;
            /** Version Plantilla */
            version_plantilla: string;
        };
        /** CargaDetalle */
        CargaDetalle: {
            carga: components["schemas"]["Carga"];
            filas: components["schemas"]["PaginaFilas"];
        };
        /** CargaIniciada */
        CargaIniciada: {
            /** Carga Id */
            carga_id: number;
            /**
             * Content Type
             * @default application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
             */
            content_type: string;
            /**
             * Expira
             * Format: date-time
             */
            expira: string;
            /** S3 Key */
            s3_key: string;
            /** Url Subida */
            url_subida: string;
        };
        /** CargaIniciar */
        CargaIniciar: {
            /** Nombre Archivo */
            nombre_archivo: string;
            /** Tamano */
            tamano: number;
        };
        /**
         * ColaboradorActualizar
         * @description Parcial. ``numero_empleado`` y ``estatus`` no están: no cambian aquí (COL-04).
         */
        ColaboradorActualizar: {
            /** Apellido Materno */
            apellido_materno?: string | null;
            /** Apellido Paterno */
            apellido_paterno?: string | null;
            /** Campos */
            campos?: {
                [key: string]: unknown;
            } | null;
            /** Celular */
            celular?: string | null;
            /** Fecha Ingreso */
            fecha_ingreso?: string | null;
            /** Nombres */
            nombres?: string | null;
            /** Organizacion Id */
            organizacion_id?: number | null;
            /** Planta Id */
            planta_id?: number | null;
            /** Puesto */
            puesto?: string | null;
            /** Tipo Empleado */
            tipo_empleado?: ("ADMINISTRATIVO" | "OPERATIVO") | null;
        };
        /**
         * ColaboradorCrear
         * @description Los once campos fijos son obligatorios (CC-REQ-020); ``estatus`` nace ``ACTIVO``.
         */
        ColaboradorCrear: {
            /** Apellido Materno */
            apellido_materno: string;
            /** Apellido Paterno */
            apellido_paterno: string;
            /** Campos */
            campos?: {
                [key: string]: unknown;
            };
            /** Celular */
            celular: string;
            /**
             * Consentimiento
             * @default false
             */
            consentimiento: boolean;
            /**
             * Fecha Ingreso
             * Format: date
             */
            fecha_ingreso: string;
            /** Nombres */
            nombres: string;
            /** Numero Empleado */
            numero_empleado: string;
            /** Organizacion Id */
            organizacion_id: number;
            /** Planta Id */
            planta_id: number;
            /** Puesto */
            puesto: string;
            /**
             * Tipo Empleado
             * @enum {string}
             */
            tipo_empleado: "ADMINISTRATIVO" | "OPERATIVO";
        };
        /** ColaboradorDetalle */
        ColaboradorDetalle: {
            /** Apellido Materno */
            apellido_materno: string;
            /** Apellido Paterno */
            apellido_paterno: string;
            /** Campos */
            campos: {
                [key: string]: unknown;
            };
            /** Celular */
            celular: string;
            /** Celular Invalido */
            celular_invalido: boolean;
            consentimiento: components["schemas"]["EstadoConsentimiento"];
            /** Elegible */
            elegible: boolean;
            /** Estatus */
            estatus: string;
            /** Fecha Baja */
            fecha_baja: string | null;
            /**
             * Fecha Ingreso
             * Format: date
             */
            fecha_ingreso: string;
            /**
             * Fecha Modificacion
             * Format: date-time
             */
            fecha_modificacion: string;
            /** Id */
            id: number;
            /** Motivo No Elegible */
            motivo_no_elegible: string | null;
            /** Nombres */
            nombres: string;
            /** Numero Empleado */
            numero_empleado: string;
            organizacion: components["schemas"]["Referencia"];
            planta: components["schemas"]["Referencia"];
            /** Puesto */
            puesto: string;
            /** Tipo Empleado */
            tipo_empleado: string;
        };
        /** ColaboradorFila */
        ColaboradorFila: {
            /** Campos */
            campos: {
                [key: string]: unknown;
            };
            /** Celular */
            celular: string;
            /** Consentimiento Vigente */
            consentimiento_vigente: boolean;
            /** Estatus */
            estatus: string;
            /**
             * Fecha Ingreso
             * Format: date
             */
            fecha_ingreso: string;
            /** Id */
            id: number;
            /** Nombre Completo */
            nombre_completo: string;
            /** Numero Empleado */
            numero_empleado: string;
            organizacion: components["schemas"]["Referencia"];
            planta: components["schemas"]["Referencia"];
            /** Puesto */
            puesto: string;
            /** Tipo Empleado */
            tipo_empleado: string;
        };
        /** Consentimiento */
        Consentimiento: {
            /** Otorgado */
            otorgado: boolean;
            /** Vigente Hasta */
            vigente_hasta?: string | null;
        };
        /** Contacto */
        Contacto: {
            /** Celular */
            celular?: string | null;
            /** Correo */
            correo?: string | null;
            /** Elegible */
            elegible: boolean;
            /** Id */
            id: number;
            /** Motivo */
            motivo?: string | null;
            /** Valores */
            valores?: {
                [key: string]: string;
            };
        };
        /** Contactos */
        Contactos: {
            /** Items */
            items: components["schemas"]["Contacto"][];
        };
        /** Datos */
        Datos: {
            /** Faltantes */
            faltantes: string[];
            /** Valores */
            valores: {
                [key: string]: string;
            };
        };
        /** DatosConstancia */
        DatosConstancia: {
            /** Variables */
            variables: string[];
        };
        /** Desafio */
        Desafio: {
            /**
             * Tipo
             * @enum {string}
             */
            tipo: "NSS_ULTIMOS4" | "FECHA_INGRESO_DDMM";
        };
        /** ErrorDeFila */
        ErrorDeFila: {
            /** Codigo */
            codigo: string;
            /** Mensaje */
            mensaje: string;
        };
        /** EstadoConsentimiento */
        EstadoConsentimiento: {
            /** Fecha */
            fecha: string | null;
            /** Otorgado */
            otorgado: boolean;
            /** Vigente */
            vigente: boolean;
            /** Vigente Hasta */
            vigente_hasta: string | null;
        };
        /** Faltantes */
        Faltantes: {
            /** Codigos Internos */
            codigos_internos: string[];
        };
        /** FilaCarga */
        FilaCarga: {
            /** Errores */
            errores: components["schemas"]["ErrorDeFila"][];
            /** Numero Fila */
            numero_fila: number;
            /**
             * Resultado
             * @enum {string}
             */
            resultado: "NUEVO" | "ACTUALIZADO" | "ERROR" | "OMITIDO";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** LogotipoConfirmar */
        LogotipoConfirmar: {
            /** S3 Key */
            s3_key: string;
        };
        /** LogotipoSolicitud */
        LogotipoSolicitud: {
            /** Content Type */
            content_type: string;
            /** Tamano */
            tamano: number;
        };
        /** Organizacion */
        Organizacion: {
            /** Activa */
            activa: boolean;
            /** Cargo Firmante */
            cargo_firmante: string | null;
            /** Ciudad */
            ciudad: string | null;
            /** Clave */
            clave: string;
            /** Correo Firmante */
            correo_firmante: string | null;
            /** Domicilio Fiscal */
            domicilio_fiscal: string | null;
            /** Id */
            id: number;
            /** Nombre Firmante */
            nombre_firmante: string | null;
            /** Razon Social */
            razon_social: string;
            /** Registro Patronal */
            registro_patronal: string | null;
            /** Rfc */
            rfc: string | null;
            /** Tiene Logotipo */
            tiene_logotipo: boolean;
        };
        /**
         * OrganizacionActualizar
         * @description La clave no está: es inmutable (DS-04); enviarla da 422 ``CAMPO_NO_PERMITIDO``.
         */
        OrganizacionActualizar: {
            /** Activa */
            activa?: boolean | null;
            /** Cargo Firmante */
            cargo_firmante?: string | null;
            /** Ciudad */
            ciudad?: string | null;
            /** Correo Firmante */
            correo_firmante?: string | null;
            /** Domicilio Fiscal */
            domicilio_fiscal?: string | null;
            /** Nombre Firmante */
            nombre_firmante?: string | null;
            /** Razon Social */
            razon_social?: string | null;
            /** Registro Patronal */
            registro_patronal?: string | null;
            /** Rfc */
            rfc?: string | null;
        };
        /** OrganizacionCrear */
        OrganizacionCrear: {
            /** Cargo Firmante */
            cargo_firmante?: string | null;
            /** Ciudad */
            ciudad?: string | null;
            /** Clave */
            clave: string;
            /** Correo Firmante */
            correo_firmante?: string | null;
            /** Domicilio Fiscal */
            domicilio_fiscal?: string | null;
            /** Nombre Firmante */
            nombre_firmante?: string | null;
            /** Razon Social */
            razon_social: string;
            /** Registro Patronal */
            registro_patronal?: string | null;
            /** Rfc */
            rfc?: string | null;
        };
        /** OrganizacionesSalida */
        OrganizacionesSalida: {
            /** Items */
            items: components["schemas"]["Organizacion"][];
        };
        /** PaginaCargas */
        PaginaCargas: {
            /** Items */
            items: components["schemas"]["Carga"][];
            /** Limite */
            limite: number;
            /** Pagina */
            pagina: number;
            /** Total */
            total: number;
        };
        /** PaginaColaboradores */
        PaginaColaboradores: {
            /** Items */
            items: components["schemas"]["ColaboradorFila"][];
            /** Limite */
            limite: number;
            /** Pagina */
            pagina: number;
            /** Total */
            total: number;
        };
        /** PaginaFilas */
        PaginaFilas: {
            /** Items */
            items: components["schemas"]["FilaCarga"][];
            /** Limite */
            limite: number;
            /** Pagina */
            pagina: number;
            /** Total */
            total: number;
        };
        /** Planta */
        Planta: {
            /** Activa */
            activa: boolean;
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
        };
        /** PlantaActualizar */
        PlantaActualizar: {
            /** Activa */
            activa?: boolean | null;
            /** Nombre */
            nombre?: string | null;
        };
        /** PlantaCrear */
        PlantaCrear: {
            /** Nombre */
            nombre: string;
        };
        /** PlantasSalida */
        PlantasSalida: {
            /** Items */
            items: components["schemas"]["Planta"][];
        };
        /** Reactivar */
        Reactivar: {
            /**
             * Consentimiento
             * @default false
             */
            consentimiento: boolean;
        };
        /** Referencia */
        Referencia: {
            /** Id */
            id: number;
            /** Nombre */
            nombre: string;
        };
        /** ResolverContactos */
        ResolverContactos: {
            /** Ids */
            ids: number[];
            /**
             * Proposito
             * @enum {string}
             */
            proposito: "NOTIFICACION" | "CONSTANCIA" | "VERIFICACION" | "CHAT" | "CORREO";
            /** Variables */
            variables?: string[] | null;
        };
        /** UrlSubida */
        UrlSubida: {
            /**
             * Expira
             * Format: date-time
             */
            expira: string;
            /** S3 Key */
            s3_key: string;
            /** Url */
            url: string;
        };
        /** UsoDeCampo */
        UsoDeCampo: {
            /** Con Valores */
            con_valores: boolean;
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
        /** Verificacion */
        Verificacion: {
            /** Valido */
            valido: boolean;
        };
        /** Verificar */
        Verificar: {
            /** Dato */
            dato: string;
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
    listar_api_v1_cargas_get: {
        parameters: {
            query?: {
                pagina?: number;
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
                    "application/json": components["schemas"]["PaginaCargas"];
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
    iniciar_api_v1_cargas_post: {
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
                "application/json": components["schemas"]["CargaIniciar"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CargaIniciada"];
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
    plantilla_api_v1_cargas_plantilla_get: {
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
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": unknown;
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
    detalle_api_v1_cargas__carga_id__get: {
        parameters: {
            query?: {
                resultado?: ("NUEVO" | "ACTUALIZADO" | "ERROR" | "OMITIDO") | null;
                pagina?: number;
                limite?: number;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                carga_id: number;
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
                    "application/json": components["schemas"]["CargaDetalle"];
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
    cancelar_api_v1_cargas__carga_id__cancelar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                carga_id: number;
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
                    "application/json": components["schemas"]["Carga"];
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
    confirmar_api_v1_cargas__carga_id__confirmar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                carga_id: number;
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
                    "application/json": components["schemas"]["Carga"];
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
    errores_api_v1_cargas__carga_id__errores_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                carga_id: number;
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
                    "text/csv": unknown;
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
    listar_api_v1_colaboradores_get: {
        parameters: {
            query?: {
                q?: string | null;
                organizacion_id?: number | null;
                planta_id?: number | null;
                estatus?: ("ACTIVO" | "BAJA") | null;
                tipo_empleado?: ("ADMINISTRATIVO" | "OPERATIVO") | null;
                columnas?: string[];
                pagina?: number;
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
                    "application/json": components["schemas"]["PaginaColaboradores"];
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
    crear_api_v1_colaboradores_post: {
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
                "application/json": components["schemas"]["ColaboradorCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    detalle_api_v1_colaboradores__colaborador_id__get: {
        parameters: {
            query?: {
                incluir_sensibles?: boolean;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                colaborador_id: number;
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
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    actualizar_api_v1_colaboradores__colaborador_id__patch: {
        parameters: {
            query?: never;
            header?: {
                "if-match"?: string | null;
                authorization?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ColaboradorActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    baja_api_v1_colaboradores__colaborador_id__baja_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Baja"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    consentimiento_api_v1_colaboradores__colaborador_id__consentimiento_put: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Consentimiento"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    reactivar_api_v1_colaboradores__colaborador_id__reactivar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Reactivar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ColaboradorDetalle"];
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
    listar_api_v1_organizaciones_get: {
        parameters: {
            query?: {
                solo_activas?: boolean;
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
                    "application/json": components["schemas"]["OrganizacionesSalida"];
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
    crear_api_v1_organizaciones_post: {
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
                "application/json": components["schemas"]["OrganizacionCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Organizacion"];
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
    actualizar_api_v1_organizaciones__organizacion_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                organizacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OrganizacionActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Organizacion"];
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
    solicitar_logotipo_api_v1_organizaciones__organizacion_id__logotipo_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                organizacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LogotipoSolicitud"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UrlSubida"];
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
    confirmar_logotipo_api_v1_organizaciones__organizacion_id__logotipo_confirmar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                organizacion_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LogotipoConfirmar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Organizacion"];
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
    listar_api_v1_plantas_get: {
        parameters: {
            query?: {
                solo_activas?: boolean;
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
                    "application/json": components["schemas"]["PlantasSalida"];
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
    crear_api_v1_plantas_post: {
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
                "application/json": components["schemas"]["PlantaCrear"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Planta"];
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
    actualizar_api_v1_plantas__planta_id__patch: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                planta_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlantaActualizar"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Planta"];
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
    uso_de_campo_internal_campos__campo_id__uso_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
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
                    "application/json": components["schemas"]["UsoDeCampo"];
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
    buscar_por_celular_internal_colaboradores_buscar_por_celular_post: {
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
                "application/json": components["schemas"]["BuscarCelular"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Busqueda"];
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
    resolver_contactos_internal_colaboradores_contactos_resolver_post: {
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
                "application/json": components["schemas"]["ResolverContactos"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Contactos"];
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
    faltantes_contar_internal_colaboradores_faltantes_contar_post: {
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
                "application/json": components["schemas"]["Faltantes"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number;
                    };
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
    datos_constancia_internal_colaboradores__colaborador_id__datos_constancia_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DatosConstancia"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Datos"];
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
    desafio_internal_colaboradores__colaborador_id__desafio_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                colaborador_id: number;
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
                    "application/json": components["schemas"]["Desafio"];
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
    resumen_internal_colaboradores__colaborador_id__resumen_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                colaborador_id: number;
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
                    "application/json": {
                        [key: string]: unknown;
                    };
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
    verificar_internal_colaboradores__colaborador_id__verificar_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                colaborador_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Verificar"];
            };
        };
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
    organizacion_internal_organizaciones__organizacion_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
                "x-empresa-id"?: string | null;
            };
            path: {
                organizacion_id: number;
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
                    "application/json": {
                        [key: string]: unknown;
                    };
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
