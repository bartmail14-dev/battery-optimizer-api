"""Static data mappings and rates."""

from app.services.data.postcode_mapping import get_netbeheerder
from app.services.data.acm_tarieven import get_tarieven, ACM_TARIEVEN_2025

__all__ = ["get_netbeheerder", "get_tarieven", "ACM_TARIEVEN_2025"]
