"""
===============================================================================
REVENUE STREAMS CALCULATOR
===============================================================================

Berekent alle mogelijke inkomstenbronnen voor batterijopslag:

1. PEAK SHAVING - Vermijden van piekvermogen overschrijding
2. SELF-CONSUMPTION - Opslaan van zonne-energie voor later gebruik
3. ARBITRAGE - Koop goedkoop, verkoop duur
4. IMBALANCE - Deelname aan onbalansmarkt
5. GOPACS - Congestiediensten voor netbeheerders
6. FCR - Frequency Containment Reserve (primaire regeling)
7. aFRR - automatic Frequency Restoration Reserve (secundaire regeling)

METHODOLOGIE:
- Elke stream wordt onafhankelijk berekend
- Overlap/kannibalisatie wordt apart geanalyseerd
- Resultaten zijn jaarlijkse waarden

REFERENTIES:
- ENTSO-E: Ancillary services markets
- TenneT: Productspecificaties FCR/aFRR
- ACM: Capaciteitstarieven besluit
===============================================================================
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from .market_params import (
    MarketParams,
    DEFAULT_MARKET_PARAMS,
    get_capacity_tariff,
)


class RevenueStreamType(Enum):
    """Alle beschikbare revenue streams."""
    PEAK_SHAVING = "peak_shaving"
    SELF_CONSUMPTION = "self_consumption"
    ARBITRAGE = "arbitrage"
    IMBALANCE = "imbalance"
    GOPACS = "gopacs"
    FCR = "fcr"
    AFRR = "afrr"


class QualificationStatus(Enum):
    """Kwalificatiestatus voor een revenue stream."""
    QUALIFIED = "qualified"           # Volledig gekwalificeerd
    PARTIAL = "partial"               # Gedeeltelijk (bijv. via aggregator)
    NOT_QUALIFIED = "not_qualified"   # Niet mogelijk


@dataclass
class RevenueStreamResult:
    """Resultaat van één revenue stream berekening."""

    stream_type: RevenueStreamType
    annual_revenue_eur: float
    utilization_hours: float  # Uren per jaar dat deze stream actief is
    capacity_required_kw: float  # Benodigde capaciteit
    qualification_status: QualificationStatus
    confidence_level: float  # 0-1, gebaseerd op databetrouwbaarheid
    methodology: str  # Beschrijving van berekeningsmethode
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Converteer naar dictionary voor JSON serialisatie."""
        return {
            "stream_type": self.stream_type.value,
            "annual_revenue_eur": round(self.annual_revenue_eur, 2),
            "utilization_hours": round(self.utilization_hours, 1),
            "capacity_required_kw": round(self.capacity_required_kw, 1),
            "qualification_status": self.qualification_status.value,
            "confidence_level": round(self.confidence_level, 2),
            "methodology": self.methodology,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


@dataclass
class MultiRevenueResult:
    """Gecombineerd resultaat van alle revenue streams."""

    streams: Dict[RevenueStreamType, RevenueStreamResult]
    total_stacked_revenue: float  # Som van alle streams
    realistic_combined_revenue: float  # Na aftrek overlap
    revenue_at_risk: float  # Overlap/kannibalisatie
    battery_utilization_percent: float  # Totale batterijbenutting
    recommended_streams: List[RevenueStreamType]

    def to_dict(self) -> dict:
        """Converteer naar dictionary voor JSON serialisatie."""
        return {
            "streams": {k.value: v.to_dict() for k, v in self.streams.items()},
            "total_stacked_revenue": round(self.total_stacked_revenue, 2),
            "realistic_combined_revenue": round(self.realistic_combined_revenue, 2),
            "revenue_at_risk": round(self.revenue_at_risk, 2),
            "battery_utilization_percent": round(self.battery_utilization_percent, 1),
            "recommended_streams": [s.value for s in self.recommended_streams],
        }


class RevenueCalculator:
    """
    Hoofdclass voor het berekenen van alle revenue streams.

    Usage:
        calculator = RevenueCalculator(market_params)
        result = calculator.calculate_all(
            profile_df=profile,
            battery_kwh=100,
            battery_kw=50,
            has_solar=True
        )
    """

    def __init__(self, market_params: Optional[MarketParams] = None):
        self.params = market_params or DEFAULT_MARKET_PARAMS

    def calculate_all(
        self,
        profile_df: pd.DataFrame,
        battery_kwh: float,
        battery_kw: float,
        has_solar: bool = False,
        solar_peak_kw: float = 0.0,
        postcode: Optional[str] = None,
        enabled_streams: Optional[List[RevenueStreamType]] = None
    ) -> MultiRevenueResult:
        """
        Bereken alle relevante revenue streams.

        Args:
            profile_df: DataFrame met kolommen 'timestamp', 'afname', 'teruglevering'
            battery_kwh: Batterijcapaciteit in kWh
            battery_kw: Batterijvermogen in kW
            has_solar: Heeft het profiel zonne-energie?
            solar_peak_kw: Piekvermogen van zonne-installatie
            postcode: Nederlandse postcode voor netbeheerder lookup
            enabled_streams: Lijst van te berekenen streams (default: allemaal)

        Returns:
            MultiRevenueResult met alle berekende streams
        """
        if enabled_streams is None:
            enabled_streams = list(RevenueStreamType)

        # Analyseer profiel
        profile_stats = self._analyze_profile(profile_df)

        results: Dict[RevenueStreamType, RevenueStreamResult] = {}

        # Bereken elke stream
        if RevenueStreamType.PEAK_SHAVING in enabled_streams:
            results[RevenueStreamType.PEAK_SHAVING] = self._calculate_peak_shaving(
                profile_stats, battery_kwh, battery_kw, postcode
            )

        if RevenueStreamType.SELF_CONSUMPTION in enabled_streams and has_solar:
            results[RevenueStreamType.SELF_CONSUMPTION] = self._calculate_self_consumption(
                profile_stats, battery_kwh, battery_kw, solar_peak_kw
            )

        if RevenueStreamType.ARBITRAGE in enabled_streams:
            results[RevenueStreamType.ARBITRAGE] = self._calculate_arbitrage(
                profile_stats, battery_kwh, battery_kw
            )

        if RevenueStreamType.IMBALANCE in enabled_streams:
            results[RevenueStreamType.IMBALANCE] = self._calculate_imbalance(
                battery_kwh, battery_kw
            )

        if RevenueStreamType.GOPACS in enabled_streams:
            results[RevenueStreamType.GOPACS] = self._calculate_gopacs(
                battery_kwh, battery_kw, postcode
            )

        if RevenueStreamType.FCR in enabled_streams:
            results[RevenueStreamType.FCR] = self._calculate_fcr(
                battery_kwh, battery_kw
            )

        if RevenueStreamType.AFRR in enabled_streams:
            results[RevenueStreamType.AFRR] = self._calculate_afrr(
                battery_kwh, battery_kw
            )

        # Bereken totalen en overlap
        total_stacked = sum(r.annual_revenue_eur for r in results.values())

        # Bereken realistische combinatie (rekening houdend met overlap)
        realistic, overlap = self._calculate_combined_revenue(results, battery_kwh)

        # Bepaal totale benutting
        total_hours = sum(r.utilization_hours for r in results.values())
        utilization = min(100, (total_hours / 8760) * 100)

        # Bepaal aanbevolen streams
        recommended = self._recommend_streams(results, battery_kw)

        return MultiRevenueResult(
            streams=results,
            total_stacked_revenue=total_stacked,
            realistic_combined_revenue=realistic,
            revenue_at_risk=overlap,
            battery_utilization_percent=utilization,
            recommended_streams=recommended
        )

    def _analyze_profile(self, df: pd.DataFrame) -> dict:
        """Analyseer energieprofiel voor revenue berekeningen."""
        if df.empty:
            return {
                "peak_kw": 0,
                "avg_kw": 0,
                "baseload_kw": 0,
                "total_kwh": 0,
                "teruglevering_kwh": 0,
                "days": 0,
                "has_solar": False,
            }

        interval_hours = 0.25  # 15-minuten intervallen

        afname = df['afname'].fillna(0)
        teruglevering = df.get('teruglevering', pd.Series([0] * len(df))).fillna(0)

        return {
            "peak_kw": afname.max() / interval_hours,
            "avg_kw": afname.mean() / interval_hours,
            "baseload_kw": afname.quantile(0.10) / interval_hours,
            "total_kwh": afname.sum(),
            "teruglevering_kwh": teruglevering.sum(),
            "days": len(df) / 96,  # 96 intervallen per dag
            "has_solar": teruglevering.sum() > 0,
        }

    def _calculate_peak_shaving(
        self,
        stats: dict,
        battery_kwh: float,
        battery_kw: float,
        postcode: Optional[str]
    ) -> RevenueStreamResult:
        """
        Bereken peak shaving opbrengst.

        Methodologie:
        - Bepaal haalbare piekvermindering op basis van batterijvermogen
        - Vermenigvuldig met capaciteitstarief
        - Correctie voor batterij responstijd en beschikbaarheid
        """
        capacity_tariff = get_capacity_tariff(postcode=postcode)

        # Haalbare piekvermindering
        # Beperkt door: batterijvermogen, SoC beschikbaarheid, responstijd
        peak_kw = stats["peak_kw"]
        avg_kw = stats["avg_kw"]

        # Typische piekvermindering is 60-80% van batterijvermogen
        # (niet 100% door SoC beperkingen en timing)
        availability_factor = 0.70
        max_reduction = battery_kw * availability_factor

        # Piekvermindering kan niet meer zijn dan verschil piek-gemiddelde
        achievable_reduction = min(max_reduction, peak_kw - avg_kw)
        achievable_reduction = max(0, achievable_reduction)

        # Jaarlijkse besparing
        annual_savings = achievable_reduction * capacity_tariff * 12

        # Benodigde uren (pieken zijn typisch 2-4 uur per dag, maar niet elke dag)
        utilization_hours = 365 * 2  # Conservatief: 2 uur per dag gemiddeld

        return RevenueStreamResult(
            stream_type=RevenueStreamType.PEAK_SHAVING,
            annual_revenue_eur=annual_savings,
            utilization_hours=utilization_hours,
            capacity_required_kw=achievable_reduction,
            qualification_status=QualificationStatus.QUALIFIED,
            confidence_level=0.85,  # Hoge zekerheid, gebaseerd op tarieven
            methodology="Capaciteitstarief × piekvermindering × 12 maanden",
            assumptions=[
                f"Capaciteitstarief: €{capacity_tariff:.2f}/kW/maand",
                f"Batterij beschikbaarheid: {availability_factor * 100:.0f}%",
                f"Originele piek: {peak_kw:.1f} kW",
            ],
            warnings=[] if achievable_reduction > 0 else [
                "Geen piekvermindering mogelijk (piek ≤ gemiddelde)"
            ]
        )

    def _calculate_self_consumption(
        self,
        stats: dict,
        battery_kwh: float,
        battery_kw: float,
        solar_peak_kw: float
    ) -> RevenueStreamResult:
        """
        Bereken zelfconsumptie opbrengst (PV buffering).

        Methodologie:
        - Bepaal hoeveel teruglevering gebufferd kan worden
        - Vermenigvuldig met spread (inkoop - teruglevering tarief)
        """
        params = self.params.self_consumption

        teruglevering_kwh = stats["teruglevering_kwh"]
        days = stats["days"]

        if teruglevering_kwh <= 0:
            return RevenueStreamResult(
                stream_type=RevenueStreamType.SELF_CONSUMPTION,
                annual_revenue_eur=0,
                utilization_hours=0,
                capacity_required_kw=0,
                qualification_status=QualificationStatus.NOT_QUALIFIED,
                confidence_level=0,
                methodology="Geen zonne-energie in profiel",
                warnings=["Geen teruglevering gedetecteerd"]
            )

        # Annualiseer
        annual_teruglevering = (teruglevering_kwh / days) * 365

        # Hoeveel kan de batterij bufferen?
        # Beperkt door: capaciteit, vermogen, en timing van productie
        daily_buffer_potential = battery_kwh * 0.8  # 80% usable capacity
        annual_buffer_potential = daily_buffer_potential * 365

        # Typisch kan 30-50% van teruglevering gebufferd worden
        # (rest valt buiten batterijtijdvenster of overtreft capaciteit)
        bufferable = min(
            annual_teruglevering * params.typical_buffer_percentage,
            annual_buffer_potential
        )

        # Opbrengst = buffered × spread
        annual_revenue = bufferable * params.spread_kwh

        # Uren (zonne-uren per dag × dagen)
        solar_hours_per_day = 5  # Effectieve uren
        utilization_hours = solar_hours_per_day * 365

        return RevenueStreamResult(
            stream_type=RevenueStreamType.SELF_CONSUMPTION,
            annual_revenue_eur=annual_revenue,
            utilization_hours=utilization_hours,
            capacity_required_kw=battery_kw,
            qualification_status=QualificationStatus.QUALIFIED,
            confidence_level=0.75,
            methodology="Gebufferde kWh × (inkoop - teruglevering tarief)",
            assumptions=[
                f"Jaarlijkse teruglevering: {annual_teruglevering:.0f} kWh",
                f"Bufferpercentage: {params.typical_buffer_percentage * 100:.0f}%",
                f"Spread: €{params.spread_kwh:.2f}/kWh",
            ],
            warnings=[
                "Saldering eindigt in 2027 - spread wordt groter"
            ] if params.saldering_ends_year else []
        )

    def _calculate_arbitrage(
        self,
        stats: dict,
        battery_kwh: float,
        battery_kw: float
    ) -> RevenueStreamResult:
        """
        Bereken arbitrage opbrengst (dag-nacht handel).

        Methodologie:
        - Aantal cycli per dag × batterijcapaciteit × spread × efficiency
        """
        params = self.params.energy

        # Maximaal 1.5 cycli per dag voor arbitrage (conservatief)
        max_cycles_per_day = 1.5

        # Effectieve capaciteit (usable)
        usable_capacity = battery_kwh * 0.8

        # Round-trip efficiency
        efficiency = 0.90

        # Jaarlijkse throughput
        annual_cycles = max_cycles_per_day * 365
        annual_throughput = annual_cycles * usable_capacity

        # Spread (gemiddeld dag-nacht verschil)
        spread = params.day_night_spread

        # Netto opbrengst
        annual_revenue = annual_throughput * spread * efficiency

        # Corrigeer voor dagen waarop arbitrage niet loont
        # (spread te klein, batterij nodig voor andere doelen)
        arbitrage_days_factor = 0.70  # 70% van dagen
        annual_revenue *= arbitrage_days_factor

        return RevenueStreamResult(
            stream_type=RevenueStreamType.ARBITRAGE,
            annual_revenue_eur=annual_revenue,
            utilization_hours=annual_cycles * 2,  # 2 uur per cycle (charge + discharge)
            capacity_required_kw=battery_kw,
            qualification_status=QualificationStatus.QUALIFIED,
            confidence_level=0.60,  # Lagere zekerheid door prijsvolatiliteit
            methodology="Cycli × capaciteit × spread × efficiency",
            assumptions=[
                f"Cycli per dag: {max_cycles_per_day}",
                f"Spread: €{spread:.2f}/kWh",
                f"Efficiency: {efficiency * 100:.0f}%",
                f"Actieve dagen: {arbitrage_days_factor * 100:.0f}%",
            ],
            warnings=[
                "Arbitrage opbrengst is sterk afhankelijk van prijsvolatiliteit"
            ]
        )

    def _calculate_imbalance(
        self,
        battery_kwh: float,
        battery_kw: float
    ) -> RevenueStreamResult:
        """
        Bereken onbalansmarkt opbrengst.

        Methodologie:
        - Beschikbaarheidsvergoeding + activatievergoeding
        - Vereist BRP contract of aggregator
        """
        params = self.params.imbalance

        # Via aggregator beschikbaar
        if battery_kw < 100:
            qualification = QualificationStatus.PARTIAL
            aggregator_fee = 0.20  # 20% voor kleine installaties
        else:
            qualification = QualificationStatus.QUALIFIED
            aggregator_fee = 0.12  # 12% voor grotere installaties

        # Beschikbaarheidsvergoeding
        # Typisch 50% van de tijd beschikbaar voor imbalance
        availability_hours = 8760 * 0.50
        availability_revenue = (battery_kw / 1000) * params.availability_fee_mw_hour * availability_hours

        # Activatievergoeding (zeer variabel)
        # Gemiddeld 100 activaties per jaar, gemiddeld 0.5 uur
        activations_per_year = 100
        avg_activation_hours = 0.5
        avg_energy_per_activation = battery_kwh * 0.3  # 30% DoD per activatie

        activation_revenue = activations_per_year * avg_energy_per_activation * (params.average_price_mwh / 1000)

        total_revenue = (availability_revenue + activation_revenue) * (1 - aggregator_fee)

        return RevenueStreamResult(
            stream_type=RevenueStreamType.IMBALANCE,
            annual_revenue_eur=total_revenue,
            utilization_hours=activations_per_year * avg_activation_hours,
            capacity_required_kw=battery_kw,
            qualification_status=qualification,
            confidence_level=0.50,  # Lage zekerheid door volatiliteit
            methodology="Beschikbaarheid + activatie - aggregator fee",
            assumptions=[
                f"Beschikbaarheid: 50% van tijd",
                f"Activaties per jaar: {activations_per_year}",
                f"Aggregator fee: {aggregator_fee * 100:.0f}%",
            ],
            warnings=[
                "Onbalansmarkt is zeer volatiel",
                "Vereist BRP contract of aggregator",
            ]
        )

    def _calculate_gopacs(
        self,
        battery_kwh: float,
        battery_kw: float,
        postcode: Optional[str]
    ) -> RevenueStreamResult:
        """
        Bereken GOPACS congestiediensten opbrengst.

        Methodologie:
        - Verwachte congestie-uren × beschikbaar vermogen × tarief
        """
        params = self.params.gopacs

        # Bepaal regio factor
        region_factor = 1.0
        if postcode:
            pc_prefix = int(postcode[:2])
            if pc_prefix in range(10, 20):  # Noord-Holland
                region_factor = params.region_factors.get("noord-holland", 1.0)
            elif pc_prefix in range(43, 47):  # Zeeland
                region_factor = params.region_factors.get("zeeland", 1.0)

        # Kwalificatie check
        if battery_kw < params.minimum_capacity_kw:
            return RevenueStreamResult(
                stream_type=RevenueStreamType.GOPACS,
                annual_revenue_eur=0,
                utilization_hours=0,
                capacity_required_kw=params.minimum_capacity_kw,
                qualification_status=QualificationStatus.NOT_QUALIFIED,
                confidence_level=0,
                methodology="Niet gekwalificeerd - minimum 100 kW vereist",
                warnings=[f"Minimum capaciteit: {params.minimum_capacity_kw} kW"]
            )

        # Berekening
        expected_hours = params.expected_hours_per_year * region_factor
        energy_per_event = battery_kwh * 0.5  # Gemiddeld 50% ontlading per event

        annual_revenue = expected_hours * (energy_per_event / (battery_kwh / battery_kw)) * params.congestion_tariff_kwh
        # Vereenvoudigd: uren × kW × tarief
        annual_revenue = expected_hours * battery_kw * params.congestion_tariff_kwh * 0.5

        return RevenueStreamResult(
            stream_type=RevenueStreamType.GOPACS,
            annual_revenue_eur=annual_revenue,
            utilization_hours=expected_hours,
            capacity_required_kw=battery_kw,
            qualification_status=QualificationStatus.QUALIFIED if battery_kw >= 100 else QualificationStatus.PARTIAL,
            confidence_level=0.55,
            methodology="Congestie-uren × vermogen × tarief",
            assumptions=[
                f"Verwachte congestie-uren: {expected_hours:.0f}/jaar",
                f"Regio factor: {region_factor:.1f}",
                f"Tarief: €{params.congestion_tariff_kwh:.2f}/kWh",
            ],
            warnings=[
                "Congestie-uren nemen toe - opbrengst kan stijgen",
                "Afhankelijk van lokale netcondities",
            ]
        )

    def _calculate_fcr(
        self,
        battery_kwh: float,
        battery_kw: float
    ) -> RevenueStreamResult:
        """
        Bereken FCR (Frequency Containment Reserve) opbrengst.

        Methodologie:
        - Capaciteitsprijs × gekwalificeerd vermogen × uren
        - Minimum 1 MW, pooling via aggregator mogelijk
        """
        params = self.params.fcr

        battery_mw = battery_kw / 1000

        # Kwalificatie check
        if battery_mw >= params.minimum_capacity_mw:
            qualification = QualificationStatus.QUALIFIED
            aggregator_fee = 0  # Direct deelname
            qualified_mw = battery_mw
        elif battery_kw >= params.pooling_minimum_kw:
            qualification = QualificationStatus.PARTIAL
            aggregator_fee = params.aggregator_fee_percent / 100
            qualified_mw = battery_mw
        else:
            return RevenueStreamResult(
                stream_type=RevenueStreamType.FCR,
                annual_revenue_eur=0,
                utilization_hours=0,
                capacity_required_kw=params.pooling_minimum_kw,
                qualification_status=QualificationStatus.NOT_QUALIFIED,
                confidence_level=0,
                methodology="Niet gekwalificeerd - minimum 100 kW voor pooling",
                warnings=[f"Minimum voor pooling: {params.pooling_minimum_kw} kW"]
            )

        # FCR vereist symmetrische capaciteit (up & down)
        # Effectief vermogen is dus beperkt
        effective_mw = qualified_mw * 0.5  # 50% voor symmetrie

        # Beschikbaarheidseis vermindert effectieve uren
        effective_hours = 8760 * params.availability_requirement

        # Revenue
        gross_revenue = effective_mw * params.capacity_price_mw_hour * effective_hours
        net_revenue = gross_revenue * (1 - aggregator_fee)

        # Prequalificatie kosten (eerste jaar)
        # We negeren dit in jaarlijkse berekening maar noemen het

        return RevenueStreamResult(
            stream_type=RevenueStreamType.FCR,
            annual_revenue_eur=net_revenue,
            utilization_hours=effective_hours,
            capacity_required_kw=battery_kw,
            qualification_status=qualification,
            confidence_level=0.70,
            methodology="Effectief MW × prijs × beschikbare uren",
            assumptions=[
                f"Capaciteitsprijs: €{params.capacity_price_mw_hour:.2f}/MW/uur",
                f"Beschikbaarheidseis: {params.availability_requirement * 100:.0f}%",
                f"Aggregator fee: {aggregator_fee * 100:.0f}%",
            ],
            warnings=[
                "FCR vereist snelle respons (30 sec)",
                "Prequalificatie nodig (eenmalige kosten ~€5000)",
            ] if qualification == QualificationStatus.PARTIAL else [
                "FCR vereist snelle respons (30 sec)"
            ]
        )

    def _calculate_afrr(
        self,
        battery_kwh: float,
        battery_kw: float
    ) -> RevenueStreamResult:
        """
        Bereken aFRR (automatic Frequency Restoration Reserve) opbrengst.

        Methodologie:
        - Capaciteitsvergoeding + energievergoeding bij activatie
        """
        params = self.params.afrr

        battery_mw = battery_kw / 1000

        # Kwalificatie check (zelfde als FCR)
        if battery_mw >= params.minimum_capacity_mw:
            qualification = QualificationStatus.QUALIFIED
            aggregator_fee = 0
        elif battery_kw >= 100:  # Via aggregator
            qualification = QualificationStatus.PARTIAL
            aggregator_fee = params.aggregator_fee_percent / 100
        else:
            return RevenueStreamResult(
                stream_type=RevenueStreamType.AFRR,
                annual_revenue_eur=0,
                utilization_hours=0,
                capacity_required_kw=100,
                qualification_status=QualificationStatus.NOT_QUALIFIED,
                confidence_level=0,
                methodology="Niet gekwalificeerd - minimum 100 kW",
                warnings=["Minimum voor pooling: 100 kW"]
            )

        effective_mw = battery_mw * 0.5  # Symmetrisch

        # Capaciteitsvergoeding
        availability_hours = 8760 * 0.95  # 95% beschikbaarheid
        capacity_revenue = effective_mw * params.capacity_price_mw_hour * availability_hours

        # Energievergoeding bij activatie
        activation_hours = 8760 * params.activation_probability
        energy_per_activation = battery_kwh * 0.3  # 30% DoD
        energy_revenue = (energy_per_activation * activation_hours / battery_kwh) * battery_kw * (params.energy_price_mwh / 1000)

        # Vereenvoudigd
        energy_revenue = activation_hours * effective_mw * params.energy_price_mwh

        total_revenue = (capacity_revenue + energy_revenue) * (1 - aggregator_fee)

        return RevenueStreamResult(
            stream_type=RevenueStreamType.AFRR,
            annual_revenue_eur=total_revenue,
            utilization_hours=activation_hours,
            capacity_required_kw=battery_kw,
            qualification_status=qualification,
            confidence_level=0.65,
            methodology="Capaciteitsvergoeding + energievergoeding",
            assumptions=[
                f"Capaciteitsprijs: €{params.capacity_price_mw_hour:.2f}/MW/uur",
                f"Activatiekans: {params.activation_probability * 100:.0f}%",
                f"Energieprijs: €{params.energy_price_mwh:.0f}/MWh",
            ],
            warnings=[
                "aFRR energieprijzen zijn zeer volatiel",
            ]
        )

    def _calculate_combined_revenue(
        self,
        results: Dict[RevenueStreamType, RevenueStreamResult],
        battery_kwh: float
    ) -> Tuple[float, float]:
        """
        Bereken realistische gecombineerde opbrengst, rekening houdend met overlap.

        Returns:
            (realistic_revenue, overlap_amount)
        """
        total_stacked = sum(r.annual_revenue_eur for r in results.values())

        if len(results) <= 1:
            return total_stacked, 0

        # Overlap factoren (empirisch)
        # Peak shaving en arbitrage kunnen grotendeels samen
        # FCR en aFRR zijn exclusief
        # GOPACS overlapt met alles

        overlap = 0

        # FCR en aFRR overlap (kies hoogste)
        fcr_rev = results.get(RevenueStreamType.FCR, RevenueStreamResult(
            stream_type=RevenueStreamType.FCR, annual_revenue_eur=0,
            utilization_hours=0, capacity_required_kw=0,
            qualification_status=QualificationStatus.NOT_QUALIFIED,
            confidence_level=0, methodology=""
        )).annual_revenue_eur
        afrr_rev = results.get(RevenueStreamType.AFRR, RevenueStreamResult(
            stream_type=RevenueStreamType.AFRR, annual_revenue_eur=0,
            utilization_hours=0, capacity_required_kw=0,
            qualification_status=QualificationStatus.NOT_QUALIFIED,
            confidence_level=0, methodology=""
        )).annual_revenue_eur

        if fcr_rev > 0 and afrr_rev > 0:
            overlap += min(fcr_rev, afrr_rev) * 0.7  # 70% overlap

        # Peak shaving en self-consumption overlap licht
        ps_rev = results.get(RevenueStreamType.PEAK_SHAVING, RevenueStreamResult(
            stream_type=RevenueStreamType.PEAK_SHAVING, annual_revenue_eur=0,
            utilization_hours=0, capacity_required_kw=0,
            qualification_status=QualificationStatus.NOT_QUALIFIED,
            confidence_level=0, methodology=""
        )).annual_revenue_eur
        sc_rev = results.get(RevenueStreamType.SELF_CONSUMPTION, RevenueStreamResult(
            stream_type=RevenueStreamType.SELF_CONSUMPTION, annual_revenue_eur=0,
            utilization_hours=0, capacity_required_kw=0,
            qualification_status=QualificationStatus.NOT_QUALIFIED,
            confidence_level=0, methodology=""
        )).annual_revenue_eur

        if ps_rev > 0 and sc_rev > 0:
            overlap += min(ps_rev, sc_rev) * 0.2  # 20% overlap

        # GOPACS overlapt met grid services
        gopacs_rev = results.get(RevenueStreamType.GOPACS, RevenueStreamResult(
            stream_type=RevenueStreamType.GOPACS, annual_revenue_eur=0,
            utilization_hours=0, capacity_required_kw=0,
            qualification_status=QualificationStatus.NOT_QUALIFIED,
            confidence_level=0, methodology=""
        )).annual_revenue_eur

        if gopacs_rev > 0 and (fcr_rev > 0 or afrr_rev > 0):
            overlap += gopacs_rev * 0.3  # 30% overlap

        realistic = total_stacked - overlap
        return max(0, realistic), overlap

    def _recommend_streams(
        self,
        results: Dict[RevenueStreamType, RevenueStreamResult],
        battery_kw: float
    ) -> List[RevenueStreamType]:
        """
        Bepaal aanbevolen revenue streams op basis van resultaten.
        """
        recommended = []

        # Sorteer op opbrengst
        sorted_streams = sorted(
            results.items(),
            key=lambda x: x[1].annual_revenue_eur,
            reverse=True
        )

        for stream_type, result in sorted_streams:
            # Alleen aanbevelen als gekwalificeerd en significant
            if result.qualification_status != QualificationStatus.NOT_QUALIFIED:
                if result.annual_revenue_eur > 100:  # Minimum €100/jaar
                    recommended.append(stream_type)

        return recommended[:5]  # Max 5 aanbevelingen
