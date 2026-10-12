"""Environment analyzer for fos simulations.

This module re-exports from the new environment_agent implementation.
The EnvironmentAnalyzer is now a thin wrapper around EnvironmentAgent.

Contains: EnvironmentAnalyzer
"""

from fos.core.environment_agent import EnvironmentAgent

# Re-export for backwards compatibility
EnvironmentAnalyzer = EnvironmentAgent

__all__ = ["EnvironmentAnalyzer"]
