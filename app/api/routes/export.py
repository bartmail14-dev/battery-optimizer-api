"""Export endpoints for reports and data."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import structlog
import pandas as pd
from io import BytesIO
from datetime import datetime

from app.api.routes.upload import SESSIONS

router = APIRouter()
logger = structlog.get_logger()


@router.get("/export/{session_id}/csv")
async def export_results_csv(session_id: str):
    """Export optimization results as CSV."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'optimization_result' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Geen optimalisatie resultaat beschikbaar."
        )

    result = SESSIONS[session_id]['optimization_result']

    # Create DataFrame with all scenarios
    scenarios_data = []

    if result.optimal:
        scenarios_data.append({
            'Capaciteit (kWh)': result.optimal.capacity_kwh,
            'Vermogen (kW)': result.optimal.max_power_kw,
            'CAPEX (EUR)': result.optimal.financials.capex,
            'Jaarlijkse besparing (EUR)': result.optimal.financials.annual_savings,
            'Terugverdientijd (jaar)': result.optimal.financials.simple_payback_years,
            'NPV (EUR)': result.optimal.financials.npv,
            'IRR': result.optimal.financials.irr,
            'Piekvermindering (kW)': result.optimal.simulation.peak_reduction_kw,
            'Cycli/jaar': result.optimal.simulation.cycles_per_year,
            'Optimaal': 'Ja'
        })

    for alt in result.alternatives:
        scenarios_data.append({
            'Capaciteit (kWh)': alt.capacity_kwh,
            'Vermogen (kW)': alt.max_power_kw,
            'CAPEX (EUR)': alt.financials.capex,
            'Jaarlijkse besparing (EUR)': alt.financials.annual_savings,
            'Terugverdientijd (jaar)': alt.financials.simple_payback_years,
            'NPV (EUR)': alt.financials.npv,
            'IRR': alt.financials.irr,
            'Piekvermindering (kW)': alt.simulation.peak_reduction_kw,
            'Cycli/jaar': alt.simulation.cycles_per_year,
            'Optimaal': 'Nee'
        })

    df = pd.DataFrame(scenarios_data)

    # Create CSV in memory
    output = BytesIO()
    df.to_csv(output, index=False, sep=';', decimal=',')
    output.seek(0)

    filename = f"battery_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/{session_id}/xlsx")
async def export_results_xlsx(session_id: str):
    """Export optimization results as Excel file."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'optimization_result' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Geen optimalisatie resultaat beschikbaar."
        )

    result = SESSIONS[session_id]['optimization_result']

    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Summary sheet
        if result.optimal:
            summary_data = {
                'Parameter': [
                    'Optimale capaciteit (kWh)',
                    'Optimaal vermogen (kW)',
                    'CAPEX (EUR)',
                    'Jaarlijkse besparing (EUR)',
                    'Terugverdientijd (jaar)',
                    'NPV 10 jaar (EUR)',
                    'IRR',
                    'Piekvermindering (kW)',
                    'Cycli per jaar'
                ],
                'Waarde': [
                    result.optimal.capacity_kwh,
                    result.optimal.max_power_kw,
                    result.optimal.financials.capex,
                    result.optimal.financials.annual_savings,
                    result.optimal.financials.simple_payback_years,
                    result.optimal.financials.npv,
                    f"{result.optimal.financials.irr:.1%}" if result.optimal.financials.irr else "N/A",
                    result.optimal.simulation.peak_reduction_kw,
                    result.optimal.simulation.cycles_per_year
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Samenvatting', index=False)

        # All scenarios sheet
        scenarios_data = []
        all_scenarios = ([result.optimal] if result.optimal else []) + result.alternatives

        for s in all_scenarios:
            scenarios_data.append({
                'Capaciteit (kWh)': s.capacity_kwh,
                'Vermogen (kW)': s.max_power_kw,
                'CAPEX (EUR)': s.financials.capex,
                'Besparing/jaar (EUR)': s.financials.annual_savings,
                'Terugverdientijd (jaar)': s.financials.simple_payback_years,
                'NPV (EUR)': s.financials.npv,
                'IRR': s.financials.irr,
                'ROI': s.financials.roi,
                'LCOE (EUR/kWh)': s.financials.lcoe,
                'Piekvermindering (kW)': s.simulation.peak_reduction_kw,
                'Cycli/jaar': s.simulation.cycles_per_year,
                'Is Optimaal': 'Ja' if s.is_optimal else 'Nee'
            })

        pd.DataFrame(scenarios_data).to_excel(writer, sheet_name='Alle Scenarios', index=False)

        # Sensitivity sheet
        if result.sensitivity_analysis:
            sensitivity_data = [
                {
                    'Parameter': s.parameter,
                    'Variatie': f"{s.variation:.0%}",
                    'NPV (EUR)': s.npv
                }
                for s in result.sensitivity_analysis
            ]
            pd.DataFrame(sensitivity_data).to_excel(writer, sheet_name='Gevoeligheidsanalyse', index=False)

    output.seek(0)
    filename = f"battery_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/{session_id}/profile")
async def export_profile_data(session_id: str):
    """Export normalized profile data."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd."
        )

    df = SESSIONS[session_id]['normalized_df'].copy()
    df['timestamp'] = df['timestamp'].astype(str)

    output = BytesIO()
    df.to_csv(output, index=False, sep=';', decimal=',')
    output.seek(0)

    filename = f"energy_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
