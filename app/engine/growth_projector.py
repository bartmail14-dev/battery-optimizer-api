"""
===============================================================================
GROWTH SCENARIO PROJECTOR
===============================================================================

Projecteert energieprofielen naar de toekomst onder verschillende groeiscenario's.

Scenario's:
- BASELINE: Geen groei (huidige situatie)
- MODERATE: +25% groei over projectieperiode
- HIGH: +50% groei
- AGGRESSIVE: +100% groei (verdubbeling, bijv. EV-lading, elektrificatie)
- CUSTOM: Gebruiker-gedefinieerde groeipercentages

METHODOLOGIE:
- Lineaire of exponentiële groei van verbruik
- Piekvermogen groeit vaak minder snel dan totaal verbruik
- Profielvorm kan wijzigen (bijv. avondpiek door EV-lading)

REFERENTIES:
- DNV Energy Outlook 2023
- Netbeheer Nederland: Capaciteitsbehoefteprognose
===============================================================================
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


class GrowthScenarioType(Enum):
    """Voorgedefinieerde groeiscenario's."""
    BASELINE = "baseline"
    MODERATE = "moderate"
    HIGH = "high"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


@dataclass
class GrowthScenario:
    """Definitie van een groeiscenario."""

    name: str
    scenario_type: GrowthScenarioType

    # Groeipercentages (totaal over projectieperiode)
    consumption_growth_total: float  # bijv. 0.25 = +25%
    peak_growth_total: float  # Piek groeit vaak minder snel

    # Of als jaarlijkse groei
    consumption_growth_annual: Optional[float] = None
    peak_growth_annual: Optional[float] = None

    # Profielaanpassingen
    profile_peakiness_factor: float = 1.0  # >1 = spitsere pieken
    evening_shift_factor: float = 1.0  # >1 = meer avondverbruik (EV)

    # Metadata
    description: str = ""
    assumptions: List[str] = field(default_factory=list)


# Voorgedefinieerde scenario's
PREDEFINED_SCENARIOS: Dict[GrowthScenarioType, GrowthScenario] = {
    GrowthScenarioType.BASELINE: GrowthScenario(
        name="Baseline",
        scenario_type=GrowthScenarioType.BASELINE,
        consumption_growth_total=0.0,
        peak_growth_total=0.0,
        description="Huidige situatie, geen groei",
        assumptions=["Geen wijzigingen in bedrijfsactiviteit", "Geen extra elektrificatie"]
    ),

    GrowthScenarioType.MODERATE: GrowthScenario(
        name="Gematigde Groei (+25%)",
        scenario_type=GrowthScenarioType.MODERATE,
        consumption_growth_total=0.25,
        peak_growth_total=0.20,  # Piek +20%
        consumption_growth_annual=0.023,  # ~2.3%/jaar voor 10 jaar
        peak_growth_annual=0.018,
        description="Organische groei bedrijfsactiviteit",
        assumptions=[
            "Geleidelijke uitbreiding productie/kantoor",
            "Beperkte elektrificatie",
            "Efficiencyverbeteringen compenseren deels"
        ]
    ),

    GrowthScenarioType.HIGH: GrowthScenario(
        name="Hoge Groei (+50%)",
        scenario_type=GrowthScenarioType.HIGH,
        consumption_growth_total=0.50,
        peak_growth_total=0.40,
        consumption_growth_annual=0.041,  # ~4.1%/jaar
        peak_growth_annual=0.034,
        profile_peakiness_factor=1.1,
        description="Sterke groei met elektrificatie",
        assumptions=[
            "Significante uitbreiding",
            "Elektrificatie processen",
            "Mogelijk warmtepomp/koeling"
        ]
    ),

    GrowthScenarioType.AGGRESSIVE: GrowthScenario(
        name="Verdubbeling (+100%)",
        scenario_type=GrowthScenarioType.AGGRESSIVE,
        consumption_growth_total=1.0,
        peak_growth_total=0.80,  # Piek +80%
        consumption_growth_annual=0.072,  # ~7.2%/jaar
        peak_growth_annual=0.060,
        profile_peakiness_factor=1.2,
        evening_shift_factor=1.3,  # Meer avondpiek (EV)
        description="Volledige elektrificatie + groei",
        assumptions=[
            "EV-vloot met laadinfra",
            "Elektrificatie verwarming",
            "Uitbreiding productiecapaciteit",
            "Nieuwe vestiging/uitbreiding"
        ]
    ),
}


@dataclass
class ProjectedYear:
    """Projectie voor één jaar."""

    year: int
    consumption_kwh: float
    peak_kw: float
    growth_factor_consumption: float  # Cumulatieve groei t.o.v. jaar 0
    growth_factor_peak: float


@dataclass
class GrowthProjectionResult:
    """Resultaat van groeiscenario projectie."""

    scenario: GrowthScenario
    base_year: int
    projection_years: int
    yearly_projections: List[ProjectedYear]

    # Samenvatting
    final_consumption_kwh: float
    final_peak_kw: float
    total_consumption_growth: float
    total_peak_growth: float

    # Geprojecteerd profiel voor eindejaar (optioneel)
    final_profile_df: Optional[pd.DataFrame] = None

    def to_dict(self) -> dict:
        """Converteer naar dictionary voor JSON serialisatie."""
        return {
            "scenario": {
                "name": self.scenario.name,
                "type": self.scenario.scenario_type.value,
                "description": self.scenario.description,
                "assumptions": self.scenario.assumptions,
            },
            "base_year": self.base_year,
            "projection_years": self.projection_years,
            "yearly_projections": [
                {
                    "year": p.year,
                    "consumption_kwh": round(p.consumption_kwh, 0),
                    "peak_kw": round(p.peak_kw, 1),
                    "growth_factor_consumption": round(p.growth_factor_consumption, 3),
                    "growth_factor_peak": round(p.growth_factor_peak, 3),
                }
                for p in self.yearly_projections
            ],
            "summary": {
                "final_consumption_kwh": round(self.final_consumption_kwh, 0),
                "final_peak_kw": round(self.final_peak_kw, 1),
                "total_consumption_growth_percent": round(self.total_consumption_growth * 100, 1),
                "total_peak_growth_percent": round(self.total_peak_growth * 100, 1),
            }
        }


class GrowthProjector:
    """
    Projecteert energieprofielen naar de toekomst.

    Usage:
        projector = GrowthProjector()
        result = projector.project(
            profile_df=profile,
            scenario=PREDEFINED_SCENARIOS[GrowthScenarioType.MODERATE],
            projection_years=10
        )
    """

    def __init__(self, base_year: Optional[int] = None):
        """
        Args:
            base_year: Startjaar voor projectie (default: huidig jaar)
        """
        import datetime
        self.base_year = base_year or datetime.datetime.now().year

    def project(
        self,
        profile_df: pd.DataFrame,
        scenario: GrowthScenario,
        projection_years: int = 10
    ) -> GrowthProjectionResult:
        """
        Projecteer een profiel naar de toekomst.

        Args:
            profile_df: DataFrame met kolommen 'timestamp', 'afname', 'teruglevering'
            scenario: GrowthScenario met groeiparameters
            projection_years: Aantal jaren vooruit te projecteren

        Returns:
            GrowthProjectionResult met jaarlijkse projecties
        """
        # Analyseer basisprofiel
        base_stats = self._analyze_base_profile(profile_df)

        # Bereken jaarlijkse groei
        yearly_projections = self._calculate_yearly_projections(
            base_stats=base_stats,
            scenario=scenario,
            years=projection_years
        )

        # Genereer geprojecteerd profiel voor eindejaar (optioneel)
        final_profile = None
        if len(profile_df) > 0:
            final_year_projection = yearly_projections[-1]
            final_profile = self._scale_profile(
                profile_df=profile_df,
                consumption_factor=final_year_projection.growth_factor_consumption,
                peak_factor=final_year_projection.growth_factor_peak,
                peakiness_factor=scenario.profile_peakiness_factor,
                evening_shift=scenario.evening_shift_factor
            )

        final = yearly_projections[-1]

        return GrowthProjectionResult(
            scenario=scenario,
            base_year=self.base_year,
            projection_years=projection_years,
            yearly_projections=yearly_projections,
            final_consumption_kwh=final.consumption_kwh,
            final_peak_kw=final.peak_kw,
            total_consumption_growth=final.growth_factor_consumption - 1,
            total_peak_growth=final.growth_factor_peak - 1,
            final_profile_df=final_profile
        )

    def project_multiple_scenarios(
        self,
        profile_df: pd.DataFrame,
        scenarios: Optional[List[GrowthScenario]] = None,
        projection_years: int = 10
    ) -> Dict[str, GrowthProjectionResult]:
        """
        Projecteer profiel onder meerdere scenario's.

        Args:
            profile_df: Basis energieprofiel
            scenarios: Lijst van scenario's (default: alle voorgedefinieerde)
            projection_years: Projectieperiode

        Returns:
            Dict met scenario naam -> projectie resultaat
        """
        if scenarios is None:
            scenarios = list(PREDEFINED_SCENARIOS.values())

        results = {}
        for scenario in scenarios:
            result = self.project(
                profile_df=profile_df,
                scenario=scenario,
                projection_years=projection_years
            )
            results[scenario.name] = result

        return results

    def _analyze_base_profile(self, df: pd.DataFrame) -> dict:
        """Analyseer basisstatistieken van profiel."""
        if df.empty:
            return {
                "total_consumption_kwh": 0,
                "peak_kw": 0,
                "days": 0,
                "annual_consumption_kwh": 0,
            }

        interval_hours = 0.25
        afname = df['afname'].fillna(0)

        total_kwh = afname.sum()
        days = len(df) / 96
        annual_kwh = (total_kwh / days) * 365 if days > 0 else 0

        peak_kw = afname.max() / interval_hours

        return {
            "total_consumption_kwh": total_kwh,
            "peak_kw": peak_kw,
            "days": days,
            "annual_consumption_kwh": annual_kwh,
        }

    def _calculate_yearly_projections(
        self,
        base_stats: dict,
        scenario: GrowthScenario,
        years: int
    ) -> List[ProjectedYear]:
        """Bereken projectie voor elk jaar."""
        projections = []

        base_consumption = base_stats["annual_consumption_kwh"]
        base_peak = base_stats["peak_kw"]

        # Bepaal jaarlijkse groeipercentages
        if scenario.consumption_growth_annual is not None:
            annual_consumption_growth = scenario.consumption_growth_annual
        else:
            # Bereken uit totale groei (exponentieel)
            annual_consumption_growth = (1 + scenario.consumption_growth_total) ** (1 / years) - 1

        if scenario.peak_growth_annual is not None:
            annual_peak_growth = scenario.peak_growth_annual
        else:
            annual_peak_growth = (1 + scenario.peak_growth_total) ** (1 / years) - 1

        for year_offset in range(years + 1):  # Inclusief jaar 0
            year = self.base_year + year_offset

            # Cumulatieve groei (exponentieel)
            consumption_factor = (1 + annual_consumption_growth) ** year_offset
            peak_factor = (1 + annual_peak_growth) ** year_offset

            projected_consumption = base_consumption * consumption_factor
            projected_peak = base_peak * peak_factor

            projections.append(ProjectedYear(
                year=year,
                consumption_kwh=projected_consumption,
                peak_kw=projected_peak,
                growth_factor_consumption=consumption_factor,
                growth_factor_peak=peak_factor
            ))

        return projections

    def _scale_profile(
        self,
        profile_df: pd.DataFrame,
        consumption_factor: float,
        peak_factor: float,
        peakiness_factor: float = 1.0,
        evening_shift: float = 1.0
    ) -> pd.DataFrame:
        """
        Schaal profiel naar geprojecteerde waarden.

        Args:
            profile_df: Origineel profiel
            consumption_factor: Vermenigvuldigingsfactor voor totaal verbruik
            peak_factor: Factor voor piekvermogen
            peakiness_factor: >1 maakt pieken relatief hoger
            evening_shift: >1 verschuift verbruik naar avond

        Returns:
            Geschaald profiel DataFrame
        """
        df = profile_df.copy()

        # Basis schaling
        df['afname'] = df['afname'] * consumption_factor

        # Peakiness aanpassing
        if peakiness_factor != 1.0:
            mean_afname = df['afname'].mean()
            df['afname'] = mean_afname + (df['afname'] - mean_afname) * peakiness_factor

        # Evening shift (verschuif naar 17:00-22:00)
        if evening_shift > 1.0 and 'timestamp' in df.columns:
            hours = pd.to_datetime(df['timestamp']).dt.hour
            evening_mask = (hours >= 17) & (hours <= 22)
            shift_amount = (evening_shift - 1) * 0.1  # 10% verschuiving per factor

            # Verhoog avond, verlaag rest
            df.loc[evening_mask, 'afname'] *= (1 + shift_amount)
            df.loc[~evening_mask, 'afname'] *= (1 - shift_amount * 0.5)

        # Normaliseer zodat totaal klopt
        current_total = df['afname'].sum()
        target_total = profile_df['afname'].sum() * consumption_factor
        df['afname'] *= target_total / current_total if current_total > 0 else 1

        # Teruglevering (PV) groeit mee met eventuele uitbreiding
        if 'teruglevering' in df.columns:
            # Aanname: PV groeit niet automatisch, alleen met expliciete uitbreiding
            # Hier houden we het gelijk (factor 1.0)
            pass

        return df

    def create_custom_scenario(
        self,
        name: str,
        consumption_growth_percent: float,
        peak_growth_percent: Optional[float] = None,
        description: str = "",
        **kwargs
    ) -> GrowthScenario:
        """
        Maak een custom groeiscenario.

        Args:
            name: Naam van scenario
            consumption_growth_percent: Totale groei verbruik (bijv. 30 voor +30%)
            peak_growth_percent: Totale groei piek (default: 80% van verbruiksgroei)
            description: Beschrijving

        Returns:
            GrowthScenario object
        """
        consumption_growth = consumption_growth_percent / 100
        peak_growth = (peak_growth_percent / 100) if peak_growth_percent else (consumption_growth * 0.8)

        return GrowthScenario(
            name=name,
            scenario_type=GrowthScenarioType.CUSTOM,
            consumption_growth_total=consumption_growth,
            peak_growth_total=peak_growth,
            description=description or f"Custom scenario: +{consumption_growth_percent}% verbruik",
            assumptions=[
                f"Verbruiksgroei: +{consumption_growth_percent}%",
                f"Piekgroei: +{peak_growth_percent or int(consumption_growth * 80)}%",
            ],
            **kwargs
        )


def get_scenario(scenario_type: GrowthScenarioType) -> GrowthScenario:
    """Haal voorgedefinieerd scenario op."""
    return PREDEFINED_SCENARIOS.get(scenario_type, PREDEFINED_SCENARIOS[GrowthScenarioType.BASELINE])
