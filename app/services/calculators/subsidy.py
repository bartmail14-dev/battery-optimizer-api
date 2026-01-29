"""
===============================================================================
SUBSIDIE CALCULATOR - EIA, MIA, ISDE, Flex-e
===============================================================================

Berekent beschikbare subsidies en fiscale voordelen voor batterij-investeringen.

NOTITIE:
Voor een batterij-investering zijn verschillende voordelen beschikbaar:

1. EIA (Energie-investeringsaftrek)
   - 40% van de investering mag je aftrekken van de winst
   - Dit levert VPB-voordeel op (19% of 25.8% van de aftrek)
   - Minimum investering: €2.500
   - Relevant voor zakelijke investeerders

2. MIA (Milieu-investeringsaftrek)
   - Extra aftrek voor milieuvriendelijke investeringen
   - Alleen voor grotere batterijen (>50 kWh)

3. ISDE (Investeringssubsidie Duurzame Energie)
   - Directe subsidie voor particulieren
   - Tot €100/kWh voor kleine batterijen

4. Flex-e subsidie
   - Specifiek voor congestiegebieden
   - Als je batterij gebruikt voor netontlasting

Bron: RVO Energielijst 2025
===============================================================================
"""

from app.models.enrichment import EIAResultaat, SubsidieOverzicht, CongestieStatus


class EIAConfig2025:
    """
    EIA configuratie voor 2025.

    NOTITIE:
    Dit zijn de parameters voor de EIA regeling in 2025.
    Elk jaar worden deze door RVO gepubliceerd in de "Energielijst".
    """
    PERCENTAGE = 0.40       # 40% van investering is aftrekbaar
    MIN_INVESTERING = 2500  # Minimum investering in EUR

    # Relevante codes uit de Energielijst
    CODE_ACCU_PV = "251118"     # Accu gekoppeld aan PV (vereist >15 kWp)
    CODE_DEELMARKT = "260101"  # Accu voor marktdeelname (geen PV-eis)

    # Vennootschapsbelasting tarieven
    VPB_LAAG = 0.19    # 19% voor winst tot €200.000
    VPB_HOOG = 0.258   # 25.8% voor winst boven €200.000


def bereken_eia(
    investering: float,
    heeft_pv: bool = True,
    pv_capaciteit_kwp: float = 0
) -> EIAResultaat:
    """
    Bereken EIA (Energie-investeringsaftrek) voordeel.

    NOTITIE:
    EIA werkt zo:
    1. Je investeert €30.000 in een batterij
    2. Je mag 40% = €12.000 aftrekken van je winst
    3. Over die €12.000 betaal je geen VPB
    4. Bij 25.8% VPB bespaar je €12.000 × 25.8% = €3.096

    Er zijn 2 manieren om EIA te krijgen:
    - Code 251118: Batterij met zonnepanelen (PV >15 kWp vereist)
    - Code 260101: Batterij voor deelname aan energiemarkt (geen PV-eis)

    Args:
        investering: Investeringsbedrag in EUR
        heeft_pv: Of er zonnepanelen aanwezig zijn
        pv_capaciteit_kwp: Capaciteit zonnepanelen in kWp

    Returns:
        EIAResultaat: Eligibility en berekend voordeel
    """
    cfg = EIAConfig2025

    # =========================================================================
    # CHECK: Minimum investering
    # =========================================================================
    # NOTITIE:
    # EIA is alleen beschikbaar voor investeringen vanaf €2.500
    if investering < cfg.MIN_INVESTERING:
        return EIAResultaat(
            eligible=False,
            reden_niet_eligible=f"Investering onder €{cfg.MIN_INVESTERING}",
            investering=investering,
            eia_aftrek=0,
            vpb_voordeel_19pct=0,
            vpb_voordeel_26pct=0,
            effectief_voordeel_pct=0
        )

    # =========================================================================
    # BEREKENING: EIA aftrek en VPB voordeel
    # =========================================================================
    # NOTITIE:
    # Via code 260101 (deelmarkt) is EIA altijd mogelijk voor batterijen.
    # Je hoeft geen zonnepanelen te hebben!

    eia_aftrek = investering * cfg.PERCENTAGE  # 40% is aftrekbaar

    # VPB voordeel hangt af van je VPB-tarief
    vpb_laag = eia_aftrek * cfg.VPB_LAAG    # Bij 19% VPB
    vpb_hoog = eia_aftrek * cfg.VPB_HOOG    # Bij 25.8% VPB

    # Effectief voordeel als percentage van investering
    effectief = ((vpb_laag + vpb_hoog) / 2) / investering

    return EIAResultaat(
        eligible=True,
        investering=investering,
        eia_percentage=cfg.PERCENTAGE,
        eia_aftrek=round(eia_aftrek, 2),
        vpb_voordeel_19pct=round(vpb_laag, 2),
        vpb_voordeel_26pct=round(vpb_hoog, 2),
        effectief_voordeel_pct=round(effectief, 4)
    )


def bereken_subsidies(
    investering: float,
    batterij_kwh: float,
    heeft_pv: bool,
    pv_kwp: float,
    congestie: CongestieStatus,
    is_zakelijk: bool = True
) -> SubsidieOverzicht:
    """
    Bereken alle beschikbare subsidies en fiscale voordelen.

    NOTITIE:
    Deze functie checkt alle mogelijke subsidies:
    - EIA (zakelijk, altijd beschikbaar)
    - MIA (zakelijk, grote batterijen)
    - ISDE (particulier, kleine batterijen)
    - Flex-e (congestiegebieden)

    Args:
        investering: Investeringsbedrag in EUR
        batterij_kwh: Capaciteit batterij in kWh
        heeft_pv: Of er zonnepanelen zijn
        pv_kwp: Capaciteit zonnepanelen in kWp
        congestie: Congestiestatus van het gebied
        is_zakelijk: True voor zakelijk, False voor particulier

    Returns:
        SubsidieOverzicht: Alle beschikbare subsidies
    """
    # =========================================================================
    # EIA berekenen
    # =========================================================================
    eia = bereken_eia(investering, heeft_pv, pv_kwp)

    # =========================================================================
    # MIA (Milieu-investeringsaftrek)
    # =========================================================================
    # NOTITIE:
    # MIA is extra aftrek bovenop EIA voor milieuvriendelijke investeringen.
    # Voor batterijen geldt dit alleen voor grotere systemen (>50 kWh).
    mia_eligible = batterij_kwh >= 50 and is_zakelijk

    # =========================================================================
    # ISDE (Investeringssubsidie Duurzame Energie)
    # =========================================================================
    # NOTITIE:
    # ISDE is een directe subsidie voor PARTICULIEREN.
    # Je krijgt tot €100 per kWh, max €2.000.
    # Alleen voor kleinere batterijen (<20 kWh).
    isde_eligible = not is_zakelijk and batterij_kwh <= 20
    isde_bedrag = min(batterij_kwh * 100, 2000) if isde_eligible else 0

    # =========================================================================
    # Flex-e subsidie
    # =========================================================================
    # NOTITIE:
    # Flex-e is een subsidie voor batterijen in CONGESTIEGEBIEDEN.
    # Als het stroomnet overbelast is, kan je batterij helpen door:
    # - Minder stroom af te nemen tijdens piek
    # - Terug te leveren als er tekort is
    flex_e_eligible = congestie in [
        CongestieStatus.WACHTRIJ,
        CongestieStatus.NIET_BESCHIKBAAR
    ]

    # =========================================================================
    # Totalen berekenen
    # =========================================================================
    totaal_fiscaal = eia.vpb_voordeel_26pct if eia.eligible else 0

    return SubsidieOverzicht(
        eia=eia,
        mia_eligible=mia_eligible,
        isde_eligible=isde_eligible,
        isde_bedrag=isde_bedrag,
        flex_e_eligible=flex_e_eligible,
        totaal_fiscaal_voordeel=round(totaal_fiscaal, 2),
        totaal_subsidies=round(isde_bedrag, 2)
    )
