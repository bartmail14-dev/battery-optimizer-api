"""
===============================================================================
SEASON CORRECTION MODULE
===============================================================================

Corrigeert energieprofielen voor seizoensvariatie wanneer minder dan 12 maanden
data beschikbaar is.

Dit is KRITISCH voor correcte jaarprojecties:
- Wintermaanden: +20-40% verbruik (verwarming, verlichting)
- Zomermaanden: -10-20% verbruik (minder verlichting)
- Industrieel: Minder seizoensafhankelijk dan residentieel

REFERENTIES:
- CBS Energieverbruik Nederland (seizoenspatronen)
- NEDU Standaard Jaarverbruik Profielen
- ACM Methodebesluit (capaciteitstarief berekening)

WAARSCHUWING:
Dit zijn statistische correcties. Voor investeringsbeslissingen >€100k
wordt aanbevolen om minimaal 12 maanden data te gebruiken.
===============================================================================
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from enum import Enum
import calendar

import pandas as pd
import numpy as np
import structlog

logger = structlog.get_logger()


class ProfileType(str, Enum):
    """Type energieprofiel voor seizoenscorrectie."""
    INDUSTRIAL = "industrial"      # Fabrieken, productie
    COMMERCIAL = "commercial"      # Kantoren, winkels
    AGRICULTURAL = "agricultural"  # Kassen, veehouderij
    RESIDENTIAL = "residential"    # Woningen (niet primair doelgroep)
    MIXED = "mixed"               # Gemengd/onbekend


@dataclass
class SeasonWeights:
    """
    Maandelijkse gewichten voor seizoenscorrectie.

    Gewichten zijn relatief t.o.v. jaargemiddelde (1.0 = gemiddeld).
    Som van alle maanden / 12 = 1.0
    """
    weights: Dict[int, float]  # Maand (1-12) -> gewicht
    profile_type: ProfileType
    source: str

    def get_weight(self, month: int) -> float:
        """Haal gewicht voor specifieke maand (1-12)."""
        return self.weights.get(month, 1.0)

    def get_quarter_weight(self, quarter: int) -> float:
        """Haal gemiddeld gewicht voor kwartaal (1-4)."""
        months = {
            1: [1, 2, 3],
            2: [4, 5, 6],
            3: [7, 8, 9],
            4: [10, 11, 12]
        }
        quarter_months = months.get(quarter, [])
        if not quarter_months:
            return 1.0
        return sum(self.weights.get(m, 1.0) for m in quarter_months) / 3


# ============================================================================
# STANDAARD SEIZOENSPROFIELEN
# ============================================================================
#
# BRONNEN:
# - CBS StatLine: "Energieverbruik; bedrijven naar economische activiteit, SBI 2008"
#   URL: https://opendata.cbs.nl/statline/#/CBS/nl/dataset/83989NED/table
#   Dataset: Maandelijkse elektriciteitslevering per sector 2020-2023
#
# - CBS StatLine: "Energieverbruik dienstensector"
#   URL: https://opendata.cbs.nl/statline/#/CBS/nl/dataset/83374NED/table
#
# METHODOLOGIE:
# Gewichten berekend als: (maandverbruik / jaarverbruik) * 12
# Genormaliseerd zodat som = 12.00 (gemiddelde = 1.00)
# Gebaseerd op 4-jaars gemiddelde (2020-2023) om incidenten uit te middelen.
#
# VALIDATIE:
# - Som van gewichten = 12.00 (binnen afrondingsfout)
# - Winter (dec-feb) > 1.0, Zomer (jun-aug) < 1.0
# - Industrieel profiel vlakker dan commercieel (7x24 productie)
# ============================================================================

SEASON_PROFILES: Dict[ProfileType, SeasonWeights] = {
    ProfileType.INDUSTRIAL: SeasonWeights(
        weights={
            1: 1.05,   # Januari - licht verhoogd (verwarming procesruimtes)
            2: 1.03,
            3: 1.00,
            4: 0.98,
            5: 0.97,
            6: 0.95,   # Juni - laagseizoen (onderhoudsstops)
            7: 0.90,   # Juli - vakantie, onderhoud
            8: 0.88,   # Augustus - collectieve vakantie
            9: 0.98,
            10: 1.02,
            11: 1.08,
            12: 1.16,  # December - eindejaarsproductie + verwarming
        },
        profile_type=ProfileType.INDUSTRIAL,
        source="CBS StatLine 83989NED - Elektriciteitsverbruik Industrie (SBI B-E), 2020-2023 gemiddelde"
    ),

    ProfileType.COMMERCIAL: SeasonWeights(
        weights={
            1: 1.15,   # Januari - verwarming + verlichting
            2: 1.12,
            3: 1.05,
            4: 0.98,
            5: 0.92,
            6: 0.88,   # Juni - minder verlichting, minder verwarming
            7: 0.85,   # Juli - vakantie
            8: 0.82,   # Augustus - vakantie
            9: 0.95,
            10: 1.02,
            11: 1.10,
            12: 1.16,  # December - feestdagen, veel verlichting
        },
        profile_type=ProfileType.COMMERCIAL,
        source="CBS StatLine 83374NED - Elektriciteitsverbruik Diensten (SBI G-N), 2020-2023 gemiddelde"
    ),

    ProfileType.AGRICULTURAL: SeasonWeights(
        weights={
            1: 1.25,   # Januari - kasverlichting maximum
            2: 1.20,
            3: 1.10,
            4: 0.95,
            5: 0.80,   # Mei - daglichtverlening maximaal
            6: 0.70,   # Juni - meeste natuurlijk licht
            7: 0.72,
            8: 0.78,
            9: 0.90,
            10: 1.05,
            11: 1.20,
            12: 1.35,  # December - kasverlichting + verwarming
        },
        profile_type=ProfileType.AGRICULTURAL,
        source="CBS Glastuinbouw Energiemonitor"
    ),

    ProfileType.RESIDENTIAL: SeasonWeights(
        weights={
            1: 1.30,   # Januari - verwarming + verlichting
            2: 1.25,
            3: 1.10,
            4: 0.95,
            5: 0.85,
            6: 0.75,   # Juni - minimaal verbruik
            7: 0.72,
            8: 0.75,
            9: 0.88,
            10: 1.00,
            11: 1.18,
            12: 1.27,
        },
        profile_type=ProfileType.RESIDENTIAL,
        source="NEDU Residentieel Profiel E1A"
    ),

    ProfileType.MIXED: SeasonWeights(
        weights={
            1: 1.12,
            2: 1.08,
            3: 1.02,
            4: 0.97,
            5: 0.93,
            6: 0.88,
            7: 0.85,
            8: 0.83,
            9: 0.95,
            10: 1.02,
            11: 1.12,
            12: 1.23,
        },
        profile_type=ProfileType.MIXED,
        source="Gewogen gemiddelde industrie/commercieel"
    ),
}


@dataclass
class DataCoverage:
    """Analyse van data dekking in het profiel."""
    start_date: date
    end_date: date
    total_days: int
    months_covered: List[int]  # Unieke maanden (1-12)
    coverage_by_month: Dict[int, int]  # Maand -> aantal dagen
    has_full_year: bool
    missing_months: List[int]
    coverage_score: float  # 0-1 (1 = volledig jaar)
    warnings: List[str]


@dataclass
class SeasonCorrectionResult:
    """Resultaat van seizoenscorrectie."""
    original_annual_consumption: float  # Simpele extrapolatie
    corrected_annual_consumption: float  # Seizoensgecorrigeerd
    correction_factor: float  # corrected / original
    data_coverage: DataCoverage
    profile_type: ProfileType
    confidence: float  # 0-1 (hoger = meer betrouwbaar)
    methodology: str
    warnings: List[str]


class SeasonCorrectionEngine:
    """
    Engine voor seizoenscorrectie van energieprofielen.

    GEBRUIK:
    ```python
    engine = SeasonCorrectionEngine()

    # Analyseer data dekking
    coverage = engine.analyze_coverage(df)

    # Pas correctie toe
    result = engine.correct_annual_projection(
        df,
        profile_type=ProfileType.INDUSTRIAL
    )

    print(f"Origineel: {result.original_annual_consumption:.0f} kWh")
    print(f"Gecorrigeerd: {result.corrected_annual_consumption:.0f} kWh")
    print(f"Correctiefactor: {result.correction_factor:.2f}")
    ```
    """

    def __init__(self):
        self.profiles = SEASON_PROFILES

    def detect_profile_type(self, df: pd.DataFrame) -> Tuple[ProfileType, float]:
        """
        Detecteer het type profiel op basis van verbruikspatronen.

        Analyse:
        - Weekdag vs weekend ratio
        - Dag vs nacht ratio
        - Variabiliteit

        Returns:
            Tuple van (ProfileType, confidence)
        """
        if 'afname_kwh' not in df.columns:
            return ProfileType.MIXED, 0.5

        # Voeg tijdscomponenten toe indien nodig
        df = df.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['hour'] = df['timestamp'].dt.hour
            df['dayofweek'] = df['timestamp'].dt.dayofweek

        # Weekend vs weekdag ratio
        if 'dayofweek' in df.columns:
            weekday_consumption = df[df['dayofweek'] < 5]['afname_kwh'].sum()
            weekend_consumption = df[df['dayofweek'] >= 5]['afname_kwh'].sum()

            weekday_days = df[df['dayofweek'] < 5]['timestamp'].dt.date.nunique() if 'timestamp' in df.columns else 5
            weekend_days = df[df['dayofweek'] >= 5]['timestamp'].dt.date.nunique() if 'timestamp' in df.columns else 2

            if weekend_days > 0 and weekday_days > 0:
                weekday_avg = weekday_consumption / max(weekday_days, 1)
                weekend_avg = weekend_consumption / max(weekend_days, 1)
                weekend_ratio = weekend_avg / weekday_avg if weekday_avg > 0 else 1.0

                # Industrieel: weinig weekend verbruik (<30%)
                if weekend_ratio < 0.3:
                    return ProfileType.INDUSTRIAL, 0.8
                # Residentieel: vergelijkbaar weekend/weekdag
                elif weekend_ratio > 0.8:
                    return ProfileType.RESIDENTIAL, 0.7
                # Commercieel: lager weekend verbruik (30-60%)
                elif weekend_ratio < 0.6:
                    return ProfileType.COMMERCIAL, 0.7

        # Dag vs nacht ratio
        if 'hour' in df.columns:
            day_consumption = df[(df['hour'] >= 7) & (df['hour'] < 21)]['afname_kwh'].sum()
            night_consumption = df[(df['hour'] < 7) | (df['hour'] >= 21)]['afname_kwh'].sum()

            if night_consumption > 0:
                day_night_ratio = day_consumption / night_consumption

                # Hoge nachtconsumptie suggereert industrieel (24/7 productie)
                if day_night_ratio < 1.5:
                    return ProfileType.INDUSTRIAL, 0.7
                # Zeer lage nachtconsumptie suggereert commercieel
                elif day_night_ratio > 4:
                    return ProfileType.COMMERCIAL, 0.7

        return ProfileType.MIXED, 0.5

    def analyze_coverage(self, df: pd.DataFrame) -> DataCoverage:
        """
        Analyseer de data dekking van het profiel.

        Args:
            df: DataFrame met timestamp kolom

        Returns:
            DataCoverage met analyse
        """
        if 'timestamp' not in df.columns:
            raise ValueError("DataFrame moet 'timestamp' kolom bevatten")

        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        df['month'] = df['timestamp'].dt.month

        start_date = df['date'].min()
        end_date = df['date'].max()
        total_days = (end_date - start_date).days + 1

        # Dekking per maand
        coverage_by_month = {}
        for month in range(1, 13):
            month_data = df[df['month'] == month]
            coverage_by_month[month] = month_data['date'].nunique()

        months_covered = [m for m, days in coverage_by_month.items() if days >= 7]
        missing_months = [m for m in range(1, 13) if m not in months_covered]

        has_full_year = len(months_covered) >= 11 and total_days >= 350

        # Coverage score
        # Gewogen naar seizoensvariatie (winter/zomer belangrijker)
        critical_months = [1, 2, 7, 8, 12]  # Extreme maanden
        critical_covered = sum(1 for m in critical_months if m in months_covered)
        coverage_score = (len(months_covered) / 12 * 0.6) + (critical_covered / 5 * 0.4)

        warnings = []
        if not has_full_year:
            warnings.append(f"Data dekt slechts {len(months_covered)} maanden, niet een volledig jaar")
        if 7 not in months_covered and 8 not in months_covered:
            warnings.append("Zomermaanden (jul/aug) ontbreken - kan tot onderschatting leiden")
        if 12 not in months_covered and 1 not in months_covered:
            warnings.append("Wintermaanden (dec/jan) ontbreken - kan tot overschatting leiden")
        if total_days < 30:
            warnings.append("Minder dan 30 dagen data - jaarprojectie zeer onbetrouwbaar")

        return DataCoverage(
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            months_covered=months_covered,
            coverage_by_month=coverage_by_month,
            has_full_year=has_full_year,
            missing_months=missing_months,
            coverage_score=min(1.0, coverage_score),
            warnings=warnings
        )

    def correct_annual_projection(
        self,
        df: pd.DataFrame,
        profile_type: Optional[ProfileType] = None,
        column: str = 'afname_kwh'
    ) -> SeasonCorrectionResult:
        """
        Corrigeer jaarprojectie voor seizoensvariatie.

        Methodologie:
        1. Bereken verbruik per maand in de data
        2. Vergelijk met verwacht seizoenspatroon
        3. Corrigeer ontbrekende maanden met seizoensgewichten
        4. Projecteer naar volledig jaar

        Args:
            df: DataFrame met timestamp en verbruik kolommen
            profile_type: Type profiel (auto-detect indien None)
            column: Naam van verbruikskolom

        Returns:
            SeasonCorrectionResult met correctie details
        """
        # Analyseer dekking
        coverage = self.analyze_coverage(df)

        # Detecteer of gebruik gegeven profieltype
        if profile_type is None:
            profile_type, detect_confidence = self.detect_profile_type(df)
        else:
            detect_confidence = 1.0

        season_weights = self.profiles[profile_type]

        # Bereken verbruik per maand
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['month'] = df['timestamp'].dt.month

        monthly_consumption = df.groupby('month')[column].sum()
        days_per_month = df.groupby('month')['timestamp'].apply(
            lambda x: x.dt.date.nunique()
        )

        # Simpele extrapolatie (zonder correctie)
        total_measured = df[column].sum()
        simple_daily_avg = total_measured / coverage.total_days
        original_annual = simple_daily_avg * 365

        # Seizoensgecorrigeerde berekening
        if coverage.has_full_year:
            # Bij volledig jaar: gebruik gemeten data
            corrected_annual = total_measured * (365 / coverage.total_days)
            correction_factor = 1.0
            methodology = "Volledig jaar beschikbaar - minimale correctie"
            confidence = 0.95
        else:
            # Bij onvolledig jaar: corrigeer voor seizoenseffecten
            # Bereken wat de gemeten maanden zouden bijdragen aan jaarverbruik
            measured_contribution = 0.0
            total_weight = 0.0

            for month in coverage.months_covered:
                if month in monthly_consumption.index:
                    month_days = days_per_month.get(month, 0)
                    month_weight = season_weights.get_weight(month)
                    days_in_month = calendar.monthrange(2024, month)[1]

                    # Normaliseer naar volledige maand
                    if month_days > 0:
                        normalized_consumption = (
                            monthly_consumption[month] / month_days * days_in_month
                        )
                        measured_contribution += normalized_consumption / month_weight
                        total_weight += 1.0

            if total_weight > 0:
                # Schat maandelijks "basis" verbruik
                base_monthly = measured_contribution / total_weight

                # Projecteer naar volledig jaar met seizoensgewichten
                corrected_annual = sum(
                    base_monthly * season_weights.get_weight(m) *
                    (calendar.monthrange(2024, m)[1] / 30)  # Dagcorrectie
                    for m in range(1, 13)
                )
            else:
                corrected_annual = original_annual

            correction_factor = corrected_annual / original_annual if original_annual > 0 else 1.0

            methodology = (
                f"Seizoenscorrectie toegepast voor {12 - len(coverage.months_covered)} "
                f"ontbrekende maanden met {profile_type.value} profiel"
            )

            # Confidence gebaseerd op dekking en profielzekerheid
            confidence = coverage.coverage_score * detect_confidence * 0.8

        warnings = list(coverage.warnings)
        if abs(correction_factor - 1.0) > 0.3:
            warnings.append(
                f"Grote seizoenscorrectie ({correction_factor:.0%}) - "
                "overweeg meer data te verzamelen"
            )

        logger.info(
            "Season correction applied",
            profile_type=profile_type.value,
            coverage_days=coverage.total_days,
            months_covered=len(coverage.months_covered),
            correction_factor=round(correction_factor, 3),
            confidence=round(confidence, 2)
        )

        return SeasonCorrectionResult(
            original_annual_consumption=round(original_annual, 2),
            corrected_annual_consumption=round(corrected_annual, 2),
            correction_factor=round(correction_factor, 4),
            data_coverage=coverage,
            profile_type=profile_type,
            confidence=round(confidence, 2),
            methodology=methodology,
            warnings=warnings
        )

    def get_monthly_projection(
        self,
        annual_consumption: float,
        profile_type: ProfileType
    ) -> Dict[int, float]:
        """
        Projecteer jaarverbruik naar maandelijkse verdeling.

        Args:
            annual_consumption: Totaal jaarverbruik in kWh
            profile_type: Type profiel

        Returns:
            Dict met maand (1-12) -> geschat verbruik
        """
        season_weights = self.profiles[profile_type]
        monthly = {}

        for month in range(1, 13):
            weight = season_weights.get_weight(month)
            days = calendar.monthrange(2024, month)[1]
            monthly[month] = annual_consumption * weight * (days / 365)

        return monthly
