-- Extensiones que usa el modelo (design.md §2): búsqueda con trigramas y sin acentos.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
