"""
Tests for the backtesting framework.
"""

import pytest
from datetime import datetime, date
import tempfile
import os

from app.engine.backtesting import (
    BacktestingFramework,
    HistoricalDataPoint,
    ProjectOutcome,
    ValidationMetric,
    DataSource,
    validate_prediction,
    INDUSTRY_BENCHMARKS,
    create_sample_validation_data,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def framework(temp_db):
    """Create a backtesting framework with temp database."""
    return BacktestingFramework(db_path=temp_db)


class TestHistoricalDataPoint:
    """Tests for HistoricalDataPoint class."""

    def test_absolute_error(self):
        """Test absolute error calculation."""
        dp = HistoricalDataPoint(
            timestamp=datetime.now(),
            metric=ValidationMetric.PEAK_PREDICTION,
            source=DataSource.PROJECT_ACTUAL,
            predicted_value=100,
            actual_value=90,
            unit="kW"
        )
        assert dp.absolute_error == 10

    def test_percentage_error(self):
        """Test percentage error calculation."""
        dp = HistoricalDataPoint(
            timestamp=datetime.now(),
            metric=ValidationMetric.SAVINGS_PREDICTION,
            source=DataSource.PROJECT_ACTUAL,
            predicted_value=110,
            actual_value=100,
            unit="EUR"
        )
        assert dp.percentage_error == 0.1  # 10%

    def test_percentage_error_zero_actual(self):
        """Test percentage error when actual is zero."""
        dp = HistoricalDataPoint(
            timestamp=datetime.now(),
            metric=ValidationMetric.SAVINGS_PREDICTION,
            source=DataSource.PROJECT_ACTUAL,
            predicted_value=100,
            actual_value=0,
            unit="EUR"
        )
        assert dp.percentage_error == 1.0

    def test_relative_error_positive_bias(self):
        """Test relative error with positive bias (overprediction)."""
        dp = HistoricalDataPoint(
            timestamp=datetime.now(),
            metric=ValidationMetric.NPV_PREDICTION,
            source=DataSource.PROJECT_ACTUAL,
            predicted_value=120,
            actual_value=100,
            unit="EUR"
        )
        assert dp.relative_error == 0.2  # 20% overprediction


class TestProjectOutcome:
    """Tests for ProjectOutcome class."""

    def test_accuracy_calculation(self):
        """Test accuracy metrics calculation."""
        outcome = ProjectOutcome(
            project_id="TEST-001",
            project_name="Test Project",
            battery_capacity_kwh=100,
            battery_power_kw=50,
            installation_date=date(2023, 1, 1),
            measurement_period_months=12,
            predicted_annual_savings=15000,
            predicted_peak_reduction_kw=35,
            predicted_payback_years=8.0,
            predicted_npv=25000,
            actual_annual_savings=14000,
            actual_peak_reduction_kw=30,
        )

        accuracy = outcome.calculate_accuracy()

        # Savings error: |15000 - 14000| / 14000 * 100 = 7.14%
        assert abs(accuracy["savings_error_percent"] - 7.14) < 0.1

        # Peak error: |35 - 30| / 30 * 100 = 16.67%
        assert abs(accuracy["peak_error_percent"] - 16.67) < 0.1

        # Bias should be positive (overprediction)
        assert accuracy["savings_bias"] > 0


class TestBacktestingFramework:
    """Tests for BacktestingFramework class."""

    def test_init_creates_database(self, temp_db):
        """Test that initialization creates database tables."""
        framework = BacktestingFramework(db_path=temp_db)
        assert os.path.exists(temp_db)

    def test_add_historical_datapoint(self, framework):
        """Test adding historical data points."""
        dp = HistoricalDataPoint(
            timestamp=datetime(2023, 6, 15),
            metric=ValidationMetric.PEAK_PREDICTION,
            source=DataSource.PROJECT_ACTUAL,
            predicted_value=100,
            actual_value=95,
            unit="kW"
        )

        framework.add_historical_datapoint(dp)
        assert len(framework.data_points) == 1

    def test_add_project_outcome(self, framework):
        """Test adding project outcomes."""
        outcome = ProjectOutcome(
            project_id="TEST-002",
            project_name="Test Project 2",
            battery_capacity_kwh=200,
            battery_power_kw=100,
            installation_date=date(2023, 6, 1),
            measurement_period_months=6,
            predicted_annual_savings=30000,
            predicted_peak_reduction_kw=70,
            predicted_payback_years=7.5,
            predicted_npv=50000,
        )

        framework.add_project_outcome(outcome)
        assert len(framework.project_outcomes) == 1

    def test_run_backtest_insufficient_data(self, framework):
        """Test that backtest fails with insufficient data."""
        # Add only 2 data points (need at least 3)
        for i in range(2):
            dp = HistoricalDataPoint(
                timestamp=datetime(2023, i + 1, 1),
                metric=ValidationMetric.PEAK_PREDICTION,
                source=DataSource.PROJECT_ACTUAL,
                predicted_value=100 + i,
                actual_value=95 + i,
                unit="kW"
            )
            framework.add_historical_datapoint(dp)

        with pytest.raises(ValueError, match="Insufficient data"):
            framework.run_backtest(ValidationMetric.PEAK_PREDICTION)

    def test_run_backtest_with_sufficient_data(self, framework):
        """Test successful backtest with sufficient data."""
        # Add 10 data points with known errors
        for i in range(10):
            dp = HistoricalDataPoint(
                timestamp=datetime(2023, (i % 12) + 1, 15),
                metric=ValidationMetric.SAVINGS_PREDICTION,
                source=DataSource.PROJECT_ACTUAL,
                predicted_value=10000 + (i * 100),  # Slight overprediction
                actual_value=10000,
                unit="EUR"
            )
            framework.add_historical_datapoint(dp)

        result = framework.run_backtest(ValidationMetric.SAVINGS_PREDICTION)

        assert result.sample_size == 10
        assert result.mean_absolute_error > 0
        assert result.mean_percentage_error > 0
        assert result.accuracy_rating in [
            "Excellent", "Good", "Acceptable", "Fair", "Poor - Recalibration Needed"
        ]

    def test_validate_against_benchmarks_normal(self, framework):
        """Test benchmark validation with normal values."""
        predicted = {
            "payback_years": 9.0,
            "npv_per_kwh": 30,
            "cycles_per_year": 280,
        }

        result = framework.validate_against_benchmarks(
            predicted,
            "peak_shaving_commercial"
        )

        assert result["confidence_score"] > 0.8
        assert len(result["warnings"]) == 0
        assert result["within_range"]["payback_years"] is True

    def test_validate_against_benchmarks_optimistic(self, framework):
        """Test benchmark validation with overly optimistic values."""
        predicted = {
            "payback_years": 3.0,  # Way too fast
            "npv_per_kwh": 200,    # Way too high
            "cycles_per_year": 600,  # Too many cycles
        }

        result = framework.validate_against_benchmarks(
            predicted,
            "peak_shaving_commercial"
        )

        assert result["confidence_score"] < 0.7
        assert len(result["warnings"]) >= 2
        assert result["within_range"]["payback_years"] is False


class TestValidatePrediction:
    """Tests for the convenience validate_prediction function."""

    def test_validate_commercial_peak_shaving(self):
        """Test validation for commercial peak shaving."""
        result = validate_prediction(
            {"payback_years": 10, "npv_per_kwh": 20},
            sector="commercial",
            revenue_model="peak_shaving"
        )

        assert "benchmark_source" in result
        assert "confidence_score" in result

    def test_validate_industrial(self):
        """Test validation for industrial sector."""
        result = validate_prediction(
            {"payback_years": 7, "npv_per_kwh": 80},
            sector="industrial",
            revenue_model="peak_shaving"
        )

        assert result["benchmark_type"] == "peak_shaving_industrial"

    def test_validate_multi_revenue(self):
        """Test validation for multi-revenue model."""
        result = validate_prediction(
            {"payback_years": 6, "npv_per_kwh": 100},
            sector="commercial",
            revenue_model="multi_revenue"
        )

        assert result["benchmark_type"] == "multi_revenue_commercial"


class TestIndustryBenchmarks:
    """Tests for industry benchmark data."""

    def test_benchmarks_have_required_fields(self):
        """Test that all benchmarks have required fields."""
        required_fields = [
            "source",
            "typical_reduction_percent",
            "payback_years",
            "npv_per_kwh_installed",
            "cycles_per_year",
        ]

        for benchmark_name, benchmark in INDUSTRY_BENCHMARKS.items():
            for field in required_fields:
                assert field in benchmark, f"Missing {field} in {benchmark_name}"

    def test_benchmark_ranges_are_valid(self):
        """Test that benchmark ranges have valid min/max."""
        for benchmark_name, benchmark in INDUSTRY_BENCHMARKS.items():
            for field in ["payback_years", "cycles_per_year"]:
                low, high = benchmark[field]
                assert low < high, f"Invalid range for {field} in {benchmark_name}"


class TestSampleDataGeneration:
    """Tests for sample data generation."""

    def test_create_sample_data(self, framework):
        """Test that sample data can be created."""
        create_sample_validation_data(framework)

        assert len(framework.data_points) > 0
        assert len(framework.project_outcomes) > 0

    def test_sample_data_allows_backtest(self, framework):
        """Test that sample data enables backtesting."""
        create_sample_validation_data(framework)

        result = framework.run_backtest(ValidationMetric.PEAK_PREDICTION)

        assert result.sample_size >= 10
        assert result.accuracy_rating is not None


class TestAccuracyReport:
    """Tests for the accuracy report generation."""

    def test_report_with_no_data(self, framework):
        """Test report generation with no data."""
        report = framework.get_historical_accuracy_report()

        assert report["overall_model_health"]["status"] == "INSUFFICIENT_DATA"
        assert len(report["recommendations"]) > 0

    def test_report_with_sample_data(self, framework):
        """Test report generation with sample data."""
        create_sample_validation_data(framework)

        # Run a backtest first to populate results
        framework.run_backtest(ValidationMetric.PEAK_PREDICTION)

        report = framework.get_historical_accuracy_report()

        assert "generated_at" in report
        assert "metric_statistics" in report
        assert "project_validation" in report
        assert "overall_model_health" in report
        assert report["overall_model_health"]["total_validation_points"] > 0
