"""Energy tax rates for 2025 (Netherlands)."""


class TaxRates2025:
    """
    Energiebelasting en ODE tarieven 2025.
    Bron: Belastingdienst / RVO
    """

    # Energiebelasting schijven (€/kWh excl. BTW)
    EB_SCHIJF_1_GRENS = 10_000  # kWh
    EB_SCHIJF_2_GRENS = 50_000  # kWh

    EB_TARIEF_1 = 0.12599  # 0-10.000 kWh
    EB_TARIEF_2 = 0.05430  # 10.000-50.000 kWh
    EB_TARIEF_3 = 0.01404  # >50.000 kWh

    # ODE schijven
    ODE_TARIEF_1 = 0.03220
    ODE_TARIEF_2 = 0.05440
    ODE_TARIEF_3 = 0.01380

    # Zakelijke korting
    ZAKELIJK_KORTING = 825.37  # €/jaar boven 10.000 kWh

    # BTW
    BTW_PERCENTAGE = 0.21
