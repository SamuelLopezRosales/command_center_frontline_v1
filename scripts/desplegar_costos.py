"""Estimación del costo de la ventana de uso de un ambiente (T-227; design.md §13, tasks.md §0.4).

Solo calcula: no llama a AWS ni a ninguna red. Las tarifas y el inventario viven en
``infra/config/costos.json`` y los parámetros del ambiente en ``infra/config/ambientes.json``.
**Son estimaciones** con tarifas públicas de us-east-1 recordadas, no la lista de precios de AWS:
antes de aprobar un despliegue se contrastan con la calculadora de precios de AWS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from infra.config.esquema import Ambiente

RAIZ = Path(__file__).resolve().parent.parent
RUTA_COSTOS = RAIZ / "infra" / "config" / "costos.json"


@dataclass(frozen=True)
class Rubro:
    concepto: str
    mensual: float
    nota: str = ""


@dataclass(frozen=True)
class Estimacion:
    ambiente: str
    dias: float
    presupuesto_usd: float
    rubros: tuple[Rubro, ...]
    parametros: dict[str, float] = field(default_factory=dict)

    @property
    def mensual(self) -> float:
        return sum(r.mensual for r in self.rubros)

    def ventana(self, rubro: Rubro, dias_mes: float) -> float:
        return rubro.mensual * self.dias / dias_mes

    @property
    def total_ventana(self) -> float:
        return sum(r.mensual for r in self.rubros) * self.dias / DIAS_MES_DEFECTO

    @property
    def tope_ventana(self) -> float:
        """El presupuesto es mensual: una ventana más larga que un mes se compara de forma
        proporcional (conservador: nunca menos de un mes completo de presupuesto)."""
        return self.presupuesto_usd * max(1.0, self.dias / DIAS_MES_DEFECTO)

    @property
    def supera(self) -> bool:
        return self.total_ventana > self.tope_ventana


DIAS_MES_DEFECTO = 30.4167


def cargar_costos(ruta: Path | None = None) -> dict:
    return json.loads((ruta or RUTA_COSTOS).read_text(encoding="utf-8"))


def estimar(
    ambiente: Ambiente,
    costos: dict,
    *,
    dias: float | None = None,
    horas_servicios_dia: float = 24.0,
    horas_workers_dia: float | None = None,
    alarmas: int | None = None,
) -> Estimacion:
    """Costo mensual por rubro y de la ventana. Los parámetros permiten explorar alcances
    menores (servicios apagados entre pruebas, menos alarmas)."""
    t = costos["tarifas"]
    inv = costos["inventario"]
    sup = costos["supuestos"]
    h_mes = float(costos["horas_mes"])
    eco = ambiente.economia
    es_prod = not eco.permite_borrado
    clave = "prod" if es_prod else "test"
    dias = float(dias if dias is not None else sup["ventana_dias_por_defecto"])
    if horas_workers_dia is None:
        horas_workers_dia = 24.0 if es_prod else float(sup["worker_horas_uso_por_dia_test"])
    frac_serv = max(0.0, min(24.0, horas_servicios_dia)) / 24.0
    frac_work = max(0.0, min(24.0, horas_workers_dia)) / 24.0

    rubros: list[Rubro] = []

    def agregar(concepto: str, mensual: float, nota: str = "") -> None:
        rubros.append(Rubro(concepto, round(mensual, 2), nota))

    # Base de datos.
    clase = eco.rds_clase
    horas_rds = t["rds_hora"].get(clase)
    if horas_rds is None:
        raise ValueError(f"sin tarifa para la clase de RDS '{clase}' en costos.json")
    factor_az = 2 if eco.rds_multi_az else 1
    agregar(
        f"RDS {clase}{' Multi-AZ' if eco.rds_multi_az else ''}",
        horas_rds * h_mes * factor_az,
        "instancia encendida todo el tiempo",
    )
    gb = inv["rds_gb"][clave]
    agregar(f"RDS almacenamiento {gb} GB gp3", t["rds_gb_mes"] * gb * factor_az)
    if eco.rds_proxy:
        vcpu = t["rds_vcpu"].get(clase, 2)
        agregar("RDS Proxy", t["rds_proxy_vcpu_hora"] * vcpu * h_mes)

    # Salida a internet.
    if eco.nat == "instancia":
        agregar(
            "Instancia NAT t4g.micro + disco",
            t["nat_instancia_hora"] * h_mes + t["nat_instancia_disco_gb_mes"] * inv["nat_disco_gb"],
        )
        agregar("IPv4 pública de la NAT", t["ipv4_publica_hora"] * h_mes)
    else:
        zonas = int(inv["zonas_nat_prod"])
        agregar(
            f"NAT Gateway x{zonas}",
            (t["nat_gateway_hora"] + t["ipv4_publica_hora"]) * h_mes * zonas,
            "sin el cobro por GB procesado",
        )

    # ECS Fargate (ARM64).
    def tarea_hora(vcpu: float, gb: float) -> float:
        return vcpu * t["fargate_vcpu_hora"] + gb * t["fargate_gb_hora"]

    tareas = max(1, eco.tareas_por_servicio)
    servicios = sum(tarea_hora(s["vcpu"], s["gb"]) for s in inv["servicios_api"]) * tareas
    agregar(
        f"Servicios de API ({len(inv['servicios_api'])} servicios x {tareas} tarea(s), "
        f"{horas_servicios_dia:g} h/día)",
        servicios * h_mes * frac_serv,
        "Fargate ARM64; con desired_count 0 entre pruebas este rubro baja a 0",
    )
    workers = 0.0
    for w in inv["workers"]:
        minimo = (
            max(eco.workers_min_tareas, w["minimo_prod"]) if es_prod else eco.workers_min_tareas
        )
        base = tarea_hora(w["vcpu"], w["gb"])
        if minimo > 0:
            workers += base * minimo * h_mes
        else:
            workers += base * h_mes * frac_work
    agregar(
        "Workers (pdf, cargas, whatsapp-entrada)",
        workers,
        "mínimo 0 tareas: solo se paga el tiempo en que se usan"
        if eco.workers_min_tareas == 0
        else "con su mínimo de tareas siempre encendidas",
    )
    agregar(
        "Balanceador de carga interno (ALB)",
        (t["alb_hora"] + t["alb_lcu_hora_minima"]) * h_mes,
        "cuota fija por hora más el mínimo de LCU",
    )

    # Fijos.
    agregar(f"Secretos de Secrets Manager ({inv['secretos']})", t["secreto_mes"] * inv["secretos"])
    agregar(f"Llaves de KMS ({inv['llaves_kms']})", t["kms_llave_mes"] * inv["llaves_kms"])
    n_alarmas = inv["alarmas"] if alarmas is None else alarmas
    agregar(f"Alarmas de CloudWatch ({n_alarmas})", t["alarma_mes"] * n_alarmas)
    agregar("Registros de CloudWatch", t["logs_gb"] * inv["logs_gb_mes"])
    agregar("ECR (imágenes)", t["ecr_gb_mes"] * inv["ecr_gb"])
    agregar("S3 (objetos, Object Lock y otros)", t["s3_otros_mes"])
    agregar(
        "Respaldo de RDS (AWS Backup)", t["backup_gb_mes"] * inv["backup_gb"][clave], "estimado"
    )
    if eco.waf_habilitado:
        agregar("AWS WAF (ACL y reglas)", t["waf_mes"])

    return Estimacion(
        ambiente=ambiente.nombre,
        dias=dias,
        presupuesto_usd=float(ambiente.presupuesto.monto_usd),
        rubros=tuple(rubros),
        parametros={
            "horas_servicios_dia": horas_servicios_dia,
            "horas_workers_dia": horas_workers_dia,
            "alarmas": float(n_alarmas),
        },
    )


def _usd(valor: float) -> str:
    return f"{valor:8.2f}"


def formatear(est: Estimacion, costos: dict) -> list[str]:
    """Líneas de texto con la tabla por rubro, el total y la comparación con el presupuesto."""
    dias_mes = float(costos["dias_mes"])
    lineas = [
        f"Costo estimado de la ventana de '{est.ambiente}': {est.dias:g} días "
        f"(presupuesto mensual {est.presupuesto_usd:.0f} USD)",
        "AVISO: son ESTIMACIONES con tarifas públicas recordadas (us-east-1), no la lista de "
        "precios de AWS.",
        "       Contrástelas con la calculadora de precios de AWS antes de aprobar.",
        f"{'Rubro':<62} {'USD/mes':>8} {'Ventana':>8}",
    ]
    for r in est.rubros:
        lineas.append(f"{r.concepto[:62]:<62} {_usd(r.mensual)} {_usd(est.ventana(r, dias_mes))}")
    lineas.append(f"{'TOTAL':<62} {_usd(est.mensual)} {_usd(est.total_ventana)}")
    lineas.append(f"Sin costo estimado: {costos['supuestos']['sin_costo_estimado']}.")
    lineas.append(
        "No incluye el gasto que ya tenga la cuenta por otros proyectos ni el cobro por "
        "transferencia de datos."
    )
    if est.supera:
        lineas.append(
            f"SUPERA EL PRESUPUESTO: {est.total_ventana:.2f} USD estimados para {est.dias:g} "
            f"días contra {est.tope_ventana:.2f} USD."
        )
    else:
        lineas.append(
            f"Dentro del presupuesto: {est.total_ventana:.2f} USD estimados contra "
            f"{est.tope_ventana:.2f} USD."
        )
    return lineas


def alternativas(ambiente: Ambiente, costos: dict, dias: float) -> list[tuple[str, Estimacion]]:
    """Escenarios de alcance menor para comparar contra el presupuesto."""
    return [
        ("Todo encendido 24 h", estimar(ambiente, costos, dias=dias)),
        (
            "Servicios de API 8 h al día (desired_count 0 entre pruebas)",
            estimar(ambiente, costos, dias=dias, horas_servicios_dia=8),
        ),
        (
            "Servicios apagados salvo pruebas (2 h al día) y sin alarmas por servicio",
            estimar(
                ambiente,
                costos,
                dias=dias,
                horas_servicios_dia=2,
                alarmas=max(
                    0,
                    costos["inventario"]["alarmas"] - costos["inventario"]["alarmas_por_servicio"],
                ),
            ),
        ),
    ]


def formatear_alternativas(ambiente: Ambiente, costos: dict, dias: float) -> list[str]:
    lineas = ["Alcances menores (estimación de la ventana):"]
    for nombre, est in alternativas(ambiente, costos, dias):
        marca = "SUPERA" if est.supera else "cabe"
        lineas.append(f"  {est.total_ventana:7.2f} USD  {marca:<6} {nombre}")
    lineas.append(
        "  Otras palancas: acortar la ventana (-Dias), no crear el pipeline (es lo predeterminado "
        "en test) y destruir (la persona) en cuanto terminen las pruebas."
    )
    return lineas
