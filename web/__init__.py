"""Web API package for AksaraSight."""

from web.app import create_app, enforce_loopback_host

__all__ = ["create_app", "enforce_loopback_host"]
