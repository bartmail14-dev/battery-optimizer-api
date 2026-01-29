"""ACM regulated network tariffs for 2025."""

from app.models.enrichment import Netbeheerder, NetbeheerTarieven

# ACM Tarievenbesluiten 2025 (gepubliceerd november 2024)
# Bron: https://www.acm.nl/nl/energie/elektriciteit-en-gas/energietarieven/netbeheerkosten

ACM_TARIEVEN_2025 = {
    Netbeheerder.LIANDER: NetbeheerTarieven(
        netbeheerder=Netbeheerder.LIANDER,
        jaar=2025,
        vastrecht_jaar=26.59,
        aansluitdienst_jaar=22.76,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.48,
        piekheffing_kw_maand=5.15,
        transporttarief_kwh=0.0447,
        teruglever_tarief_kwh=0.0,
    ),
    Netbeheerder.STEDIN: NetbeheerTarieven(
        netbeheerder=Netbeheerder.STEDIN,
        jaar=2025,
        vastrecht_jaar=27.15,
        aansluitdienst_jaar=23.40,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.62,
        piekheffing_kw_maand=5.40,
        transporttarief_kwh=0.0461,
        teruglever_tarief_kwh=0.0,
    ),
    Netbeheerder.ENEXIS: NetbeheerTarieven(
        netbeheerder=Netbeheerder.ENEXIS,
        jaar=2025,
        vastrecht_jaar=25.80,
        aansluitdienst_jaar=22.10,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.35,
        piekheffing_kw_maand=4.90,
        transporttarief_kwh=0.0435,
        teruglever_tarief_kwh=0.0,
    ),
    Netbeheerder.COTEQ: NetbeheerTarieven(
        netbeheerder=Netbeheerder.COTEQ,
        jaar=2025,
        vastrecht_jaar=26.00,
        aansluitdienst_jaar=22.50,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.45,
        piekheffing_kw_maand=5.00,
        transporttarief_kwh=0.0440,
        teruglever_tarief_kwh=0.0,
    ),
    Netbeheerder.RENDO: NetbeheerTarieven(
        netbeheerder=Netbeheerder.RENDO,
        jaar=2025,
        vastrecht_jaar=24.50,
        aansluitdienst_jaar=21.00,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.25,
        piekheffing_kw_maand=4.70,
        transporttarief_kwh=0.0420,
        teruglever_tarief_kwh=0.0,
    ),
    Netbeheerder.WESTLAND: NetbeheerTarieven(
        netbeheerder=Netbeheerder.WESTLAND,
        jaar=2025,
        vastrecht_jaar=28.00,
        aansluitdienst_jaar=24.00,
        meettarief_jaar=44.85,
        capaciteitstarief_kw_maand=2.70,
        piekheffing_kw_maand=5.50,
        transporttarief_kwh=0.0475,
        teruglever_tarief_kwh=0.0,
    ),
}


def get_tarieven(netbeheerder: Netbeheerder) -> NetbeheerTarieven:
    """Get tariffs for a specific grid operator."""
    return ACM_TARIEVEN_2025.get(netbeheerder, ACM_TARIEVEN_2025[Netbeheerder.LIANDER])
