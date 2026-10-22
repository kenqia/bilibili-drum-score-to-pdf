"""Public automatic conversion boundary, shared by CLI and service."""
from .core import ConversionError, convert

__all__ = ['ConversionError', 'convert']
