"""DocEngine — Application Service: OpenAI Structured Extractor.

Extracts structured JSON data (coberturas, sumas aseguradas, condiciones)
from Markdown using OpenAI gpt-4.1-mini with Structured Outputs (Pydantic).
"""

from __future__ import annotations

import os
import time
from typing import Any

from pydantic import BaseModel, Field

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Output
# ---------------------------------------------------------------------------

class DatosCabeceraSchema(BaseModel):
    numero_poliza: str | None = Field(default=None, description="Texto exacto del número de póliza (CRÍTICO)")
    poliza_anterior: str | None = Field(default=None, description="Número de póliza anterior o renovada")
    asegurado: str | None = Field(default=None, description="Nombre completo de la persona o entidad asegurada (CRÍTICO)")
    documento_identidad: str | None = Field(default=None, description="CI o documento de identidad del asegurado")
    nit: str | None = Field(default=None, description="NIT del asegurado o tomador")
    direccion: str | None = Field(default=None, description="Dirección registrada del asegurado")
    zona: str | None = Field(default=None, description="Zona de ubicación o domicilio")
    barrio_distrito: str | None = Field(default=None, description="Barrio o distrito de ubicación")
    telefono: str | None = Field(default=None, description="Teléfono fijo")
    celular: str | None = Field(default=None, description="Número de celular de contacto")
    email: str | None = Field(default=None, description="Correo electrónico / e-mail")
    actividad_economica: str | None = Field(default=None, description="Actividad o giro económico")
    tomador: str | None = Field(default=None, description="Nombre de quien contrata la póliza")
    aseguradora: str | None = Field(default=None, description="Nombre completo de la compañía de seguros")
    sigla_empresa: str | None = Field(default=None, description="Sigla de la empresa aseguradora (ej. CRI, BIS)")
    vigencia_desde: str | None = Field(default=None, description="Fecha de inicio (DD/MM/AAAA)")
    vigencia_hasta: str | None = Field(default=None, description="Fecha de fin (DD/MM/AAAA)")
    moneda: str | None = Field(default=None, description="Moneda (USD, BOB)")
    prima_total: str | None = Field(default=None, description="Monto total de la prima")


class ObjetoAseguradoSchema(BaseModel):
    tipo_bien: str | None = Field(default=None, description="Tipo de bien asegurado (ej. Camioneta, Automóvil)")
    marca: str | None = Field(default=None, description="Marca del vehículo o bien")
    modelo: str | None = Field(default=None, description="Modelo")
    ano: str | None = Field(default=None, description="Año de fabricación o modelo")
    placa: str | None = Field(default=None, description="Número de placa")
    motor: str | None = Field(default=None, description="Número de motor")
    chasis: str | None = Field(default=None, description="Número de chasis / VIN")
    color: str | None = Field(default=None, description="Color")
    uso_servicio: str | None = Field(default=None, description="Uso o servicio (ej. Particular, Privado)")
    valor_declarado: str | None = Field(default=None, description="Valor o suma asegurada del bien")
    alcance_territorial: str | None = Field(default=None, description="Alcance o delimitación geográfica")


class CoberturaItem(BaseModel):
    nombre: str = Field(description="Descripción o nombre de la cobertura")
    suma_asegurada: str | None = Field(default=None, description="Monto de la suma asegurada")
    deducible: str | None = Field(default=None, description="Condiciones del deducible o franquicia")
    limite: str | None = Field(default=None, description="Límite máximo de indemnización o sublímites")


class PolicyStructuredSchema(BaseModel):
    datos_cabecera: DatosCabeceraSchema
    objeto_asegurado: ObjetoAseguradoSchema | None = None
    coberturas: list[CoberturaItem] = Field(default_factory=list)
    condiciones_especiales: list[str] = Field(default_factory=list)
    sigla_empresa: str | None = None


# ---------------------------------------------------------------------------
# Extractor Class
# ---------------------------------------------------------------------------

class OpenAIStructuredExtractor:
    """Uses gpt-4.1-mini with Pydantic structured outputs to atomize policy data."""

    def __init__(self, model_name: str = "gpt-4.1-mini") -> None:
        self._model_name = model_name

    def _build_system_prompt(self, company_sigla: str | None = None) -> str:
        """Construct extraction system prompt with critical instructions and schema."""
        sigla_instruction = (
            f'5. Ten en cuenta que la empresa aseguradora corresponde a la sigla \'{company_sigla}\', utiliza este dato para el campo "sigla_empresa" si es necesario.\n'
            if company_sigla
            else ""
        )
        return f"""INSTRUCCIONES CRÍTICAS:
1. Extrae únicamente los campos especificados en la estructura JSON a continuación. No agregues claves adicionales.
2. Es de máxima prioridad localizar y extraer con absoluta precisión el "numero_poliza", "poliza_anterior", nombre del "asegurado", "documento_identidad", "direccion", "zona", "barrio_distrito", "celular", "email" (correo electrónico) y datos del objeto/vehículo asegurado. Revisa detenidamente el texto para estos campos.
3. Si un dato específico no se encuentra en el texto, asigna el valor null al campo correspondiente (no inventes ni infieras información que no esté explícita).
4. Devuelve ÚNICAMENTE el objeto JSON, sin texto introductorio, sin explicaciones y sin bloques de código Markdown (```json).
{sigla_instruction}
ESTRUCTURA JSON REQUERIDA:
{{
  "datos_cabecera": {{
    "numero_poliza": "Texto exacto del número de póliza (CRÍTICO)",
    "poliza_anterior": "Número de póliza anterior o renovada (si figura)",
    "asegurado": "Nombre completo de la persona o entidad asegurada (CRÍTICO)",
    "documento_identidad": "CI o documento del asegurado",
    "nit": "NIT del asegurado o tomador",
    "direccion": "Dirección registrada del asegurado",
    "zona": "Zona de ubicación o domicilio",
    "barrio_distrito": "Barrio o distrito de ubicación",
    "telefono": "Teléfono fijo",
    "celular": "Número de celular de contacto",
    "email": "Correo electrónico / e-mail",
    "actividad_economica": "Actividad o giro económico",
    "tomador": "Nombre de quien contrata la póliza (si es distinto al asegurado, sino null)",
    "aseguradora": "Nombre completo de la compañía de seguros",
    "sigla_empresa": "Sigla de la empresa aseguradora",
    "vigencia_desde": "Fecha de inicio (formato DD/MM/AAAA)",
    "vigencia_hasta": "Fecha de fin (formato DD/MM/AAAA)",
    "moneda": "Tipo de moneda (ej. USD, BOB)",
    "prima_total": "Monto total de la prima"
  }},
  "objeto_asegurado": {{
    "tipo_bien": "Tipo de bien (ej. Camioneta, Automóvil)",
    "marca": "Marca",
    "modelo": "Modelo",
    "ano": "Año",
    "placa": "Número de placa",
    "motor": "Número de motor",
    "chasis": "Número de chasis",
    "color": "Color",
    "uso_servicio": "Uso o servicio (ej. Particular, Privado)",
    "valor_declarado": "Valor o suma asegurada del bien",
    "alcance_territorial": "Alcance o delimitación geográfica"
  }},
  "coberturas": [
    {{
      "nombre": "Descripción o nombre de la cobertura",
      "suma_asegurada": "Monto de la suma asegurada",
      "deducible": "Condiciones del deducible o franquicia",
      "limite": "Límite máximo de indemnización o sublímites"
    }}
  ],
  "condiciones_especiales": [
    "Cláusula particular 1",
    "Cláusula particular 2"
  ]
}}"""



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

        t_start = time.perf_counter()
        try:
            from openai import OpenAI  # noqa: PLC0415

            client = OpenAI(api_key=api_key)

            # Limit text length to stay well within context limit (~12,000 chars preview/start)
            truncated_markdown = markdown[:12000]

            prompt = self._build_system_prompt(company_sigla)

            completion = client.beta.chat.completions.parse(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": truncated_markdown},
                ],
                response_format=PolicyStructuredSchema,
                temperature=0.0,
            )

            duration = time.perf_counter() - t_start
            parsed_data = completion.choices[0].message.parsed
            if parsed_data is None:
                logger.warning("OpenAI parsed message is None. Using fallback dict.")
                return self._build_fallback_dict(company_sigla)

            result_dict = parsed_data.model_dump()

            # Capture OpenAI usage statistics
            prompt_tokens = getattr(completion.usage, "prompt_tokens", 0) if hasattr(completion, "usage") and completion.usage else 0
            completion_tokens = getattr(completion.usage, "completion_tokens", 0) if hasattr(completion, "usage") and completion.usage else 0
            total_tokens = getattr(completion.usage, "total_tokens", 0) if hasattr(completion, "usage") and completion.usage else 0
            # GPT-4.1-mini approx pricing: $0.15 / 1M prompt, $0.60 / 1M completion
            estimated_cost = (prompt_tokens * 0.00000015) + (completion_tokens * 0.00000060)

            result_dict["_usage"] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": round(estimated_cost, 6),
                "duration_seconds": round(duration, 3),
            }

            if company_sigla:
                cabecera = result_dict.get("datos_cabecera")
                if isinstance(cabecera, dict) and not cabecera.get("sigla_empresa"):
                    cabecera["sigla_empresa"] = company_sigla.upper()
                if not result_dict.get("sigla_empresa"):
                    result_dict["sigla_empresa"] = company_sigla.upper()

            cabecera_data = result_dict.get("datos_cabecera") if isinstance(result_dict.get("datos_cabecera"), dict) else {}
            sigla_val = cabecera_data.get("sigla_empresa") or result_dict.get("sigla_empresa")

            logger.info(
                "Structured JSON extraction succeeded via gpt-4.1-mini",
                coberturas_count=len(result_dict.get("coberturas", [])),
                sigla=sigla_val,
                numero_poliza=cabecera_data.get("numero_poliza"),
                asegurado=cabecera_data.get("asegurado"),
                total_tokens=total_tokens,
                duration_seconds=round(duration, 3),
            )
            return result_dict

        except Exception as e:
            logger.error("OpenAI structured extraction failed. Using fallback dict.", error=str(e))
            return self._build_fallback_dict(company_sigla)

    def _build_fallback_dict(self, company_sigla: str | None) -> dict[str, Any]:
        """Provide a fallback structured data object when OpenAI is unavailable."""
        sigla = company_sigla.upper() if company_sigla else None
        return {
            "datos_cabecera": {
                "numero_poliza": None,
                "asegurado": None,
                "tomador": None,
                "aseguradora": None,
                "sigla_empresa": sigla,
                "vigencia_desde": None,
                "vigencia_hasta": None,
                "moneda": None,
                "prima_total": None,
            },
            "coberturas": [],
            "condiciones_especiales": [],
            "sigla_empresa": sigla,
            "extraction_source": "fallback",
        }
