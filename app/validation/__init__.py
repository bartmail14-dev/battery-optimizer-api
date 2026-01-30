"""
===============================================================================
VALIDATION MODULE
===============================================================================

Validatie en sanity checks voor batterij-optimalisatie.

Dit module bevat:
- Input validatie (data quality, format)
- Sanity checks (realistische waarden)
- Benchmark validatie (tegen industrie-standaarden)

REFERENTIES:
- NREL ATB 2024 benchmarks
- Lazard LCOS v9.0 ranges
- IEC 62933 standaarden
===============================================================================
"""

from .sanity_checks import SanityChecker, ValidationResult

__all__ = ['SanityChecker', 'ValidationResult']
