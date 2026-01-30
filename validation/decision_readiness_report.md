# Decision Readiness Report

## Executive Summary

| Item | Waarde |
|------|--------|
| **Status** | **[KRITIEK] NOT READY** |
| Datum analyse | 2026-01-30 21:32:15 |
| MUST HAVE aanwezig | 7/12 |
| SHOULD HAVE aanwezig | 7/10 |

De tool mist kritieke informatie en mag niet worden gebruikt voor klantadvisering zonder significante handmatige aanvulling.

---

## MUST HAVE Velden - Aanwezig

Deze velden zijn essentieel en aanwezig in de tool output:

| Veld | Categorie | Locatie | Notes |
|------|-----------|---------|-------|
| CAPEX totaal | Financieel | `ScenarioResult.capex` | Berekend als capacity_kwh * cost_per_kwh |
| NPV (Netto Contante Waarde) | Financieel | `ScenarioResult.npv_p5, npv_p50, npv_p95` | Inclusief Monte Carlo percentiles |
| Terugverdientijd | Financieel | `ScenarioResult.payback_p50, payback_p5, payback_p95` | Met onzekerheidsband |
| Best/Base/Worst case scenario | Risico | `npv_p5 (worst), npv_p50 (base), npv_p95 (best)` | Via Monte Carlo percentiles |
| Breakdown revenue streams | Revenue | `revenue_breakdown.streams` | Per stream: peak_shaving, arbitrage, self_consumption, etc. |
| Onderbouwing sizing aanbeveling | Sizing | `sizing_advice.optimal.rationale` | Minimum/Optimaal/Strategisch met rationale |
| Baseline zonder batterij | Vergelijking | `original_peak_kw, baseline vergelijking` | Originele piek en verbruik worden getoond |

---

## MUST HAVE Velden - Ontbrekend of Onvolledig

Deze velden zijn essentieel maar ontbreken of zijn onvolledig:

| Veld | Categorie | Status | Waarom Essentieel | Locatie |
|------|-----------|--------|-------------------|---------|
| IRR (Internal Rate of Return) | Financieel | DEELS | Vergelijking met alternatieve investeringen en WACC | `ScenarioResult.irr_mean (optioneel)` |
| Jaarlijkse cashflows | Financieel | DEELS | Onderbouwing NPV en financieringsplanning | `ScenarioResult.yearly_cashflows (optioneel)` |
| Vermelding niet-meegenomen streams | Revenue | ONTBREEKT | Voorkomt dat klant denkt dat alle mogelijkheden zijn meegenomen | `Geen expliciete disclaimer` |
| Gebruikte energietarieven | Aannames | DEELS | Financier vraagt: waar is dit op gebaseerd? | `TariffStructure defaults` |
| Gebruikte capaciteitstarieven | Aannames | DEELS | Grootste component van besparing | `capacity_tariff parameter` |

---

## SHOULD HAVE Velden - Aanwezig

| Veld | Categorie | Status | Notes |
|------|-----------|--------|-------|
| Gevoeligheidsanalyse (prijs ±20%) | Risico | DEELS | Backend berekent, frontend visualisatie niet altijd actief |
| Monte Carlo P10/P50/P90 | Risico | AANWEZIG | Volledig geimplementeerd |
| Degradatie berekening | Operationeel | AANWEZIG | C-rate, SoC en temperatuur afhankelijk |
| Kans op positieve NPV (%) | Risico | AANWEZIG | Direct uit Monte Carlo |
| Discontovoet aanpasbaar | Financieel | DEELS | Backend ondersteunt, UI niet |
| Levensduur batterij | Operationeel | AANWEZIG | Hardcoded, niet configureerbaar |
| Round-trip efficiency | Operationeel | AANWEZIG | Berekend en getoond |

---

## SHOULD HAVE Velden - Ontbrekend

| Veld | Categorie | Waarom Belangrijk |
|------|-----------|-------------------|
| Onderhoudskosten | Operationeel | Verlaagt netto cashflow |
| Break-even energieprijs | Risico | Risico-indicator voor prijsdalingen |
| Restwaarde batterij | Financieel | Kan significant zijn voor NPV |

---

## Risico-beoordeling

**KRITIEK RISICO**

Als een consultant nu een beslissing neemt op basis van deze output, dan:
- Ontbreken essentiële financiële metrics voor verantwoording
- Is de onderbouwing naar klant/directie/financier onvolledig
- Kunnen aannames niet worden gevalideerd
- Is er risico op verkeerde investeringsbeslissingen

**Aanbeveling:** Gebruik de tool NIET voor klantadvisering tot alle MUST HAVE velden zijn geimplementeerd.

---

## Verplichte Disclaimer voor UI

De volgende disclaimer MOET worden getoond in de gebruikersinterface:

> Let op: Deze analyse is indicatief. Voor een volledige investeringsbeslissing ontbreken nog: IRR (Internal Rate of Return), Jaarlijkse cashflows, Vermelding niet-meegenomen streams, Gebruikte energietarieven, Gebruikte capaciteitstarieven. Raadpleeg een COMCAM consultant voor een complete business case.


---

## Aanbevelingen voor Ontwikkeling

PRIORITEIT 1: Implementeer ontbrekende MUST HAVE velden:
  - IRR (Internal Rate of Return): Backend berekent, maar niet altijd zichtbaar in frontend
  - Jaarlijkse cashflows: Backend berekent, frontend toont soms synthetische projectie
  - Vermelding niet-meegenomen streams: FCR/aFRR status onduidelijk - klant weet niet wat ontbreekt
  - Gebruikte energietarieven: Gebruikt defaults, niet zichtbaar voor eindgebruiker
  - Gebruikte capaciteitstarieven: Instelbaar maar niet prominent getoond

PRIORITEIT 2: Implementeer SHOULD HAVE velden voor betere onderbouwing:
  - Onderhoudskosten
  - Break-even energieprijs
  - Restwaarde batterij

---

## Tijdelijke Workarounds voor Consultants

Totdat de ontbrekende velden zijn geimplementeerd:

- IRR (Internal Rate of Return): Handmatig aanvullen door consultant
- Jaarlijkse cashflows: Gebruik Excel template voor cashflow projectie
- Vermelding niet-meegenomen streams: Voeg handmatig disclaimer toe over FCR/aFRR potentieel
- Gebruikte energietarieven: Handmatig aanvullen door consultant
- Gebruikte capaciteitstarieven: Handmatig aanvullen door consultant

---

## Actieplan

### Immediate Actions (voor gebruik):
1. [ ] Implementeer alle ontbrekende MUST HAVE velden
2. [ ] Voer opnieuw Decision Readiness Check uit
3. [ ] Pas aan tot status CONDITIONALLY READY of READY

### Geen gebruik voor klantadvisering tot bovenstaande is afgerond.

---

*Rapport gegenereerd: 2026-01-30 21:32:15*
*Battery Optimizer Decision Readiness Check v1.0*
