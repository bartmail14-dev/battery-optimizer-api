"""
===============================================================================
FASE 6: DECISION READINESS CHECK
===============================================================================

De centrale vraag:
"Kan een consultant op basis van deze output een investeringsbeslissing van
€100.000 - €1.000.000+ verantwoorden tegenover een klant, directie, of financier?"

Dit script analyseert of de tool output compleet genoeg is voor professionele
investeringsbeslissingen.

Run: python validation/decision_readiness.py
===============================================================================
"""

import sys
from datetime import datetime
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


class ReadinessStatus(Enum):
    READY = "READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"


class FieldStatus(Enum):
    PRESENT = "AANWEZIG"
    PARTIAL = "DEELS"
    MISSING = "ONTBREEKT"


@dataclass
class FieldCheck:
    """Check resultaat voor een specifiek veld."""
    name: str
    category: str
    priority: str  # "MUST_HAVE" or "SHOULD_HAVE"
    status: FieldStatus
    location: str  # Waar in de code/API
    notes: str = ""


@dataclass
class DecisionReadinessReport:
    """Volledig Decision Readiness rapport."""
    status: ReadinessStatus
    timestamp: datetime
    must_have_present: List[FieldCheck] = field(default_factory=list)
    must_have_missing: List[FieldCheck] = field(default_factory=list)
    should_have_present: List[FieldCheck] = field(default_factory=list)
    should_have_missing: List[FieldCheck] = field(default_factory=list)
    disclaimer: str = ""
    recommendations: List[str] = field(default_factory=list)
    workarounds: List[str] = field(default_factory=list)


# =============================================================================
# MUST HAVE CHECKLIST - Tool is ONBRUIKBAAR zonder deze
# =============================================================================
MUST_HAVE_FIELDS = [
    # A. Financiële Onderbouwing
    {
        "name": "CAPEX totaal",
        "category": "Financieel",
        "description": "Totale investeringskosten inclusief installatie",
        "check_location": "ScenarioResult.capex",
        "why_essential": "Basis voor elke investeringsbeslissing"
    },
    {
        "name": "NPV (Netto Contante Waarde)",
        "category": "Financieel",
        "description": "Verdisconteerde waarde van alle cashflows",
        "check_location": "ScenarioResult.npv_p50, npv_p5, npv_p95",
        "why_essential": "Primaire metric voor investeringsbeslissing"
    },
    {
        "name": "IRR (Internal Rate of Return)",
        "category": "Financieel",
        "description": "Intern rendement van de investering",
        "check_location": "ScenarioResult.irr_mean",
        "why_essential": "Vergelijking met alternatieve investeringen en WACC"
    },
    {
        "name": "Terugverdientijd",
        "category": "Financieel",
        "description": "Jaren tot break-even",
        "check_location": "ScenarioResult.payback_p50",
        "why_essential": "Risicobeoordeling en liquiditeitsplanning"
    },
    {
        "name": "Jaarlijkse cashflows",
        "category": "Financieel",
        "description": "Cashflow projectie per jaar (minimaal jaar 1-10)",
        "check_location": "ScenarioResult.yearly_cashflows",
        "why_essential": "Onderbouwing NPV en financieringsplanning"
    },

    # B. Risico-analyse
    {
        "name": "Best/Base/Worst case scenario",
        "category": "Risico",
        "description": "Meerdere scenario's met verschillende aannames",
        "check_location": "npv_p5/p50/p95, payback varianten",
        "why_essential": "Beslisser moet weten wat er gebeurt als aannames niet uitkomen"
    },

    # C. Revenue Stream Transparantie
    {
        "name": "Breakdown revenue streams",
        "category": "Revenue",
        "description": "Bedragen per revenue stream (peak shaving, arbitrage, etc.)",
        "check_location": "revenue_breakdown.streams",
        "why_essential": "Transparantie over waar opbrengsten vandaan komen"
    },
    {
        "name": "Vermelding niet-meegenomen streams",
        "category": "Revenue",
        "description": "Expliciete lijst van wat NIET is berekend",
        "check_location": "UI disclaimer of API metadata",
        "why_essential": "Voorkomt dat klant denkt dat alle mogelijkheden zijn meegenomen"
    },

    # D. Sizing Onderbouwing
    {
        "name": "Onderbouwing sizing aanbeveling",
        "category": "Sizing",
        "description": "Uitleg WAAROM deze batterijgrootte optimaal is",
        "check_location": "sizing_advice.optimal.rationale",
        "why_essential": "Klant moet begrijpen waarom niet groter/kleiner"
    },

    # E. Aannames
    {
        "name": "Gebruikte energietarieven",
        "category": "Aannames",
        "description": "Piek/dal tarieven die zijn gebruikt",
        "check_location": "Zichtbaar in UI of API response",
        "why_essential": "Financier vraagt: waar is dit op gebaseerd?"
    },
    {
        "name": "Gebruikte capaciteitstarieven",
        "category": "Aannames",
        "description": "€/kW/maand die is gebruikt",
        "check_location": "Zichtbaar in UI of API response",
        "why_essential": "Grootste component van besparing"
    },

    # F. Vergelijkbaarheid
    {
        "name": "Baseline zonder batterij",
        "category": "Vergelijking",
        "description": "Kosten/situatie ZONDER batterij als referentie",
        "check_location": "original_peak_kw, baseline costs",
        "why_essential": "Moet kunnen zien wat de verbetering is t.o.v. huidige situatie"
    },
]


# =============================================================================
# SHOULD HAVE CHECKLIST - Tool is BEPERKT bruikbaar zonder deze
# =============================================================================
SHOULD_HAVE_FIELDS = [
    {
        "name": "Gevoeligheidsanalyse (prijs ±20%)",
        "category": "Risico",
        "description": "Impact van prijsveranderingen op NPV",
        "check_location": "sensitivity analysis",
        "why_important": "Energieprijzen fluctueren significant"
    },
    {
        "name": "Monte Carlo P10/P50/P90",
        "category": "Risico",
        "description": "Waarschijnlijkheidsverdeling van uitkomsten",
        "check_location": "Monte Carlo resultaten",
        "why_important": "Kwantificeert onzekerheid"
    },
    {
        "name": "Degradatie berekening",
        "category": "Operationeel",
        "description": "Capaciteitsverlies over levensduur",
        "check_location": "degradation factor",
        "why_important": "Beinvloedt langetermijn opbrengsten"
    },
    {
        "name": "Onderhoudskosten",
        "category": "Operationeel",
        "description": "Jaarlijkse OPEX schatting",
        "check_location": "opex_annual",
        "why_important": "Verlaagt netto cashflow"
    },
    {
        "name": "Break-even energieprijs",
        "category": "Risico",
        "description": "Bij welke prijs wordt NPV = 0?",
        "check_location": "break_even_analysis",
        "why_important": "Risico-indicator voor prijsdalingen"
    },
    {
        "name": "Kans op positieve NPV (%)",
        "category": "Risico",
        "description": "Probability > 0 uit Monte Carlo",
        "check_location": "probability_positive_npv",
        "why_important": "Directe risico-indicator"
    },
    {
        "name": "Discontovoet aanpasbaar",
        "category": "Financieel",
        "description": "Mogelijkheid om WACC aan te passen",
        "check_location": "discount_rate parameter",
        "why_important": "Klanten hebben verschillende kapitaalkosten"
    },
    {
        "name": "Restwaarde batterij",
        "category": "Financieel",
        "description": "Waarde aan einde levensduur",
        "check_location": "residual_value",
        "why_important": "Kan significant zijn voor NPV"
    },
    {
        "name": "Levensduur batterij",
        "category": "Operationeel",
        "description": "Verwachte jaren operationeel",
        "check_location": "battery_lifetime_years",
        "why_important": "Bepaalt cashflow horizon"
    },
    {
        "name": "Round-trip efficiency",
        "category": "Operationeel",
        "description": "Percentage energie dat behouden blijft",
        "check_location": "average_efficiency",
        "why_important": "Beinvloedt alle opbrengstberekeningen"
    },
]


def check_api_response_fields() -> Dict[str, FieldCheck]:
    """
    Analyseer welke velden de huidige API response bevat.
    Gebaseerd op de schemas en stream response.
    """
    # Dit is gebaseerd op analyse van de codebase
    # In een echte implementatie zou dit de API aanroepen

    checks = {}

    # =========================================================================
    # MUST HAVE CHECKS
    # =========================================================================

    # CAPEX - AANWEZIG in ScenarioResult
    checks["CAPEX totaal"] = FieldCheck(
        name="CAPEX totaal",
        category="Financieel",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="ScenarioResult.capex",
        notes="Berekend als capacity_kwh * cost_per_kwh"
    )

    # NPV - AANWEZIG met P5/P50/P95
    checks["NPV (Netto Contante Waarde)"] = FieldCheck(
        name="NPV (Netto Contante Waarde)",
        category="Financieel",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="ScenarioResult.npv_p5, npv_p50, npv_p95",
        notes="Inclusief Monte Carlo percentiles"
    )

    # IRR - DEELS aanwezig (optioneel veld)
    checks["IRR (Internal Rate of Return)"] = FieldCheck(
        name="IRR (Internal Rate of Return)",
        category="Financieel",
        priority="MUST_HAVE",
        status=FieldStatus.PARTIAL,
        location="ScenarioResult.irr_mean (optioneel)",
        notes="Backend berekent, maar niet altijd zichtbaar in frontend"
    )

    # Terugverdientijd - AANWEZIG
    checks["Terugverdientijd"] = FieldCheck(
        name="Terugverdientijd",
        category="Financieel",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="ScenarioResult.payback_p50, payback_p5, payback_p95",
        notes="Met onzekerheidsband"
    )

    # Jaarlijkse cashflows - DEELS (optioneel veld)
    checks["Jaarlijkse cashflows"] = FieldCheck(
        name="Jaarlijkse cashflows",
        category="Financieel",
        priority="MUST_HAVE",
        status=FieldStatus.PARTIAL,
        location="ScenarioResult.yearly_cashflows (optioneel)",
        notes="Backend berekent, frontend toont soms synthetische projectie"
    )

    # Best/Base/Worst case - AANWEZIG via P5/P50/P95
    checks["Best/Base/Worst case scenario"] = FieldCheck(
        name="Best/Base/Worst case scenario",
        category="Risico",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="npv_p5 (worst), npv_p50 (base), npv_p95 (best)",
        notes="Via Monte Carlo percentiles"
    )

    # Revenue breakdown - AANWEZIG
    checks["Breakdown revenue streams"] = FieldCheck(
        name="Breakdown revenue streams",
        category="Revenue",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="revenue_breakdown.streams",
        notes="Per stream: peak_shaving, arbitrage, self_consumption, etc."
    )

    # Niet-meegenomen streams - ONTBREEKT
    checks["Vermelding niet-meegenomen streams"] = FieldCheck(
        name="Vermelding niet-meegenomen streams",
        category="Revenue",
        priority="MUST_HAVE",
        status=FieldStatus.MISSING,
        location="Geen expliciete disclaimer",
        notes="FCR/aFRR status onduidelijk - klant weet niet wat ontbreekt"
    )

    # Sizing onderbouwing - AANWEZIG
    checks["Onderbouwing sizing aanbeveling"] = FieldCheck(
        name="Onderbouwing sizing aanbeveling",
        category="Sizing",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="sizing_advice.optimal.rationale",
        notes="Minimum/Optimaal/Strategisch met rationale"
    )

    # Energietarieven - DEELS (hardcoded defaults)
    checks["Gebruikte energietarieven"] = FieldCheck(
        name="Gebruikte energietarieven",
        category="Aannames",
        priority="MUST_HAVE",
        status=FieldStatus.PARTIAL,
        location="TariffStructure defaults",
        notes="Gebruikt defaults, niet zichtbaar voor eindgebruiker"
    )

    # Capaciteitstarieven - DEELS
    checks["Gebruikte capaciteitstarieven"] = FieldCheck(
        name="Gebruikte capaciteitstarieven",
        category="Aannames",
        priority="MUST_HAVE",
        status=FieldStatus.PARTIAL,
        location="capacity_tariff parameter",
        notes="Instelbaar maar niet prominent getoond"
    )

    # Baseline - AANWEZIG
    checks["Baseline zonder batterij"] = FieldCheck(
        name="Baseline zonder batterij",
        category="Vergelijking",
        priority="MUST_HAVE",
        status=FieldStatus.PRESENT,
        location="original_peak_kw, baseline vergelijking",
        notes="Originele piek en verbruik worden getoond"
    )

    # =========================================================================
    # SHOULD HAVE CHECKS
    # =========================================================================

    checks["Gevoeligheidsanalyse (prijs ±20%)"] = FieldCheck(
        name="Gevoeligheidsanalyse (prijs ±20%)",
        category="Risico",
        priority="SHOULD_HAVE",
        status=FieldStatus.PARTIAL,
        location="sensitivity array (optioneel)",
        notes="Backend berekent, frontend visualisatie niet altijd actief"
    )

    checks["Monte Carlo P10/P50/P90"] = FieldCheck(
        name="Monte Carlo P10/P50/P90",
        category="Risico",
        priority="SHOULD_HAVE",
        status=FieldStatus.PRESENT,
        location="MonteCarloResult percentiles",
        notes="Volledig geimplementeerd"
    )

    checks["Degradatie berekening"] = FieldCheck(
        name="Degradatie berekening",
        category="Operationeel",
        priority="SHOULD_HAVE",
        status=FieldStatus.PRESENT,
        location="DegradationModel",
        notes="C-rate, SoC en temperatuur afhankelijk"
    )

    checks["Onderhoudskosten"] = FieldCheck(
        name="Onderhoudskosten",
        category="Operationeel",
        priority="SHOULD_HAVE",
        status=FieldStatus.MISSING,
        location="Niet geimplementeerd",
        notes="Geen OPEX in NPV berekening"
    )

    checks["Break-even energieprijs"] = FieldCheck(
        name="Break-even energieprijs",
        category="Risico",
        priority="SHOULD_HAVE",
        status=FieldStatus.MISSING,
        location="Niet geimplementeerd",
        notes="Nuttige risico-indicator"
    )

    checks["Kans op positieve NPV (%)"] = FieldCheck(
        name="Kans op positieve NPV (%)",
        category="Risico",
        priority="SHOULD_HAVE",
        status=FieldStatus.PRESENT,
        location="probability_positive_npv",
        notes="Direct uit Monte Carlo"
    )

    checks["Discontovoet aanpasbaar"] = FieldCheck(
        name="Discontovoet aanpasbaar",
        category="Financieel",
        priority="SHOULD_HAVE",
        status=FieldStatus.PARTIAL,
        location="discount_rate parameter",
        notes="Backend ondersteunt, UI niet"
    )

    checks["Restwaarde batterij"] = FieldCheck(
        name="Restwaarde batterij",
        category="Financieel",
        priority="SHOULD_HAVE",
        status=FieldStatus.MISSING,
        location="Niet geimplementeerd",
        notes="Aangenomen 0 na levensduur"
    )

    checks["Levensduur batterij"] = FieldCheck(
        name="Levensduur batterij",
        category="Operationeel",
        priority="SHOULD_HAVE",
        status=FieldStatus.PRESENT,
        location="15 jaar default",
        notes="Hardcoded, niet configureerbaar"
    )

    checks["Round-trip efficiency"] = FieldCheck(
        name="Round-trip efficiency",
        category="Operationeel",
        priority="SHOULD_HAVE",
        status=FieldStatus.PRESENT,
        location="average_efficiency in SimulationSummary",
        notes="Berekend en getoond"
    )

    return checks


def analyze_decision_readiness() -> DecisionReadinessReport:
    """
    Voer volledige decision readiness analyse uit.
    """
    checks = check_api_response_fields()

    # Categoriseer checks
    must_have_present = []
    must_have_missing = []
    should_have_present = []
    should_have_missing = []

    for name, check in checks.items():
        if check.priority == "MUST_HAVE":
            if check.status == FieldStatus.PRESENT:
                must_have_present.append(check)
            elif check.status == FieldStatus.PARTIAL:
                must_have_missing.append(check)  # Deels telt als missing voor MUST HAVE
            else:
                must_have_missing.append(check)
        else:  # SHOULD_HAVE
            if check.status in [FieldStatus.PRESENT, FieldStatus.PARTIAL]:
                should_have_present.append(check)
            else:
                should_have_missing.append(check)

    # Bepaal status
    must_have_missing_count = len(must_have_missing)

    if must_have_missing_count == 0:
        status = ReadinessStatus.READY
    elif must_have_missing_count <= 2:
        status = ReadinessStatus.CONDITIONALLY_READY
    else:
        status = ReadinessStatus.NOT_READY

    # Genereer disclaimer
    if status != ReadinessStatus.READY:
        missing_items = [c.name for c in must_have_missing]
        disclaimer = (
            f"Let op: Deze analyse is indicatief. Voor een volledige investeringsbeslissing "
            f"ontbreken nog: {', '.join(missing_items)}. "
            f"Raadpleeg een COMCAM consultant voor een complete business case."
        )
    else:
        disclaimer = ""

    # Genereer aanbevelingen
    recommendations = []
    if must_have_missing:
        recommendations.append("PRIORITEIT 1: Implementeer ontbrekende MUST HAVE velden:")
        for check in must_have_missing:
            recommendations.append(f"  - {check.name}: {check.notes}")

    if should_have_missing:
        recommendations.append("\nPRIORITEIT 2: Implementeer SHOULD HAVE velden voor betere onderbouwing:")
        for check in should_have_missing:
            recommendations.append(f"  - {check.name}")

    # Genereer workarounds
    workarounds = []
    for check in must_have_missing:
        if "tarief" in check.name.lower():
            workarounds.append(f"- {check.name}: Consultant moet tarieven handmatig documenteren in rapport")
        elif "cashflow" in check.name.lower():
            workarounds.append(f"- {check.name}: Gebruik Excel template voor cashflow projectie")
        elif "stream" in check.name.lower():
            workarounds.append(f"- {check.name}: Voeg handmatig disclaimer toe over FCR/aFRR potentieel")
        else:
            workarounds.append(f"- {check.name}: Handmatig aanvullen door consultant")

    return DecisionReadinessReport(
        status=status,
        timestamp=datetime.now(),
        must_have_present=must_have_present,
        must_have_missing=must_have_missing,
        should_have_present=should_have_present,
        should_have_missing=should_have_missing,
        disclaimer=disclaimer,
        recommendations=recommendations,
        workarounds=workarounds
    )


def generate_markdown_report(report: DecisionReadinessReport) -> str:
    """Genereer Markdown rapport."""

    status_emoji = {
        ReadinessStatus.READY: "[OK] READY",
        ReadinessStatus.CONDITIONALLY_READY: "[WAARSCHUWING] CONDITIONALLY READY",
        ReadinessStatus.NOT_READY: "[KRITIEK] NOT READY"
    }

    status_description = {
        ReadinessStatus.READY: "De tool levert alle essentiële informatie voor professionele investeringsbeslissingen.",
        ReadinessStatus.CONDITIONALLY_READY: "De tool levert de meeste essentiële informatie, maar enkele velden moeten handmatig worden aangevuld.",
        ReadinessStatus.NOT_READY: "De tool mist kritieke informatie en mag niet worden gebruikt voor klantadvisering zonder significante handmatige aanvulling."
    }

    md = f"""# Decision Readiness Report

## Executive Summary

| Item | Waarde |
|------|--------|
| **Status** | **{status_emoji[report.status]}** |
| Datum analyse | {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')} |
| MUST HAVE aanwezig | {len(report.must_have_present)}/{len(report.must_have_present) + len(report.must_have_missing)} |
| SHOULD HAVE aanwezig | {len(report.should_have_present)}/{len(report.should_have_present) + len(report.should_have_missing)} |

{status_description[report.status]}

---

## MUST HAVE Velden - Aanwezig

Deze velden zijn essentieel en aanwezig in de tool output:

| Veld | Categorie | Locatie | Notes |
|------|-----------|---------|-------|
"""

    for check in report.must_have_present:
        md += f"| {check.name} | {check.category} | `{check.location}` | {check.notes} |\n"

    md += """
---

## MUST HAVE Velden - Ontbrekend of Onvolledig

Deze velden zijn essentieel maar ontbreken of zijn onvolledig:

| Veld | Categorie | Status | Waarom Essentieel | Locatie |
|------|-----------|--------|-------------------|---------|
"""

    if report.must_have_missing:
        for check in report.must_have_missing:
            # Find the original field description
            original = next((f for f in MUST_HAVE_FIELDS if f["name"] == check.name), {})
            why = original.get("why_essential", "")
            md += f"| {check.name} | {check.category} | {check.status.value} | {why} | `{check.location}` |\n"
    else:
        md += "| - | - | - | Geen ontbrekende MUST HAVE velden | - |\n"

    md += """
---

## SHOULD HAVE Velden - Aanwezig

| Veld | Categorie | Status | Notes |
|------|-----------|--------|-------|
"""

    for check in report.should_have_present:
        md += f"| {check.name} | {check.category} | {check.status.value} | {check.notes} |\n"

    md += """
---

## SHOULD HAVE Velden - Ontbrekend

| Veld | Categorie | Waarom Belangrijk |
|------|-----------|-------------------|
"""

    if report.should_have_missing:
        for check in report.should_have_missing:
            original = next((f for f in SHOULD_HAVE_FIELDS if f["name"] == check.name), {})
            why = original.get("why_important", "")
            md += f"| {check.name} | {check.category} | {why} |\n"
    else:
        md += "| - | - | Alle SHOULD HAVE velden aanwezig |\n"

    md += """
---

## Risico-beoordeling

"""

    if report.status == ReadinessStatus.NOT_READY:
        md += """**KRITIEK RISICO**

Als een consultant nu een beslissing neemt op basis van deze output, dan:
- Ontbreken essentiële financiële metrics voor verantwoording
- Is de onderbouwing naar klant/directie/financier onvolledig
- Kunnen aannames niet worden gevalideerd
- Is er risico op verkeerde investeringsbeslissingen

**Aanbeveling:** Gebruik de tool NIET voor klantadvisering tot alle MUST HAVE velden zijn geimplementeerd.
"""
    elif report.status == ReadinessStatus.CONDITIONALLY_READY:
        md += """**MATIG RISICO**

Als een consultant nu een beslissing neemt op basis van deze output, dan:
- Zijn de meeste essentiële metrics beschikbaar
- Moeten enkele velden handmatig worden aangevuld
- Is extra documentatie nodig voor volledige onderbouwing

**Aanbeveling:** Gebruik de tool met de bijgevoegde disclaimer en handmatige aanvulling.
"""
    else:
        md += """**LAAG RISICO**

De tool levert alle essentiële informatie voor professionele besluitvorming.
- Alle MUST HAVE velden zijn aanwezig
- Aannames zijn zichtbaar en documenteerbaar
- Output kan worden gebruikt voor klantadvisering

**Aanbeveling:** Tool is gereed voor gebruik met standaard consultatie-begeleiding.
"""

    if report.disclaimer:
        md += f"""
---

## Verplichte Disclaimer voor UI

De volgende disclaimer MOET worden getoond in de gebruikersinterface:

> {report.disclaimer}

"""

    if report.recommendations:
        md += """
---

## Aanbevelingen voor Ontwikkeling

"""
        for rec in report.recommendations:
            md += f"{rec}\n"

    if report.workarounds:
        md += """
---

## Tijdelijke Workarounds voor Consultants

Totdat de ontbrekende velden zijn geimplementeerd:

"""
        for wa in report.workarounds:
            md += f"{wa}\n"

    md += """
---

## Actieplan

"""

    if report.status == ReadinessStatus.NOT_READY:
        md += """### Immediate Actions (voor gebruik):
1. [ ] Implementeer alle ontbrekende MUST HAVE velden
2. [ ] Voer opnieuw Decision Readiness Check uit
3. [ ] Pas aan tot status CONDITIONALLY READY of READY

### Geen gebruik voor klantadvisering tot bovenstaande is afgerond.
"""
    elif report.status == ReadinessStatus.CONDITIONALLY_READY:
        md += """### Voor direct gebruik:
1. [x] Voeg disclaimer toe aan alle outputs
2. [ ] Maak template voor handmatige aanvulling
3. [ ] Train consultants op wat zij moeten toevoegen
4. [ ] Documenteer alle aannames

### Voor verbetering:
1. [ ] Implementeer ontbrekende MUST HAVE velden
2. [ ] Implementeer SHOULD HAVE velden
3. [ ] Voer opnieuw Decision Readiness Check uit
"""
    else:
        md += """### Gereed voor gebruik:
1. [x] Documenteer alle aannames
2. [ ] Maak gebruikershandleiding
3. [ ] Train consultants op interpretatie
4. [ ] Plan review na eerste 5 echte cases
5. [ ] Overweeg SHOULD HAVE velden toe te voegen
"""

    md += f"""
---

*Rapport gegenereerd: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}*
*Battery Optimizer Decision Readiness Check v1.0*
"""

    return md


def run_decision_readiness_check():
    """Main functie voor Decision Readiness Check."""
    print("\n" + "="*70)
    print("FASE 6: DECISION READINESS CHECK")
    print("="*70)
    print("Vraag: Kan een consultant op basis van deze output een")
    print("investeringsbeslissing van EUR 100.000 - EUR 1.000.000+ verantwoorden?")
    print("="*70 + "\n")

    # Analyseer
    print("Analyseren van API response en UI output...")
    report = analyze_decision_readiness()

    # Print summary
    status_text = {
        ReadinessStatus.READY: "[OK] READY - Tool is gereed voor besluitvorming",
        ReadinessStatus.CONDITIONALLY_READY: "[WAARSCHUWING] CONDITIONALLY READY - Gebruik met disclaimer",
        ReadinessStatus.NOT_READY: "[KRITIEK] NOT READY - Niet gebruiken voor klantadvisering"
    }

    print(f"\nStatus: {status_text[report.status]}")
    print(f"\nMUST HAVE velden:")
    print(f"  - Aanwezig: {len(report.must_have_present)}")
    print(f"  - Ontbrekend/Onvolledig: {len(report.must_have_missing)}")

    print(f"\nSHOULD HAVE velden:")
    print(f"  - Aanwezig: {len(report.should_have_present)}")
    print(f"  - Ontbrekend: {len(report.should_have_missing)}")

    if report.must_have_missing:
        print("\nOntbrekende MUST HAVE velden:")
        for check in report.must_have_missing:
            print(f"  - {check.name} ({check.status.value})")

    if report.disclaimer:
        print(f"\nDisclaimer voor UI:")
        print(f"  \"{report.disclaimer}\"")

    # Genereer rapport
    markdown = generate_markdown_report(report)
    report_path = Path("validation/decision_readiness_report.md")
    report_path.write_text(markdown, encoding='utf-8')

    print(f"\n[OK] Rapport opgeslagen: {report_path.absolute()}")
    print("="*70 + "\n")

    return report


if __name__ == "__main__":
    run_decision_readiness_check()
