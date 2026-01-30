"""
===============================================================================
SANITY CHECKS
===============================================================================

Validatie en sanity checks voor batterij-optimalisatie resultaten.

Dit module valideert:
1. Input data kwaliteit
2. Configuratie parameters
3. Resultaten tegen industrie-benchmarks
4. Fysieke constraints (energy balance, efficiency bounds)

BENCHMARKS:
- NREL ATB 2024 utility-scale battery costs
- Lazard LCOS v9.0 ranges
- IEC 62933-4-1 performance standards

WAARSCHUWING:
- Resultaten buiten benchmarks zijn NIET per definitie fout
- Maar verdienen wel extra aandacht en validatie
===============================================================================
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

import pandas as pd
import numpy as np
import structlog

logger = structlog.get_logger()


class ValidationSeverity(str, Enum):
    """Severity levels voor validatie issues."""
    INFO = "info"           # Informatief, geen actie nodig
    WARNING = "warning"     # Verdient aandacht
    ERROR = "error"         # Kritiek probleem
    CRITICAL = "critical"   # Blokkeert verdere verwerking


@dataclass
class ValidationIssue:
    """Eén validatie issue."""
    code: str
    message: str
    severity: ValidationSeverity
    field: Optional[str] = None
    expected_range: Optional[Tuple[float, float]] = None
    actual_value: Optional[float] = None


@dataclass
class ValidationResult:
    """Resultaat van validatie."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    def add_issue(self, issue: ValidationIssue):
        """Voeg issue toe en update is_valid."""
        self.issues.append(issue)
        if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]:
            self.is_valid = False

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "is_valid": self.is_valid,
            "issues": [
                {
                    "code": i.code,
                    "message": i.message,
                    "severity": i.severity.value,
                    "field": i.field,
                    "expected_range": i.expected_range,
                    "actual_value": i.actual_value
                }
                for i in self.issues
            ],
            "warnings": self.warnings,
            "info": self.info
        }


# =============================================================================
# INDUSTRY BENCHMARKS
# =============================================================================

# CAPEX benchmarks (€/kWh) - NREL ATB 2024, aangepast voor NL
CAPEX_BENCHMARKS = {
    "utility_scale_min": 180,      # Zeer grote installaties, ideale omstandigheden
    "utility_scale_max": 350,
    "commercial_min": 280,         # Commerciële schaal (50-500 kWh)
    "commercial_max": 550,
    "residential_min": 400,        # Residentieel (5-20 kWh)
    "residential_max": 900,
}

# LCOS benchmarks (€/kWh) - Lazard LCOS v9.0
LCOS_BENCHMARKS = {
    "utility_scale": (0.08, 0.15),     # €/kWh throughput
    "commercial": (0.10, 0.20),
    "residential": (0.15, 0.35),
}

# Efficiency benchmarks - IEC 62933-4-1
EFFICIENCY_BENCHMARKS = {
    "round_trip_min": 0.82,       # Minimale RT efficiency
    "round_trip_typical": 0.90,   # Typische waarde
    "round_trip_max": 0.96,       # Maximum (LTO)
}

# Cycle life benchmarks
CYCLE_LIFE_BENCHMARKS = {
    "lfp_min": 3000,
    "lfp_typical": 5000,
    "lfp_max": 8000,
    "nmc_min": 1500,
    "nmc_typical": 2500,
    "nmc_max": 4000,
}

# Degradation benchmarks (% per jaar bij normale operatie)
DEGRADATION_BENCHMARKS = {
    "calendar_min": 0.01,    # 1% per jaar
    "calendar_typical": 0.02,
    "calendar_max": 0.04,
    "cycle_min": 0.01,
    "cycle_typical": 0.02,
    "cycle_max": 0.05,
}


class SanityChecker:
    """
    Sanity checker voor batterij-optimalisatie.

    GEBRUIK:
    ```python
    checker = SanityChecker()

    # Valideer input data
    result = checker.validate_profile(profile_df)
    if not result.is_valid:
        raise ValueError(f"Invalid profile: {result.issues}")

    # Valideer configuratie
    result = checker.validate_config(capacity_kwh=100, ...)

    # Valideer resultaten
    result = checker.validate_results(
        capex=35000,
        lcos=0.12,
        annual_savings=4500,
        ...
    )
    ```
    """

    def __init__(self, scale: str = "commercial"):
        """
        Initialiseer checker.

        Args:
            scale: Schaal van installatie ('utility', 'commercial', 'residential')
        """
        self.scale = scale

    def validate_profile(
        self,
        df: pd.DataFrame,
        interval_minutes: int = 15
    ) -> ValidationResult:
        """
        Valideer energieprofiel data.

        Checks:
        - Vereiste kolommen aanwezig
        - Data types correct
        - Geen negatieve waarden (waar niet verwacht)
        - Outlier detectie
        - Tijdsreeks volledigheid
        """
        result = ValidationResult(is_valid=True)

        # === REQUIRED COLUMNS ===
        required_cols = ['timestamp', 'afname_kwh']
        for col in required_cols:
            if col not in df.columns:
                result.add_issue(ValidationIssue(
                    code="MISSING_COLUMN",
                    message=f"Required column '{col}' not found in data",
                    severity=ValidationSeverity.CRITICAL,
                    field=col
                ))

        if not result.is_valid:
            return result

        # === DATA TYPES ===
        try:
            pd.to_datetime(df['timestamp'])
        except Exception as e:
            result.add_issue(ValidationIssue(
                code="INVALID_TIMESTAMP",
                message=f"Cannot parse timestamp column: {str(e)}",
                severity=ValidationSeverity.CRITICAL,
                field="timestamp"
            ))

        # === DATA QUALITY ===
        n_rows = len(df)
        n_nulls = df['afname_kwh'].isnull().sum()

        if n_nulls > 0:
            null_pct = n_nulls / n_rows
            if null_pct > 0.05:
                result.add_issue(ValidationIssue(
                    code="HIGH_NULL_RATE",
                    message=f"{null_pct:.1%} of afname_kwh values are null",
                    severity=ValidationSeverity.WARNING,
                    field="afname_kwh",
                    actual_value=null_pct
                ))

        # === NEGATIVE VALUES ===
        n_negative = (df['afname_kwh'] < 0).sum()
        if n_negative > 0:
            result.add_issue(ValidationIssue(
                code="NEGATIVE_AFNAME",
                message=f"{n_negative} negative values in afname_kwh (should be positive for consumption)",
                severity=ValidationSeverity.WARNING,
                field="afname_kwh",
                actual_value=n_negative
            ))

        # === OUTLIER DETECTION ===
        afname = df['afname_kwh'].dropna()
        if len(afname) > 100:
            q99 = afname.quantile(0.99)
            q01 = afname.quantile(0.01)
            median = afname.median()

            # Extreme outliers: > 10x median
            n_extreme = (afname > median * 10).sum()
            if n_extreme > 0:
                result.add_issue(ValidationIssue(
                    code="EXTREME_OUTLIERS",
                    message=f"{n_extreme} values are > 10x median consumption",
                    severity=ValidationSeverity.WARNING,
                    field="afname_kwh",
                    actual_value=n_extreme
                ))

        # === TIME SERIES COMPLETENESS ===
        if n_rows >= 2:
            df_sorted = df.sort_values('timestamp')
            timestamps = pd.to_datetime(df_sorted['timestamp'])
            expected_points = (timestamps.max() - timestamps.min()).total_seconds() / (interval_minutes * 60)
            completeness = n_rows / expected_points if expected_points > 0 else 0

            if completeness < 0.9:
                result.add_issue(ValidationIssue(
                    code="INCOMPLETE_TIMESERIES",
                    message=f"Data completeness is {completeness:.1%}, expected > 90%",
                    severity=ValidationSeverity.WARNING,
                    expected_range=(0.9, 1.0),
                    actual_value=completeness
                ))

        # === SUFFICIENT DATA ===
        days_of_data = n_rows * interval_minutes / (60 * 24)
        if days_of_data < 7:
            result.add_issue(ValidationIssue(
                code="INSUFFICIENT_DATA",
                message=f"Only {days_of_data:.1f} days of data, recommend at least 7 days",
                severity=ValidationSeverity.WARNING,
                expected_range=(7, None),
                actual_value=days_of_data
            ))

        if days_of_data < 1:
            result.add_issue(ValidationIssue(
                code="CRITICAL_DATA_SHORTAGE",
                message="Less than 1 day of data, cannot perform reliable analysis",
                severity=ValidationSeverity.ERROR,
                actual_value=days_of_data
            ))

        # Add info
        result.info.append(f"Data points: {n_rows:,}")
        result.info.append(f"Days of data: {days_of_data:.1f}")

        return result

    def validate_config(
        self,
        capacity_kwh: float,
        max_power_kw: float,
        efficiency: float = 0.90,
        min_soc: float = 0.10,
        max_soc: float = 0.90
    ) -> ValidationResult:
        """
        Valideer batterij configuratie.

        Checks:
        - Realistische capaciteit
        - C-rate binnen normale range
        - Efficiency binnen fysieke grenzen
        - SoC constraints logisch
        """
        result = ValidationResult(is_valid=True)

        # === CAPACITY ===
        if capacity_kwh <= 0:
            result.add_issue(ValidationIssue(
                code="INVALID_CAPACITY",
                message="Capacity must be positive",
                severity=ValidationSeverity.CRITICAL,
                field="capacity_kwh",
                actual_value=capacity_kwh
            ))

        if capacity_kwh < 1:
            result.add_issue(ValidationIssue(
                code="CAPACITY_TOO_SMALL",
                message="Capacity < 1 kWh is unusual for grid applications",
                severity=ValidationSeverity.WARNING,
                field="capacity_kwh",
                expected_range=(1, None),
                actual_value=capacity_kwh
            ))

        if capacity_kwh > 10000:
            result.add_issue(ValidationIssue(
                code="CAPACITY_VERY_LARGE",
                message="Capacity > 10 MWh is utility scale",
                severity=ValidationSeverity.INFO,
                field="capacity_kwh",
                actual_value=capacity_kwh
            ))

        # === C-RATE ===
        if max_power_kw > 0 and capacity_kwh > 0:
            c_rate = max_power_kw / capacity_kwh
            if c_rate > 2:
                result.add_issue(ValidationIssue(
                    code="HIGH_C_RATE",
                    message=f"C-rate of {c_rate:.1f}C is very high, may impact battery life",
                    severity=ValidationSeverity.WARNING,
                    field="c_rate",
                    expected_range=(0.1, 2.0),
                    actual_value=c_rate
                ))

            if c_rate < 0.1:
                result.add_issue(ValidationIssue(
                    code="LOW_C_RATE",
                    message=f"C-rate of {c_rate:.2f}C is very low, battery may be underutilized",
                    severity=ValidationSeverity.INFO,
                    field="c_rate",
                    actual_value=c_rate
                ))

        # === EFFICIENCY ===
        if efficiency < EFFICIENCY_BENCHMARKS["round_trip_min"]:
            result.add_issue(ValidationIssue(
                code="LOW_EFFICIENCY",
                message=f"Efficiency {efficiency:.1%} is below typical minimum {EFFICIENCY_BENCHMARKS['round_trip_min']:.1%}",
                severity=ValidationSeverity.WARNING,
                field="efficiency",
                expected_range=(EFFICIENCY_BENCHMARKS["round_trip_min"], EFFICIENCY_BENCHMARKS["round_trip_max"]),
                actual_value=efficiency
            ))

        if efficiency > EFFICIENCY_BENCHMARKS["round_trip_max"]:
            result.add_issue(ValidationIssue(
                code="UNREALISTIC_EFFICIENCY",
                message=f"Efficiency {efficiency:.1%} exceeds physical limits ({EFFICIENCY_BENCHMARKS['round_trip_max']:.1%})",
                severity=ValidationSeverity.ERROR,
                field="efficiency",
                expected_range=(EFFICIENCY_BENCHMARKS["round_trip_min"], EFFICIENCY_BENCHMARKS["round_trip_max"]),
                actual_value=efficiency
            ))

        # === SOC CONSTRAINTS ===
        if min_soc >= max_soc:
            result.add_issue(ValidationIssue(
                code="INVALID_SOC_RANGE",
                message="min_soc must be less than max_soc",
                severity=ValidationSeverity.ERROR,
                field="soc_range"
            ))

        usable_capacity = max_soc - min_soc
        if usable_capacity < 0.5:
            result.add_issue(ValidationIssue(
                code="LIMITED_USABLE_CAPACITY",
                message=f"Usable capacity is only {usable_capacity:.0%} of total",
                severity=ValidationSeverity.WARNING,
                expected_range=(0.5, 0.9),
                actual_value=usable_capacity
            ))

        return result

    def validate_results(
        self,
        capex: float,
        capex_per_kwh: float,
        lcos: float,
        annual_savings: float,
        payback_years: float,
        npv: float,
        irr: Optional[float],
        cycles_per_year: float,
        efficiency: float,
        capacity_kwh: float
    ) -> ValidationResult:
        """
        Valideer berekende resultaten tegen benchmarks.

        Checks:
        - CAPEX binnen verwachte range
        - LCOS realistisch
        - Payback niet negatief of oneindig
        - Cycles binnen typische range
        """
        result = ValidationResult(is_valid=True)

        # Determine scale-appropriate benchmarks
        if capacity_kwh > 1000:
            scale = "utility_scale"
            capex_range = (CAPEX_BENCHMARKS["utility_scale_min"], CAPEX_BENCHMARKS["utility_scale_max"])
            lcos_range = LCOS_BENCHMARKS["utility_scale"]
        elif capacity_kwh > 50:
            scale = "commercial"
            capex_range = (CAPEX_BENCHMARKS["commercial_min"], CAPEX_BENCHMARKS["commercial_max"])
            lcos_range = LCOS_BENCHMARKS["commercial"]
        else:
            scale = "residential"
            capex_range = (CAPEX_BENCHMARKS["residential_min"], CAPEX_BENCHMARKS["residential_max"])
            lcos_range = LCOS_BENCHMARKS["residential"]

        # === CAPEX VALIDATION ===
        if capex_per_kwh < capex_range[0]:
            result.add_issue(ValidationIssue(
                code="CAPEX_BELOW_BENCHMARK",
                message=f"CAPEX €{capex_per_kwh:.0f}/kWh is below {scale} benchmark €{capex_range[0]}-{capex_range[1]}/kWh",
                severity=ValidationSeverity.WARNING,
                field="capex_per_kwh",
                expected_range=capex_range,
                actual_value=capex_per_kwh
            ))
            result.warnings.append("Low CAPEX may indicate missing cost components")

        if capex_per_kwh > capex_range[1] * 1.5:
            result.add_issue(ValidationIssue(
                code="CAPEX_ABOVE_BENCHMARK",
                message=f"CAPEX €{capex_per_kwh:.0f}/kWh is significantly above benchmark",
                severity=ValidationSeverity.WARNING,
                field="capex_per_kwh",
                expected_range=capex_range,
                actual_value=capex_per_kwh
            ))

        # === LCOS VALIDATION ===
        if lcos < lcos_range[0]:
            result.add_issue(ValidationIssue(
                code="LCOS_BELOW_BENCHMARK",
                message=f"LCOS €{lcos:.3f}/kWh is below Lazard benchmark (€{lcos_range[0]:.3f}-{lcos_range[1]:.3f}/kWh)",
                severity=ValidationSeverity.WARNING,
                field="lcos",
                expected_range=lcos_range,
                actual_value=lcos
            ))

        if lcos > lcos_range[1] * 1.5:
            result.add_issue(ValidationIssue(
                code="LCOS_ABOVE_BENCHMARK",
                message=f"LCOS €{lcos:.3f}/kWh is significantly above benchmark",
                severity=ValidationSeverity.WARNING,
                field="lcos",
                expected_range=lcos_range,
                actual_value=lcos
            ))

        # === PAYBACK VALIDATION ===
        if payback_years < 0:
            result.add_issue(ValidationIssue(
                code="NEGATIVE_PAYBACK",
                message="Negative payback indicates calculation error",
                severity=ValidationSeverity.ERROR,
                field="payback_years",
                actual_value=payback_years
            ))

        if payback_years > 25:
            result.add_issue(ValidationIssue(
                code="EXCESSIVE_PAYBACK",
                message=f"Payback of {payback_years:.1f} years exceeds typical battery lifetime",
                severity=ValidationSeverity.WARNING,
                field="payback_years",
                expected_range=(3, 15),
                actual_value=payback_years
            ))

        # === CYCLES VALIDATION ===
        if cycles_per_year < 50:
            result.add_issue(ValidationIssue(
                code="LOW_CYCLE_COUNT",
                message=f"Only {cycles_per_year:.0f} cycles/year - battery may be underutilized",
                severity=ValidationSeverity.INFO,
                field="cycles_per_year",
                expected_range=(100, 500),
                actual_value=cycles_per_year
            ))

        if cycles_per_year > 600:
            result.add_issue(ValidationIssue(
                code="HIGH_CYCLE_COUNT",
                message=f"{cycles_per_year:.0f} cycles/year may accelerate degradation",
                severity=ValidationSeverity.WARNING,
                field="cycles_per_year",
                expected_range=(100, 500),
                actual_value=cycles_per_year
            ))

        # === SAVINGS VS CAPEX SANITY ===
        if annual_savings > 0 and capex > 0:
            implied_roi = annual_savings / capex
            if implied_roi > 0.3:
                result.add_issue(ValidationIssue(
                    code="HIGH_IMPLIED_ROI",
                    message=f"Implied ROI of {implied_roi:.0%} is unusually high",
                    severity=ValidationSeverity.WARNING,
                    expected_range=(0.05, 0.20),
                    actual_value=implied_roi
                ))

        # === IRR VALIDATION ===
        if irr is not None:
            if irr > 0.5:
                result.add_issue(ValidationIssue(
                    code="UNREALISTIC_IRR",
                    message=f"IRR of {irr:.0%} is unusually high",
                    severity=ValidationSeverity.WARNING,
                    field="irr",
                    expected_range=(0.05, 0.25),
                    actual_value=irr
                ))

        # Add summary info
        result.info.append(f"Scale category: {scale}")
        result.info.append(f"CAPEX benchmark range: €{capex_range[0]}-{capex_range[1]}/kWh")
        result.info.append(f"LCOS benchmark range: €{lcos_range[0]:.3f}-{lcos_range[1]:.3f}/kWh")

        return result

    def validate_energy_balance(
        self,
        total_charged_kwh: float,
        total_discharged_kwh: float,
        total_losses_kwh: float,
        efficiency: float
    ) -> ValidationResult:
        """
        Valideer energie balans.

        Law of conservation of energy:
        charged = discharged + losses
        """
        result = ValidationResult(is_valid=True)

        # Energy balance check
        expected_losses = total_charged_kwh - total_discharged_kwh
        loss_error = abs(expected_losses - total_losses_kwh)

        if loss_error > 1.0:  # > 1 kWh discrepancy
            result.add_issue(ValidationIssue(
                code="ENERGY_BALANCE_ERROR",
                message=f"Energy balance discrepancy: {loss_error:.2f} kWh",
                severity=ValidationSeverity.ERROR,
                actual_value=loss_error
            ))

        # Implied efficiency check
        if total_charged_kwh > 0:
            implied_eff = total_discharged_kwh / total_charged_kwh
            eff_error = abs(implied_eff - efficiency)

            if eff_error > 0.05:  # > 5% discrepancy
                result.add_issue(ValidationIssue(
                    code="EFFICIENCY_MISMATCH",
                    message=f"Implied efficiency {implied_eff:.1%} differs from configured {efficiency:.1%}",
                    severity=ValidationSeverity.WARNING,
                    expected_range=(efficiency - 0.05, efficiency + 0.05),
                    actual_value=implied_eff
                ))

        return result
