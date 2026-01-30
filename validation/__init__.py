"""
Battery Optimizer Validation Suite
===================================

Dit pakket bevat alle validatie tests voor de Battery Optimizer.

Quick start:
    python validation/generate_report.py

Of individuele fasen:
    python validation/test_calculations.py   # Fase 1: Technische tests
    python validation/sensitivity_test.py    # Fase 2: Logische tests
    python validation/reality_check.py       # Fase 3: Realisme checks
    python validation/excel_verification.py  # Fase 4: Excel export
"""

from .test_calculations import run_all_tests, ValidationResult
from .sensitivity_test import run_all_sensitivity_tests, SensitivityResult
from .reality_check import run_reality_checks, RealityCheck, CheckStatus
from .excel_verification import export_to_excel
from .generate_report import run_full_validation

__all__ = [
    'run_all_tests',
    'run_all_sensitivity_tests',
    'run_reality_checks',
    'export_to_excel',
    'run_full_validation',
    'ValidationResult',
    'SensitivityResult',
    'RealityCheck',
    'CheckStatus',
]
