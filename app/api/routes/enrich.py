"""API endpoints for data enrichment."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from app.services.enrichment import get_service, EnrichmentService
from app.models.enrichment import EnrichmentResultaat, EnrichmentRequest

router = APIRouter()


@router.post("/enrich", response_model=EnrichmentResultaat)
async def enrich_profile(
    request: EnrichmentRequest,
    service: EnrichmentService = Depends(get_service)
):
    """
    Verrijk energieprofiel met alle externe data.

    Haalt automatisch op:
    - Netbeheertarieven (ACM 2025)
    - Congestiestatus (Netbeheer NL Capaciteitskaart)
    - Day-ahead prijzen (ENTSO-E Transparency Platform)
    - Onbalansprijzen (TenneT)
    - Energiebelasting berekening (Belastingdienst 2025)
    - EIA/subsidie berekening (RVO Energielijst 2025)
    - PV productie schatting (KNMI zondata)

    Args:
        request: EnrichmentRequest with profile data

    Returns:
        EnrichmentResultaat with all enriched data and sources
    """
    try:
        return await service.enrich(
            postcode=request.postcode,
            verbruik_kwh=request.verbruik_kwh,
            teruglevering_kwh=request.teruglevering_kwh,
            piek_kw=request.piek_kw,
            batterij_investering=request.batterij_investering,
            batterij_kwh=request.batterij_kwh,
            pv_kwp=request.pv_kwp,
            is_zakelijk=request.is_zakelijk
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {str(e)}")


@router.get("/enrich/tarieven/{postcode}")
async def get_tarieven_voor_postcode(postcode: str):
    """
    Haal netbeheertarieven op voor een postcode.

    Args:
        postcode: Dutch postal code (4 digits or full)

    Returns:
        Grid operator and ACM regulated tariffs
    """
    from app.services.data.postcode_mapping import get_netbeheerder
    from app.services.data.acm_tarieven import get_tarieven

    netbeheerder = get_netbeheerder(postcode)
    tarieven = get_tarieven(netbeheerder)

    return {
        "postcode": postcode,
        "netbeheerder": netbeheerder,
        "tarieven": tarieven
    }


@router.get("/enrich/belasting")
async def bereken_belasting(
    verbruik_kwh: float,
    is_zakelijk: bool = True
):
    """
    Bereken energiebelasting en ODE.

    Args:
        verbruik_kwh: Annual consumption in kWh
        is_zakelijk: Whether this is a business connection

    Returns:
        Detailed tax breakdown with effective rate
    """
    from app.services.calculators.tax import bereken_energiebelasting

    return bereken_energiebelasting(verbruik_kwh, is_zakelijk)


@router.get("/enrich/eia")
async def bereken_eia_voordeel(
    investering: float,
    heeft_pv: bool = True,
    pv_kwp: float = 0
):
    """
    Bereken EIA fiscaal voordeel.

    Args:
        investering: Investment amount in EUR
        heeft_pv: Whether PV installation is present
        pv_kwp: PV capacity in kWp

    Returns:
        EIA eligibility and tax benefit calculation
    """
    from app.services.calculators.subsidy import bereken_eia

    return bereken_eia(investering, heeft_pv, pv_kwp)


@router.get("/enrich/pv-schatting")
async def schat_pv(
    postcode: str,
    teruglevering_kwh: float,
    orientatie: str = "zuid",
    hellingshoek: int = 35
):
    """
    Schat PV capaciteit en productie.

    Args:
        postcode: Dutch postal code
        teruglevering_kwh: Annual feed-in in kWh
        orientatie: Panel orientation
        hellingshoek: Panel tilt angle

    Returns:
        Estimated PV capacity and monthly production distribution
    """
    from app.services.clients.knmi import schat_pv_productie

    return schat_pv_productie(postcode, teruglevering_kwh, orientatie, hellingshoek)
