"""Grid cost calculator based on ACM tariffs."""

from app.models.enrichment import NetbeheerTarieven


def bereken_netkosten(
    tarieven: NetbeheerTarieven,
    verbruik_kwh: float,
    piek_kw: float,
    gecontracteerd_kw: float = 0
) -> float:
    """
    Bereken jaarlijkse netbeheerkosten.

    Components:
    - Vastrecht (fixed annual fee)
    - Aansluitdienst (connection service)
    - Meettarief (metering)
    - Capaciteitstarief (contracted capacity)
    - Piekheffing (peak demand charge)
    - Transporttarief (transport per kWh)

    Args:
        tarieven: NetbeheerTarieven for the grid operator
        verbruik_kwh: Annual consumption in kWh
        piek_kw: Peak demand in kW
        gecontracteerd_kw: Contracted capacity in kW (if different from peak)

    Returns:
        Total annual grid costs in EUR
    """
    # Vaste kosten
    vast = (
        tarieven.vastrecht_jaar +
        tarieven.aansluitdienst_jaar +
        tarieven.meettarief_jaar
    )

    # Use contracted capacity or peak, whichever is higher
    effectief_kw = max(piek_kw, gecontracteerd_kw)

    # Capaciteitsafhankelijke kosten
    capaciteit = effectief_kw * tarieven.capaciteitstarief_kw_maand * 12

    # Piekheffing (based on highest monthly peak)
    piekheffing = piek_kw * tarieven.piekheffing_kw_maand * 12

    # Transportkosten
    transport = verbruik_kwh * tarieven.transporttarief_kwh

    return round(vast + capaciteit + piekheffing + transport, 2)


def bereken_netkosten_met_batterij(
    tarieven: NetbeheerTarieven,
    verbruik_kwh: float,
    piek_kw_zonder_batterij: float,
    piek_kw_met_batterij: float,
    gecontracteerd_kw: float = 0
) -> dict:
    """
    Bereken netkosten met en zonder batterij voor vergelijking.

    Args:
        tarieven: NetbeheerTarieven for the grid operator
        verbruik_kwh: Annual consumption in kWh
        piek_kw_zonder_batterij: Peak demand without battery
        piek_kw_met_batterij: Peak demand with battery (peak shaving)
        gecontracteerd_kw: Contracted capacity in kW

    Returns:
        Dictionary with costs comparison and savings
    """
    kosten_zonder = bereken_netkosten(
        tarieven, verbruik_kwh, piek_kw_zonder_batterij, gecontracteerd_kw
    )
    kosten_met = bereken_netkosten(
        tarieven, verbruik_kwh, piek_kw_met_batterij, gecontracteerd_kw
    )

    besparing = kosten_zonder - kosten_met

    return {
        "netkosten_zonder_batterij": kosten_zonder,
        "netkosten_met_batterij": kosten_met,
        "jaarlijkse_besparing": besparing,
        "piekreductie_kw": piek_kw_zonder_batterij - piek_kw_met_batterij,
        "piekreductie_procent": round(
            (1 - piek_kw_met_batterij / piek_kw_zonder_batterij) * 100, 1
        ) if piek_kw_zonder_batterij > 0 else 0
    }
