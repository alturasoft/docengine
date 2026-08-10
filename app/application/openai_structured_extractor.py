"""DocEngine — Application Service: OpenAI Structured Extractor.

Extracts structured JSON data (coberturas, sumas aseguradas, condiciones)
from Markdown using OpenAI gpt-4o with Structured Outputs (Pydantic).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Output
# ---------------------------------------------------------------------------

class CoberturaItem(BaseModel):
    nombre: str = Field(description="Nombre de la cobertura o anexo")
    suma_asegurada: str | None = Field(default=None, description="Monto o suma asegurada")
    deducible: str | None = Field(default=None, description="Deducible o franquicia aplicable")
    limite: str | None = Field(default=None, description="Límite máximo de indemnización")


class PolicyStructuredSchema(BaseModel):
    numero_poliza: str | None = Field(default=None, description="Número de póliza o certificado")
    asegurado: str | None = Field(default=None, description="Nombre o razón social del asegurado")
    tomador: str | None = Field(default=None, description="Nombre o razón social del tomador/contratante")
    aseguradora: str | None = Field(default=None, description="Nombre de la compañía aseguradora")
    sigla_empresa: str | None = Field(default=None, description="Sigla de 3 letras de la aseguradora (ej. CRI, LBC)")
    vigencia_desde: str | None = Field(default=None, description="Fecha de inicio de vigencia (YYYY-MM-DD o texto original)")
    vigencia_hasta: str | None = Field(default=None, description="Fecha de fin de vigencia (YYYY-MM-DD o texto original)")
    moneda: str | None = Field(default=None, description="Moneda de la póliza (USD, BOB, etc.)")
    prima_total: str | None = Field(default=None, description="Prima total de la póliza")
    coberturas: list[CoberturaItem] = Field(default_factory=list, description="Lista de coberturas contratadas")
    condiciones_especiales: list[str] = Field(default_factory=list, description="Cláusulas o condiciones especiales")


# ---------------------------------------------------------------------------
# Extractor Class
# ---------------------------------------------------------------------------

class OpenAIStructuredExtractor:
    """Uses gpt-4o with Pydantic structured outputs to atomize policy data."""

    def __init__(self, model_name: str = "gpt-4o") -> None:
        self._model_name = model_name

    def extract_structured_json(
        self, markdown: str, company_sigla: str | None = None
    ) -> dict[str, Any]:
        """Extract structured insurance policy data from Markdown.

        Args:
            markdown: Markdown text extracted from PDF.
            company_sigla: 3-letter company code (e.g., 'CRI').

        Returns:
            Dictionary containing atomized coverage and policy details.
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set. Returning basic structured fallback.")
            return self._build_fallback_dict(company_sigla)

        try:
            from openai import OpenAI  # noqa: PLC0415

            client = OpenAI(api_key=api_key)

            # Limit text length to stay well within context limit (~12,000 chars preview/start)
            truncated_markdown = markdown[:12000]

            prompt = (
                "Extrae los datos estructurados clave de la siguiente póliza de seguro boliviana en formato JSON. "
                "Incluye coberturas, sumas aseguradas, vigencia, número de póliza, asegurado y condiciones principales."
            )
            if company_sigla:
                prompt += f" La empresa aseguradora corresponde a la sigla '{company_sigla}'."

            completion = client.beta.chat.completions.parse(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": truncated_markdown},
                ],
                response_format=PolicyStructuredSchema,
                temperature=0.0,
            )

            parsed_data = completion.choices[0].message.parsed
            if parsed_data is None:
                logger.warning("OpenAI parsed message is None. Using fallback dict.")
                return self._build_fallback_dict(company_sigla)

            result_dict = parsed_data.model_dump()


            if company_sigla and not result_dict.get("sigla_empresa"):
                result_dict["sigla_empresa"] = company_sigla.upper()

            logger.info(
                "Structured JSON extraction succeeded via gpt-4o",
                coberturas_count=len(result_dict.get("coberturas", [])),
                sigla=result_dict.get("sigla_empresa"),
            )
            return result_dict

        except Exception as e:
            logger.error("OpenAI structured extraction failed. Using fallback dict.", error=str(e))
            return self._build_fallback_dict(company_sigla)

    def _build_fallback_dict(self, company_sigla: str | None) -> dict[str, Any]:
        """Provide a fallback structured data object when OpenAI is unavailable."""
        return {
            "numero_poliza": None,
            "asegurado": None,
            "tomador": None,
            "aseguradora": None,
            "sigla_empresa": company_sigla.upper() if company_sigla else None,
            "vigencia_desde": None,
            "vigencia_hasta": None,
            "moneda": None,
            "prima_total": None,
            "coberturas": [],
            "condiciones_especiales": [],
            "extraction_source": "fallback",
        }
