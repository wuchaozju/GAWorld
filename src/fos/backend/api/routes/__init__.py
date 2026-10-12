# src/fos/backend/api/__init__.py
from litestar import Router

from . import (
    admin,
    auth,
    config,
    providers,
    scenes,
    scenarios,
    simulations,
    search_providers,
    llm,  # LLM related routes
    ai_scientist,
    experiments,  # Simulation experiment routes (A/B testing)
    experiment_templates,  # Experiment template management routes
    uploads,
    environment,  # Dynamic environment routes
    xihu_round1,  # Xihu Yilianbao experiment scenario routes
    health,  # Health check and metrics endpoints
)

router = Router(
    path="",
    route_handlers=[
        auth.router,
        config.router,
        scenes.router,
        scenarios.router,
        simulations.router,
        providers.router,
        search_providers.router,
        llm.router,
        ai_scientist.router,
        experiments.router,
        experiment_templates.router,  # Experiment template CRUD and run
        uploads.router,
        admin.router,
        environment.router,
        xihu_round1.router,  # Xihu Yilianbao scenario API
        health.router,  # Health check and metrics
    ],
)
