"""
===============================================================================
PROGRESS EVENT TYPES FOR SSE STREAMING
===============================================================================

Event types en dataclasses voor real-time progress updates via Server-Sent Events.

Dit module definieert:
1. ProgressEventType - Enum met alle event types
2. ProgressEvent - Dataclass voor events
3. Helper functies voor SSE formatting
===============================================================================
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import json
import time
import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles numpy types."""

    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class ProgressEventType(Enum):
    """Event types voor progress updates."""

    # Lifecycle events
    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"

    # Phase events
    PHASE_START = "phase_start"
    PHASE_COMPLETE = "phase_complete"
    PHASE_UPDATE = "phase_update"

    # Progress events
    SIMULATION_PROGRESS = "simulation_progress"
    SCENARIO_PROGRESS = "scenario_progress"

    # Result events
    INTERMEDIATE_RESULT = "intermediate_result"
    SCENARIO_RESULT = "scenario_result"

    # Validation events
    VALIDATION_START = "validation_start"
    VALIDATION_CHECK = "validation_check"
    VALIDATION_COMPLETE = "validation_complete"

    # Info events
    LOG = "log"
    METRIC = "metric"


@dataclass
class ProgressEvent:
    """
    Event dat naar frontend wordt gestuurd via SSE.

    Attributes:
        type: Type of event (from ProgressEventType)
        timestamp: Unix timestamp when event occurred
        progress_percent: Overall progress (0-100)
        current_step: Current step number
        total_steps: Total number of steps
        phase: Current phase name
        scenario_kwh: Battery size being analyzed
        message: Human-readable message
        data: Additional event-specific data
    """

    type: ProgressEventType
    timestamp: float = field(default_factory=time.time)

    # Progress info
    progress_percent: Optional[float] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None

    # Context
    phase: Optional[str] = None
    scenario_kwh: Optional[float] = None
    message: Optional[str] = None

    # Data
    data: Optional[Dict[str, Any]] = None

    def to_sse(self) -> str:
        """Convert to SSE format string."""
        payload = {
            "type": self.type.value,
            "timestamp": self.timestamp,
        }

        # Add optional fields if present
        if self.progress_percent is not None:
            payload["progress_percent"] = round(self.progress_percent, 2)
        if self.current_step is not None:
            payload["current_step"] = self.current_step
        if self.total_steps is not None:
            payload["total_steps"] = self.total_steps
        if self.phase is not None:
            payload["phase"] = self.phase
        if self.scenario_kwh is not None:
            payload["scenario_kwh"] = self.scenario_kwh
        if self.message is not None:
            payload["message"] = self.message
        if self.data is not None:
            payload["data"] = self.data

        return f"data: {json.dumps(payload, cls=NumpyEncoder)}\n\n"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "type": self.type.value,
            "timestamp": self.timestamp,
        }

        if self.progress_percent is not None:
            result["progress_percent"] = self.progress_percent
        if self.current_step is not None:
            result["current_step"] = self.current_step
        if self.total_steps is not None:
            result["total_steps"] = self.total_steps
        if self.phase is not None:
            result["phase"] = self.phase
        if self.scenario_kwh is not None:
            result["scenario_kwh"] = self.scenario_kwh
        if self.message is not None:
            result["message"] = self.message
        if self.data is not None:
            result["data"] = self.data

        return result


def create_started_event(
    battery_sizes: List[float],
    n_simulations: int,
    profile_records: int
) -> ProgressEvent:
    """Create a STARTED event."""
    return ProgressEvent(
        type=ProgressEventType.STARTED,
        message="Analyse gestart",
        data={
            "scenarios": battery_sizes,
            "simulations_per_scenario": n_simulations,
            "total_simulations": len(battery_sizes) * n_simulations,
            "profile_records": profile_records,
        }
    )


def create_phase_event(
    phase: str,
    message: str,
    complete: bool = False,
    data: Optional[Dict] = None
) -> ProgressEvent:
    """Create a phase start/complete event."""
    return ProgressEvent(
        type=ProgressEventType.PHASE_COMPLETE if complete else ProgressEventType.PHASE_START,
        phase=phase,
        message=message,
        data=data
    )


def create_simulation_progress_event(
    scenario_kwh: float,
    current_sim: int,
    total_sims: int,
    scenario_idx: int,
    total_scenarios: int,
    intermediate_npv: Optional[float] = None,
    intermediate_std: Optional[float] = None,
) -> ProgressEvent:
    """Create a simulation progress event."""
    # Calculate overall progress
    overall_progress = (
        (scenario_idx * total_sims + current_sim) /
        (total_scenarios * total_sims)
    ) * 100

    data = {
        "simulations_complete": current_sim,
    }

    if intermediate_npv is not None:
        data["intermediate_npv_mean"] = round(intermediate_npv, 2)
    if intermediate_std is not None:
        data["intermediate_npv_std"] = round(intermediate_std, 2)
        data["convergence_indicator"] = round(intermediate_std / (current_sim ** 0.5), 2)

    return ProgressEvent(
        type=ProgressEventType.SIMULATION_PROGRESS,
        progress_percent=overall_progress,
        current_step=current_sim,
        total_steps=total_sims,
        scenario_kwh=scenario_kwh,
        phase="monte_carlo",
        message=f"Simulatie {current_sim}/{total_sims}",
        data=data
    )


def create_scenario_result_event(
    scenario_kwh: float,
    npv_mean: float,
    npv_p5: float,
    npv_p95: float,
    payback_mean: float,
    cycles_per_year: float
) -> ProgressEvent:
    """Create a scenario completion event."""
    return ProgressEvent(
        type=ProgressEventType.SCENARIO_RESULT,
        scenario_kwh=scenario_kwh,
        message=f"Scenario {scenario_kwh} kWh compleet",
        data={
            "npv_mean": round(npv_mean, 2),
            "npv_p5": round(npv_p5, 2),
            "npv_p95": round(npv_p95, 2),
            "payback_mean": round(payback_mean, 2),
            "cycles_per_year": round(cycles_per_year, 1),
        }
    )


def create_validation_check_event(
    check_name: str,
    passed: bool,
    message: str
) -> ProgressEvent:
    """Create a validation check event."""
    return ProgressEvent(
        type=ProgressEventType.VALIDATION_CHECK,
        phase="validation",
        message=f"Check: {check_name}",
        data={
            "check_name": check_name,
            "passed": passed,
            "message": message,
        }
    )


def create_completed_event(
    optimal_size_kwh: float,
    scenarios: List[Dict],
    validation_summary: Dict,
    revenue_breakdown: Optional[Dict] = None,
    growth_projections: Optional[Dict] = None,
    sizing_advice: Optional[Dict] = None,
    charts: Optional[Dict[str, str]] = None,
) -> ProgressEvent:
    """Create a completion event with final results including COMCAM features."""
    data = {
        "optimal_size_kwh": optimal_size_kwh,
        "scenarios": scenarios,
        "validation": validation_summary,
    }

    # Add COMCAM features if provided
    if revenue_breakdown is not None:
        data["revenue_breakdown"] = revenue_breakdown
    if growth_projections is not None:
        data["growth_projections"] = growth_projections
    if sizing_advice is not None:
        data["sizing_advice"] = sizing_advice
    if charts is not None:
        data["charts"] = charts

    return ProgressEvent(
        type=ProgressEventType.COMPLETED,
        progress_percent=100,
        message="Analyse compleet!",
        data=data
    )


def create_error_event(error: str, error_type: str = "Error") -> ProgressEvent:
    """Create an error event."""
    return ProgressEvent(
        type=ProgressEventType.ERROR,
        message=f"Fout: {error}",
        data={
            "error": error,
            "type": error_type,
        }
    )
