import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { CLAVE_CAMPOS, apiCampos, type CampoDto } from "@/features/campos/api";
import { CLAVE_ORGANIZACIONES, CLAVE_PLANTAS, apiOrganizaciones, apiPlantas } from "@/features/organizaciones/api";
import { fechaCivil } from "@/shared/fechas";
import { CLAVE_COLABORADORES, apiColaboradores, type ColaboradorFila, type FiltrosListado } from "./api";
import "./colaboradores.css";
import { textos as t } from "./textos";

const LIMITE = 10;

interface Columna {
  id: string;
  etiqueta: string;
  defecto: boolean;
  /** Código interno si es un campo dinámico (se pide a la API en `columnas`). */
  codigo?: string;
  celda(f: ColaboradorFila, campo?: CampoDto): ReactNode;
}

const TIPOS: Record<string, string> = { ADMINISTRATIVO: t.administrativo, OPERATIVO: t.operativo };

function Estatus({ valor }: { valor: string }) {
  return <span className={`insignia ${valor === "ACTIVO" ? "ok" : "error"}`}>{valor}</span>;
}

const FIJAS: Columna[] = [
  { id: "numero_empleado", etiqueta: t.col.numero_empleado, defecto: true, celda: (f) => f.numero_empleado },
  { id: "nombre", etiqueta: t.col.nombre, defecto: true, celda: (f) => f.nombre_completo },
  { id: "organizacion", etiqueta: t.col.organizacion, defecto: true, celda: (f) => f.organizacion.nombre },
  { id: "planta", etiqueta: t.col.planta, defecto: true, celda: (f) => f.planta.nombre },
  { id: "puesto", etiqueta: t.col.puesto, defecto: true, celda: (f) => f.puesto },
  { id: "tipo", etiqueta: t.col.tipo, defecto: true, celda: (f) => TIPOS[f.tipo_empleado] ?? f.tipo_empleado },
  { id: "estatus", etiqueta: t.col.estatus, defecto: true, celda: (f) => <Estatus valor={f.estatus} /> },
  // La API entrega el celular ya enmascarado en el listado.
  { id: "celular", etiqueta: t.col.celular, defecto: false, celda: (f) => f.celular },
  { id: "fecha_ingreso", etiqueta: t.col.fecha_ingreso, defecto: false, celda: (f) => fechaCivil(f.fecha_ingreso) },
  { id: "consentimiento", etiqueta: t.col.consentimiento, defecto: false, celda: (f) => (f.consentimiento_vigente ? t.si : t.no) },
];

function valorDinamico(valor: unknown, campo?: CampoDto): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  if (typeof valor === "boolean") return valor ? t.si : t.no;
  if (typeof valor === "object") return "—";
  const texto = String(valor);
  const opcion = campo?.opciones?.find((o) => o.valor === texto);
  return opcion ? opcion.etiqueta : texto;
}

function useRetraso<T>(valor: T, ms: number): T {
  const [v, setV] = useState(valor);
  useEffect(() => {
    const id = setTimeout(() => setV(valor), ms);
    return () => clearTimeout(id);
  }, [valor, ms]);
  return v;
}

export function ListadoColaboradores() {
  const [texto, setTexto] = useState("");
  const q = useRetraso(texto, 300);
  const [organizacion, setOrganizacion] = useState("");
  const [planta, setPlanta] = useState("");
  const [estatus, setEstatus] = useState("ACTIVO");
  const [tipo, setTipo] = useState("");
  const [pagina, setPagina] = useState(1);
  const [menuAbierto, setMenuAbierto] = useState(false);
  const [elegidas, setElegidas] = useState<Set<string> | null>(null);

  const orgs = useQuery({ queryKey: [...CLAVE_ORGANIZACIONES], queryFn: () => apiOrganizaciones.listar(false) });
  const plantas = useQuery({ queryKey: [...CLAVE_PLANTAS], queryFn: () => apiPlantas.listar(false) });
  const campos = useQuery({ queryKey: [...CLAVE_CAMPOS, "listado"], queryFn: () => apiCampos.listar("todos") });

  const columnas: Columna[] = useMemo(() => {
    const dinamicas = (campos.data?.dinamicos ?? [])
      .filter((c) => c.activo && !c.es_sensible)
      .map<Columna>((c) => ({
        id: `campo:${c.codigo_interno}`,
        etiqueta: c.nombre_campo,
        defecto: false,
        codigo: c.codigo_interno,
        celda: (f) => valorDinamico(f.campos[c.codigo_interno], c),
      }));
    return [...FIJAS, ...dinamicas];
  }, [campos.data]);

  const visibles = columnas.filter((c) => (elegidas ? elegidas.has(c.id) : c.defecto));
  const codigosPedidos = visibles.flatMap((c) => (c.codigo ? [c.codigo] : []));

  const filtros: FiltrosListado = {
    q,
    organizacion_id: organizacion,
    planta_id: planta,
    estatus,
    tipo_empleado: tipo,
    columnas: codigosPedidos,
    pagina,
    limite: LIMITE,
  };
  const lista = useQuery({
    queryKey: [...CLAVE_COLABORADORES, "lista", filtros],
    queryFn: () => apiColaboradores.listar(filtros),
    placeholderData: keepPreviousData,
  });

  const cambiar = (fn: () => void) => {
    fn();
    setPagina(1);
  };

  function alternarColumna(c: Columna) {
    const actual = new Set(elegidas ?? columnas.filter((x) => x.defecto).map((x) => x.id));
    if (actual.has(c.id)) actual.delete(c.id);
    else actual.add(c.id);
    setElegidas(actual);
  }

  const datos = lista.data;
  const total = datos?.total ?? 0;
  const desde = total === 0 ? 0 : (pagina - 1) * LIMITE + 1;
  const hasta = Math.min(pagina * LIMITE, total);

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{datos ? t.registrados(total) : " "}</p>
        </div>
        <div className="col-acciones-cabecera">
          <Link className="btn btn-contorno" to="/campos">
            {t.configurarCampos}
          </Link>
          <Link className="btn btn-contorno" to="/cargas">
            {t.cargaMasiva}
          </Link>
          <Link className="btn btn-contorno" to="/organizaciones">
            {t.organizaciones}
          </Link>
          <Link className="btn btn-primario" to="/colaboradores/nuevo">
            {t.nuevo}
          </Link>
        </div>
      </div>

      <div className="col-filtros" role="search">
        <input
          type="search"
          aria-label={t.buscar}
          placeholder={t.buscar}
          value={texto}
          onChange={(e) => cambiar(() => setTexto(e.target.value))}
        />
        <select aria-label={t.organizacion} value={organizacion} onChange={(e) => cambiar(() => setOrganizacion(e.target.value))}>
          <option value="">{t.todasOrganizaciones}</option>
          {(orgs.data ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.clave} · {o.razon_social}
            </option>
          ))}
        </select>
        <select aria-label={t.planta} value={planta} onChange={(e) => cambiar(() => setPlanta(e.target.value))}>
          <option value="">{t.todasPlantas}</option>
          {(plantas.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.nombre}
            </option>
          ))}
        </select>
        <select aria-label={t.estatus} value={estatus} onChange={(e) => cambiar(() => setEstatus(e.target.value))}>
          <option value="">{t.todosEstatus}</option>
          <option value="ACTIVO">ACTIVO</option>
          <option value="BAJA">BAJA</option>
        </select>
        <select aria-label={t.tipoEmpleado} value={tipo} onChange={(e) => cambiar(() => setTipo(e.target.value))}>
          <option value="">{t.todosTipos}</option>
          <option value="ADMINISTRATIVO">{t.administrativo}</option>
          <option value="OPERATIVO">{t.operativo}</option>
        </select>
        <div className="col-columnas">
          <button className="btn btn-contorno" aria-expanded={menuAbierto} aria-haspopup="true" onClick={() => setMenuAbierto((a) => !a)}>
            {t.columnas(visibles.length, columnas.length)}
          </button>
          {menuAbierto && (
            <div className="col-menu" role="group" aria-label={t.columnasMenu}>
              {columnas.map((c) => (
                <label key={c.id}>
                  <input type="checkbox" checked={visibles.includes(c)} onChange={() => alternarColumna(c)} /> {c.etiqueta}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {lista.isError && (
        <div className="alerta-error" role="alert">
          {t.errorCarga}{" "}
          <button className="btn-enlace" onClick={() => void lista.refetch()}>
            {t.reintentar}
          </button>
        </div>
      )}
      {lista.isPending && <p role="status">{t.cargando}</p>}

      {datos && (
        <section className="tarjeta col-tabla" aria-label={t.titulo}>
          <table className="tabla">
            <thead>
              <tr>
                {visibles.map((c) => (
                  <th key={c.id}>{c.etiqueta}</th>
                ))}
                <th>{t.col.accion}</th>
              </tr>
            </thead>
            <tbody>
              {datos.items.map((f) => (
                <tr key={f.id}>
                  {visibles.map((c) => (
                    <td key={c.id}>{c.celda(f)}</td>
                  ))}
                  <td>
                    <Link to={`/colaboradores/${f.id}`} aria-label={`${t.abrir} ${f.nombre_completo}`}>
                      {t.abrir}
                    </Link>
                  </td>
                </tr>
              ))}
              {datos.items.length === 0 && (
                <tr>
                  <td colSpan={visibles.length + 1}>{t.sinResultados}</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="col-pie">
            <span aria-live="polite">{t.mostrando(desde, hasta, total)}</span>
            <div>
              <button className="btn btn-contorno" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
                {t.anterior}
              </button>
              <button className="btn btn-contorno" disabled={hasta >= total} onClick={() => setPagina((p) => p + 1)}>
                {t.siguiente}
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
