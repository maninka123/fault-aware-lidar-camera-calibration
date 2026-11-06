"""Experimental geometry-conditioned fault diagnosis; no hardware access."""
from .config import SignatureConfig
from .runner import diagnose_v3, diagnose_from_records
from .diagnostic_inference import infer_signatures

__all__ = ['SignatureConfig', 'diagnose_v3', 'diagnose_from_records', 'infer_signatures']
