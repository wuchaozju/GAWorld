"""
Simulation API routes module.

This module contains all simulation-related API routes, broken down into
focused submodules for better maintainability.

The module is organized as follows:
- crud: Basic CRUD operations (list, create, read, update, delete)
- lifecycle: Simulation lifecycle management (start, resume, reset, copy)
- snapshots: Snapshot management (save, list)
- tree_operations: Tree manipulation (graph, advance, branch, delete)
- websocket_handlers: WebSocket event subscriptions
- agent_documents: Agent document upload/list/delete
- global_knowledge: Global knowledge management

Each submodule exports its route handlers which are registered to the
main router in this module.
"""

from litestar import Router


def create_router() -> Router:
    """
    Create and return the main simulation routes router.

    Combines all simulation-related route handlers into a single router
    with the /simulations path prefix.
    """
    # Import route handlers from submodules
    from . import crud, lifecycle, snapshots, tree_operations
    from . import websocket_handlers, agent_documents, global_knowledge, export

    return Router(
        path="/simulations",
        route_handlers=[
            # CRUD operations
            crud.list_simulations,
            crud.create_simulation,
            crud.read_simulation,
            crud.update_simulation,
            crud.delete_simulation,
            crud.delete_all_user_simulations,
            crud.update_agent_llm_config,
            # Lifecycle operations
            lifecycle.start_simulation,
            lifecycle.resume_simulation,
            lifecycle.reset_simulation,
            lifecycle.copy_simulation,
            lifecycle.rehydrate_simulation,
            # Snapshot operations
            snapshots.create_snapshot,
            snapshots.list_snapshots,
            snapshots.list_logs,
            # Tree operations
            tree_operations.simulation_tree_graph,
            tree_operations.simulation_tree_advance_frontier,
            tree_operations.simulation_tree_advance_multi,
            tree_operations.simulation_tree_advance_chain,
            tree_operations.simulation_tree_branch,
            tree_operations.simulation_tree_delete_subtree,
            tree_operations.simulation_tree_events,
            tree_operations.simulation_tree_state,
            tree_operations.test_agent_knowledge,
            tree_operations.ask_agents_question,
            tree_operations.inject_host_message,
            # WebSocket handlers
            websocket_handlers.simulation_tree_events_ws,
            websocket_handlers.simulation_tree_node_events_ws,
            # Document operations
            agent_documents.upload_agent_document,
            agent_documents.list_agent_documents,
            agent_documents.delete_agent_document,
            agent_documents.get_agent_memory,
            # Global knowledge operations
            global_knowledge.add_global_knowledge,
            global_knowledge.upload_global_document,
            global_knowledge.list_global_knowledge,
            global_knowledge.delete_global_knowledge,
            # Export operations
            export.export_simulation,
        ],
    )


# Export the router for use in the main app
router = create_router()
