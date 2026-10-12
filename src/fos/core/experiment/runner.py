"""
Experiment Runner - orchestrates round-based experiment execution.

The runner manages the main experiment loop:
- Executes rounds according to visibility settings
- Handles simultaneous vs sequential decision-making
- Updates context summaries after each round
- Emits round completion events
"""

import asyncio
import logging
import os
import threading
from datetime import datetime
from typing import List, Dict, Any, Literal, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from fos.core.experiment.scene import ExperimentScene

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.controller import ExperimentController, ActionResult
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.prompt_builder import build_prompt
from fos.core.experiment.action_handler import ActionHandler
from fos.experiments.confederates import (
    ConfederateSpec,
    record_confederate_vote,
)
from fos.i18n import T
from fos.core.experiment.payoff.engine import PayoffEngine
from fos.core.experiment.feedback.builder import CoordinationFeedbackBuilder
from fos.core.experiment.debug_log import write_debug
from fos.core.llm.client import LLMClient, PromptOverflowError
from fos.core.context_builder import _count_tokens, _truncate_speech_events, build_structured_context

logger = logging.getLogger(__name__)

# Maps FOS model names (LM Studio style) to router model names (GGUF filename without .gguf)
# Used when communicating with llama.cpp router server /models/load and /models/unload
LLAMACPP_ROUTER_MODEL_MAP: dict[str, str] = {
    "openai/gpt-oss-20b": "gpt-oss-20b",
    "google/gemma-4-26b-a4b": "gemma-4-26b-a4b",
    "qwen/qwen3.6-35b-a3b": "qwen3.6-35b-a3b",
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced": "gemma4-26b-a4b-uncensored",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": "qwen3.6-35b-a3b-uncensored",
}


@dataclass
class RoundResult:
    """Results from a single round.

    Attributes:
        round_num: Round number
        actions: List of action results from all agents
        completed: Whether all agents completed the round
        payoffs: Per-agent payoffs earned this round (None if not applicable)
    """
    round_num: int
    actions: List[ActionResult]
    completed: bool
    payoffs: Optional[Dict[str, int]] = None


class ExperimentRunner:
    """Orchestrates round-based experiment execution.

    The runner handles the main experiment loop, supporting:
    - Simultaneous: All agents decide without seeing each other's choices
    - Sequential: Agents decide one at a time, seeing previous choices
    - Random: Agents decide in shuffled order, seeing previous choices
    - Paired: Agents are randomly paired each round, play within pairs
    """

    def __init__(
        self,
        agents: List[ExperimentAgent],
        game_config: GameConfig,
        llm_client: LLMClient,
        kernel: ExperimentKernel | None = None,
        round_visibility: Literal["simultaneous", "sequential", "random", "paired"] = "simultaneous",
        information_model: "InformationModel | None" = None,
        scene: Optional["ExperimentScene"] = None,
        agent_llm_clients: Optional[Dict[str, LLMClient]] = None,
    ):
        """Initialize the experiment runner.

        Args:
            agents: List of agents in the experiment
            game_config: Game configuration
            llm_client: Default LLM client for prompts and context updates (fallback)
            kernel: Action registry (uses default if None)
            round_visibility: How agents see each other's choices
            information_model: Optional InformationModel for structured context
            scene: Optional scene instance for action filtering (GAP-CLOSURE-01)
            agent_llm_clients: Optional dict mapping agent names to their specific LLM clients
        """
        self.agents = agents
        self.game_config = game_config
        self.llm_client = llm_client  # Default/fallback client
        self.agent_llm_clients = agent_llm_clients or {}  # Per-agent LLM clients
        self.kernel = kernel or ExperimentKernel()
        self.round_visibility = round_visibility
        self.information_model = information_model
        self.scene = scene  # Store scene reference for action filtering
        self.scene_state: Dict[str, Any] = {}  # shared mutable ref; update via set_scene_state()
        self._debug_lock = asyncio.Lock()  # Lock for atomic debug file writes
        self._model_switch_lock = threading.Lock()  # Lock to serialize model-switch operations

        self.context_manager = RoundContextManager(
            information_model=information_model,
            scene_state=self.scene_state,
            all_agent_names=[a.name for a in agents],
        )
        self.controller = ExperimentController(self.kernel, self.context_manager)
        self.action_handler = ActionHandler()

        # Initialize round state (moved from dead code after return statement)
        self.payoff_engine = PayoffEngine()
        self.feedback_builder = CoordinationFeedbackBuilder()
        self.current_round = 0  # Start at 0, incremented when rounds run
        self.turn_order: List[str] | None = None  # Store shuffled order for random/paired mode
        self.scores: Dict[str, int] = {}  # Track cumulative scores per agent (for paired mode)
        self.pending_host_messages: list[str] = []  # Injected by host before each round
        self._last_model: str | None = None  # Track last model for sequential prompt path
        self._last_model_per_port: dict[int, str | None] = {}  # Track last model per port for dual-server

        # Compute model-block boundaries for predictive preloading
        self._model_blocks: list[tuple[int, int, str]] = []
        current_model = None
        block_start = 0
        for idx, a in enumerate(self.agents):
            client = self.get_agent_llm_client(a)
            m = getattr(getattr(client, "provider", None), "model", "")
            if not isinstance(m, str):
                m = ""
            if m != current_model:
                if current_model is not None:
                    self._model_blocks.append((block_start, idx - 1, current_model))
                current_model = m
                block_start = idx
        if current_model is not None:
            self._model_blocks.append((block_start, len(self.agents) - 1, current_model))
        self._preloaded_blocks: set[int] = set()  # block start indices already preloaded

    def get_agent_llm_client(self, agent: ExperimentAgent) -> LLMClient:
        """Get the LLM client for a specific agent.

        Uses per-agent client if available (LLM distribution),
        otherwise falls back to the default client.

        Args:
            agent: The agent to get the LLM client for

        Returns:
            LLMClient to use for this agent
        """
        if agent.name in self.agent_llm_clients:
            logger.debug(f"Using per-agent LLM client for {agent.name}")
            return self.agent_llm_clients[agent.name]
        logger.debug(f"Using default LLM client for {agent.name}")
        return self.llm_client

    def _get_agent_model(self, agent: ExperimentAgent) -> str | None:
        """Get the model name for an agent, or None if unavailable (mock/test)."""
        client = self.get_agent_llm_client(agent)
        model = getattr(getattr(client, "provider", None), "model", "")
        if isinstance(model, str) and model:
            return model
        return None

    def _group_agents_by_model(self, agents_list: list) -> list:
        """Partition agents by model name. Returns list of (model_name, agent_list) tuples."""
        from collections import OrderedDict
        groups = OrderedDict()
        for agent in agents_list:
            model = self._get_agent_model(agent)
            if model not in groups:
                groups[model] = []
            groups[model].append(agent)
        return list(groups.items())

    @staticmethod
    def _get_model_manager_url() -> str | None:
        """Return the model manager URL if configured, or None.

        Checks the FOS_MODEL_MANAGER_URL environment variable first.
        If not set and port 8080 is detected, returns the router URL.
        """
        return os.environ.get("FOS_MODEL_MANAGER_URL") or None

    @staticmethod
    def _get_router_base_url(client_base_url: str) -> str:
        """Extract the router base URL from the provider's base_url.

        When FOS_MODEL_MANAGER_URL env var is set, returns that URL,
        routing all model management calls through the model_manager proxy.
        Otherwise strips trailing /v1 to get the raw server root.
        Defaults to http://127.0.0.1:8080.
        """
        mm_url = os.environ.get("FOS_MODEL_MANAGER_URL")
        if mm_url:
            return mm_url.rstrip("/")
        url = client_base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        elif "/v1/" in url:
            idx = url.index("/v1/")
            url = url[:idx]
        if not url:
            url = "http://127.0.0.1:8080"
        return url

    def _is_llama_cpp_port(self, base_url: str) -> bool:
        """Check if base_url points to a llama.cpp server on port 8080."""
        return "8080" in base_url

    def _is_model_manager_active(self, base_url: str) -> bool:
        """Check whether the model manager should be used for this provider.

        Priority:
        1. FOS_MODEL_MANAGER_URL env var is set → use model manager
        2. base_url contains "8080" → assume llama.cpp router mode
        3. Otherwise → False (use LM Studio or other provider path)
        """
        if self._get_model_manager_url():
            return True
        return self._is_llama_cpp_port(base_url)

    def _preload_model(self, model_name: str, client: "LLMClient") -> bool:
        """Preload a model before the first chat request.

        Two modes:
        - **Model router mode** (port 8080 or FOS_MODEL_MANAGER_URL set):
          1. POST /models/unload to unload current model
          2. POST /models/load to start loading the target model
          3. Poll GET /models every 2s until status.value == "loaded"
             (timeout 300s, same as current HEALTH_TIMEOUT)
          4. Send warmup chat request to prime the inference engine
        - **LM Studio mode** (port 1234): Legacy path — polls GET /api/v0/models
          until the target model is loaded, then unloads stale models.
        - **Other providers**: No-op returning True.

        Returns True when the model is ready; False if load/poll fails.
        """
        import time as _time

        base_url = getattr(getattr(client, "provider", None), "base_url", None) or ""
        if not isinstance(base_url, str):
            logger.debug("Skipping preload — no base_url on provider")
            return True

        # ── Model router path (port 8080 or env var) ──────────────
        if self._is_model_manager_active(base_url):
            mm_url = self._get_model_manager_url()
            router_base = mm_url if mm_url else self._get_router_base_url(base_url)
            router_model = self._get_router_model_name(model_name)
            logger.info(
                "Preloading model '%s' (router name: %s) via router (%s) ...",
                model_name, router_model, router_base,
            )

            # Step 1-2: Unload current model and trigger load
            port = self._get_port_from_client(client)
            was_already_loaded = (
                port in self._last_model_per_port
                and self._last_model_per_port[port] == model_name
            )
            if not self._trigger_model_load(model_name, client):
                logger.error(
                    "Failed to load model '%s' via router (port %s)", model_name, port
                )
                return False

            # If the model was already loaded (no actual load happened),
            # skip the poll loop and warmup — they're unnecessary.
            if was_already_loaded:
                logger.info(
                    "Model '%s' was already loaded on port %s — skipping poll and warmup",
                    model_name, port,
                )
                return True

            # Step 3: Poll GET /models until loaded
            models_url = f"{router_base}/models"
            logger.info("Entering poll loop, models_url=%s", models_url)
            poll_interval = 2.0
            timeout = 300.0
            deadline = _time.time() + timeout

            while _time.time() < deadline:
                try:
                    import requests as _requests
                    resp = _requests.get(models_url, timeout=10)
                    if resp.status_code == 200:
                        models_list = resp.json().get("data", [])
                        for m in models_list:
                            m_name = m.get("id", "") if isinstance(m, dict) else ""
                            m_status = m.get("status", {}) if isinstance(m, dict) else {}
                            if isinstance(m_status, dict):
                                status_val = m_status.get("value", "") or m_status.get("status", "")
                            else:
                                status_val = str(m_status)

                            # Accept both dict-with-value and direct-string status representations
                            if m_name == router_model:
                                self._last_model_per_port[port] = model_name
                                if status_val == "loaded":
                                    logger.info("Model '%s' is loaded (%.1fs)", router_model, _time.time() - (deadline - timeout))
                                    break
                                elif status_val == "error":
                                    logger.info("Model '%s' failed to load (status=error)", router_model)
                                    return False
                        else:
                            # Target model not yet in list — still loading or queued
                            _time.sleep(poll_interval)
                            continue
                        # Model found and loaded
                        break
                    else:
                        logger.info("GET /models returned %s — retrying in %ss", resp.status_code, poll_interval)
                        _time.sleep(poll_interval)
                        continue
                except Exception as exc:
                    logger.debug(
                        "Poll GET /models failed: %s — retrying in %ds",
                        exc, poll_interval,
                    )
                    _time.sleep(poll_interval)
                    continue
            else:
                logger.error(
                    "Timed out (%.1fs) waiting for model '%s' to load",
                    timeout, router_model,
                )
                return False

            # ── Give inference engine time to initialize ──────
            # llama.cpp reports "loaded" when the model file is memory-mapped,
            # but CUDA graph compilation and KV cache allocation may still be
            # in progress. A short sleep here avoids "model is not loaded"
            # errors on the first chat request.
            _time.sleep(5.0)

            # Step 4: warmup chat
            if not self._warmup_model(model_name, client):
                logger.warning(
                    "Model '%s' warmup failed — continuing anyway",
                    model_name,
                )
            return True

        # ── LM Studio path (port 1234) ────────────────────────────
        if "1234" not in base_url:
            logger.debug(
                "Skipping preload — not an LM Studio or model manager provider (%s)",
                base_url,
            )
            return True

        admin_url = base_url.rstrip("/")
        if admin_url.endswith("/v1"):
            admin_url = admin_url[:-3]

        logger.info(
            "Preloading model '%s' via LM Studio (%s) ...", model_name, admin_url
        )

        # ── Step 1: synchronous load via /api/v1/models/load ────
        if not self._trigger_model_load(model_name, client):
            logger.warning(
                "Model '%s' preload check failed — continuing anyway (model may already be loaded in LM Studio GUI)",
                model_name,
            )
            # Fall through to warmup — chat may still work

        logger.info("Model '%s' loaded. Sending warmup request...", model_name)

        # ── warmup chat (json_mode=True, retry up to 5×) ──────
        if not self._warmup_model(model_name, client):
            logger.warning(
                "Model '%s' warmup failed — continuing anyway",
                model_name,
            )

        # ── Unload all other models (only if warmup succeeded) ──
        self._unload_stale_lm_studio_models(model_name, admin_url)

        return True

    def _warmup_model(self, model_name: str, client: "LLMClient") -> bool:
        """Send a warmup chat request to prime the inference engine.

        Retries up to 5 times with a 3-second delay, then an extended
        phase with 3 more attempts and 5-second delays.
        Returns True if the model produces a non-empty response.
        """
        import time as _time

        warmup_message = [
            {
                "role": "user",
                "content": "Hi",
            }
        ]
        for attempt in range(1, 6):
            try:
                resp = client.chat(warmup_message)
                if resp and resp.strip():
                    logger.info(
                        "Model '%s' warmup successful (attempt %d)", model_name, attempt
                    )
                    return True
                else:
                    logger.debug(
                        "Model '%s' warmup attempt %d returned empty — retrying...",
                        model_name, attempt,
                    )
            except Exception as exc:
                logger.debug(
                    "Model '%s' warmup attempt %d raised %s — retrying...",
                    model_name, attempt, exc,
                )
            _time.sleep(3.0)
        
        # Extended retry phase: inference engine may still be initializing
        logger.warning(
            "Model '%s' warmup: initial 5 attempts failed — waiting 10s then retrying...",
            model_name,
        )
        _time.sleep(10.0)
        for attempt in range(6, 9):
            try:
                resp = client.chat(warmup_message)
                if resp and resp.strip():
                    logger.info(
                        "Model '%s' warmup successful (extended attempt %d)", model_name, attempt
                    )
                    return True
                else:
                    logger.debug(
                        "Model '%s' warmup extended attempt %d returned empty — retrying...",
                        model_name, attempt,
                    )
            except Exception as exc:
                logger.debug(
                    "Model '%s' warmup extended attempt %d raised %s — retrying...",
                    model_name, attempt, exc,
                )
            _time.sleep(5.0)
        
        logger.warning(
            "Model '%s' did not produce a non-empty response after 8 warmup attempts",
            model_name,
        )
        return False

    def _unload_stale_lm_studio_models(self, model_name: str, admin_url: str) -> None:
        """Unload all LM Studio models except the current one.

        Fetches the model list from GET /api/v1/models and unloads every
        loaded instance whose key does not match *model_name*.
        Failures are logged but not fatal.
        """
        try:
            import requests as _requests
            models_url = f"{admin_url}/api/v1/models"
            unload_url = f"{admin_url}/api/v1/models/unload"

            resp = _requests.get(models_url, timeout=10)
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    other_key = m.get("key", "")
                    instances = m.get("loaded_instances", [])
                    if other_key and other_key != model_name and instances:
                        for inst in instances:
                            inst_id = inst if isinstance(inst, str) else inst.get("instance_id", "")
                            if inst_id:
                                logger.info(
                                    "Unloading stale model '%s' (instance %s) ...",
                                    other_key, inst_id,
                                )
                                try:
                                    unload_resp = _requests.post(
                                        unload_url,
                                        json={"instance_id": inst_id},
                                        timeout=30,
                                    )
                                    if unload_resp.status_code == 200:
                                        logger.info(
                                            "Stale model '%s' unloaded successfully",
                                            other_key,
                                        )
                                    else:
                                        logger.warning(
                                            "Unload of stale '%s' returned %s: %s",
                                            other_key,
                                            unload_resp.status_code,
                                            unload_resp.text[:200],
                                        )
                                except Exception as exc:
                                    logger.warning(
                                        "Failed to unload stale model '%s': %s",
                                        other_key, exc,
                                    )
        except Exception as exc:
            logger.warning(
                "Model enumeration for unload failed: %s — continuing",
                exc,
            )

    def _get_router_model_name(self, model_name: str) -> str:
        """Map a FOS model name to a router model name.

        Falls back to the original name if not found in the map.
        """
        return LLAMACPP_ROUTER_MODEL_MAP.get(model_name, model_name)

    @staticmethod
    def _get_port_from_client(client):
        """Extract the llama-server port from an LLMClient's base_url.

        Returns the port number (e.g., 8080 or 8082), defaulting to 8080.
        Handles non-string base_url values (e.g. Mock objects in tests)
        by returning the default port.
        """
        from urllib.parse import urlparse
        base_url = getattr(getattr(client, 'provider', None), 'base_url', '')
        if not isinstance(base_url, str) or not base_url:
            return 8080
        try:
            parsed = urlparse(base_url)
            port = parsed.port
            if isinstance(port, int):
                return port
            return 8080
        except Exception:
            return 8080

    def _trigger_model_load(self, model_name: str, client: "LLMClient") -> bool:
        port = self._get_port_from_client(client)
        """Trigger a model switch/load via the active provider.

        Two modes:
        - **Model router** (port 8080 or FOS_MODEL_MANAGER_URL):
          1. POST ``/models/unload`` (required with ``--models-max 1``)
          2. Wait 3 seconds for the child process to fully exit
          3. POST ``/models/load`` with ``{"model": MODEL_ROUTER_NAME}``
          The load is async; polling happens in _preload_model().
        - **LM Studio** (port 1234): Calls ``POST /api/v1/models/load`` on
          the LM Studio admin endpoint.  First checks if the model is
          already loaded to avoid hangs.
        - **Other providers**: No-op returning True.

        Returns True on success, False on failure.
        """
        import time as _time
        import requests as _requests

        base_url = getattr(getattr(client, "provider", None), "base_url", None) or ""
        if not isinstance(base_url, str):
            return True

        # ── Model router path (llama.cpp router on port 8080) ──────
        if self._is_model_manager_active(base_url):
            mm_url = self._get_model_manager_url()
            router_base = mm_url if mm_url else self._get_router_base_url(base_url)
            router_model = self._get_router_model_name(model_name)
            logger.debug("router_base=%s", router_base)
            logger.debug("about to GET %s/models", router_base)

            # Step 1: Find and unload the currently-loaded model
            # We must unload the CURRENT model, not the TARGET model.
            # Query GET /models to find what's loaded, then unload by name.
            unload_url = f"{router_base}/models/unload"
            logger.info("Finding current model to unload...")
            current_model = None
            try:
                logger.debug("calling GET...")
                models_resp = _requests.get(
                    f"{router_base}/models",
                    timeout=10,
                )
                logger.debug("GET returned status=%s", models_resp.status_code)
                if models_resp.status_code == 200:
                    for m in models_resp.json().get("data", []):
                        m_name = m.get("id", "") if isinstance(m, dict) else ""
                        m_status = m.get("status", {}) if isinstance(m, dict) else {}
                        status_val = m_status.get("value", "") if isinstance(m_status, dict) else ""
                        if status_val == "loaded" and m_name:
                            current_model = m_name
                            break
            except Exception as exc:
                logger.debug("Failed to query model list: %s", exc)

            logger.debug("after GET: current_model=%r, router_model=%r", current_model, router_model)
            if current_model and current_model != router_model:
                logger.info("Unloading current model '%s' via %s ...", current_model, unload_url)
                try:
                    resp = _requests.post(
                        unload_url,
                        json={"model": current_model, "port": port},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        logger.info("Unload request accepted by router")
                    else:
                        logger.warning(
                            "Unload request returned %s: %s",
                            resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    logger.warning("Unload request failed: %s", exc)
            elif current_model == router_model:
                logger.debug("model already loaded, returning True")
                logger.info(
                    "Model '%s' is already loaded — no unload/load needed",
                    router_model,
                )
                return True
            else:
                logger.info("No model currently running — nothing to unload")

            # Step 2: Wait 3 seconds for the child process to fully exit
            # before loading a new model. This prevents port conflicts and
            # stale GPU memory.
            logger.info("Waiting 3 seconds for child process to exit...")
            _time.sleep(3.0)

            # Step 3: Load target model
            load_url = f"{router_base}/models/load"
            logger.info("Loading model '%s' via %s ...", router_model, load_url)
            try:
                resp = _requests.post(
                    load_url,
                    json={"model": router_model, "port": port},
                    timeout=300,  # model loads sync via model_manager; 35B GGUF takes 60-180s
                )
                if resp.status_code == 200:
                    logger.info(
                        "Load request for '%s' accepted by router", router_model,
                    )
                    return True
                elif resp.status_code == 400 and "already running" in resp.text:
                    logger.info(
                        "Model '%s' is already running — no load needed", router_model,
                    )
                    return True
                else:
                    logger.warning(
                        "Load request for '%s' returned %s: %s",
                        router_model, resp.status_code, resp.text[:200],
                    )
                    return False
            except Exception as exc:
                logger.warning("Load request for '%s' failed: %s", router_model, exc)
                return False

        # ── LM Studio path (port 1234) ────────────────────────────
        if "1234" not in base_url:
            return True  # Not LM Studio — nothing to do

        admin_url = base_url.rstrip("/")
        if admin_url.endswith("/v1"):
            admin_url = admin_url[:-3]
        models_url = f"{admin_url}/api/v1/models"
        load_url = f"{admin_url}/api/v1/models/load"

        # ── Check if already loaded ──────────────────────────
        try:
            resp = _requests.get(models_url, timeout=10)
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    if m.get("key") == model_name and m.get("loaded_instances"):
                        logger.info(
                            "Model '%s' is already loaded — skipping load request",
                            model_name,
                        )
                        return True
        except Exception:
            pass  # proceed to load attempt

        # ── Explicitly load the model ────────────────────────
        logger.info("Requesting load of %s...", model_name)
        try:
            resp = _requests.post(
                load_url,
                json={"model": model_name},
                timeout=300,  # large models can take minutes
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    "Model '%s' loaded in %.1fs (status=%s)",
                    model_name,
                    data.get("load_time_seconds", -1),
                    data.get("status", "?"),
                )
                return True
            else:
                logger.warning(
                    "Load request for '%s' returned %s: %s",
                    model_name, resp.status_code, resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.warning("Load of '%s' failed: %s", model_name, exc)
            return False


    def _trigger_model_load_bg(self, model_name: str, client: "LLMClient") -> None:
        """Fire-and-forget background load trigger for predictive preloading.

        LM Studio path: Sends a minimal chat request (max_tokens=1) to the
        target model.  LM Studio sees the unknown model and starts loading
        it without unloading the current model.  The request times out —
        that is expected.

        Model manager path: No-op for now — the model manager does not
        support predictive background preloading yet.

        The actual synchronous load + warmup happens later in
        _preload_model when the model switch is detected.
        """
        import requests as _requests
        import threading

        base_url = getattr(getattr(client, "provider", None), "base_url", None) or ""
        if not isinstance(base_url, str):
            return

        # Model manager: no background preloading yet
        if self._is_model_manager_active(base_url):
            # TODO: implement predictive background loading via model manager
            return

        if "1234" not in base_url:
            return

        chat_url = base_url.rstrip("/")
        if not chat_url.endswith("/chat/completions"):
            if chat_url.endswith("/v1"):
                chat_url += "/chat/completions"
            else:
                chat_url += "/v1/chat/completions"

        def _trigger():
            try:
                _requests.post(
                    chat_url,
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "."}],
                        "max_tokens": 1,
                    },
                    timeout=5,
                )
            except Exception:
                pass  # Expected — request triggers load but times out

        t = threading.Thread(target=_trigger, daemon=True)
        t.start()
        logger.debug("Predictive load triggered for %s", model_name)

    def _build_custom_action_followup_schema(self, action_name: str, locale: str) -> dict[str, dict[str, str] | str]:
        """Collect a short visible response and rationale for custom experiments.

        Custom experiments do not have scenario-specific runtime events like
        policy cascade scenes, so we ask each agent to provide a compact
        response plus a brief reason tied to the chosen action. These fields
        are later emitted as a separate UI log entry for custom-only flows.
        """
        is_zh = str(locale or "").lower().startswith("zh")
        schema: dict[str, dict[str, str]] = {
            "response": {
                "type": "string",
                "description": (
                    f"你在本轮收到提示后对外展现出的实际回应，要和动作“{action_name}”一致。"
                    if is_zh else
                    f"The visible response you give this round after receiving the prompt. It must align with the action '{action_name}'."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    f"你为什么基于当前角色、处境和收到的信息选择“{action_name}”。简短但具体。"
                    if is_zh else
                    f"Why you chose '{action_name}' based on your role, situation, and the prompt you received. Keep it brief but specific."
                ),
            },
        }
        if str(action_name).strip().lower() in {"speak", "say", "talk"}:
            schema["message"] = {
                "type": "string",
                "description": (
                    "你本轮真正说出口的话。"
                    if is_zh else
                    "The exact words you say aloud this round."
                ),
            }
        mode = "plain_text" if str(action_name).strip().lower() in {"speak", "say", "talk"} else "json"
        return {"schema": schema, "mode": mode}

    def set_scene_state(self, state: Dict[str, Any]) -> None:
        """Merge new state into scene_state. context_manager holds the same reference."""
        self.scene_state.update(state)

    async def _write_debug_atomically(self, buffer: list) -> None:
        """Write debug buffer to shared debug file atomically using lock."""
        async with self._debug_lock:
            write_debug(''.join(buffer))

    def execute_action(self, action_name, agent_name, params, state, scene=None):
        """Delegate action execution to ActionHandler.

        Args:
            action_name: Name of action to execute
            agent_name: Name of agent performing action
            params: Action parameters
            state: Current experiment state
            scene: Optional scene instance for handlers that need scene context
        """
        from fos.core.experiment.actions.registry import get_action as _get_action
        # Game-configured actions not in the global registry are treated as record-only:
        # they are valid game choices (e.g., "red", "blue", "invest") that have no
        # registered state effects. Returning success=True lets them flow through to
        # round history so per-agent context is populated for subsequent rounds.
        if _get_action(action_name) is None:
            configured = {str(a).lower() for a in self.game_config.actions}
            if action_name.lower() in configured:
                return {"success": True}
        return self.action_handler.execute(action_name, agent_name, params, state, scene)

    def _scene_has_followup_actions(self) -> bool:
        """Whether any allowed action in this scene requires a follow-up prompt."""
        action_schemas = self.kernel.get_action_schemas()
        action_schemas.update(self.game_config.action_schemas)
        allowed_actions = {str(action).lower() for action in self.game_config.actions}
        return any(schema_name.lower() in allowed_actions for schema_name in action_schemas)

    def _replay_history_to_events(self, round_history: list) -> None:
        """Replay round_history into context_manager._round_events.

        This populates _round_events from persisted history so that
        get_context_for_agent() (which reads _round_events when information_model
        is set) has data to build structured context.

        Args:
            round_history: List of round entries with "round", "actions", and optional "payoffs"
        """
        # Rebuild the structured event log from persisted history each round.
        self.context_manager._round_events.clear()

        # Reset agent scores before rebuilding from history so we don't
        # double-count when this method is called on a reused runner.
        agent_objs = {a.name: a for a in self.agents}
        for agent in self.agents:
            agent.score = 0

        for entry in round_history:
            entry_round = entry.get("round", 0)
            payoffs = entry.get("payoffs", {})

            for action in entry.get("actions", []):
                agent_name = action.get("agent", "")
                action_name = action.get("action", "")
                parameters = action.get("parameters", {})
                summary = action.get("summary", f"{agent_name} chose {action_name}")
                agent_payoff = payoffs.get(agent_name)

                # Determine who observed this action using InformationModel
                if self.information_model:
                    observed_by = self.information_model.get_observers(
                        for_agent=agent_name,
                        scene_state=self.scene_state,
                        all_agent_names=[a.name for a in self.agents],
                        round_num=entry_round,
                    )
                else:
                    observed_by = [agent_name]

                self.context_manager.record_action(
                    agent_name=agent_name,
                    action_name=action_name,
                    parameters=parameters,
                    round_num=entry_round,
                    summary=summary,
                    observed_by=observed_by,
                    payoff=agent_payoff,
                    feedback=action.get("feedback"),
                )

            # Restore cumulative scores from this round's historical payoffs
            for agent_name, payoff in payoffs.items():
                if agent_name in agent_objs:
                    agent_objs[agent_name].score += payoff

        logger.debug(f"Replayed {len(round_history)} rounds of history to _round_events")

    async def run(self, max_rounds: int) -> List[RoundResult]:
        """Run the experiment for a specified number of rounds.

        Args:
            max_rounds: Maximum number of rounds to run

        Returns:
            List of round results
        """
        results = []

        for round_num in range(1, max_rounds + 1):
            self.current_round = round_num
            logger.info(f"Starting round {round_num}/{max_rounds}")

            if self.round_visibility == "simultaneous":
                round_result = await self._run_simultaneous_round(round_num)
            elif self.round_visibility == "random":
                round_result = await self._run_random_round(round_num)
            elif self.round_visibility == "paired":
                round_result = await self._run_paired_round(round_num)
            else:  # sequential
                round_result = await self._run_sequential_round(round_num)

            results.append(round_result)

            # Emit round completion event (could hook into websocket)
            logger.info(f"Round {round_num} complete: {len(round_result.actions)} actions")

            # Notify scene of round completion for phase transitions (council cycle phase)
            if self.scene and hasattr(self.scene, '_advance_round'):
                logger.info(f"[CYCLE PHASE FIX] Calling scene._advance_round() for {type(self.scene).__name__}")
                self.scene._advance_round()
                logger.info(f"[CYCLE PHASE FIX] Phase is now: {getattr(self.scene, 'cycle_phase', 'N/A')}, rounds_in_phase: {getattr(self.scene, 'rounds_in_cycle_phase', 'N/A')}")

        return results

    def _record_action_to_agent(self, result: ActionResult) -> None:
        """Record an action result to the agent's history.

        Args:
            result: The action result to record
        """
        for agent in self.agents:
            if agent.name == result.agent_name:
                agent.action_history.append({
                    "round": result.round_num,
                    "action": result.action_name,
                    "content": f"Round {result.round_num}: chose {result.action_name}",
                    "success": result.success,
                    "skipped": result.skipped,
                    "summary": result.summary,
                })
                break

    def _get_pairs_for_round(self, round_num: int) -> List[tuple[str, str]] | None:
        """Find the pairs that should play in this round.

        Pairing sources (in priority order):
        1. InformationModel with pair scope and a pairing_fn
        2. Default sequential pairing when the game uses pairwise payoffs
           (grouping_mode="pairwise" AND payoff_type is not "none")

        When payoff_type is "none", pairing is skipped — every agent
        participates regardless of grouping_mode.
        """
        if (
            self.information_model
            and self.information_model.scope_type == "pair"
            and self.information_model.pairing_fn
        ):
            return self.information_model.pairing_fn(
                [agent.name for agent in self.agents],
                round_num,
            )

        # Default pairing only when the game actually calculates pairwise payoffs.
        # Games with payoff_type="none" never need pairing — all agents play.
        if (
            self.game_config.grouping_mode == "pairwise"
            and self.game_config.payoff_type not in ("none",)
        ):
            agent_names = [agent.name for agent in self.agents]
            if len(agent_names) < 2:
                return None
            return [
                (agent_names[i], agent_names[i + 1])
                for i in range(0, len(agent_names) - 1, 2)
            ]

        return None

    def _get_active_agent_names_for_pairs(self, pairs: List[tuple[str, str]] | None) -> set[str] | None:
        """List which agents should act when a round uses pairs."""
        if pairs is None:
            return None
        active_agents: set[str] = set()
        for agent1_name, agent2_name in pairs:
            active_agents.add(agent1_name)
            active_agents.add(agent2_name)
        return active_agents

    def _should_prompt_only_paired_agents(self) -> bool:
        """Return True only for real pairwise payoff rounds."""
        return (
            self.game_config.grouping_mode == "pairwise"
            and self.game_config.payoff_type not in ("none",)
        )

    def _calculate_scores(self, round_actions: List[ActionResult], pairs: List[tuple] = None) -> Dict[str, int | float]:
        """Calculate and update scores based on game outcomes using PayoffEngine.

        Args:
            round_actions: List of action results from the round
            pairs: Optional list of (agent1_name, agent2_name) tuples for paired mode.
                   If not provided, all agents play against each other (2-agent case).

        Returns:
            Dict mapping agent name to payoff earned this round (empty if not applicable)
        """
        # Get payoff_type from game_config
        payoff_type = getattr(self.game_config, 'payoff_type', 'none')

        # Build graph from pairs if available
        graph = None
        if pairs:
            graph = {"edges": pairs}

        # Get payoff_config from game_config
        payoff_config = getattr(self.game_config, 'payoff_config', {})

        # Fallback: Build config from legacy fields if payoff_config is empty
        if not payoff_config and self.game_config.cooperate_reward is not None:
            payoff_config = {
                "matrix": {
                    "cooperate_cooperate": {"value": self.game_config.cooperate_reward or 0},
                    "cooperate_defect": {"row": self.game_config.sucker_penalty or 0, "col": self.game_config.temptation_reward or 0},
                    "defect_cooperate": {"row": self.game_config.temptation_reward or 0, "col": self.game_config.sucker_penalty or 0},
                    "defect_defect": {"value": self.game_config.defect_penalty or 0},
                }
            }

        # Get grouping_mode from game_config
        grouping_mode = getattr(self.game_config, 'grouping_mode', 'pairwise')

        # Get ExperimentState from scene for contribution validation (BUG-PGG-01, BUG-PGG-02)
        current_state = None
        if self.scene and hasattr(self.scene, 'state'):
            current_state = self.scene.state

        # Calculate payoffs using PayoffEngine
        round_payoffs = self.payoff_engine.calculate_round_payoffs(
            payoff_type=payoff_type,
            actions=round_actions,
            config=payoff_config,
            grouping_mode=grouping_mode,
            graph=graph,
            state=current_state,
        )

        # Update agent scores
        agent_objs = {a.name: a for a in self.agents}
        for agent_name, payoff in round_payoffs.items():
            if agent_name in agent_objs:
                agent_objs[agent_name].score += round(payoff, 2)
                logger.debug(f"Score updated: {agent_name}={agent_objs[agent_name].score}")

        return round_payoffs

    def _apply_coordination_feedback(self, actions: List[ActionResult], round_num: int) -> None:
        """Apply coordination feedback for feedback-type games to all round modes.

        Generates neighbor-based feedback for each agent and stores it on the
        corresponding round event so the next prompt includes it.
        """
        if self.game_config.payoff_type != "feedback":
            return
        for result in actions:
            if not result.skipped:
                feedback = self._generate_coordination_feedback(
                    result.agent_name,
                    result.action_name,
                    actions,
                )
                for event in self.context_manager._round_events:
                    if event.agent_name == result.agent_name and event.round_num == round_num:
                        event.feedback = feedback

    def _generate_coordination_feedback(
        self,
        agent_name: str,
        agent_choice: str,
        round_actions: List[ActionResult],
    ) -> str:
        """Generate coordination feedback for an agent based on neighbor choices.

        Args:
            agent_name: The agent to generate feedback for
            agent_choice: What the agent chose
            round_actions: All actions from this round

        Returns:
            Human-readable feedback string
        """
        # Get neighbors from graph
        graph = self.scene_state.get("graph", {})
        edges = graph.get("edges", [])

        # Find this agent's neighbors
        neighbors = []
        for a, b in edges:
            if a == agent_name:
                neighbors.append(b)
            elif b == agent_name:
                neighbors.append(a)

        # Build choices dict from round actions
        all_choices = {a.agent_name: a.action_name for a in round_actions if not a.skipped}

        return self.feedback_builder.build_feedback(
            agent_name=agent_name,
            agent_choice=agent_choice,
            neighbors=neighbors,
            all_choices=all_choices,
            goal=self.game_config.payoff_config.get("goal", "match"),
        )

    async def _run_simultaneous_round(self, round_num: int) -> RoundResult:
        """Run a round where all agents decide simultaneously.

        Agents cannot see each other's choices for this round.
        """
        actions = []
        pairs = self._get_pairs_for_round(round_num)
        agents_to_prompt = self.agents
        if self._should_prompt_only_paired_agents():
            active_agent_names = self._get_active_agent_names_for_pairs(pairs)
            if active_agent_names is not None:
                agents_to_prompt = [
                    agent for agent in self.agents if agent.name in active_agent_names
                ]

        # Cap concurrent LLM calls so the model server is not overwhelmed.
        # Tune via FOS_LLM_CONCURRENCY env var (default 10).
        max_concurrent = int(os.environ.get("FOS_LLM_CONCURRENCY", "10"))
        semaphore = asyncio.Semaphore(max_concurrent)

        # Circuit breaker: if N consecutive agents fail, the LLM provider is
        # likely down. Fail-fast remaining agents instead of each one independently
        # timing out. Tune via FOS_CIRCUIT_BREAKER env var (default 5).
        circuit_threshold = int(os.environ.get("FOS_CIRCUIT_BREAKER", "5"))
        consecutive_failures = 0

        # Group agents by model for batched execution
        model_groups = self._group_agents_by_model(agents_to_prompt)

        async def _prompt_with_limit(agent):
            nonlocal consecutive_failures

            if consecutive_failures >= circuit_threshold:
                logger.warning(
                    f"Circuit breaker tripped ({consecutive_failures} consecutive "
                    f"failures), skipping {agent.name}"
                )
                return ActionResult(
                    agent_name=agent.name,
                    action_name="skip",
                    parameters={"error": "Circuit breaker: LLM provider appears down"},
                    summary="Skipped - circuit breaker tripped",
                    success=False,
                    skipped=True,
                    round_num=round_num,
                    error="Circuit breaker tripped"
                )

            async with semaphore:
                result = await self._prompt_agent(agent, round_num)

            if isinstance(result, Exception) or getattr(result, 'skipped', False) or not getattr(result, 'success', True):
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            return result

        for model_name, group_agents in model_groups:
            # Preload this model once for the entire group (if it has a real model)
            if model_name is not None:
                self._model_switch_lock.acquire()
                try:
                    first_agent_client = self.get_agent_llm_client(group_agents[0])
                    port = self._get_port_from_client(first_agent_client)
                    if model_name != self._last_model_per_port.get(port):
                        logger.info("Model batch switch: %s -> %s", self._last_model_per_port.get(port), model_name)
                        logger.debug("port=%s _last=%s, switching to %s", port, self._last_model_per_port.get(port), model_name)
                        if not self._preload_model(model_name, first_agent_client):
                            logger.error("Preload FAILED for model '%s' — skipping group", model_name)
                            for agent in group_agents:
                                actions.append(ActionResult(
                                    agent_name=agent.name,
                                    action_name="skip",
                                    parameters={"error": f"Model '{model_name}' failed to load"},
                                    summary="Skipped - model load failed",
                                    success=False,
                                    skipped=True,
                                    round_num=round_num,
                                    error=f"Model load timeout: {model_name}",
                                ))
                                self._record_action_to_agent(ActionResult(
                                    agent_name=agent.name,
                                    action_name="skip",
                                    parameters={"error": f"Model '{model_name}' failed to load"},
                                    summary="Skipped - model load failed",
                                    success=False,
                                    skipped=True,
                                    round_num=round_num,
                                    error=f"Model load timeout: {model_name}",
                                ))
                            continue
                        self._last_model_per_port[port] = model_name
                finally:
                    self._model_switch_lock.release()

            # Run all agents in this group concurrently (same model, no race)
            tasks = [_prompt_with_limit(agent) for agent in group_agents]
            self._skip_model_lock = True
            try:
                group_results = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self._skip_model_lock = False

            for result in group_results:
                if isinstance(result, Exception):
                    logger.error(f"Agent failed: {result}")
                    continue
                actions.append(result)
                self._record_action_to_agent(result)

        # Calculate scores - use InformationModel's pairing_fn if available so
        # n-agent games calculate per-pair payoffs correctly.
        round_payoffs = self._calculate_scores(actions, pairs=pairs)

        # CRITICAL: Store last_contribution for show_average_contribution display setting
        # This must happen before record_action_with_observers so context builder
        # can read it when building context for the NEXT round
        if self.scene and hasattr(self.scene, 'state'):
            for result in actions:
                if not result.skipped and result.action_name in ("allocate", "contribute"):
                    amount = result.parameters.get("amount", 0)
                    # Ensure amount is an integer (LLM might return string)
                    if isinstance(amount, str):
                        try:
                            amount = int(amount)
                        except ValueError:
                            amount = 0
                    if result.agent_name in self.scene.state.agents:
                        self.scene.state.agents[result.agent_name].properties["last_contribution"] = amount

        # Record to context with observers and payoffs (done after scores are known
        # so payoff can be stored with the event; simultaneous = no mid-round visibility)
        for result in actions:
            if result.success:
                self.context_manager.record_action_with_observers(
                    agent_name=result.agent_name,
                    action_name=result.action_name,
                    parameters=result.parameters,
                    round_num=round_num,
                    summary=result.summary,
                    payoff=round_payoffs.get(result.agent_name),
                )

        self._apply_coordination_feedback(actions, round_num)

        return RoundResult(
            round_num=round_num,
            actions=actions,
            completed=len(actions) == len(agents_to_prompt),
            payoffs=round_payoffs if round_payoffs else None
        )

    async def _run_sequential_round(self, round_num: int) -> RoundResult:
        """Run a round where agents decide sequentially.

        Each agent sees previous agents' choices from this round.
        The controller records each action immediately, making it visible
        to subsequent agents via the context_manager.
        """
        actions = []
        pairs = self._get_pairs_for_round(round_num)
        agents_to_prompt = self.agents
        if self._should_prompt_only_paired_agents():
            active_agent_names = self._get_active_agent_names_for_pairs(pairs)
            if active_agent_names is not None:
                agents_to_prompt = [
                    agent for agent in self.agents if agent.name in active_agent_names
                ]

        for agent in agents_to_prompt:
            result = await self._prompt_agent(agent, round_num)
            actions.append(result)
            # Record action to agent's history
            self._record_action_to_agent(result)
            # Record to context immediately so the next agent can observe it
            if result.success:
                self.context_manager.record_action_with_observers(
                    agent_name=result.agent_name,
                    action_name=result.action_name,
                    parameters=result.parameters,
                    round_num=round_num,
                    summary=result.summary,
                    payoff=None,  # payoff unknown until round ends
                )

        # Calculate scores based on actions
        round_payoffs = self._calculate_scores(actions, pairs=pairs)

        # CRITICAL: Store last_contribution for show_average_contribution display setting
        if self.scene and hasattr(self.scene, 'state'):
            for result in actions:
                if not result.skipped and result.action_name in ("allocate", "contribute"):
                    amount = result.parameters.get("amount", 0)
                    if result.agent_name in self.scene.state.agents:
                        self.scene.state.agents[result.agent_name].properties["last_contribution"] = amount

        self._apply_coordination_feedback(actions, round_num)

        return RoundResult(
            round_num=round_num,
            actions=actions,
            completed=len(actions) == len(agents_to_prompt),
            payoffs=round_payoffs if round_payoffs else None
        )

    async def _run_random_round(self, round_num: int) -> RoundResult:
        """Run a round where agents decide in random order.

        Each agent sees previous agents' choices from this round.
        The order is shuffled at the start of each round.
        """
        import random

        # Shuffle agent order for this round
        self.turn_order = [agent.name for agent in self.agents]
        random.shuffle(self.turn_order)

        logger.debug(f"Random turn order for round {round_num}: {self.turn_order}")

        # Create a mapping from name to agent
        agent_map = {agent.name: agent for agent in self.agents}
        pairs = self._get_pairs_for_round(round_num)
        active_agent_names = None
        if self._should_prompt_only_paired_agents():
            active_agent_names = self._get_active_agent_names_for_pairs(pairs)

        actions = []
        for agent_name in self.turn_order:
            if active_agent_names is not None and agent_name not in active_agent_names:
                continue
            agent = agent_map[agent_name]
            result = await self._prompt_agent(agent, round_num)
            actions.append(result)
            # Record action to agent's history
            self._record_action_to_agent(result)
            # Record to context immediately so the next agent can observe it
            if result.success:
                self.context_manager.record_action_with_observers(
                    agent_name=result.agent_name,
                    action_name=result.action_name,
                    parameters=result.parameters,
                    round_num=round_num,
                    summary=result.summary,
                    payoff=None,  # payoff unknown until round ends
                )

        # Calculate scores - use InformationModel's pairing_fn if available so
        # n-agent games calculate per-pair payoffs correctly.
        round_payoffs = self._calculate_scores(actions, pairs=pairs)

        # CRITICAL: Store last_contribution for show_average_contribution display setting
        if self.scene and hasattr(self.scene, 'state'):
            for result in actions:
                if not result.skipped and result.action_name in ("allocate", "contribute"):
                    amount = result.parameters.get("amount", 0)
                    if result.agent_name in self.scene.state.agents:
                        self.scene.state.agents[result.agent_name].properties["last_contribution"] = amount

        self._apply_coordination_feedback(actions, round_num)

        return RoundResult(
            round_num=round_num,
            actions=actions,
            completed=len(actions) == len(
                [name for name in self.turn_order if active_agent_names is None or name in active_agent_names]
            ),
            payoffs=round_payoffs if round_payoffs else None
        )

    async def _run_paired_round(self, round_num: int) -> RoundResult:
        """Run a round where agents are randomly paired.

        Each round:
        1. Shuffle agents randomly
        2. Form pairs (agent[0] vs agent[1], agent[2] vs agent[3], etc.)
        3. If odd number of agents, one sits out
        4. Each pair plays simultaneously (within the pair, they don't see each other's choices)
        5. Track cumulative scores per agent

        Cumulative scores are stored in self.scores and can be used for
        payoff calculations or tournament-style scenarios.
        """
        import random

        # Shuffle agent order for this round
        self.turn_order = [agent.name for agent in self.agents]
        random.shuffle(self.turn_order)

        logger.debug(f"Paired mode - shuffled order for round {round_num}: {self.turn_order}")

        # Create a mapping from name to agent
        agent_map = {agent.name: agent for agent in self.agents}

        # Form pairs and track who sits out
        pairs = []
        sat_out = None

        for i in range(0, len(self.turn_order), 2):
            if i + 1 < len(self.turn_order):
                pairs.append((self.turn_order[i], self.turn_order[i + 1]))
            else:
                sat_out = self.turn_order[i]

        if sat_out:
            logger.debug(f"Agent {sat_out} sits out this round (odd number of agents)")

        # Execute each pair simultaneously (within the pair)
        all_actions = []

        for pair_idx, (agent1_name, agent2_name) in enumerate(pairs):
            logger.debug(f"Pair {pair_idx + 1}: {agent1_name} vs {agent2_name}")

            # Get the agents for this pair
            agent1 = agent_map[agent1_name]
            agent2 = agent_map[agent2_name]

            # Prompt both agents in parallel (simultaneous within the pair)
            tasks = [
                self._prompt_agent(agent1, round_num),
                self._prompt_agent(agent2, round_num)
            ]
            pair_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in pair_results:
                if isinstance(result, Exception):
                    logger.error(f"Agent in pair failed: {result}")
                    continue
                all_actions.append(result)
                # Record action to agent's history
                self._record_action_to_agent(result)

        # Calculate scores based on actions (for paired mode, scores are calculated per-pair)
        round_payoffs = self._calculate_scores(all_actions, pairs=pairs)

        # CRITICAL: Store last_contribution for show_average_contribution display setting
        if self.scene and hasattr(self.scene, 'state'):
            for result in all_actions:
                if not result.skipped and result.action_name in ("allocate", "contribute"):
                    amount = result.parameters.get("amount", 0)
                    # Ensure amount is an integer (LLM might return string)
                    if isinstance(amount, str):
                        try:
                            amount = int(amount)
                        except ValueError:
                            amount = 0
                    if result.agent_name in self.scene.state.agents:
                        self.scene.state.agents[result.agent_name].properties["last_contribution"] = amount

        # Record to context with observers and payoffs (after scores are known)
        for result in all_actions:
            if result.success:
                self.context_manager.record_action_with_observers(
                    agent_name=result.agent_name,
                    action_name=result.action_name,
                    parameters=result.parameters,
                    round_num=round_num,
                    summary=result.summary,
                    payoff=round_payoffs.get(result.agent_name),
                )

        # Also update the legacy scores dict for backwards compatibility
        for action in all_actions:
            if not action.skipped and action.agent_name not in self.scores:
                self.scores[action.agent_name] = 0

        logger.debug(f"Paired round {round_num} complete: {len(all_actions)} actions across {len(pairs)} pairs")

        self._apply_coordination_feedback(all_actions, round_num)

        return RoundResult(
            round_num=round_num,
            actions=all_actions,
            completed=len(all_actions) == len(pairs) * 2,
            payoffs=round_payoffs if round_payoffs else None
        )

    async def _run_single_round(
        self, round_num: int, context_summary: str, round_history: list = None
    ) -> RoundResult:
        """Run a single round with provided context summary.

        This method is called by ExperimentScene to run one round at a time.
        It builds per-agent context based on visibility settings.

        Args:
            round_num: The round number to run
            context_summary: Shared context summary from previous rounds (fallback)
            round_history: Full round history for per-agent context filtering

        Returns:
            RoundResult with all agent actions for this round
        """
        self.current_round = round_num
        # Capture host messages for this round then clear so they don't repeat
        self._round_host_messages: list[str] = list(self.pending_host_messages)
        self.pending_host_messages = []
        logger.info(f"Starting round {round_num}")

        # Populate _round_events from round_history so get_context_for_agent()
        # (which reads from _round_events when information_model is set) has data
        if round_history:
            self._replay_history_to_events(round_history)

        elif context_summary:
            # Fallback to shared context if no round_history provided
            self.context_manager.set_initial_context(context_summary)

        # PGG Phase: Reset deduction budget when entering deduct phase
        # This must happen BEFORE agents are prompted so they see fresh budget
        if (self.scene and
            hasattr(self.scene, 'config') and
            getattr(self.scene.config, 'scenario_id', None) == "public_goods" and
            hasattr(self.scene, 'get_pgg_phase') and
            self.scene.get_pgg_phase() == "deduct"):
            self.scene._reset_deduction_budgets()
            logger.debug(f"[PGG] Reset deduction budgets for deduct phase (round {round_num})")

        # Run the round with appropriate visibility mode
        if self.round_visibility == "simultaneous":
            round_result = await self._run_simultaneous_round(round_num)
        elif self.round_visibility == "random":
            round_result = await self._run_random_round(round_num)
        elif self.round_visibility == "paired":
            round_result = await self._run_paired_round(round_num)
        else:  # sequential
            round_result = await self._run_sequential_round(round_num)

        # PGG Phase: Advance phase after round completes
        # This toggles between allocate <-> deduct for next round
        if self.scene and hasattr(self.scene, 'advance_pgg_phase'):
            old_phase = self.scene.get_pgg_phase() if hasattr(self.scene, 'get_pgg_phase') else 'unknown'
            self.scene.advance_pgg_phase()
            new_phase = self.scene.get_pgg_phase() if hasattr(self.scene, 'get_pgg_phase') else 'unknown'
            logger.info(f"[PGG] Phase advanced: {old_phase} -> {new_phase} (round {round_num} complete)")
            logger.debug(f"[PGG] Advanced phase (round {round_num} complete)")
            # Also write to debug file for visibility
            write_debug(f"\n[PGG] Phase advanced: {old_phase} -> {new_phase} (round {round_num} complete)\n")

        logger.info(f"Round {round_num} complete: {len(round_result.actions)} actions")

        return round_result

    async def _prompt_agent(self, agent: ExperimentAgent, round_num: int) -> ActionResult:
        """Prompt a single agent and process their response.

        Args:
            agent: Agent to prompt
            round_num: Current round number

        Returns:
            ActionResult from processing the response
        """
        # Build prompt with current context (with section markers for debugging)
        context = self.context_manager.get_context_for_agent(agent.name, agent_score=agent.score)

        # Prepend host messages to context
        round_host_msgs = getattr(self, '_round_host_messages', [])
        if round_host_msgs:
            host_block = "\n".join(f"[HOST MESSAGE]: {m}" for m in round_host_msgs)
            context = f"{host_block}\n\n{context}" if context else host_block

        # Build KB context from agent's knowledge base (keyword match against context)
        kb_context = agent.get_rag_context(
            query=context[:200] if context else "",
            global_knowledge=getattr(self.scene, 'global_knowledge', {}),
            top_k=3,
        )

        # Build neighbor context from social graph
        neighbor_context = ""
        graph = self.scene_state.get("graph", {})
        if not graph and self.scene is not None:
            graph = getattr(getattr(self.scene, "config", None), "social_network", {}) or {}
        edges = graph.get("edges", [])
        if edges:
            neighbors = [b for a, b in edges if a == agent.name] + [a for a, b in edges if b == agent.name]
            if neighbors:
                neighbor_context = f"Your social network neighbors: {', '.join(neighbors)}."
        if self.scene and hasattr(self.scene, "include_social_network_section"):
            if not self.scene.include_social_network_section():
                neighbor_context = ""

        # Feedback buffer injection: include any environment feedback
        # from the previous turn in the agent's context so they see
        # error messages about invalid targets, missing messages, etc.
        feedback_text = agent.get_feedback_text()
        if feedback_text:
            context = f"{context}\n\n[ENVIRONMENT FEEDBACK]\n{feedback_text}" if context else feedback_text

        # GAP-CLOSURE-01: Get filtered actions from scene if available (phase-based filtering)
        # IMPORTANT: Must happen BEFORE build_prompt, not after!
        allowed_actions = None
        speak_instruction = None
        if self.scene and hasattr(self.scene, 'get_scene_actions'):
            allowed_actions = self.scene.get_scene_actions(agent.name)
        if self.scene and hasattr(self.scene, 'get_speak_instruction'):
            speak_instruction = self.scene.get_speak_instruction()

        # CONFEDERATE VOTE INTERCEPTION
        # If this agent is a confederate and we're in VOTING phase,
        # write its predetermined vote directly — no LLM call.
        conf_lookup = getattr(self.scene, '_conf_lookup', {}) if self.scene else {}
        if agent.name in conf_lookup and allowed_actions and 'vote_yes' in allowed_actions:
            conf_spec = conf_lookup[agent.name]
            record_confederate_vote(conf_spec, self.scene.state.extensions)
            # Return a synthetic ActionResult — no LLM call was made
            vote_str = conf_spec.stance
            return ActionResult(
                agent_name=agent.name,
                action_name=f'vote_{vote_str}',
                parameters={'choice': vote_str},
                summary=f'{agent.name} voted {vote_str} (confederate)',
                round_num=0,
                success=True,
                skipped=False,
            )

        _locale = getattr(getattr(self.scene, 'config', None), 'locale', 'en') if self.scene else 'en'
        prompt = build_prompt(
            agent, self.game_config, context, include_section_markers=True,
            information_model=self.information_model,
            kb_context=kb_context,
            neighbor_context=neighbor_context,
            allowed_actions=allowed_actions,
            speak_instruction=speak_instruction,
            locale=_locale,
        )

        # Build debug output buffer (will be written atomically after LLM call)
        debug_buffer = []
        debug_buffer.append(f"\n{'#'*80}\n")
        debug_buffer.append(f"# LLM DEBUG LOG - {datetime.now().isoformat()}\n")
        debug_buffer.append(f"{'#'*80}\n\n")
        debug_buffer.append(f"## AGENT: {agent.name}\n")
        debug_buffer.append(f"## ROUND: {round_num}\n")
        debug_buffer.append(f"## VISIBILITY MODE: {self.round_visibility}\n")

        # ACTION FILTERING DEBUG - show what actions were filtered
        debug_buffer.append("\n--- ACTION FILTERING ---\n")
        debug_buffer.append(f"  self.scene type: {type(self.scene).__name__ if self.scene else 'None'}\n")
        debug_buffer.append(f"  has get_scene_actions: {hasattr(self.scene, 'get_scene_actions') if self.scene else 'N/A'}\n")
        # PGG Phase debug
        if self.scene and hasattr(self.scene, 'get_pgg_phase'):
            debug_buffer.append(f"  PGG phase: {self.scene.get_pgg_phase()}\n")
        if allowed_actions:
            debug_buffer.append(f"  filtered actions for {agent.name}: {allowed_actions}\n")
        else:
            debug_buffer.append("  filtered actions: None (no filtering available)\n")

        # --- NETWORK VISIBILITY DEBUG ---
        if self.information_model and self.information_model.scope_type in ("neighborhood", "neighbor"):
            debug_buffer.append("\n--- NETWORK VISIBILITY ---\n")
            graph = self.scene_state.get("graph", {})
            edges = graph.get("edges", [])
            if edges:
                # Build a map of agent -> neighbors
                neighbor_map = {}
                for a, b in edges:
                    if a not in neighbor_map:
                        neighbor_map[a] = []
                    if b not in neighbor_map:
                        neighbor_map[b] = []
                    neighbor_map[a].append(b)
                    neighbor_map[b].append(a)
                # Show each agent's connections
                for agent_obj in sorted(self.agents, key=lambda x: neighbor_map.get(x.name, [])):
                    neighbor_names = sorted(neighbor_map.get(agent_obj.name, []))
                    debug_buffer.append(f"  {agent_obj.name}: connected to {neighbor_names}\n")
            else:
                debug_buffer.append("  (No network edges configured)\n")

        # --- PAIRINGS (for paired games) ---
        if self.information_model and self.information_model.scope_type == "pair" and self.information_model.pairing_fn:
            debug_buffer.append(f"\n--- ROUND {round_num} PAIRINGS ---\n")
            pairs = self.information_model.pairing_fn([a.name for a in self.agents], round_num)
            for a, b in pairs:
                debug_buffer.append(f"  {a} paired with {b}\n")

        debug_buffer.append("--- AGENT PROPERTIES ---\n")
        for k, v in agent.get_properties_dict().items():
            debug_buffer.append(f"  {k}: {v}\n")

        # --- LLM CLIENT DEBUG --- show the ACTUAL client that will make the LLM call
        # This uses the same resolution logic as get_agent_llm_client() at the call site
        _resolved_client = self.agent_llm_clients.get(agent.name) if self.agent_llm_clients else None
        if _resolved_client is None:
            _resolved_client = self.llm_client
        _p = _resolved_client.provider if hasattr(_resolved_client, "provider") else None
        if _p:
            debug_buffer.append("\n--- LLM CLIENT (actual) ---\n")
            debug_buffer.append(f"  source: {'per-agent distribution' if agent.name in (self.agent_llm_clients or {}) else 'default/fallback'}\n")
            debug_buffer.append(f"  provider_id: {agent.properties.get('provider_id', 'N/A')}\n")
            debug_buffer.append(f"  dialect: {_p.dialect}\n")
            debug_buffer.append(f"  model: {_p.model}\n")
            debug_buffer.append(f"  base_url: {_p.base_url}\n")
        else:
            debug_buffer.append("\n--- LLM CLIENT (actual) ---\n")
            debug_buffer.append(f"  source: {'per-agent distribution' if agent.name in (self.agent_llm_clients or {}) else 'default/fallback'}\n")
            debug_buffer.append(f"  provider_id: {agent.properties.get('provider_id', 'N/A')}\n")
            debug_buffer.append(f"  client type: {type(_resolved_client).__name__}\n")
        debug_buffer.append("\n--- GAME CONFIG ---\n")
        debug_buffer.append(f"  scenario: {self.game_config.description[:100]}...\n")
        # GAP-CLOSURE-01: Show filtered actions in debug output
        if allowed_actions:
            debug_buffer.append(f"  actions (filtered): {allowed_actions}\n")
        else:
            debug_buffer.append(f"  actions: {self.game_config.actions}\n")
        debug_buffer.append(f"  action_type: {self.game_config.action_type}\n")
        debug_buffer.append(f"  output_field: {self.game_config.output_field}\n")
        if self.game_config.action_descriptions:
            debug_buffer.append(f"  action_descriptions: {self.game_config.action_descriptions}\n")
        debug_buffer.append("\n--- CONTEXT (filtered for this agent) ---\n")
        debug_buffer.append(f"{context[:500]}...\n" if len(context) > 500 else f"{context}\n")
        debug_buffer.append(f"\n{'='*80}\n")
        debug_buffer.append("FULL PROMPT SENT TO LLM\n")
        debug_buffer.append(f"{'='*80}\n\n")
        debug_buffer.append(prompt)
        debug_buffer.append(f"\n\n{'='*80}\n")
        debug_buffer.append("END OF PROMPT\n")
        debug_buffer.append(f"{'='*80}\n\n")

        logger.debug(f"Prompting agent {agent.name} for round {round_num}")
        logger.debug(f"Game config: actions={self.game_config.actions}, type={self.game_config.action_type}")

        try:
            # Get per-agent LLM client (LLM distribution)
            agent_llm_client = self.get_agent_llm_client(agent)

            # Preload model if switching, then hold lock through entire chat
            # lifecycle (preload + chat + controller) so no other agent can
            # unload the model while we are using it.
            model_name = getattr(getattr(agent_llm_client, "provider", None), "model", "")
            # Guard: model_name must be a non-empty string (Mock objects in tests
            # return Mock attributes, not real strings)
            if isinstance(model_name, str) and model_name:
                _skip_model_lock = getattr(self, '_skip_model_lock', False)
                if not _skip_model_lock:
                    self._model_switch_lock.acquire()
                try:
                    if not _skip_model_lock and model_name != self._last_model:
                        logger.info(
                            "Model switch: %s -> %s", self._last_model, model_name
                        )
                        if not self._preload_model(model_name, agent_llm_client):
                            logger.error(
                                "Preload FAILED for model '%s' — cannot prompt agent %s",
                                model_name, agent.name,
                            )
                            # Write debug buffer before returning
                            await self._write_debug_atomically(debug_buffer)
                            agent.clear_feedback_buffer()
                            return ActionResult(
                                agent_name=agent.name,
                                action_name="skip",
                                parameters={"error": f"Model '{model_name}' failed to load"},
                                summary="Skipped - model load failed",
                                success=False,
                                skipped=True,
                                round_num=round_num,
                                error=f"Model load timeout: {model_name}",
                                prompt_tokens=0,
                                degraded=False,
                                degrade_reason="",
                                rounds_dropped=0,
                                tokens_before=0,
                                tokens_after=0,
                            )
                        self._last_model = model_name

                    # Chat request: model is locked, no other agent can unload it
                    # --- 3-tier degradation handling ---
                    _tokens_before = _count_tokens(prompt)
                    _degraded = False
                    _degrade_reason = ""
                    _rounds_dropped = 0
                    _tokens_after = 0
                    _limit = getattr(agent_llm_client, 'server_ctx_size', None)
                    if isinstance(_limit, int):
                        _max_tokens = getattr(getattr(agent_llm_client, 'provider', None), 'max_tokens', 1024)
                        if isinstance(_max_tokens, int):
                            _limit = _limit - _max_tokens - 100
                        else:
                            _limit = None
                    else:
                        _limit = None

                    if _limit is None or _tokens_before <= _limit:
                        # Fits — send normally
                        messages = [{"role": "user", "content": prompt}]
                        raw_response = await asyncio.to_thread(
                            agent_llm_client.chat, messages, json_mode=True
                        )
                    else:
                        _degraded = True
                        _tokens_after = _tokens_before
                        # Tier 1: Rebuild with truncated speech (recap)
                        _recap = getattr(self.information_model, "recap_tokens", 400) if hasattr(self, "information_model") else 400
                        visible_events = [
                            e for e in self.context_manager._round_events
                            if agent.name in e.observed_by
                        ]
                        _capped_events = _truncate_speech_events(list(visible_events), _recap)
                        _recap_context = build_structured_context(
                            for_agent=agent.name, events=_capped_events, info_model=self.information_model,
                            agent_score=agent.score if getattr(self.information_model, 'include_scores', False) else None,
                        )
                        _recap_prompt = build_prompt(
                            agent=agent, game_config=self.game_config, context_summary=_recap_context,
                            information_model=self.information_model, kb_context=kb_context,
                            neighbor_context=neighbor_context, allowed_actions=allowed_actions,
                            speak_instruction=speak_instruction, locale=_locale,
                        )
                        _recap_tokens = _count_tokens(_recap_prompt)
                        if _recap_tokens <= _limit:
                            _degrade_reason = "recap_400"
                            _tokens_after = _recap_tokens
                            messages = [{"role": "user", "content": _recap_prompt}]
                            raw_response = await asyncio.to_thread(
                                agent_llm_client.chat, messages, json_mode=True
                            )
                        else:
                            # Tier 2: Drop oldest non-round-1 rounds one at a time
                            _round_nums = sorted(set(e.round_num for e in visible_events))
                            _drop_candidates = sorted([r for r in _round_nums if r != 1])
                            raw_response = None
                            for _drop_idx in range(len(_drop_candidates)):
                                _kept_rounds = {1} | set(_drop_candidates[_drop_idx+1:])
                                _filtered = [e for e in visible_events if e.round_num in _kept_rounds]
                                _ctx = build_structured_context(
                                    for_agent=agent.name, events=_filtered, info_model=self.information_model,
                                    agent_score=agent.score if getattr(self.information_model, 'include_scores', False) else None,
                                )
                                _p = build_prompt(
                                    agent=agent, game_config=self.game_config, context_summary=_ctx,
                                    information_model=self.information_model, kb_context=kb_context,
                                    neighbor_context=neighbor_context, allowed_actions=allowed_actions,
                                    speak_instruction=speak_instruction, locale=_locale,
                                )
                                _tok = _count_tokens(_p)
                                if _tok <= _limit:
                                    _degrade_reason = "rounds_dropped"
                                    _rounds_dropped = _drop_idx + 1
                                    _tokens_after = _tok
                                    messages = [{"role": "user", "content": _p}]
                                    raw_response = await asyncio.to_thread(
                                        agent_llm_client.chat, messages, json_mode=True
                                    )
                                    break
                            # Tier 3: Nothing fits — return failure
                            if raw_response is None:
                                _degrade_reason = "failed"
                                await self._write_debug_atomically(debug_buffer)
                                agent.clear_feedback_buffer()
                                return ActionResult(
                                    agent_name=agent.name,
                                    action_name="skip",
                                    parameters={"error": "Prompt too large after all degradation tiers"},
                                    summary="Skipped - prompt overflow",
                                    success=False,
                                    skipped=True,
                                    round_num=round_num,
                                    error=f"Prompt {_tokens_before}t exceeds limit {_limit}t after all degradation",
                                    prompt_tokens=_tokens_before,
                                    degraded=True,
                                    degrade_reason="failed",
                                    rounds_dropped=0,
                                    tokens_before=_tokens_before,
                                    tokens_after=_tokens_before,
                                )

                    # Handle empty response gracefully (e.g., Qwen3 via Ollama returns 0 chars)
                    if not raw_response or not raw_response.strip():
                        logger.error(f"Empty response from LLM for {agent.name}")
                        debug_buffer.append(f"\n{'!'*80}\n")
                        debug_buffer.append("EMPTY RESPONSE\n")
                        debug_buffer.append(f"{'!'*80}\n")
                        debug_buffer.append(f"Agent {agent.name} received empty response from LLM\n\n")
                        # Write debug output atomically
                        await self._write_debug_atomically(debug_buffer)
                        agent.clear_feedback_buffer()
                        return ActionResult(
                            agent_name=agent.name,
                            action_name="skip",
                            parameters={"error": "LLM returned empty response"},
                            summary="Skipped - LLM returned empty response",
                            success=False,
                            skipped=True,
                            round_num=round_num,
                            error="Empty LLM response",
                            prompt_tokens=0,
                            degraded=False,
                            degrade_reason="",
                            rounds_dropped=0,
                            tokens_before=0,
                            tokens_after=0,
                        )

                    # Process response through controller (Layer 3) — still inside lock
                    # so follow-up prompts are also protected from model switches.
                    action_schemas = self.kernel.get_action_schemas() if self.kernel else {}
                    if self.scene and getattr(getattr(self.scene, "config", None), "scenario_id", None) == "custom":
                        action_schemas.pop("speak", None)
                    action_schemas.update(self.game_config.action_schemas)

                    logger.debug(f"[RUNNER] game_config.action_followup_modes={self.game_config.action_followup_modes}")

                    if self.game_config.action_followup_modes:
                        for action_name, mode in self.game_config.action_followup_modes.items():
                            existing_schema = action_schemas.get(action_name, {})
                            if "schema" in existing_schema:
                                merged_schema = dict(existing_schema)
                                merged_schema["mode"] = mode
                                action_schemas[action_name] = merged_schema
                            else:
                                action_schemas[action_name] = {
                                    "schema": {
                                        "message": {
                                            "type": "string",
                                            "description": T("Content for {action_name}", action_name=action_name),
                                        }
                                    },
                                    "mode": mode,
                                }
                            logger.debug(f"[RUNNER] Added action_schema for '{action_name}': mode={mode}")

                    if self.scene and getattr(getattr(self.scene, "config", None), "scenario_id", None) == "custom":
                        custom_actions = allowed_actions or self.game_config.actions
                        for action_name in custom_actions:
                            custom_action_name = str(action_name)
                            if custom_action_name in action_schemas:
                                continue
                            action_schemas[custom_action_name] = self._build_custom_action_followup_schema(
                                custom_action_name,
                                _locale,
                            )
                            logger.debug(
                                f"[RUNNER] Added custom followup schema for '{action_name}' with response/reason logging"
                            )

                    logger.debug(f"[RUNNER] Final action_schemas keys: {list(action_schemas.keys())}")
                    result = await self.controller.process_response_with_followup(
                        raw_response, agent, self.game_config,
                        agent_llm_client, round_num,
                        action_schemas=action_schemas,
                        context_summary=context,
                        information_model=self.information_model,
                        kb_context=kb_context,
                        neighbor_context=neighbor_context,
                        allowed_actions=allowed_actions,
                        speak_instruction=speak_instruction,
                        locale=_locale,
                    )
                finally:
                    if not _skip_model_lock:
                        self._model_switch_lock.release()
            else:
                # No model name (mock/test client) — proceed without lock
                # --- 3-tier degradation handling ---
                _tokens_before = _count_tokens(prompt)
                _degraded = False
                _degrade_reason = ""
                _rounds_dropped = 0
                _tokens_after = 0
                _limit = getattr(agent_llm_client, 'server_ctx_size', None)
                if isinstance(_limit, int):
                    _max_tokens = getattr(getattr(agent_llm_client, 'provider', None), 'max_tokens', 1024)
                    if isinstance(_max_tokens, int):
                        _limit = _limit - _max_tokens - 100
                    else:
                        _limit = None
                else:
                    _limit = None

                if _limit is None or _tokens_before <= _limit:
                    messages = [{"role": "user", "content": prompt}]
                    raw_response = await asyncio.to_thread(
                        agent_llm_client.chat, messages, json_mode=True
                    )
                else:
                    _degraded = True
                    _tokens_after = _tokens_before
                    # Tier 1: Rebuild with truncated speech (recap)
                    _recap = getattr(self.information_model, "recap_tokens", 400) if hasattr(self, "information_model") else 400
                    visible_events = [
                        e for e in self.context_manager._round_events
                        if agent.name in e.observed_by
                    ]
                    _capped_events = _truncate_speech_events(list(visible_events), _recap)
                    _recap_context = build_structured_context(
                        for_agent=agent.name, events=_capped_events, info_model=self.information_model,
                        agent_score=agent.score if getattr(self.information_model, 'include_scores', False) else None,
                    )
                    _recap_prompt = build_prompt(
                        agent=agent, game_config=self.game_config, context_summary=_recap_context,
                        information_model=self.information_model, kb_context=kb_context,
                        neighbor_context=neighbor_context, allowed_actions=allowed_actions,
                        speak_instruction=speak_instruction, locale=_locale,
                    )
                    _recap_tokens = _count_tokens(_recap_prompt)
                    if _recap_tokens <= _limit:
                        _degrade_reason = "recap_400"
                        _tokens_after = _recap_tokens
                        messages = [{"role": "user", "content": _recap_prompt}]
                        raw_response = await asyncio.to_thread(
                            agent_llm_client.chat, messages, json_mode=True
                        )
                    else:
                        # Tier 2: Drop oldest non-round-1 rounds one at a time
                        _round_nums = sorted(set(e.round_num for e in visible_events))
                        _drop_candidates = sorted([r for r in _round_nums if r != 1])
                        raw_response = None
                        for _drop_idx in range(len(_drop_candidates)):
                            _kept_rounds = {1} | set(_drop_candidates[_drop_idx+1:])
                            _filtered = [e for e in visible_events if e.round_num in _kept_rounds]
                            _ctx = build_structured_context(
                                for_agent=agent.name, events=_filtered, info_model=self.information_model,
                                agent_score=agent.score if getattr(self.information_model, 'include_scores', False) else None,
                            )
                            _p = build_prompt(
                                agent=agent, game_config=self.game_config, context_summary=_ctx,
                                information_model=self.information_model, kb_context=kb_context,
                                neighbor_context=neighbor_context, allowed_actions=allowed_actions,
                                speak_instruction=speak_instruction, locale=_locale,
                            )
                            _tok = _count_tokens(_p)
                            if _tok <= _limit:
                                _degrade_reason = "rounds_dropped"
                                _rounds_dropped = _drop_idx + 1
                                _tokens_after = _tok
                                messages = [{"role": "user", "content": _p}]
                                raw_response = await asyncio.to_thread(
                                    agent_llm_client.chat, messages, json_mode=True
                                )
                                break
                        # Tier 3: Nothing fits — return failure
                        if raw_response is None:
                            _degrade_reason = "failed"
                            await self._write_debug_atomically(debug_buffer)
                            agent.clear_feedback_buffer()
                            return ActionResult(
                                agent_name=agent.name,
                                action_name="skip",
                                parameters={"error": "Prompt too large after all degradation tiers"},
                                summary="Skipped - prompt overflow",
                                success=False,
                                skipped=True,
                                round_num=round_num,
                                error=f"Prompt {_tokens_before}t exceeds limit {_limit}t after all degradation",
                                prompt_tokens=_tokens_before,
                                degraded=True,
                                degrade_reason="failed",
                                rounds_dropped=0,
                                tokens_before=_tokens_before,
                                tokens_after=_tokens_before,
                            )

                if not raw_response or not raw_response.strip():
                    logger.error(f"Empty response from LLM for {agent.name}")
                    debug_buffer.append(f"\n{'!'*80}\n")
                    debug_buffer.append("EMPTY RESPONSE\n")
                    debug_buffer.append(f"{'!'*80}\n")
                    debug_buffer.append(f"Agent {agent.name} received empty response from LLM\n\n")
                    await self._write_debug_atomically(debug_buffer)
                    agent.clear_feedback_buffer()
                    return ActionResult(
                        agent_name=agent.name,
                        action_name="skip",
                        parameters={"error": "LLM returned empty response"},
                        summary="Skipped - LLM returned empty response",
                        success=False,
                        skipped=True,
                        round_num=round_num,
                        error="Empty LLM response",
                        prompt_tokens=0,
                        degraded=False,
                        degrade_reason="",
                        rounds_dropped=0,
                        tokens_before=0,
                        tokens_after=0,
                    )

                action_schemas = self.kernel.get_action_schemas() if self.kernel else {}
                if self.scene and getattr(getattr(self.scene, "config", None), "scenario_id", None) == "custom":
                    action_schemas.pop("speak", None)
                action_schemas.update(self.game_config.action_schemas)

                logger.debug(f"[RUNNER] game_config.action_followup_modes={self.game_config.action_followup_modes}")

                if self.game_config.action_followup_modes:
                    for action_name, mode in self.game_config.action_followup_modes.items():
                        existing_schema = action_schemas.get(action_name, {})
                        if "schema" in existing_schema:
                            merged_schema = dict(existing_schema)
                            merged_schema["mode"] = mode
                            action_schemas[action_name] = merged_schema
                        else:
                            action_schemas[action_name] = {
                                "schema": {
                                    "message": {
                                        "type": "string",
                                        "description": T("Content for {action_name}", action_name=action_name),
                                    }
                                },
                                "mode": mode,
                            }
                        logger.debug(f"[RUNNER] Added action_schema for '{action_name}': mode={mode}")

                if self.scene and getattr(getattr(self.scene, "config", None), "scenario_id", None) == "custom":
                    custom_actions = allowed_actions or self.game_config.actions
                    for action_name in custom_actions:
                        custom_action_name = str(action_name)
                        if custom_action_name in action_schemas:
                            continue
                        action_schemas[custom_action_name] = self._build_custom_action_followup_schema(
                            custom_action_name,
                            _locale,
                        )
                        logger.debug(
                            f"[RUNNER] Added custom followup schema for '{action_name}' with response/reason logging"
                        )

                logger.debug(f"[RUNNER] Final action_schemas keys: {list(action_schemas.keys())}")
                result = await self.controller.process_response_with_followup(
                    raw_response, agent, self.game_config,
                    agent_llm_client, round_num,
                    action_schemas=action_schemas,
                    context_summary=context,
                    information_model=self.information_model,
                    kb_context=kb_context,
                    neighbor_context=neighbor_context,
                    allowed_actions=allowed_actions,
                    speak_instruction=speak_instruction,
                    locale=_locale,
                )

            # Common post-processing (outside lock):
            # Add response to debug buffer
            debug_buffer.append(f"\n{'='*80}\n")
            debug_buffer.append("LLM RAW RESPONSE\n")
            debug_buffer.append(f"{'='*80}\n\n")
            debug_buffer.append(raw_response)
            debug_buffer.append(f"\n\n{'='*80}\n")
            debug_buffer.append("END OF RESPONSE\n")
            debug_buffer.append(f"{'='*80}\n\n")

            logger.debug(f"LLM response for {agent.name}: {len(raw_response)} chars")

            logger.debug(f"Raw response from {agent.name}: {raw_response[:200]}...")

            # Append controller's debug log to buffer
            if result.debug_log:
                debug_buffer.extend(result.debug_log)


            # Write all debug output atomically (prompt + response + controller + followup)
            await self._write_debug_atomically(debug_buffer)

            logger.debug(f"Processed result: action={result.action_name}, success={result.success}, skipped={result.skipped}")
            if result.error:
                logger.debug(f"Error: {result.error}")

            # Set degradation fields on result
            result.prompt_tokens = _tokens_before
            result.degraded = _degraded
            result.degrade_reason = _degrade_reason
            result.rounds_dropped = _rounds_dropped
            result.tokens_before = _tokens_before
            result.tokens_after = _tokens_after

            agent.clear_feedback_buffer()
            return result

        except Exception as e:
            debug_buffer.append(f"\n{'!'*80}\n")
            debug_buffer.append("ERROR\n")
            debug_buffer.append(f"{'!'*80}\n")
            debug_buffer.append(f"Agent {agent.name} failed: {e}\n\n")
            # Write debug output atomically
            await self._write_debug_atomically(debug_buffer)
            logger.error(f"Error prompting agent {agent.name}: {e}")
            agent.clear_feedback_buffer()
            return ActionResult(
                success=False,
                action_name="",
                parameters={},
                summary="",
                agent_name=agent.name,
                round_num=round_num,
                skipped=True,
                error=str(e),
                prompt_tokens=0,
                degraded=False,
                degrade_reason="",
                rounds_dropped=0,
                tokens_before=0,
                tokens_after=0,
            )
