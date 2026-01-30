"""External API clients."""

from app.services.clients.entsoe import ENTSOEClient
from app.services.clients.tennet import TennetClient
from app.services.clients.netbeheer import NetbeheerClient
from app.services.clients.knmi import schat_pv_productie
from app.services.clients.fcr_afrr import FCRAFRRClient
from app.services.clients.gopacs import GOPACSClient

__all__ = [
    "ENTSOEClient",
    "TennetClient",
    "NetbeheerClient",
    "schat_pv_productie",
    "FCRAFRRClient",
    "GOPACSClient"
]
