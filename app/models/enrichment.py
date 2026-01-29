from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum


class Netbeheerder(str, Enum):
    LIANDER = "liander"
    STEDIN = "stedin"
    ENEXIS = "enexis"
    COTEQ = "coteq"
    RENDO = "rendo"
    WESTLAND = "westland"


class CongestieStatus(str, Enum):
    BESCHIKBAAR = "beschikbaar"
    BEPERKT = "beperkt"
    WACHTRIJ = "wachtrij"
    NIET_BESCHIKBAAR = "niet_beschikbaar"


class NetbeheerTarieven(BaseModel):
    netbeheerder: Netbeheerder
    jaar: int = 2025

    # Vaste kosten
    vastrecht_jaar: float
    aansluitdienst_jaar: float
    meettarief_jaar: float

    # Capaciteitsafhankelijk
    capaciteitstarief_kw_maand: float
    piekheffing_kw_maand: float

    # Verbruiksafhankelijk
    transporttarief_kwh: float
    transporttarief_piek_kwh: Optional[float] = None
    transporttarief_dal_kwh: Optional[float] = None
    teruglever_tarief_kwh: float = 0.0


class CongestieInfo(BaseModel):
    postcode: str
    netbeheerder: Netbeheerder
    voedingsgebied: Optional[str] = None

    afname_status: CongestieStatus
    teruglevering_status: CongestieStatus

    wachtrij_afname_mw: Optional[float] = None
    wachtrij_aantal: Optional[int] = None
    beschikbaar_afname_mw: Optional[float] = None

    congestiemanagement_actief: bool = False
    export_beperking: bool = False
    max_export_kw: Optional[float] = None


class MarktPrijzen(BaseModel):
    bron: str
    periode_start: datetime
    periode_eind: datetime

    gemiddelde_eur_mwh: float
    min_eur_mwh: float
    max_eur_mwh: float
    std_dev: float

    piek_gemiddelde: float  # 07:00-21:00
    dal_gemiddelde: float  # 21:00-07:00

    uurprijzen: Optional[List[Dict]] = None


class OnbalansPrijzen(BaseModel):
    bron: str = "TenneT"

    gem_tekort_eur_mwh: float
    gem_overschot_eur_mwh: float
    max_tekort_eur_mwh: float
    volatiliteit_index: float


class EnergieBelasting(BaseModel):
    verbruik_kwh: float

    schijf_1_kwh: float  # 0-10.000
    schijf_2_kwh: float  # 10.000-50.000
    schijf_3_kwh: float  # >50.000

    eb_tarief_1: float
    eb_tarief_2: float
    eb_tarief_3: float

    energiebelasting_totaal: float
    ode_totaal: float
    totaal_heffingen: float
    effectief_tarief_kwh: float


class EIAResultaat(BaseModel):
    eligible: bool
    reden_niet_eligible: Optional[str] = None

    investering: float
    eia_percentage: float = 0.40
    eia_aftrek: float

    vpb_voordeel_19pct: float
    vpb_voordeel_26pct: float
    effectief_voordeel_pct: float


class SubsidieOverzicht(BaseModel):
    eia: EIAResultaat

    mia_eligible: bool = False
    isde_eligible: bool = False
    isde_bedrag: float = 0
    flex_e_eligible: bool = False

    totaal_fiscaal_voordeel: float
    totaal_subsidies: float


class PVSchatting(BaseModel):
    geschatte_capaciteit_kwp: float
    orientatie: str = "zuid"
    hellingshoek: int = 35

    specifieke_opbrengst: float  # kWh/kWp/jaar
    geschatte_productie_kwh: float
    maandverdeling: Dict[int, float]


class EnrichmentResultaat(BaseModel):
    """Volledig verrijkt profiel met alle externe data."""

    postcode: str
    timestamp: datetime

    # Netbeheer
    netbeheerder: Netbeheerder
    netbeheer_tarieven: NetbeheerTarieven
    jaarlijkse_netkosten: float

    # Congestie
    congestie: CongestieInfo

    # Markt
    commodity_prijzen: MarktPrijzen
    onbalans_prijzen: Optional[OnbalansPrijzen] = None

    # Belasting
    energie_belasting: EnergieBelasting

    # Subsidies
    subsidies: SubsidieOverzicht

    # PV (indien teruglevering > 0)
    pv_schatting: Optional[PVSchatting] = None

    # Meta
    data_compleetheid: float  # 0-1
    warnings: List[str] = []
    bronnen: List[str] = []


class EnrichmentRequest(BaseModel):
    """Request model voor enrichment endpoint."""
    postcode: str = Field(..., description="Nederlandse postcode (4 cijfers of volledig)")
    verbruik_kwh: float = Field(..., gt=0, description="Jaarlijks verbruik in kWh")
    teruglevering_kwh: float = Field(default=0, ge=0, description="Jaarlijkse teruglevering in kWh")
    piek_kw: float = Field(default=0, ge=0, description="Piekvermogen in kW")
    batterij_investering: float = Field(default=0, ge=0, description="Batterij investering in EUR")
    batterij_kwh: float = Field(default=0, ge=0, description="Batterij capaciteit in kWh")
    pv_kwp: Optional[float] = Field(default=None, ge=0, description="PV capaciteit in kWp")
    is_zakelijk: bool = Field(default=True, description="Zakelijke aansluiting")
