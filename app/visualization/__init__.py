"""
===============================================================================
VISUALIZATION MODULE
===============================================================================

Genereert professionele visualisaties voor batterij-analyses.

Alle charts worden gegenereerd als base64-encoded PNG voor eenvoudige
integratie met de frontend.

Beschikbare chart types:
- Monte Carlo fan chart (confidence intervals)
- NPV distribution histogram
- Revenue breakdown stacked bar
- Growth scenario comparison
- Sensitivity tornado chart
- Sizing recommendation comparison

TECHNOLOGIE:
- Matplotlib voor statische charts
- Seaborn voor styling
- Base64 encoding voor transport
===============================================================================
"""

from .charts import ChartGenerator

__all__ = ['ChartGenerator']
