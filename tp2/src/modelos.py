"""Modelos de datos: estados, la tarea interna y el cuerpo del POST."""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Estado(str, Enum):
    PENDIENTE = "pendiente"
    EJECUTANDO = "ejecutando"
    COMPLETADA = "completada"
    FALLIDA = "fallida"
    CANCELADA = "cancelada"


# Estados de los que una tarea ya no sale
ESTADOS_FINALES = {Estado.COMPLETADA, Estado.FALLIDA, Estado.CANCELADA}

TipoTarea = Literal["descargar", "hashear", "esperar"]


class TareaEntrada(BaseModel):
    """Lo que manda el cliente en POST /tareas."""

    tipo: TipoTarea
    parametros: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = Field(default=None, gt=0)


@dataclass
class Tarea:
    """Una tarea tal como la guarda el sistema en memoria."""

    tipo: str
    parametros: dict[str, Any]
    timeout: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    estado: Estado = Estado.PENDIENTE
    resultado: Any = None
    error: str | None = None
    creada: float = field(default_factory=time.time)
    iniciada: float | None = None
    finalizada: float | None = None

    def duracion(self) -> float | None:
        if self.iniciada is None or self.finalizada is None:
            return None
        return self.finalizada - self.iniciada

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "parametros": self.parametros,
            "timeout": self.timeout,
            "estado": self.estado.value,
            "resultado": self.resultado,
            "error": self.error,
            "creada": self.creada,
            "iniciada": self.iniciada,
            "finalizada": self.finalizada,
            "duracion": self.duracion(),
        }
