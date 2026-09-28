"""DocEngine — Domain Models: Policy Envelope.

Defines the entity for grouping multiple document artifacts
under a single logical policy envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
import unicodedata


class DocumentType(str, Enum):
    """Standard document classifications within a policy envelope."""

    CONDICIONADO_GENERAL = "CONDICIONADO_GENERAL"
    CONDICIONADO_PARTICULAR = "CONDICIONADO_PARTICULAR"
    LIQUIDACION_PAGOS = "LIQUIDACION_PAGOS"
    ANEXO = "ANEXO"
    POLIZA_PRINCIPAL = "POLIZA_PRINCIPAL"
    ENDOSO = "ENDOSO"
    CERTIFICADO = "CERTIFICADO"
    DECLARACION_INDIVIDUAL = "DECLARACION_INDIVIDUAL"
    OTRO = "OTRO"


def normalize_document_type(raw_type: str | None) -> str | None:
    """Normalize a document type string to a standard DocumentType enum value.

    Handles variations in casing, accents, dashes, and whitespace.
    If no direct match is found, returns an upper-cased alphanumeric string
    or DocumentType.OTRO.value.
    """
    if not raw_type or not raw_type.strip():
        return None

    # Strip accents and normalize
    text = unicodedata.normalize("NFKD", raw_type.strip())
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")

    # Direct match against enum members
    for dt in DocumentType:
        if cleaned == dt.value:
            return dt.value

    # Common aliases / heuristics
    if "CONDICIONADO" in cleaned and "GENERAL" in cleaned:
        return DocumentType.CONDICIONADO_GENERAL.value
    if "CONDICIONADO" in cleaned and ("PARTICULAR" in cleaned or "ESPECIAL" in cleaned):
        return DocumentType.CONDICIONADO_PARTICULAR.value
    if "LIQUIDACION" in cleaned or "PAGO" in cleaned or "PLAN_PAGO" in cleaned:
        return DocumentType.LIQUIDACION_PAGOS.value
    if "ANEXO" in cleaned:
        return DocumentType.ANEXO.value
    if "ENDOSO" in cleaned:
        return DocumentType.ENDOSO.value
    if "CERTIFICADO" in cleaned:
        return DocumentType.CERTIFICADO.value
    if "POLIZA" in cleaned or "CARATULA" in cleaned:
        return DocumentType.POLIZA_PRINCIPAL.value

    return cleaned if cleaned else DocumentType.OTRO.value


@dataclass
class PolicyEnvelope:
    """Logical container grouping one or more documents belonging to the same policy.

    Attributes:
        id: Unique UUID string for the envelope.
        numero_poliza: Standard policy number identifier.
        company_sigla: Insurance company 3-letter code.
        ramo: Line of insurance (e.g. AUTOMOTOR, INCENDIO, SALUD).
        created_at: Creation timestamp in UTC.
        updated_at: Last update timestamp in UTC.
        documents: Optional list of documents associated with this envelope.
    """

    id: str
    numero_poliza: str
    company_sigla: str | None = None
    ramo: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    documents: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize envelope to dictionary."""
        return {
            "id": self.id,
            "numero_poliza": self.numero_poliza,
            "company_sigla": self.company_sigla,
            "ramo": self.ramo,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "documents_count": len(self.documents),
            "documents": self.documents,
        }
