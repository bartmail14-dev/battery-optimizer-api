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


# === Revenue Stream Models ===


class RevenueStreamType(str, Enum):
    """Available revenue streams."""
    PEAK_SHAVING = "peak_shaving"
    SELF_CONSUMPTION = "self_consumption"
    ARBITRAGE = "arbitrage"
    IMBALANCE = "imbalance"
    GOPACS = "gopacs"
    FCR = "fcr"
    AFRR = "afrr"


class QualificationStatus(str, Enum):
    """Qualification status for revenue stream."""
    QUALIFIED = "qualified"
    PARTIAL = "partial"
    NOT_QUALIFIED = "not_qualified"


class RevenueStreamResult(BaseModel):
    """Result of single revenue stream calculation."""
    stream_type: str
    annual_revenue_eur: float
    utilization_hours: float
    capacity_required_kw: float
    qualification_status: str
    confidence_level: float
    methodology: str
    assumptions: list[str] = []
    warnings: list[str] = []


class MultiRevenueResult(BaseModel):
    """Combined revenue stream results."""
    streams: dict[str, RevenueStreamResult]
    total_stacked_revenue: float
    realistic_combined_revenue: float
    revenue_at_risk: float
    battery_utilization_percent: float
    recommended_streams: list[str]


# === Growth Scenario Models ===


class GrowthScenarioType(str, Enum):
    """Growth scenario types."""
    BASELINE = "baseline"
    MODERATE = "moderate"
    HIGH = "high"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class GrowthScenarioConfig(BaseModel):
    """Configuration for growth scenario."""
    scenario_type: GrowthScenarioType = GrowthScenarioType.BASELINE
    projection_years: int = Field(ge=5, le=20, default=10)
    custom_consumption_growth: Optional[float] = None
    custom_peak_growth: Optional[float] = None


class ProjectedYear(BaseModel):
    """Projection for single year."""
    year: int
    consumption_kwh: float
    peak_kw: float
    growth_factor_consumption: float
    growth_factor_peak: float


class GrowthProjectionResult(BaseModel):
    """Growth scenario projection result."""
    scenario_name: str
    scenario_type: str
    base_year: int
    projection_years: int
    yearly_projections: list[ProjectedYear]
    final_consumption_kwh: float
    final_peak_kw: float
    total_consumption_growth_percent: float
    total_peak_growth_percent: float


# === Sizing Advisor Models ===


class SizingTier(str, Enum):
    """Sizing recommendation tiers."""
    MINIMUM = "minimum"
    OPTIMAL = "optimal"
    STRATEGIC = "strategic"


class SizingRecommendationSchema(BaseModel):
    """Single sizing recommendation."""
    tier: str
    capacity_kwh: float
    max_power_kw: float
    capex_eur: float
    annual_savings_eur: float
    npv_eur: float
    payback_years: float
    irr_percent: Optional[float]
    probability_positive_npv: float
    peak_reduction_kw: float
    cycles_per_year: float
    battery_utilization_percent: float
    revenue_streams: dict[str, float]
    enabled_streams: list[str]
    rationale: str
    growth_buffer_years: int
    assumptions: list[str] = []
    warnings: list[str] = []


class SizingRecommendationsSchema(BaseModel):
    """Complete sizing recommendations."""
    minimum: SizingRecommendationSchema
    optimal: SizingRecommendationSchema
    strategic: SizingRecommendationSchema
    profile_summary: dict
    analysis_date: str
    methodology_notes: str


# === Validation Models ===


class ValidationSeverity(str, Enum):
    """Validation warning severity."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationWarning(BaseModel):
    """Single validation warning."""
    code: str
    severity: ValidationSeverity
    message: str
    field: Optional[str] = None
    benchmark_range: Optional[tuple[float, float]] = None
    actual_value: Optional[float] = None
    recommendation: Optional[str] = None


class ValidationReport(BaseModel):
    """Complete validation report."""
    is_realistic: bool
    confidence_score: float
    warnings: list[ValidationWarning]
    benchmark_comparison: dict


# === Chart Response Models ===


class ChartData(BaseModel):
    """Base64 encoded chart data."""
    chart_type: str
    image_base64: str
    title: str
    alt_text: str


class AnalysisWithChartsResponse(BaseModel):
    """Analysis response including charts."""
    success: bool
    summary: dict
    scenarios: list[dict]
    sizing_advice: Optional[SizingRecommendationsSchema] = None
    revenue_breakdown: Optional[MultiRevenueResult] = None
    growth_projections: Optional[dict[str, GrowthProjectionResult]] = None
    validation: Optional[ValidationReport] = None
    charts: dict[str, str] = {}  # chart_type -> base64 PNG
    error: Optional[str] = None
