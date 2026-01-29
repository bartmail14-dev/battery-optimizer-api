"""KNMI solar data and PV production estimation."""

from typing import Dict

from app.models.enrichment import PVSchatting

# Gemiddelde zonuren Nederland per maand
ZONUREN_MAAND = {
    1: 62, 2: 85, 3: 125, 4: 175, 5: 215, 6: 210,
    7: 205, 8: 195, 9: 145, 10: 105, 11: 60, 12: 45
}
TOTAAL_ZONUREN = sum(ZONUREN_MAAND.values())  # ~1627

# Specifieke opbrengst per regio (kWh/kWp/jaar)
OPBRENGST_REGIO = {
    "noord": 875,
    "oost": 900,
    "west": 925,
    "zuid": 950,
    "zeeland": 975,
}

# Oriëntatie factoren (bij 35° hellingshoek)
ORIENTATIE_FACTOR = {
    "zuid": 1.00,
    "zuidoost": 0.95,
    "zuidwest": 0.95,
    "oost": 0.85,
    "west": 0.85,
    "noord": 0.60,
}


def get_regio(postcode: str) -> str:
    """
    Bepaal regio uit postcode.

    Args:
        postcode: Dutch postal code

    Returns:
        Region name (noord, oost, west, zuid, zeeland)
    """
    pc_str = "".join(filter(str.isdigit, postcode))[:4]
    if len(pc_str) < 2:
        return "west"

    prefix = int(pc_str[:2])

    if prefix in range(80, 100):
        return "noord"
    elif prefix in range(70, 80):
        return "oost"
    elif prefix in range(10, 40):
        return "west"
    elif prefix in range(43, 47):  # Zeeland
        return "zeeland"
    elif prefix in range(40, 70):
        return "zuid"

    return "west"


def schat_pv_productie(
    postcode: str,
    teruglevering_kwh: float,
    orientatie: str = "zuid",
    hellingshoek: int = 35
) -> PVSchatting:
    """
    Schat PV capaciteit en productie.

    Aanname: teruglevering ≈ 50-60% van totale productie
    (rest wordt direct verbruikt)

    Args:
        postcode: Dutch postal code
        teruglevering_kwh: Annual feed-in in kWh
        orientatie: Panel orientation (zuid, oost, west, etc.)
        hellingshoek: Panel tilt angle in degrees

    Returns:
        PVSchatting with estimated capacity and production
    """
    regio = get_regio(postcode)
    base_opbrengst = OPBRENGST_REGIO.get(regio, 925)

    # Correctiefactor oriëntatie
    orient_factor = ORIENTATIE_FACTOR.get(orientatie.lower(), 0.90)

    # Correctie hellingshoek (optimaal ~35° in NL)
    if 30 <= hellingshoek <= 40:
        helling_factor = 1.0
    elif 15 <= hellingshoek <= 55:
        helling_factor = 0.95
    else:
        helling_factor = 0.85

    specifieke_opbrengst = base_opbrengst * orient_factor * helling_factor

    # Schat totale productie (teruglevering = 55% van productie)
    teruglevering_fractie = 0.55
    geschatte_productie = teruglevering_kwh / teruglevering_fractie

    # Capaciteit
    geschatte_kwp = geschatte_productie / specifieke_opbrengst if specifieke_opbrengst > 0 else 0

    # Maandverdeling
    maandverdeling = {
        m: round(geschatte_productie * (uren / TOTAAL_ZONUREN), 1)
        for m, uren in ZONUREN_MAAND.items()
    }

    return PVSchatting(
        geschatte_capaciteit_kwp=round(geschatte_kwp, 1),
        orientatie=orientatie,
        hellingshoek=hellingshoek,
        specifieke_opbrengst=round(specifieke_opbrengst, 0),
        geschatte_productie_kwh=round(geschatte_productie, 0),
        maandverdeling=maandverdeling
    )
