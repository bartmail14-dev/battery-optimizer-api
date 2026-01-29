"""
===============================================================================
ENERGIEBELASTING CALCULATOR
===============================================================================

Berekent de Nederlandse energiebelasting en ODE voor elektriciteit.

NOTITIE VOOR BART:
In Nederland betaal je over je elektriciteitsverbruik:
1. Energiebelasting (EB) - gaat naar de schatkist
2. ODE (Opslag Duurzame Energie) - financiert duurzame energieprojecten

Beide worden berekend in SCHIJVEN:
- Schijf 1: 0 - 10.000 kWh → hoogste tarief (huishoudens)
- Schijf 2: 10.000 - 50.000 kWh → middel tarief
- Schijf 3: > 50.000 kWh → laagste tarief (grootverbruikers)

Zakelijke klanten krijgen een korting van €825,37/jaar.

De tarieven worden elk jaar aangepast. Dit zijn de 2025 tarieven.
Bron: Belastingdienst / RVO
===============================================================================
"""

from app.models.enrichment import EnergieBelasting
from app.services.data.tax_rates import TaxRates2025


def bereken_energiebelasting(
    verbruik_kwh: float,
    is_zakelijk: bool = True
) -> EnergieBelasting:
    """
    Bereken energiebelasting en ODE op basis van jaarverbruik.

    NOTITIE VOOR BART:
    Deze functie berekent hoeveel belasting je betaalt over je elektriciteit.

    Voorbeeld voor 50.000 kWh zakelijk:
    - Schijf 1: 10.000 kWh × €0.126 = €1.260
    - Schijf 2: 40.000 kWh × €0.054 = €2.160
    - Zakelijke korting: -€825
    - Energiebelasting totaal: €2.595

    Plus ODE (zelfde schijven) erbij = totale heffingen.

    Args:
        verbruik_kwh: Jaarlijks elektriciteitsverbruik in kWh
        is_zakelijk: True voor zakelijke aansluiting, False voor particulier

    Returns:
        EnergieBelasting: Object met complete belastingberekening
    """
    rates = TaxRates2025

    # =========================================================================
    # STAP 1: Verdeel verbruik over de schijven
    # =========================================================================
    # NOTITIE VOOR BART:
    # We verdelen het verbruik over 3 schijven met elk een eigen tarief.
    # Voorbeeld: 75.000 kWh wordt:
    # - Schijf 1: 10.000 kWh (de eerste 10k)
    # - Schijf 2: 40.000 kWh (van 10k tot 50k)
    # - Schijf 3: 25.000 kWh (alles boven 50k)

    schijf_1 = min(verbruik_kwh, rates.EB_SCHIJF_1_GRENS)
    # Schijf 1 is maximaal 10.000 kWh

    schijf_2 = min(
        max(verbruik_kwh - rates.EB_SCHIJF_1_GRENS, 0),
        rates.EB_SCHIJF_2_GRENS - rates.EB_SCHIJF_1_GRENS
    )
    # Schijf 2 is het deel tussen 10.000 en 50.000 kWh

    schijf_3 = max(verbruik_kwh - rates.EB_SCHIJF_2_GRENS, 0)
    # Schijf 3 is alles boven 50.000 kWh

    # =========================================================================
    # STAP 2: Bereken energiebelasting
    # =========================================================================
    # NOTITIE VOOR BART:
    # Elke schijf × eigen tarief, dan optellen
    eb_totaal = (
        schijf_1 * rates.EB_TARIEF_1 +  # Hoogste tarief
        schijf_2 * rates.EB_TARIEF_2 +  # Middel tarief
        schijf_3 * rates.EB_TARIEF_3    # Laagste tarief
    )

    # =========================================================================
    # STAP 3: Zakelijke korting toepassen
    # =========================================================================
    # NOTITIE VOOR BART:
    # Zakelijke klanten met >10.000 kWh krijgen een vaste korting.
    # Dit is een belastingteruggave die je moet aanvragen bij de Belastingdienst.
    if is_zakelijk and verbruik_kwh > rates.EB_SCHIJF_1_GRENS:
        eb_totaal = max(0, eb_totaal - rates.ZAKELIJK_KORTING)

    # =========================================================================
    # STAP 4: Bereken ODE (Opslag Duurzame Energie)
    # =========================================================================
    # NOTITIE VOOR BART:
    # ODE heeft dezelfde schijven als energiebelasting, maar andere tarieven.
    # ODE financiert subsidies voor duurzame energie (zonnepanelen, windmolens).
    ode_totaal = (
        schijf_1 * rates.ODE_TARIEF_1 +
        schijf_2 * rates.ODE_TARIEF_2 +
        schijf_3 * rates.ODE_TARIEF_3
    )

    # =========================================================================
    # STAP 5: Totalen berekenen
    # =========================================================================
    totaal = eb_totaal + ode_totaal
    effectief = totaal / verbruik_kwh if verbruik_kwh > 0 else 0
    # Effectief tarief = gemiddelde prijs per kWh na alle schijven

    return EnergieBelasting(
        verbruik_kwh=verbruik_kwh,
        schijf_1_kwh=schijf_1,
        schijf_2_kwh=schijf_2,
        schijf_3_kwh=schijf_3,
        eb_tarief_1=rates.EB_TARIEF_1,
        eb_tarief_2=rates.EB_TARIEF_2,
        eb_tarief_3=rates.EB_TARIEF_3,
        energiebelasting_totaal=round(eb_totaal, 2),
        ode_totaal=round(ode_totaal, 2),
        totaal_heffingen=round(totaal, 2),
        effectief_tarief_kwh=round(effectief, 5)
    )
