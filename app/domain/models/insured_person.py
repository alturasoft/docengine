"""DocEngine — Domain Models: Insured Person (Pólizas Colectivas).

[ADITIVO] Define el modelo de dominio para representar a un asegurado individual
en pólizas colectivas de personas (Salud, Accidentes Personales, Vida en Grupo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InsuredPerson:
    """Representa a una persona física asegurada dentro de una póliza colectiva.

    Attributes:
        item_number: Número correlativo del asegurado en la nómina.
        nombre_completo: Nombre y apellidos completos del asegurado.
        policy_id: Identificador de la póliza específica (documento).
        envelope_id: Identificador del sobre lógico que agrupa la póliza.
        id: Identificador único UUID del registro.
        documento_identidad: Cédula de identidad (CI), carnet o pasaporte.
        fecha_nacimiento: Fecha de nacimiento en formato DD/MM/AAAA o texto original.
        edad: Edad cronológica del asegurado.
        genero: Género o sexo (M, F, MASCULINO, FEMENINO).
        parentesco_categoria: Relación respecto al tomador/titular (TITULAR, DEPENDIENTE, HIJO, CONYUGE, EMPLEADO).
        cargo_ocupacion: Cargo, profesión u ocupación desempeñada.
        suma_asegurada_usd: Monto de capital asegurado o cobertura principal expresado en USD.
        prima_usd: Prima individual asignada (si aplica) en USD.
        raw_metadata: Metadatos adicionales extraídos (coberturas específicas, sublímites, etc.).
    """

    nombre_completo: str
    item_number: int = 1
    policy_id: str | None = None
    envelope_id: str | None = None
    id: str | None = None
    documento_identidad: str | None = None
    fecha_nacimiento: str | None = None
    edad: int | None = None
    genero: str | None = None
    parentesco_categoria: str = "TITULAR"
    cargo_ocupacion: str | None = None
    suma_asegurada_usd: float = 0.0
    prima_usd: float = 0.0
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa la entidad a diccionario plano para API o persistencia."""
        return {
            "id": self.id,
            "policy_id": self.policy_id,
            "envelope_id": self.envelope_id,
            "item_number": self.item_number,
            "nombre_completo": self.nombre_completo,
            "documento_identidad": self.documento_identidad,
            "fecha_nacimiento": self.fecha_nacimiento,
            "edad": self.edad,
            "genero": self.genero,
            "parentesco_categoria": self.parentesco_categoria,
            "cargo_ocupacion": self.cargo_ocupacion,
            "suma_asegurada_usd": self.suma_asegurada_usd,
            "prima_usd": self.prima_usd,
            "raw_metadata": self.raw_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
