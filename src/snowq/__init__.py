"""Query ServiceNow using an SSO browser session."""

from .client import SessionExpired, SnowClient

__all__ = ["SnowClient", "SessionExpired"]
__version__ = "0.1.0"
