"""
===============================================================================
FASE 5: GENEREER VALIDATIERAPPORT VOOR COLLEGA'S
===============================================================================

Dit script runt alle validatie fasen en genereert een samenvattend rapport.

Run: python validation/generate_report.py

Output: validation/VALIDATIERAPPORT.md
===============================================================================
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all test modules
from validation.test_calculations import run_all_tests, ValidationResult
from validation.sensitivity_test import run_all_sensitivity_tests, SensitivityResult
from validation.reality_check import run_reality_checks, RealityCheck, CheckStatus
from validation.excel_verification import export_to_excel
from validation.decision_readiness import run_decision_readiness_check, ReadinessStatus


def run_full_validation():
    """
    Run alle validatie fasen en genereer compleet rapport.
    """
    # Set UTF-8 encoding for Windows console
    import sys
    import io
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    print("\n" + "="*70)
    print("[VALIDATION] BATTERY OPTIMIZER - VOLLEDIGE VALIDATIE")
    print("="*70)
    print(f"Gestart: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

    results = {
        'timestamp': datetime.now(),
        'fase1': None,
        'fase2': None,
        'fase3': None,
        'fase4': None,
    }

    # FASE 1: Technische tests
    print("\n[FASE] FASE 1: Technische Basisvalidatie...")
    print("-"*50)
    fase1_results = run_all_tests()
    results['fase1'] = fase1_results
    fase1_passed = sum(1 for r in fase1_results if r.passed)
    fase1_total = len(fase1_results)

    # FASE 2: Sensitivity tests
    print("\n[FASE] FASE 2: Logische Validatie...")
    print("-"*50)
    fase2_results = run_all_sensitivity_tests()
    results['fase2'] = fase2_results
    fase2_passed = sum(1 for r in fase2_results if r.passed)
    fase2_total = len(fase2_results)

    # FASE 3: Reality check
    print("\n[FASE] FASE 3: Realisme-check...")
    print("-"*50)
    fase3_results = run_reality_checks()
    results['fase3'] = fase3_results
    fase3_green = sum(1 for r in fase3_results if r.status == CheckStatus.GREEN)
    fase3_orange = sum(1 for r in fase3_results if r.status == CheckStatus.ORANGE)
    fase3_red = sum(1 for r in fase3_results if r.status == CheckStatus.RED)

    # FASE 4: Excel export
    print("\n[FASE] FASE 4: Excel Verificatie...")
    print("-"*50)
    try:
        excel_path = export_to_excel()
        results['fase4'] = str(excel_path)
        fase4_ok = True
    except Exception as e:
        print(f"[ERROR] Excel export gefaald: {e}")
        results['fase4'] = None
        fase4_ok = False

    # FASE 6: Decision Readiness Check
    print("\n[FASE] FASE 6: Decision Readiness Check...")
    print("-"*50)
    fase6_report = run_decision_readiness_check()
    results['fase6'] = fase6_report
    fase6_status = fase6_report.status

    # Generate report
    print("\n[FASE] FASE 5: Genereer Validatierapport...")
    print("-"*50)

    report = generate_markdown_report(results)
    report_path = Path("validation/VALIDATIERAPPORT.md")
    report_path.write_text(report, encoding='utf-8')

    print(f"✅ Rapport opgeslagen: {report_path.absolute()}")

    # Final summary
    print("\n" + "="*70)
    print("[RESULT] VALIDATIE SAMENVATTING")
    print("="*70)
    print(f"  Fase 1 (Technisch):    {fase1_passed}/{fase1_total} tests geslaagd")
    print(f"  Fase 2 (Logisch):      {fase2_passed}/{fase2_total} tests geslaagd")
    print(f"  Fase 3 (Realisme):     {fase3_green} groen, {fase3_orange} oranje, {fase3_red} rood")
    print(f"  Fase 4 (Excel):        {'[OK] Aangemaakt' if fase4_ok else '[ERROR] Gefaald'}")
    print(f"  Fase 6 (Decision):     {fase6_status.value}")

    # Overall verdict
    all_passed = (
        fase1_passed == fase1_total and
        fase2_passed == fase2_total and
        fase3_red == 0 and
        fase4_ok
    )

    mostly_passed = (
        fase1_passed >= fase1_total - 1 and
        fase2_passed >= fase2_total - 1 and
        fase3_red == 0
    )

    print("\n" + "-"*70)
    if all_passed:
        print("✅ CONCLUSIE: GOEDGEKEURD")
        print("   Alle validatie tests geslaagd.")
    elif mostly_passed:
        print("⚠️  CONCLUSIE: VOORWAARDELIJK GOEDGEKEURD")
        print("   De meeste tests geslaagd, review mineure issues.")
    else:
        print("❌ CONCLUSIE: AFGEKEURD")
        print("   Significante issues gevonden - review nodig.")
    print("-"*70)

    print(f"\n[FILE] Volledig rapport: {report_path.absolute()}")
    print("="*70 + "\n")

    return results


def generate_markdown_report(results: dict) -> str:
    """Genereer Markdown validatierapport."""

    fase1 = results['fase1']
    fase2 = results['fase2']
    fase3 = results['fase3']
    fase4 = results['fase4']

    # Calculate totals
    fase1_passed = sum(1 for r in fase1 if r.passed) if fase1 else 0
    fase1_total = len(fase1) if fase1 else 0
    fase2_passed = sum(1 for r in fase2 if r.passed) if fase2 else 0
    fase2_total = len(fase2) if fase2 else 0

    fase3_green = sum(1 for r in fase3 if r.status == CheckStatus.GREEN) if fase3 else 0
    fase3_orange = sum(1 for r in fase3 if r.status == CheckStatus.ORANGE) if fase3 else 0
    fase3_red = sum(1 for r in fase3 if r.status == CheckStatus.RED) if fase3 else 0

    # Determine overall conclusion
    all_passed = (
        fase1_passed == fase1_total and
        fase2_passed == fase2_total and
        fase3_red == 0 and
        fase4 is not None
    )

    mostly_passed = (
        fase1_passed >= fase1_total - 1 and
        fase2_passed >= fase2_total - 1 and
        fase3_red == 0
    )

    if all_passed:
        conclusion = "✅ GOEDGEKEURD"
        conclusion_text = "Alle validatie tests zijn geslaagd. De tool kan worden gebruikt voor eerste indicaties en scenario-vergelijkingen."
    elif mostly_passed:
        conclusion = "⚠️ VOORWAARDELIJK GOEDGEKEURD"
        conclusion_text = "De meeste tests zijn geslaagd. Review de oranje/gefaalde items voordat je de tool inzet voor belangrijke beslissingen."
    else:
        conclusion = "❌ AFGEKEURD"
        conclusion_text = "Significante issues gevonden. De tool moet eerst worden aangepast voordat deze kan worden gebruikt."

    report = f"""# Battery Optimizer - Validatierapport

## 1. Samenvatting

| Item | Waarde |
|------|--------|
| Datum validatie | {results['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} |
| Versie tool | 1.0.0 |
| **Conclusie** | **{conclusion}** |

{conclusion_text}

---

## 2. Technische Tests (Fase 1)

Deze tests valideren de fundamentele correctheid van de berekeningen.

| Test | Status | Resultaat |
|------|--------|-----------|
"""

    for r in fase1:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        report += f"| {r.test_name} | {status} | {r.message} |\n"

    report += f"""
**Totaal: {fase1_passed}/{fase1_total} tests geslaagd**

---

## 3. Logische Tests (Fase 2)

Deze tests valideren of de tool logisch reageert op input-veranderingen.

| Test | Status | Resultaat |
|------|--------|-----------|
"""

    for r in fase2:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        report += f"| {r.test_name} | {status} | {r.message} |\n"

    report += f"""
**Totaal: {fase2_passed}/{fase2_total} tests geslaagd**

---

## 4. Realisme-Check (Fase 3)

Deze checks vergelijken de uitkomsten met industrie-benchmarks.

| Check | Status | Waarde | Bereik | Beoordeling |
|-------|--------|--------|--------|-------------|
"""

    for r in fase3:
        status = r.status.value
        report += f"| {r.check_name} | {status} | {r.value:.1f} {r.unit} | {r.range_min:.0f}-{r.range_max:.0f} | {r.message} |\n"

    report += f"""
**Totaal: {fase3_green} groen, {fase3_orange} oranje, {fase3_red} rood**

---

## 5. Handmatige Verificatie

| Item | Status |
|------|--------|
| Excel steekproef beschikbaar | {"✅ JA" if fase4 else "❌ NEE"} |
| Locatie | {fase4 if fase4 else 'N/A'} |

De Excel bevat:
- 24 uur aan simulatiedata (96 intervallen)
- Alle formules zichtbaar voor verificatie
- Samenvatting van key metrics
- Tarief documentatie

---

## 6. Bekende Beperkingen

De huidige versie van de tool heeft de volgende beperkingen:

| Beperking | Impact | Toekomstige versie |
|-----------|--------|-------------------|
| Geen live marktdata | FCR/aFRR opbrengsten zijn schattingen | v2.0 |
| Vaste efficiency curves | Geen temperatuur/SoC afhankelijke berekening | v1.5 |
| Geen multi-jaar degradatie | NPV over 15 jaar neemt geen capaciteitsverlies mee | v2.0 |
| Geen seizoenspatronen | Zomer/winter variatie niet meegenomen | v1.5 |

---

## 7. Aanbevolen Gebruik

### ✅ Geschikt voor:
- Eerste indicatie van battery business case
- Vergelijking van verschillende batterijgroottes
- Identificatie van peak shaving potentieel
- Gevoeligheidsanalyse (wat als scenario's)

### ❌ NIET geschikt voor:
- Finale investeringsbeslissing zonder expert review
- Exacte terugverdientijd garantie
- Gedetailleerde cashflow projecties
- Contractonderhandelingen met leveranciers

---

## 8. Volgende Stappen

- [ ] Review dit rapport met technisch team
- [ ] Valideer tegen echte case (bijv. Murre project)
- [ ] Implementeer live marktdata integratie
- [ ] Voeg multi-jaar degradatie model toe
- [ ] Valideer met externe auditor

---

## 9. Ondertekening

| Rol | Naam | Datum |
|-----|------|-------|
| Validatie uitgevoerd door | Battery Optimizer Validation Suite | {results['timestamp'].strftime('%Y-%m-%d')} |
| Review door | [NAAM INVULLEN] | [DATUM] |
| Goedkeuring door | [NAAM INVULLEN] | [DATUM] |

---

*Dit rapport is automatisch gegenereerd door de Battery Optimizer Validation Suite.*
*Voor vragen, neem contact op met het ontwikkelteam.*
"""

    return report


if __name__ == "__main__":
    run_full_validation()
