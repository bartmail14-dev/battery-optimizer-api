"""
===============================================================================
MARKET DATA API ENDPOINTS
===============================================================================

API endpoints voor het ophalen van marktdata:
- Day-ahead prijzen (ENTSO-E)
- Onbalansprijzen (TenneT)
- FCR capaciteitsprijzen (TenneT)
- aFRR capaciteits- en energieprijzen (TenneT)
- GOPACS congestiemanagement (Netbeheer NL)

Gebruik:
- GET /market/all - Alle marktdata in één call
- GET /market/day-ahead - Alleen day-ahead prijzen
- GET /market/fcr - Alleen FCR prijzen
- GET /market/afrr - Alleen aFRR prijzen
- GET /market/gopacs - Alleen GOPACS data
- GET /market/revenue-potential - Bereken potentiële revenues voor een batterij
===============================================================================
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from app.services.market_data import get_market_data_service
from app.models.enrichment import (
    MarketDataSummary, MarktPrijzen, OnbalansPrijzen,
    FCRPrijzen, AFRRPrijzen, GOPACSData
)

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class RevenuePotentialRequest(BaseModel):
    """Request model voor revenue potentieel berekening."""
    postcode: Optional[str] = Field(None, description="Postcode voor GOPACS regio")
    battery_kw: float = Field(..., gt=0, description="Batterij vermogen in kW")
    battery_kwh: float = Field(..., gt=0, description="Batterij capaciteit in kWh")
    annual_cycles: int = Field(default=365, ge=100, le=1000, description="Verwacht aantal cycli per jaar")


class RevenuePotentialResponse(BaseModel):
    """Response model voor revenue potentieel."""
    timestamp: datetime
    battery_kw: float
    battery_kwh: float
    revenues: dict
    totaal_conservatief: float
    totaal_gemiddeld: float
    totaal_optimistisch: float
    bronnen: list[str]
    warnings: list[str]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/all", response_model=MarketDataSummary)
async def get_all_market_data(
    postcode: Optional[str] = Query(None, description="Postcode voor GOPACS regio-bepaling"),
    lookback_days: int = Query(365, ge=7, le=730, description="Dagen historie voor prijsstatistieken")
):
    """
    Haal alle marktdata op in één call.

    Retourneert:
    - Day-ahead stroomprijzen (ENTSO-E)
    - Onbalansprijzen (TenneT)
    - FCR capaciteitsprijzen
    - aFRR capaciteits- en energieprijzen
    - GOPACS congestiedata

    Args:
        postcode: Nederlandse postcode (optioneel, voor GOPACS regio)
        lookback_days: Aantal dagen historie (default 365)

    Returns:
        MarketDataSummary met alle marktdata en bronvermelding
    """
    try:
        service = await get_market_data_service()
        return await service.get_all_market_data(
            postcode=postcode,
            lookback_days=lookback_days
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen marktdata: {str(e)}"
        )


@router.get("/day-ahead", response_model=MarktPrijzen)
async def get_day_ahead_prices(
    days: int = Query(365, ge=1, le=730, description="Aantal dagen historie")
):
    """
    Haal day-ahead stroomprijzen op (ENTSO-E).

    Retourneert:
    - Gemiddelde prijs (€/MWh)
    - Min/max prijzen
    - Piek/dal gemiddelden (07:00-21:00 vs 21:00-07:00)
    - Standaarddeviatie

    Args:
        days: Aantal dagen historie

    Returns:
        MarktPrijzen met statistieken
    """
    try:
        service = await get_market_data_service()
        now = datetime.now()
        start = now - timedelta(days=days)
        return await service.get_day_ahead_prices(start, now)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen day-ahead prijzen: {str(e)}"
        )


@router.get("/imbalance", response_model=OnbalansPrijzen)
async def get_imbalance_prices(
    days: int = Query(30, ge=1, le=90, description="Aantal dagen historie")
):
    """
    Haal onbalansprijzen op (TenneT).

    Retourneert:
    - Gemiddelde tekort/overschot prijzen (€/MWh)
    - Maximum tekortprijs
    - Volatiliteitsindex

    Args:
        days: Aantal dagen historie

    Returns:
        OnbalansPrijzen met statistieken
    """
    try:
        service = await get_market_data_service()
        now = datetime.now()
        start = now - timedelta(days=days)
        return await service.get_imbalance_prices(start, now)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen onbalansprijzen: {str(e)}"
        )


@router.get("/fcr", response_model=FCRPrijzen)
async def get_fcr_prices(
    days: int = Query(30, ge=1, le=365, description="Aantal dagen historie")
):
    """
    Haal FCR (Frequency Containment Reserve) prijzen op.

    FCR is primaire frequentieregeling:
    - Activatie binnen 30 seconden bij frequentieafwijking
    - Minimum deelname: 1 MW (pooling via aggregator vanaf 100 kW)
    - Typische prijs: €8-20/MW/uur

    Args:
        days: Aantal dagen historie

    Returns:
        FCRPrijzen met capaciteitsprijzen en veilingresultaten
    """
    try:
        service = await get_market_data_service()
        now = datetime.now()
        start = now - timedelta(days=days)
        return await service.get_fcr_prices(start, now)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen FCR prijzen: {str(e)}"
        )


@router.get("/afrr", response_model=AFRRPrijzen)
async def get_afrr_prices(
    days: int = Query(30, ge=1, le=365, description="Aantal dagen historie")
):
    """
    Haal aFRR (automatic Frequency Restoration Reserve) prijzen op.

    aFRR is secundaire frequentieregeling:
    - Activatie binnen 5-15 minuten
    - Minimum deelname: 1 MW (pooling via aggregator vanaf 100 kW)
    - Capaciteitsprijs + energievergoeding bij activatie

    Args:
        days: Aantal dagen historie

    Returns:
        AFRRPrijzen met capaciteits- en energieprijzen
    """
    try:
        service = await get_market_data_service()
        now = datetime.now()
        start = now - timedelta(days=days)
        return await service.get_afrr_prices(start, now)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen aFRR prijzen: {str(e)}"
        )


@router.get("/gopacs", response_model=GOPACSData)
async def get_gopacs_data(
    postcode: Optional[str] = Query(None, description="Postcode voor regio-bepaling"),
    regio: Optional[str] = Query(None, description="Directe regio specificatie")
):
    """
    Haal GOPACS congestiemanagement data op.

    GOPACS is het platform waar netbeheerders flexibiliteit inkopen:
    - Tarieven: €0.10-0.25/kWh
    - Verwachte uren: ~200/jaar (regio-afhankelijk)
    - Minimum vermogen: 100 kW (via aggregator)

    Regio's met veel congestie:
    - Zeeland (factor 1.5)
    - Noord-Holland Noord (factor 1.4)
    - Groningen/Friesland (factor 1.2-1.3)

    Args:
        postcode: Nederlandse postcode
        regio: Directe regio naam (overschrijft postcode)

    Returns:
        GOPACSData met tarieven en verwachte uren
    """
    try:
        service = await get_market_data_service()
        return await service.get_gopacs_data(postcode=postcode, regio=regio)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij ophalen GOPACS data: {str(e)}"
        )


@router.post("/revenue-potential", response_model=RevenuePotentialResponse)
async def calculate_revenue_potential(request: RevenuePotentialRequest):
    """
    Bereken potentiële revenue streams voor een batterijconfiguratie.

    Berekent potentiële opbrengsten voor:
    - Arbitrage (day-ahead spreads)
    - FCR (primaire frequentieregeling)
    - aFRR (secundaire frequentieregeling)
    - GOPACS (congestiemanagement)
    - Imbalance trading

    Elke stream geeft conservatief/gemiddeld/optimistisch scenario.

    Args:
        request: Batterijconfiguratie en postcode

    Returns:
        Revenue breakdown per stream met totalen
    """
    try:
        service = await get_market_data_service()

        # Haal eerst alle marktdata op
        market_data = await service.get_all_market_data(
            postcode=request.postcode,
            lookback_days=365
        )

        # Bereken revenues
        revenues = service.calculate_potential_revenues(
            market_data=market_data,
            battery_kw=request.battery_kw,
            battery_kwh=request.battery_kwh,
            annual_cycles=request.annual_cycles
        )

        # Bereken totalen
        totaal_cons = sum(
            r.get("conservatief", 0) for r in revenues.values()
            if isinstance(r.get("conservatief"), (int, float))
        )
        totaal_gem = sum(
            r.get("gemiddeld", 0) for r in revenues.values()
            if isinstance(r.get("gemiddeld"), (int, float))
        )
        totaal_opt = sum(
            r.get("optimistisch", 0) for r in revenues.values()
            if isinstance(r.get("optimistisch"), (int, float))
        )

        return RevenuePotentialResponse(
            timestamp=datetime.now(),
            battery_kw=request.battery_kw,
            battery_kwh=request.battery_kwh,
            revenues=revenues,
            totaal_conservatief=round(totaal_cons, 2),
            totaal_gemiddeld=round(totaal_gem, 2),
            totaal_optimistisch=round(totaal_opt, 2),
            bronnen=market_data.bronnen,
            warnings=market_data.warnings
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Fout bij berekenen revenue potentieel: {str(e)}"
        )


@router.get("/health")
async def market_health():
    """
    Health check voor marktdata services.

    Controleert of alle externe APIs bereikbaar zijn.
    """
    service = await get_market_data_service()
    now = datetime.now()
    start = now - timedelta(days=7)

    results = {}

    # Test ENTSO-E
    try:
        await service.get_day_ahead_prices(start, now)
        results["entsoe"] = "ok"
    except Exception as e:
        results["entsoe"] = f"error: {str(e)}"

    # Test TenneT
    try:
        await service.get_imbalance_prices(start, now)
        results["tennet"] = "ok"
    except Exception as e:
        results["tennet"] = f"error: {str(e)}"

    # Test FCR/aFRR
    try:
        await service.get_fcr_prices(start, now)
        results["fcr"] = "ok"
    except Exception as e:
        results["fcr"] = f"error: {str(e)}"

    # Test GOPACS
    try:
        await service.get_gopacs_data()
        results["gopacs"] = "ok"
    except Exception as e:
        results["gopacs"] = f"error: {str(e)}"

    healthy = all(v == "ok" for v in results.values())

    return {
        "status": "healthy" if healthy else "degraded",
        "services": results,
        "timestamp": now.isoformat()
    }
