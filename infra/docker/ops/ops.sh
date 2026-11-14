#!/bin/sh
# Operaciones manuales dentro de la tarea "ops" de ECS (design.md §13.9, T-049).
#
#   ops.sh contrasenas                       fija las contraseñas de los roles de base de datos
#   ops.sh bootstrap --razon-social "..."    crea la primera empresa y su invitación
#
# ECS inyecta el host, el puerto, el usuario y la contraseña del propietario de los esquemas
# (secreto cc/{env}/db/admin) y las contraseñas de los roles (CC_PWD_*). Aquí se compone la URL de
# conexión, que nunca se escribe en disco ni se imprime.
set -eu

: "${CC_DB_HOST:?falta CC_DB_HOST}" "${CC_DB_PORT:?falta CC_DB_PORT}"
: "${CC_DB_NAME:?falta CC_DB_NAME}" "${CC_DB_USER:?falta CC_DB_USER}"
: "${CC_DB_PASSWORD:?falta CC_DB_PASSWORD}"

# La contraseña generada por Secrets Manager excluye los caracteres reservados de una URL.
CC_MIGRAR_URL="postgresql+psycopg://${CC_DB_USER}:${CC_DB_PASSWORD}@${CC_DB_HOST}:${CC_DB_PORT}/${CC_DB_NAME}?sslmode=require"
export CC_MIGRAR_URL

orden="${1:-}"
[ "$#" -gt 0 ] && shift
case "$orden" in
  contrasenas) exec python scripts/asignar_contrasenas.py "$@" ;;
  bootstrap) exec python scripts/bootstrap_admin.py "$@" ;;
  *)
    echo "Uso: ops.sh contrasenas | ops.sh bootstrap --razon-social \"...\"" >&2
    exit 2
    ;;
esac
