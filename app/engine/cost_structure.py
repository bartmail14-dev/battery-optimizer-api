"""
===============================================================================
COMPLETE COST STRUCTURE FOR BATTERY INVESTMENTS
===============================================================================

This module provides a complete, transparent cost structure for battery
investment business cases, including often-overlooked costs.

SOURCES:
- DNV GL (2023): "Battery Energy Storage Systems for Grid Applications"
- Fraunhofer ISE (2024): "Batteriespeicher in der Industrie"
- BloombergNEF (2024): "Battery Pack Prices"
- Industry interviews and project data

IMPORTANT: These are DEFAULT ESTIMATES. Actual costs vary significantly
based on project specifics. Always validate with actual quotes.
===============================================================================
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import math

import structlog

logger = structlog.get_logger()


class CostCategory(str, Enum):
    """Categories of costs in a battery investment."""
    BATTERY_SYSTEM = "battery_system"
    INSTALLATION = "installation"
    GRID_CONNECTION = "grid_connection"
    PERMITS = "permits"
    PROJECT_MANAGEMENT = "project_management"
    MAINTENANCE = "maintenance"
    INSURANCE = "insurance"
    END_OF_LIFE = "end_of_life"
    CONTINGENCY = "contingency"


@dataclass
class CostItem:
    """A single cost item with source attribution."""
    category: CostCategory
    name: str
    value: float
    unit: str
    is_annual: bool  # True for OPEX, False for CAPEX
    source: str
    notes: str = ""
    confidence: str = "medium"  # low, medium, high


@dataclass
class CostEstimate:
    """Complete cost estimate with all items itemized."""
    # Summary totals
    total_capex: float
    total_annual_opex: float
    total_lifetime_cost: float

    # Itemized costs
    capex_items: List[CostItem]
    opex_items: List[CostItem]

    # Project parameters
    battery_capacity_kwh: float
    battery_power_kw: float
    project_years: int

    # Metadata
    currency: str = "EUR"
    estimation_date: str = ""
    methodology_version: str = "1.0"
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# COST PARAMETERS (with sources)
# =============================================================================

# Battery system costs - Source: BloombergNEF 2024, industry quotes
BATTERY_COSTS = {
    "lfp_pack_per_kwh": {
        "value": 140,  # EUR/kWh
        "range": (120, 180),
        "source": "BloombergNEF Battery Price Survey 2024",
        "trend": "declining ~10% per year",
    },
    "nmc_pack_per_kwh": {
        "value": 160,
        "range": (140, 200),
        "source": "BloombergNEF Battery Price Survey 2024",
        "trend": "declining ~8% per year",
    },
    "bms_per_kwh": {
        "value": 15,
        "range": (10, 25),
        "source": "Industry average",
    },
    "inverter_per_kw": {
        "value": 80,
        "range": (60, 120),
        "source": "Solar Edge, SMA price lists 2024",
    },
    "thermal_management_per_kwh": {
        "value": 10,
        "range": (5, 20),
        "source": "DNV GL BESS cost breakdown 2023",
    },
    "enclosure_container_per_kwh": {
        "value": 25,
        "range": (15, 40),
        "source": "Industry quotes",
    },
}

# Installation costs - Source: DNV GL, Fraunhofer ISE
INSTALLATION_COSTS = {
    "civil_works_per_kwh": {
        "value": 15,
        "range": (10, 25),
        "source": "Fraunhofer ISE 2024",
        "note": "Foundation, fencing, access roads",
    },
    "electrical_installation_per_kw": {
        "value": 50,
        "range": (30, 80),
        "source": "DNV GL project database",
        "note": "Cabling, switchgear, protection",
    },
    "commissioning_flat": {
        "value": 5000,
        "range": (3000, 10000),
        "source": "Industry average",
        "note": "Testing, documentation, handover",
    },
}

# Grid connection costs - Source: ACM, Netbeheerders
GRID_COSTS = {
    "connection_study_flat": {
        "value": 2500,
        "range": (1500, 5000),
        "source": "Netbeheerders tarievenbladen",
    },
    "connection_upgrade_per_kw": {
        "value": 30,
        "range": (0, 100),
        "source": "ACM Tarievenbesluit 2024",
        "note": "Only if capacity increase needed",
    },
    "transformer_upgrade_flat": {
        "value": 15000,
        "range": (10000, 50000),
        "source": "Industry estimates",
        "note": "Only if required",
    },
}

# Permits and studies - Source: RVO, gemeente tarieven
PERMIT_COSTS = {
    "omgevingsvergunning_flat": {
        "value": 3000,
        "range": (500, 10000),
        "source": "Gemeente tarieven 2024",
        "note": "Varies by municipality and project size",
    },
    "fire_safety_assessment_flat": {
        "value": 5000,
        "range": (2000, 15000),
        "source": "Brandweer Nederland",
        "note": "Required for Li-ion storage >50 kWh",
    },
    "environmental_study_flat": {
        "value": 2000,
        "range": (1000, 5000),
        "source": "MER consultants",
        "note": "Only for larger installations",
    },
}

# Project management - Source: Industry standard
PROJECT_MANAGEMENT_COSTS = {
    "engineering_pct_capex": {
        "value": 0.05,  # 5% of equipment CAPEX
        "range": (0.03, 0.08),
        "source": "DNV GL project analysis",
    },
    "project_management_pct_capex": {
        "value": 0.08,  # 8% of total CAPEX
        "range": (0.05, 0.12),
        "source": "Industry standard",
        "note": "Includes contractor management, QA",
    },
}

# Annual OPEX - Source: DNV GL, O&M contracts
ANNUAL_OPEX = {
    "maintenance_per_kwh_year": {
        "value": 5,  # EUR/kWh/year
        "range": (3, 10),
        "source": "DNV GL O&M cost study 2023",
        "note": "Preventive maintenance, inspections",
    },
    "monitoring_per_kw_year": {
        "value": 2,
        "range": (1, 5),
        "source": "SCADA/EMS providers",
        "note": "Remote monitoring, data services",
    },
    "insurance_pct_capex_year": {
        "value": 0.005,  # 0.5% of CAPEX per year
        "range": (0.003, 0.01),
        "source": "Insurance brokers (Aon, Marsh)",
        "note": "All-risk including fire, theft, business interruption",
    },
    "grid_fees_per_kw_year": {
        "value": 10,
        "range": (5, 20),
        "source": "ACM Tarievenbesluit",
        "note": "Standing charges for grid connection",
    },
}

# End-of-life costs - Source: EU Battery Regulation, recyclers
END_OF_LIFE_COSTS = {
    "recycling_per_kwh": {
        "value": 50,
        "range": (30, 100),
        "source": "EU Battery Regulation impact assessment",
        "note": "Expected cost by 2030, currently producer responsibility",
    },
    "decommissioning_per_kw": {
        "value": 20,
        "range": (10, 40),
        "source": "Fraunhofer ISE end-of-life analysis",
        "note": "Removal, transport, site restoration",
    },
    "residual_value_pct_capex": {
        "value": 0.05,  # 5% of original CAPEX
        "range": (0, 0.15),
        "source": "Industry estimates",
        "note": "May be higher if second-life market develops",
    },
}

# Contingency - Source: Project management best practice
CONTINGENCY = {
    "capex_contingency_pct": {
        "value": 0.10,  # 10% contingency
        "range": (0.05, 0.20),
        "source": "PMI project risk management",
        "note": "Higher for novel technology or complex sites",
    },
}


class CostEstimator:
    """
    Estimates complete costs for battery storage investments.

    All costs are itemized with sources for full transparency.
    """

    def __init__(
        self,
        project_years: int = 15,
        include_contingency: bool = True,
        battery_chemistry: str = "LFP"
    ):
        self.project_years = project_years
        self.include_contingency = include_contingency
        self.battery_chemistry = battery_chemistry

    def estimate_capex(
        self,
        capacity_kwh: float,
        power_kw: float,
        needs_grid_upgrade: bool = False,
        needs_transformer: bool = False
    ) -> tuple[float, List[CostItem]]:
        """
        Estimate all CAPEX components.

        Returns:
            Tuple of (total_capex, list of CostItems)
        """
        items = []

        # Battery system
        battery_cost = BATTERY_COSTS["lfp_pack_per_kwh" if self.battery_chemistry == "LFP" else "nmc_pack_per_kwh"]
        items.append(CostItem(
            category=CostCategory.BATTERY_SYSTEM,
            name="Batterijpakket",
            value=capacity_kwh * battery_cost["value"],
            unit="EUR",
            is_annual=False,
            source=battery_cost["source"],
            notes=f"{battery_cost['value']} EUR/kWh"
        ))

        items.append(CostItem(
            category=CostCategory.BATTERY_SYSTEM,
            name="Battery Management System (BMS)",
            value=capacity_kwh * BATTERY_COSTS["bms_per_kwh"]["value"],
            unit="EUR",
            is_annual=False,
            source=BATTERY_COSTS["bms_per_kwh"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.BATTERY_SYSTEM,
            name="Omvormer/Inverter",
            value=power_kw * BATTERY_COSTS["inverter_per_kw"]["value"],
            unit="EUR",
            is_annual=False,
            source=BATTERY_COSTS["inverter_per_kw"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.BATTERY_SYSTEM,
            name="Thermisch management",
            value=capacity_kwh * BATTERY_COSTS["thermal_management_per_kwh"]["value"],
            unit="EUR",
            is_annual=False,
            source=BATTERY_COSTS["thermal_management_per_kwh"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.BATTERY_SYSTEM,
            name="Behuizing/Container",
            value=capacity_kwh * BATTERY_COSTS["enclosure_container_per_kwh"]["value"],
            unit="EUR",
            is_annual=False,
            source=BATTERY_COSTS["enclosure_container_per_kwh"]["source"],
        ))

        # Installation
        items.append(CostItem(
            category=CostCategory.INSTALLATION,
            name="Civiele werken",
            value=capacity_kwh * INSTALLATION_COSTS["civil_works_per_kwh"]["value"],
            unit="EUR",
            is_annual=False,
            source=INSTALLATION_COSTS["civil_works_per_kwh"]["source"],
            notes=INSTALLATION_COSTS["civil_works_per_kwh"]["note"],
        ))

        items.append(CostItem(
            category=CostCategory.INSTALLATION,
            name="Elektrische installatie",
            value=power_kw * INSTALLATION_COSTS["electrical_installation_per_kw"]["value"],
            unit="EUR",
            is_annual=False,
            source=INSTALLATION_COSTS["electrical_installation_per_kw"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.INSTALLATION,
            name="Inbedrijfstelling",
            value=INSTALLATION_COSTS["commissioning_flat"]["value"],
            unit="EUR",
            is_annual=False,
            source=INSTALLATION_COSTS["commissioning_flat"]["source"],
        ))

        # Grid connection
        items.append(CostItem(
            category=CostCategory.GRID_CONNECTION,
            name="Aansluitingsstudie",
            value=GRID_COSTS["connection_study_flat"]["value"],
            unit="EUR",
            is_annual=False,
            source=GRID_COSTS["connection_study_flat"]["source"],
        ))

        if needs_grid_upgrade:
            items.append(CostItem(
                category=CostCategory.GRID_CONNECTION,
                name="Netaansluiting upgrade",
                value=power_kw * GRID_COSTS["connection_upgrade_per_kw"]["value"],
                unit="EUR",
                is_annual=False,
                source=GRID_COSTS["connection_upgrade_per_kw"]["source"],
                notes=GRID_COSTS["connection_upgrade_per_kw"]["note"],
            ))

        if needs_transformer:
            items.append(CostItem(
                category=CostCategory.GRID_CONNECTION,
                name="Transformator upgrade",
                value=GRID_COSTS["transformer_upgrade_flat"]["value"],
                unit="EUR",
                is_annual=False,
                source=GRID_COSTS["transformer_upgrade_flat"]["source"],
            ))

        # Permits
        items.append(CostItem(
            category=CostCategory.PERMITS,
            name="Omgevingsvergunning",
            value=PERMIT_COSTS["omgevingsvergunning_flat"]["value"],
            unit="EUR",
            is_annual=False,
            source=PERMIT_COSTS["omgevingsvergunning_flat"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.PERMITS,
            name="Brandveiligheidsstudie",
            value=PERMIT_COSTS["fire_safety_assessment_flat"]["value"],
            unit="EUR",
            is_annual=False,
            source=PERMIT_COSTS["fire_safety_assessment_flat"]["source"],
            notes=PERMIT_COSTS["fire_safety_assessment_flat"]["note"],
        ))

        # Calculate equipment subtotal for percentage-based costs
        equipment_subtotal = sum(
            item.value for item in items
            if item.category == CostCategory.BATTERY_SYSTEM
        )

        # Project management
        items.append(CostItem(
            category=CostCategory.PROJECT_MANAGEMENT,
            name="Engineering",
            value=equipment_subtotal * PROJECT_MANAGEMENT_COSTS["engineering_pct_capex"]["value"],
            unit="EUR",
            is_annual=False,
            source=PROJECT_MANAGEMENT_COSTS["engineering_pct_capex"]["source"],
            notes=f"{PROJECT_MANAGEMENT_COSTS['engineering_pct_capex']['value']*100}% van equipment",
        ))

        subtotal = sum(item.value for item in items)

        items.append(CostItem(
            category=CostCategory.PROJECT_MANAGEMENT,
            name="Projectmanagement",
            value=subtotal * PROJECT_MANAGEMENT_COSTS["project_management_pct_capex"]["value"],
            unit="EUR",
            is_annual=False,
            source=PROJECT_MANAGEMENT_COSTS["project_management_pct_capex"]["source"],
            notes=f"{PROJECT_MANAGEMENT_COSTS['project_management_pct_capex']['value']*100}% van subtotaal",
        ))

        # Contingency
        if self.include_contingency:
            subtotal_with_pm = sum(item.value for item in items)
            items.append(CostItem(
                category=CostCategory.CONTINGENCY,
                name="Onvoorzien (contingency)",
                value=subtotal_with_pm * CONTINGENCY["capex_contingency_pct"]["value"],
                unit="EUR",
                is_annual=False,
                source=CONTINGENCY["capex_contingency_pct"]["source"],
                notes=f"{CONTINGENCY['capex_contingency_pct']['value']*100}% van totaal",
            ))

        total_capex = sum(item.value for item in items)
        return total_capex, items

    def estimate_annual_opex(
        self,
        capacity_kwh: float,
        power_kw: float,
        total_capex: float
    ) -> tuple[float, List[CostItem]]:
        """
        Estimate all annual OPEX components.

        Returns:
            Tuple of (total_annual_opex, list of CostItems)
        """
        items = []

        items.append(CostItem(
            category=CostCategory.MAINTENANCE,
            name="Preventief onderhoud",
            value=capacity_kwh * ANNUAL_OPEX["maintenance_per_kwh_year"]["value"],
            unit="EUR/jaar",
            is_annual=True,
            source=ANNUAL_OPEX["maintenance_per_kwh_year"]["source"],
            notes=ANNUAL_OPEX["maintenance_per_kwh_year"]["note"],
        ))

        items.append(CostItem(
            category=CostCategory.MAINTENANCE,
            name="Monitoring & dataservices",
            value=power_kw * ANNUAL_OPEX["monitoring_per_kw_year"]["value"],
            unit="EUR/jaar",
            is_annual=True,
            source=ANNUAL_OPEX["monitoring_per_kw_year"]["source"],
        ))

        items.append(CostItem(
            category=CostCategory.INSURANCE,
            name="Verzekering (all-risk)",
            value=total_capex * ANNUAL_OPEX["insurance_pct_capex_year"]["value"],
            unit="EUR/jaar",
            is_annual=True,
            source=ANNUAL_OPEX["insurance_pct_capex_year"]["source"],
            notes=f"{ANNUAL_OPEX['insurance_pct_capex_year']['value']*100}% van CAPEX",
        ))

        items.append(CostItem(
            category=CostCategory.MAINTENANCE,
            name="Netaansluitingskosten (vast)",
            value=power_kw * ANNUAL_OPEX["grid_fees_per_kw_year"]["value"],
            unit="EUR/jaar",
            is_annual=True,
            source=ANNUAL_OPEX["grid_fees_per_kw_year"]["source"],
        ))

        total_opex = sum(item.value for item in items)
        return total_opex, items

    def estimate_end_of_life(
        self,
        capacity_kwh: float,
        power_kw: float,
        total_capex: float
    ) -> tuple[float, List[CostItem]]:
        """
        Estimate end-of-life costs (recycling, decommissioning).

        Returns:
            Tuple of (net_eol_cost, list of CostItems)
        """
        items = []

        items.append(CostItem(
            category=CostCategory.END_OF_LIFE,
            name="Recycling batterijen",
            value=capacity_kwh * END_OF_LIFE_COSTS["recycling_per_kwh"]["value"],
            unit="EUR",
            is_annual=False,
            source=END_OF_LIFE_COSTS["recycling_per_kwh"]["source"],
            notes=END_OF_LIFE_COSTS["recycling_per_kwh"]["note"],
        ))

        items.append(CostItem(
            category=CostCategory.END_OF_LIFE,
            name="Ontmanteling",
            value=power_kw * END_OF_LIFE_COSTS["decommissioning_per_kw"]["value"],
            unit="EUR",
            is_annual=False,
            source=END_OF_LIFE_COSTS["decommissioning_per_kw"]["source"],
        ))

        # Residual value (negative cost = credit)
        residual = total_capex * END_OF_LIFE_COSTS["residual_value_pct_capex"]["value"]
        items.append(CostItem(
            category=CostCategory.END_OF_LIFE,
            name="Restwaarde (credit)",
            value=-residual,  # Negative = credit
            unit="EUR",
            is_annual=False,
            source=END_OF_LIFE_COSTS["residual_value_pct_capex"]["source"],
            notes=END_OF_LIFE_COSTS["residual_value_pct_capex"]["note"],
        ))

        net_eol = sum(item.value for item in items)
        return net_eol, items

    def estimate_complete(
        self,
        capacity_kwh: float,
        power_kw: float,
        needs_grid_upgrade: bool = False,
        needs_transformer: bool = False
    ) -> CostEstimate:
        """
        Generate complete cost estimate for battery investment.

        Returns:
            CostEstimate with all itemized costs
        """
        from datetime import datetime

        warnings = []

        # Validate inputs
        if capacity_kwh <= 0 or power_kw <= 0:
            raise ValueError("Capacity and power must be positive")

        c_rate = power_kw / capacity_kwh
        if c_rate > 2:
            warnings.append(f"Hoge C-rate ({c_rate:.1f}) - kan leiden tot versnelde degradatie")
        if c_rate < 0.25:
            warnings.append(f"Lage C-rate ({c_rate:.2f}) - batterij mogelijk over-gedimensioneerd")

        # Estimate all costs
        total_capex, capex_items = self.estimate_capex(
            capacity_kwh, power_kw, needs_grid_upgrade, needs_transformer
        )

        total_opex, opex_items = self.estimate_annual_opex(
            capacity_kwh, power_kw, total_capex
        )

        eol_cost, eol_items = self.estimate_end_of_life(
            capacity_kwh, power_kw, total_capex
        )

        # Calculate lifetime cost
        # NPV of OPEX over project life (simplified, no discounting)
        total_opex_lifetime = total_opex * self.project_years
        total_lifetime_cost = total_capex + total_opex_lifetime + eol_cost

        # Add warnings for high costs
        cost_per_kwh = total_capex / capacity_kwh
        if cost_per_kwh > 400:
            warnings.append(f"CAPEX ({cost_per_kwh:.0f} EUR/kWh) is hoog - controleer specifieke situatie")
        if cost_per_kwh < 200:
            warnings.append(f"CAPEX ({cost_per_kwh:.0f} EUR/kWh) is laag - controleer of alle kosten zijn meegenomen")

        logger.info(
            "Cost estimate completed",
            capacity_kwh=capacity_kwh,
            power_kw=power_kw,
            total_capex=round(total_capex),
            cost_per_kwh=round(cost_per_kwh),
            annual_opex=round(total_opex)
        )

        return CostEstimate(
            total_capex=round(total_capex, 2),
            total_annual_opex=round(total_opex, 2),
            total_lifetime_cost=round(total_lifetime_cost, 2),
            capex_items=capex_items,
            opex_items=opex_items + eol_items,  # Include EOL in OPEX for display
            battery_capacity_kwh=capacity_kwh,
            battery_power_kw=power_kw,
            project_years=self.project_years,
            estimation_date=datetime.now().isoformat(),
            warnings=warnings
        )


def get_cost_breakdown_summary(estimate: CostEstimate) -> Dict[str, Any]:
    """
    Generate a summary of costs by category.
    """
    capex_by_category = {}
    opex_by_category = {}

    for item in estimate.capex_items:
        cat = item.category.value
        capex_by_category[cat] = capex_by_category.get(cat, 0) + item.value

    for item in estimate.opex_items:
        cat = item.category.value
        opex_by_category[cat] = opex_by_category.get(cat, 0) + item.value

    return {
        "capex_breakdown": capex_by_category,
        "opex_breakdown": opex_by_category,
        "capex_per_kwh": round(estimate.total_capex / estimate.battery_capacity_kwh, 2),
        "capex_per_kw": round(estimate.total_capex / estimate.battery_power_kw, 2),
        "opex_per_kwh_year": round(estimate.total_annual_opex / estimate.battery_capacity_kwh, 2),
        "opex_pct_capex": round(estimate.total_annual_opex / estimate.total_capex * 100, 2),
    }
