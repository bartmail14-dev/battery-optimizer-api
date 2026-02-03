"""
===============================================================================
GEMINI AI REVIEWER SERVICE
===============================================================================

AI-gestuurde validatie en contextualisering van batterij-analyses.

Functies:
1. VALIDATIE - Controleert of resultaten realistisch zijn
2. CONTEXT - Voegt marktkennis en nuance toe
3. ADVIES - Schrijft onderbouwde aanbevelingen
4. RISICO's - Identificeert potentiële valkuilen

===============================================================================
"""

import os
import json
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# Load .env file explicitly
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

import google.generativeai as genai
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

GEMINI_MODEL = "gemini-3-pro-preview"  # Gemini 3 Pro - latest model
GEMINI_TIMEOUT = 30  # seconds


# ============================================================================
# OUTPUT SCHEMA
# ============================================================================

class ValidationCheck(BaseModel):
    """Een validatie check resultaat."""
    category: str  # 'data_quality', 'financial', 'technical', 'market'
    status: str  # 'pass', 'warning', 'fail'
    message: str
    details: Optional[str] = None


class RiskFactor(BaseModel):
    """Een geïdentificeerd risico."""
    severity: str  # 'low', 'medium', 'high', 'critical'
    category: str  # 'market', 'technical', 'financial', 'regulatory'
    title: str
    description: str
    mitigation: Optional[str] = None


class Opportunity(BaseModel):
    """Een geïdentificeerde kans."""
    potential: str  # 'low', 'medium', 'high'
    category: str
    title: str
    description: str


class GeminiReviewResult(BaseModel):
    """Volledig review resultaat van Gemini."""

    # Metadata
    reviewed_at: str
    model_used: str
    review_duration_ms: int

    # Validatie
    validation_checks: List[ValidationCheck] = []
    overall_validation: str  # 'valid', 'concerns', 'invalid'

    # Risico's en kansen
    risk_factors: List[RiskFactor] = []
    opportunities: List[Opportunity] = []

    # Analyse
    recommendation_reasoning: str  # Onderbouwing van het advies
    market_context: str  # Relevante marktcontext

    # Executive summary
    executive_summary: str  # Plain language samenvatting
    key_concerns: List[str] = []  # Top 3 zorgen
    key_strengths: List[str] = []  # Top 3 sterke punten

    # Advies
    recommendation: str  # 'strongly_recommend', 'recommend', 'neutral', 'caution', 'advise_against'
    confidence_level: float  # 0-1

    # Error handling
    error: Optional[str] = None


# ============================================================================
# PROMPT TEMPLATE
# ============================================================================

REVIEW_PROMPT = """Je bent een ervaren energie-consultant die batterijopslagprojecten beoordeelt voor grote zakelijke klanten. Je taak is om de Monte Carlo analyse resultaten te valideren en een onderbouwd advies te schrijven.

## ANALYSE RESULTATEN

### Bedrijfsprofiel
- Locatie: {postcode}
- Netbeheerder: {netbeheerder}
- Piekverbruik: {peak_kw:.1f} kW
- Jaarverbruik: {annual_kwh:,.0f} kWh
- Load factor: {load_factor:.1%}

### Optimale Batterij Configuratie
- Capaciteit: {optimal_size_kwh} kWh
- Vermogen: {optimal_power_kw} kW
- Investering: €{capex:,.0f}

### Financiële Resultaten (Monte Carlo, {n_simulations} simulaties)
- NPV (P50): €{npv_p50:,.0f}
- NPV (P5 - worst case): €{npv_p5:,.0f}
- NPV (P95 - best case): €{npv_p95:,.0f}
- Terugverdientijd (P50): {payback_p50:.1f} jaar
- Kans op positieve NPV: {prob_positive:.1%}
- IRR (gemiddeld): {irr_mean:.1%}

### Piekvermindering
- Originele piek: {original_peak_kw:.1f} kW
- Nieuwe piek: {new_peak_kw:.1f} kW
- Reductie: {peak_reduction_kw:.1f} kW ({peak_reduction_pct:.1%})

### Marktdata (Enrichment)
- Capaciteitstarief: €{capacity_tariff:.2f}/kW/maand
- Piek stroomtarief: €{peak_rate:.3f}/kWh
- Dal stroomtarief: €{offpeak_rate:.3f}/kWh
{enrichment_extra}

### Andere Scenario's Geanalyseerd
{other_scenarios}

## INSTRUCTIES

Analyseer deze resultaten en geef een professioneel oordeel. Let op:

1. **VALIDATIE**: Zijn de resultaten realistisch? Check:
   - Is de NPV range plausibel voor deze batterijgrootte?
   - Is de terugverdientijd realistisch (typisch 5-12 jaar)?
   - Is de piekvermindering haalbaar met deze batterij?
   - Klopt de load factor met het type bedrijf?

2. **RISICO'S**: Identificeer potentiële risico's:
   - Marktrisico's (prijsvolatiliteit, tariefwijzigingen)
   - Technische risico's (degradatie, onderhoud)
   - Financiële risico's (kapitaalkosten, subsidies)
   - Regulatorische risico's (netcodes, belastingen)

3. **KANSEN**: Identificeer mogelijke kansen:
   - Additionele revenue streams (FCR, aFRR, GOPACS)
   - Subsidies (EIA, MIA, ISDE)
   - Combinatie met zonnepanelen
   - Toekomstige netcongestie

4. **ADVIES**: Geef een onderbouwde aanbeveling:
   - Is dit een verstandige investering?
   - Welke batterijgrootte is optimaal en waarom?
   - Wat zijn de belangrijkste voorwaarden voor succes?

## OUTPUT FORMAT

Geef je antwoord als JSON in exact dit format:
```json
{{
  "validation_checks": [
    {{"category": "financial", "status": "pass|warning|fail", "message": "...", "details": "..."}}
  ],
  "overall_validation": "valid|concerns|invalid",
  "risk_factors": [
    {{"severity": "low|medium|high|critical", "category": "market|technical|financial|regulatory", "title": "...", "description": "...", "mitigation": "..."}}
  ],
  "opportunities": [
    {{"potential": "low|medium|high", "category": "...", "title": "...", "description": "..."}}
  ],
  "recommendation_reasoning": "Uitgebreide onderbouwing van het advies...",
  "market_context": "Relevante marktcontext en trends...",
  "executive_summary": "Samenvatting in begrijpelijke taal voor de klant...",
  "key_concerns": ["Zorg 1", "Zorg 2", "Zorg 3"],
  "key_strengths": ["Sterk punt 1", "Sterk punt 2", "Sterk punt 3"],
  "recommendation": "strongly_recommend|recommend|neutral|caution|advise_against",
  "confidence_level": 0.85
}}
```

Antwoord ALLEEN met de JSON, geen andere tekst."""


# ============================================================================
# SERVICE CLASS
# ============================================================================

class GeminiReviewerService:
    """
    Service voor AI-gestuurde review van batterij-analyses.

    Gebruikt Google Gemini om:
    1. Resultaten te valideren
    2. Risico's te identificeren
    3. Kansen te signaleren
    4. Onderbouwde adviezen te schrijven
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialiseer de Gemini service.

        Args:
            api_key: Google API key. Als None, wordt GOOGLE_API_KEY env var gebruikt.
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            logger.warning("No Gemini API key configured - AI review will be skipped")
            self.enabled = False
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            self.enabled = True
            logger.info(f"Gemini reviewer initialized with model {GEMINI_MODEL}")

    async def review_analysis(
        self,
        scenarios: List[Dict[str, Any]],
        optimal_size_kwh: float,
        profile_stats: Dict[str, Any],
        enrichment_data: Optional[Dict[str, Any]] = None,
        n_simulations: int = 1000,
        postcode: Optional[str] = None,
    ) -> GeminiReviewResult:
        """
        Review de analyse resultaten met Gemini.

        Args:
            scenarios: Lijst van scenario resultaten
            optimal_size_kwh: Optimale batterijgrootte
            profile_stats: Profiel statistieken
            enrichment_data: Enrichment data (tarieven, netbeheerder, etc.)
            n_simulations: Aantal Monte Carlo simulaties
            postcode: Postcode voor locatie context

        Returns:
            GeminiReviewResult met validatie, risico's, kansen en advies
        """
        start_time = datetime.now()

        # Check if enabled
        if not self.enabled:
            return GeminiReviewResult(
                reviewed_at=datetime.now().isoformat(),
                model_used="none",
                review_duration_ms=0,
                overall_validation="skipped",
                executive_summary="AI review is niet geconfigureerd (geen API key).",
                recommendation="neutral",
                confidence_level=0.0,
                error="No API key configured"
            )

        try:
            # Find optimal scenario
            optimal = next((s for s in scenarios if s.get("size_kwh") == optimal_size_kwh), scenarios[0])

            # Format other scenarios
            other_scenarios_text = "\n".join([
                f"- {s['size_kwh']} kWh: NPV €{s.get('npv_p50', 0):,.0f}, "
                f"Terugverdientijd {s.get('payback_p50', 0):.1f}j, "
                f"Score {s.get('decision_score', 0):.1f}"
                for s in scenarios if s.get("size_kwh") != optimal_size_kwh
            ]) or "Geen andere scenario's"

            # Format enrichment extra data
            enrichment_extra = ""
            if enrichment_data:
                if enrichment_data.get("congestie"):
                    cong = enrichment_data["congestie"]
                    enrichment_extra += f"\n- Congestie status: {cong.get('afname_status', 'onbekend')}"
                    if cong.get("congestiemanagement_actief"):
                        enrichment_extra += " (ACTIEF!)"

                if enrichment_data.get("fcr_prijzen"):
                    fcr = enrichment_data["fcr_prijzen"]
                    enrichment_extra += f"\n- FCR prijs: €{fcr.get('gem_capaciteit_eur_mw_hour', 0):.2f}/MW/uur"

                if enrichment_data.get("subsidies"):
                    subs = enrichment_data["subsidies"]
                    if subs.get("eia", {}).get("eligible"):
                        enrichment_extra += f"\n- EIA subsidie: €{subs['eia'].get('vpb_voordeel_19pct', 0):,.0f} mogelijk"

            # Build prompt
            prompt = REVIEW_PROMPT.format(
                postcode=postcode or "Onbekend",
                netbeheerder=enrichment_data.get("netbeheerder", "Onbekend") if enrichment_data else "Onbekend",
                peak_kw=profile_stats.get("peak_kw", 0),
                annual_kwh=profile_stats.get("annual_kwh", 0),
                load_factor=profile_stats.get("load_factor", 0) or (
                    profile_stats.get("avg_kw", 0) / profile_stats.get("peak_kw", 1)
                    if profile_stats.get("peak_kw", 0) > 0 else 0
                ),
                optimal_size_kwh=optimal_size_kwh,
                optimal_power_kw=optimal_size_kwh / 2,
                capex=optimal.get("capex", 0),
                npv_p50=optimal.get("npv_p50", 0),
                npv_p5=optimal.get("npv_p5", 0),
                npv_p95=optimal.get("npv_p95", 0),
                payback_p50=optimal.get("payback_p50", 0),
                prob_positive=optimal.get("probability_positive_npv", 0),
                irr_mean=optimal.get("irr_mean", 0) or 0,
                original_peak_kw=profile_stats.get("peak_kw", 0),
                new_peak_kw=profile_stats.get("peak_kw", 0) - optimal.get("peak_reduction_kw", 0),
                peak_reduction_kw=optimal.get("peak_reduction_kw", 0),
                peak_reduction_pct=optimal.get("peak_reduction_kw", 0) / max(profile_stats.get("peak_kw", 1), 1),
                capacity_tariff=enrichment_data.get("netbeheer_tarieven", {}).get("capaciteitstarief_kw_maand", 5.0) if enrichment_data else 5.0,
                peak_rate=(enrichment_data.get("commodity_prijzen", {}).get("piek_gemiddelde", 95) / 1000) if enrichment_data else 0.095,
                offpeak_rate=(enrichment_data.get("commodity_prijzen", {}).get("dal_gemiddelde", 65) / 1000) if enrichment_data else 0.065,
                enrichment_extra=enrichment_extra,
                other_scenarios=other_scenarios_text,
                n_simulations=n_simulations,
            )

            logger.info("Sending analysis to Gemini for review...")

            # Call Gemini
            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,  # Lower temperature for more consistent output
                )
            )

            # Parse response
            response_text = response.text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            result_data = json.loads(response_text)

            # Calculate duration
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Build result
            result = GeminiReviewResult(
                reviewed_at=datetime.now().isoformat(),
                model_used=GEMINI_MODEL,
                review_duration_ms=duration_ms,
                validation_checks=[ValidationCheck(**v) for v in result_data.get("validation_checks", [])],
                overall_validation=result_data.get("overall_validation", "unknown"),
                risk_factors=[RiskFactor(**r) for r in result_data.get("risk_factors", [])],
                opportunities=[Opportunity(**o) for o in result_data.get("opportunities", [])],
                recommendation_reasoning=result_data.get("recommendation_reasoning", ""),
                market_context=result_data.get("market_context", ""),
                executive_summary=result_data.get("executive_summary", ""),
                key_concerns=result_data.get("key_concerns", []),
                key_strengths=result_data.get("key_strengths", []),
                recommendation=result_data.get("recommendation", "neutral"),
                confidence_level=result_data.get("confidence_level", 0.5),
            )

            logger.info(
                f"Gemini review completed",
                extra={
                    "duration_ms": duration_ms,
                    "recommendation": result.recommendation,
                    "confidence": result.confidence_level,
                    "validation": result.overall_validation,
                }
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return GeminiReviewResult(
                reviewed_at=datetime.now().isoformat(),
                model_used=GEMINI_MODEL,
                review_duration_ms=duration_ms,
                overall_validation="error",
                executive_summary="Er is een fout opgetreden bij het verwerken van de AI review.",
                recommendation="neutral",
                confidence_level=0.0,
                error=f"JSON parse error: {str(e)}"
            )

        except Exception as e:
            logger.error(f"Gemini review failed: {e}")
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return GeminiReviewResult(
                reviewed_at=datetime.now().isoformat(),
                model_used=GEMINI_MODEL,
                review_duration_ms=duration_ms,
                overall_validation="error",
                executive_summary="Er is een fout opgetreden bij de AI review.",
                recommendation="neutral",
                confidence_level=0.0,
                error=str(e)
            )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_reviewer_instance: Optional[GeminiReviewerService] = None


def get_gemini_reviewer() -> GeminiReviewerService:
    """Get or create the singleton Gemini reviewer instance."""
    global _reviewer_instance
    if _reviewer_instance is None:
        _reviewer_instance = GeminiReviewerService()
    return _reviewer_instance
