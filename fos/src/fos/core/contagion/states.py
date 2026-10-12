"""
Contagion state definitions for agent infection status.

This module provides the ContagionState enum that represents the possible
infection states of agents in the contagion simulation framework. States
follow the SEIR model (Susceptible, Exposed, Infected, Recovered).

The str inheritance ensures JSON serialization works correctly when states
are sent to the frontend or stored in configuration files.

Contains: ContagionState
"""
from enum import Enum


class ContagionState(str, Enum):
    """
    Infection states for agents in contagion simulations.

    Follows the SEIR epidemiological model:
    - SUSCEPTIBLE: Agent can be infected
    - EXPOSED: Agent has been exposed but not yet infectious
    - INFECTED: Agent is actively infectious
    - RECOVERED: Agent has recovered and is immune

    Inherits from str and Enum for JSON serialization compatibility.
    """

    SUSCEPTIBLE = "susceptible"
    EXPOSED = "exposed"
    INFECTED = "infected"
    RECOVERED = "recovered"
