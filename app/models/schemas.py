from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum
from typing import Optional


# === Enums ===


class OptimizationStrategy(str, Enum):
    """Available optimization strategies."""
    PEAK_SHAVING = "peak_shaving"
    ARBITRAGE = "arbitrage"
    SELF_CONSUMPTION = "self_consumption"
    HYBRID = "hybrid"


class FileType(str, Enum):
    """Supported file types."""
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"


# === Input Models ===


class ColumnMapping(BaseModel):
    """Mapping of CSV columns to expected fields."""
    timestamp: str
    afname: str
    teruglevering: Optional[str] = None
    vermogen: Optional[str] = None


class TariffStructure(BaseModel):
    """Electricity tariff configuration."""
    peak_rate: float = Field(ge=0, default=0.35, description="€/kWh tijdens piekuren")
    off_peak_rate: float = Field(ge=0, default=0.22, description="€/kWh tijdens daluren")
    peak_hours_start: int = Field(ge=0, le=23, default=7)
    peak_hours_end: int = Field(ge=0, le=23, default=21)
    capacity_tariff: float = Field(ge=0, default=12.50, description="€/kW/maand")
    feed_in_tariff: float = Field(ge=0, default=0.08, description="€/kWh teruglevering")

    @field_validator('peak_hours_end')
    @classmethod
    def validate_peak_hours(cls, v: int, info) -> int:
        if 'peak_hours_start' in info.data and v <= info.data['peak_hours_start']:
            raise ValueError('peak_hours_end must be greater than peak_hours_start')
        return v


class BatteryConstraints(BaseModel):
    """Constraints for battery optimization."""
    min_capacity_kwh: float = Field(ge=1, default=5)
    max_capacity_kwh: float = Field(le=10000, default=500)
    max_budget_eur: Optional[float] = Field(ge=0, default=None)
    max_payback_years: Optional[float] = Field(ge=0, default=None)
    min_npv: Optional[float] = None


class BatteryConfig(BaseModel):
    """Battery technical configuration."""
    capacity_kwh: float = Field(gt=0)
    max_power_kw: float = Field(gt=0)
    charge_efficiency: float = Field(ge=0.8, le=0.99, default=0.959)
    discharge_efficiency: float = Field(ge=0.8, le=0.99, default=0.959)
    min_soc: float = Field(ge=0, le=1, default=0.1)
    max_soc: float = Field(ge=0, le=1, default=0.9)
    degradation_rate: float = Field(ge=0, le=0.1, default=0.02)
    cycle_life: int = Field(gt=0, default=6000)
    price_per_kwh: float = Field(gt=0, default=450)


class AnalyzeRequest(BaseModel):
    """Request for profile analysis."""
    session_id: str
    column_mapping: ColumnMapping


class OptimizationRequest(BaseModel):
    """Request for battery optimization."""
    session_id: str
    tariffs: TariffStructure = Field(default_factory=TariffStructure)
    constraints: BatteryConstraints = Field(default_factory=BatteryConstraints)
    strategy: OptimizationStrategy = OptimizationStrategy.HYBRID
    analysis_years: int = Field(ge=1, le=25, default=10)
    discount_rate: float = Field(ge=0, le=0.3, default=0.05)


# === Output Models ===


class EnergyInterval(BaseModel):
    """Single energy measurement interval."""
    timestamp: datetime
    afname_kwh: float
    teruglevering_kwh: float = 0.0
    vermogen_kw: Optional[float] = None
    netto_kwh: float


class DataQualityReport(BaseModel):
    """Data quality analysis report."""
    total_rows: int
    valid_rows: int
    completeness: float  # 0-1
    outlier_percentage: float
    gaps_detected: int
    interpolated_points: int
    warnings: list[str]


class ParseResult(BaseModel):
    """Result of file parsing."""
    success: bool
    session_id: str
    headers: list[str]
    detected_mapping: Optional[ColumnMapping] = None
    row_count: int
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None
    detected_interval_minutes: int
    preview: list[dict]
    data_quality: DataQualityReport
    warnings: list[str]
    error: Optional[str] = None


class HourlyProfile(BaseModel):
    """Hourly aggregated profile data."""
    hour: int
    avg_afname_kw: float
    avg_teruglevering_kw: float
    peak_afname_kw: float
    std_dev: float


class ProfileAnalysis(BaseModel):
    """Complete profile analysis results."""
    total_afname_kwh: float
    total_teruglevering_kwh: float
    netto_verbruik_kwh: float
    peak_afname_kw: float
    avg_afname_kw: float
    baseload_kw: float
    load_factor: float
    peak_hours: list[int]
    hourly_profile: list[HourlyProfile]
    monthly_totals: dict[str, float]
    has_solar_data: bool
    data_days: int
    recommendations: list[str]


class AnalysisResult(BaseModel):
    """Result of profile analysis."""
    success: bool
    session_id: str
    analysis: Optional[ProfileAnalysis] = None
    error: Optional[str] = None


class SimulationSummary(BaseModel):
    """Summary of battery simulation results."""
    total_energy_savings_kwh: float
    total_cost_savings_eur: float
    peak_reduction_kw: float
    peak_savings_eur_year: float
    self_consumption_increase: float
    cycles_per_year: float
    strategy_breakdown: dict[str, float]


class FinancialAnalysis(BaseModel):
    """Financial analysis of battery investment."""
    capex: float
    annual_savings: float
    simple_payback_years: float
    npv: float
    irr: Optional[float] = None
    lcoe: float
    roi: float


class BatteryScenario(BaseModel):
    """Complete battery scenario with simulation and financials."""
    capacity_kwh: float
    max_power_kw: float
    config: BatteryConfig
    simulation: SimulationSummary
    financials: FinancialAnalysis
    is_optimal: bool = False


class SensitivityPoint(BaseModel):
    """Single point in sensitivity analysis."""
    parameter: str
    variation: float
    npv: float


class OptimizationResult(BaseModel):
    """Complete optimization result."""
    success: bool
    optimal: Optional[BatteryScenario] = None
    alternatives: list[BatteryScenario] = []
    sensitivity_analysis: list[SensitivityPoint] = []
    computation_time_seconds: float = 0
    methodology_notes: str = ""
    error: Optional[str] = None
