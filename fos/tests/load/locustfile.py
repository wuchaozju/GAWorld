"""
Locust load testing suite for FOS platform.

Simulates realistic user workflows: browsing, authentication,
dashboard usage, simulation management, and API interactions.
Run with: locust -f tests/load/locustfile.py --host https://mo.zju.edu.cn/css/fos

Contains: SocialSimVisitor, SocialSimUser, SocialSimPowerUser
"""

import os
import random
import string
from locust import HttpUser, task, between, tag


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_PREFIX = "/api"
TEST_USERNAME = os.getenv("LOCUST_USERNAME", "zjucss")
TEST_PASSWORD = os.getenv("LOCUST_PASSWORD", "zjucss107")


# ---------------------------------------------------------------------------
# Helper: authenticated user mixin
# ---------------------------------------------------------------------------
class AuthMixin:
    """Provides login/token management for authenticated user classes."""

    def login(self):
        """Authenticate and store the access token."""
        resp = self.client.post(
            f"{API_PREFIX}/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            name="/api/auth/login",
        )
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    def authenticated_request(self, method, path, **kwargs):
        """Make an authenticated HTTP request with the stored token."""
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(self.headers)
        kwargs.setdefault("name", path)
        return getattr(self.client, method)(path, **kwargs)


# ---------------------------------------------------------------------------
# User Type 1: Anonymous visitor browsing public pages
# ---------------------------------------------------------------------------
class SocialSimVisitor(HttpUser):
    """Simulates unauthenticated visitors exploring the landing page and docs."""

    wait_time = between(2, 5)
    weight = 3  # 3x more visitors than authenticated users by default

    @task(5)
    @tag("browse")
    def view_landing(self):
        """Load the main landing page (HTML + static assets)."""
        self.client.get("/", name="GET / (landing page)")

    @task(2)
    @tag("browse")
    def view_docs(self):
        """Load the documentation/tutorial page."""
        self.client.get("/docs", name="GET /docs")

    @task(1)
    @tag("browse")
    def check_config(self):
        """Hit the public config endpoint (used by frontend on load)."""
        self.client.get(f"{API_PREFIX}/config", name="GET /api/config")


# ---------------------------------------------------------------------------
# User Type 2: Regular authenticated user
# ---------------------------------------------------------------------------
class SocialSimUser(HttpUser, AuthMixin):
    """Simulates a logged-in user browsing dashboard and managing simulations."""

    wait_time = between(1, 4)
    weight = 2

    def on_start(self):
        """Login when the simulated user starts their session."""
        self.login()

    @task(5)
    @tag("dashboard")
    def view_dashboard(self):
        """Load the dashboard page."""
        self.client.get("/dashboard", name="GET /dashboard")

    @task(4)
    @tag("simulations")
    def list_simulations(self):
        """List all simulations for the current user."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/simulations", name="GET /api/simulations"
        )

    @task(3)
    @tag("simulations")
    def list_scenes(self):
        """Browse available scene types."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/scenes", name="GET /api/scenes"
        )

    @task(3)
    @tag("simulations")
    def list_scenarios(self):
        """Browse available scenario definitions."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/scenarios", name="GET /api/scenarios"
        )

    @task(2)
    @tag("simulations")
    def list_providers(self):
        """Check configured LLM providers."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/providers", name="GET /api/providers"
        )

    @task(2)
    @tag("simulations")
    def list_templates(self):
        """Browse scene templates."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/scenes/templates", name="GET /api/scenes/templates"
        )

    @task(1)
    @tag("simulations")
    def get_user_info(self):
        """Fetch current user profile."""
        self.authenticated_request(
            "get", f"{API_PREFIX}/auth/me", name="GET /api/auth/me"
        )


# ---------------------------------------------------------------------------
# User Type 3: Power user creating and running simulations
# ---------------------------------------------------------------------------
class SocialSimPowerUser(HttpUser, AuthMixin):
    """Simulates a power user creating simulations, viewing tree structures,
    and exporting results — heavier API usage patterns."""

    wait_time = between(2, 6)
    weight = 1

    def on_start(self):
        """Login when the simulated user starts their session."""
        self.login()
        self.created_sim_ids = []

    @task(3)
    @tag("create")
    def create_and_explore_simulation(self):
        """Create a simulation, then explore its tree structure."""
        # Step 1: Create a simulation
        sim_name = "load-test-" + "".join(random.choices(string.ascii_lowercase, k=6))
        payload = {
            "name": sim_name,
            "scenario_id": "public_goods_game",
            "scene_config": {
                "num_agents": 4,
                "rounds": 3,
                "multiplier": 1.5,
                "endowment": 10,
            },
            "agents": [
                {
                    "name": f"Agent-{i}",
                    "personality": "cooperative",
                    "backstory": f"Load test agent {i}",
                }
                for i in range(4)
            ],
        }

        resp = self.authenticated_request(
            "post",
            f"{API_PREFIX}/simulations",
            json=payload,
            name="POST /api/simulations",
        )

        if resp.status_code != 201:
            return

        sim_id = resp.json().get("id")
        if not sim_id:
            return

        self.created_sim_ids.append(sim_id)

        # Step 2: Get simulation details
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}",
            name="GET /api/simulations/{id}",
        )

        # Step 3: Get tree graph
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}/tree/graph",
            name="GET /api/simulations/{id}/tree/graph",
        )

        # Step 4: Get logs
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}/logs?limit=50",
            name="GET /api/simulations/{id}/logs",
        )

    @task(2)
    @tag("browse")
    def browse_existing_simulations(self):
        """List simulations and drill into a random one."""
        resp = self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations",
            name="GET /api/simulations",
        )

        if resp.status_code != 200:
            return

        sims = resp.json()
        if not sims:
            return

        # Pick a random simulation to inspect
        sim = random.choice(sims) if isinstance(sims, list) else None
        if not sim:
            return

        sim_id = sim.get("id")
        if not sim_id:
            return

        # Drill into details
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}",
            name="GET /api/simulations/{id}",
        )

        # Get tree structure
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}/tree/graph",
            name="GET /api/simulations/{id}/tree/graph",
        )

    @task(1)
    @tag("export")
    def export_simulation(self):
        """Export a previously created simulation."""
        if not self.created_sim_ids:
            return

        sim_id = random.choice(self.created_sim_ids)
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/simulations/{sim_id}/export?format=json",
            name="GET /api/simulations/{id}/export",
        )

    @task(1)
    @tag("create")
    def create_experiment_template(self):
        """Create an experiment template (lighter weight test)."""
        payload = {
            "name": "load-test-experiment-" + "".join(random.choices(string.ascii_lowercase, k=4)),
            "description": "Load test experiment template",
            "scenario_id": "public_goods_game",
            "action_type": "contribute",
            "variables": [
                {"name": "multiplier", "values": [1.0, 1.5, 2.0]},
            ],
        }

        self.authenticated_request(
            "post",
            f"{API_PREFIX}/experiment-templates/templates",
            json=payload,
            name="POST /api/experiment-templates/templates",
        )

    @task(1)
    @tag("browse")
    def list_experiment_templates(self):
        """Browse experiment templates."""
        self.authenticated_request(
            "get",
            f"{API_PREFIX}/experiment-templates/templates?limit=20",
            name="GET /api/experiment-templates/templates",
        )

    @task(1)
    @tag("cleanup")
    def cleanup_created_simulations(self):
        """Delete previously created simulations to avoid polluting the DB."""
        if not self.created_sim_ids:
            return

        # Delete up to 2 simulations per cleanup cycle
        to_delete = self.created_sim_ids[:2]
        for sim_id in to_delete:
            self.authenticated_request(
                "delete",
                f"{API_PREFIX}/simulations/{sim_id}",
                name="DELETE /api/simulations/{id}",
            )
            if sim_id in self.created_sim_ids:
                self.created_sim_ids.remove(sim_id)

    def on_stop(self):
        """Clean up any remaining created simulations."""
        for sim_id in list(self.created_sim_ids):
            self.authenticated_request(
                "delete",
                f"{API_PREFIX}/simulations/{sim_id}",
                name="DELETE /api/simulations/{id} (cleanup)",
            )
        self.created_sim_ids.clear()
