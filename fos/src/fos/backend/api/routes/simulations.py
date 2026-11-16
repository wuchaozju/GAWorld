"""
Simulation API routes - Facade for modular structure.

This file provides backwards compatibility by re-exporting the
router from the new modular simulations package.

The actual implementation has been refactored into focused modules:
- simulations/crud.py: Basic CRUD operations
- simulations/lifecycle.py: Lifecycle management
- simulations/snapshots.py: Snapshot operations
- simulations/tree_operations.py: Tree manipulation
- simulations/websocket_handlers.py: WebSocket subscriptions
- simulations/agent_documents.py: Agent document management
- simulations/global_knowledge.py: Global knowledge management
- simulations/helpers.py: Shared utility functions

Each module has detailed documentation explaining its purpose
and the functions it contains.
"""

# Import the router from the new modular package
from .simulations import router

# Re-export for backwards compatibility
__all__ = ["router"]
