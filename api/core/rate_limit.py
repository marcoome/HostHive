"""Rate limiter instance for the HostHive API."""
from slowapi import Limiter
from slowapi.util import get_remote_address
from api.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
)
