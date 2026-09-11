"""Capability definitions exposed to the SatQuery query engine."""

from .catalog import TASK_TO_CAPABILITY, get_capabilities

__all__ = ["TASK_TO_CAPABILITY", "get_capabilities"]