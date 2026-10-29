"""This file lists scene templates and validates template-based scene input.

- scene_config_template builds one frontend-friendly template for a scene type.
- get_template_loader finds the folders where saved templates live.
- load_all_templates reads user and system templates for the API.
- list_scenes returns the scene list used by the builder screen.
- list_templates returns saved templates grouped by source.
- validate_template checks whether one template payload is valid.
- build_scene_from_template turns one template payload into a runnable scene config.
- get_template_schema returns the JSON schema for template validation.
"""

import json
from pathlib import Path

from litestar import Router, get, post
from litestar.exceptions import HTTPException
from pydantic import ValidationError

from fos.core.agent import Agent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.game_configs import create_council_config
from fos.core.registry import SCENE_ACTIONS, SCENE_DESCRIPTIONS, SCENE_MAP, get_scene_class
from fos.i18n import T
from fos.templates.loader import TemplateLoader
from fos.templates.schema import GenericTemplate, export_json_schema


PUBLIC_SCENE_KEYS = {key for key in SCENE_MAP.keys()}

DEFAULT_SIMPLE_CHAT_NEWS = (
    "News: A new study suggests AI models now match human-level performance in creative writing benchmarks."
)

DEFAULT_COUNCIL_DRAFT = (
    "Draft Ordinance: Urban Air Quality and Congestion Management (Pilot).\n"
    "1) Establish a 12-month congestion charge pilot in the CBD with base fee 30 CNY per entry.\n"
    "2) Revenue ring-fenced for transit upgrades and air-quality programs.\n"
    "3) Monthly public dashboard on PM2.5/NOx, traffic speed, ridership.\n"
    "4) Camera enforcement with strict privacy limits.\n"
    "5) Independent evaluation at 12 months with target reductions."
)

# Template directories
USER_TEMPLATES_DIR = Path("templates")
SYSTEM_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"


def _default_experiment_scene(scene_key: str, scene_cls: type[ExperimentScene]) -> ExperimentScene:
    """Build one experiment-style scene instance with safe default config."""
    return scene_cls(
        ExperimentConfig(
            agents=[],
            actions=[],
            parameters={},
            description="",
            scenario_id=scene_key,
        )
    )


def scene_config_template(scene_key: str, scene_cls) -> dict:
    # Special handling for ExperimentScene - it has a different constructor
    if scene_key == "experiment_template":
        return {
            "type": scene_key,
            "name": "ExperimentScene",
            "description": SCENE_DESCRIPTIONS.get(scene_key, ""),
            "config_schema": {
                "agents": [],
                "actions": [],
                "parameters": {},
                "description": "",
                "scenario_id": "custom",
                "round_visibility": "simultaneous",
            },
            "allowed_actions": [],
            "basic_actions": [],
        }

    if scene_key == "council_experiment":
        council_config = create_council_config(
            proposal_text=DEFAULT_COUNCIL_DRAFT,
            deliberation_rounds=3,
            voting_threshold=0.5,
        )
        return {
            "type": scene_key,
            "name": "CouncilExperimentScene",
            "description": SCENE_DESCRIPTIONS.get(scene_key, ""),
            "config_schema": {
                "deliberation_rounds": council_config.deliberation_rounds,
                "voting_threshold": council_config.voting_threshold,
                "proposal_text": council_config.proposal_text,
                "initial_events": [],
            },
            "allowed_actions": [],
            "basic_actions": list(council_config.actions),
        }

    if scene_key == "contagion_scene":
        return {
            "type": scene_key,
            "name": "Contagion Spread",
            "description": SCENE_DESCRIPTIONS.get(scene_key, ""),
            "config_schema": {
                "parameters": {
                    "initial_infected": 1,
                    "proximity_probability": 0.3,
                    "action_probability": 0.5,
                    "recovery_turns": 5,
                    "grid_size": 10,
                },
                "initial_events": [],
            },
            "allowed_actions": [],
            "basic_actions": ["move", "speak_to"],
        }

    if isinstance(scene_cls, type) and issubclass(scene_cls, ExperimentScene):
        scene = _default_experiment_scene(scene_key, scene_cls)
        config_schema = scene.serialize_config() or {}
    else:
        scene = scene_cls("preview", "")
        config_schema = scene.serialize_config() or {}

    if scene_key == "council_scene":
        config_schema = {
            "draft_text": config_schema.get("draft_text") or DEFAULT_COUNCIL_DRAFT,
        }
    # Generalized initial events list for all scenes (shown separately in UI)
    # Provide a friendly default for simple chat
    if scene_key == "simple_chat_scene":
        config_schema["initial_events"] = [DEFAULT_SIMPLE_CHAT_NEWS]
    elif scene_key == "emotional_conflict_scene":
        # Suggest initial announcements
        config_schema["initial_events"] = [
            "Participants: Host, Lily, Alex",
            (
                "Scene start: Lily feels Alex has become emotionally distant, while Alex thinks Lily is overreacting. "
                "The host will guide them to express their emotions and seek resolution."
            ),
        ]
    else:
        config_schema.setdefault("initial_events", [])

    # Read from registry; fallback to scene introspection if not present
    reg = SCENE_ACTIONS.get(scene_key)
    if reg:
        basic_actions = list(reg.get("basic", []))
        allowed = set(reg.get("allowed", []))
    else:
        dummy = Agent.deserialize(
            {
                "name": "Preview",
                "user_profile": "",
                "style": "",
                "initial_instruction": "",
                "role_prompt": "",
                "action_space": [],
                "properties": {},
            }
        )
        basic_actions = [a.NAME for a in (scene.get_scene_actions(dummy) or []) if getattr(a, "NAME", None)]
        allowed = set()
    allowed_list = sorted(a for a in allowed if a not in set(basic_actions) and a != "yield")
    basic_list = sorted(a for a in basic_actions if a != "yield")

    # Prefer the registry key as the public type to allow aliases
    name = scene_cls.__name__
    if scene_key == "emotional_conflict_scene":
        name = "EmotionalConflictScene"
    get_description = getattr(scene, "get_scenario_description", None)
    scene_description = get_description() if callable(get_description) else ""
    return {
        "type": scene_key,
        "name": name,
        "description": SCENE_DESCRIPTIONS.get(scene_key) or scene_description or "",
        "config_schema": config_schema,
        "allowed_actions": allowed_list,
        "basic_actions": basic_list,
    }


def get_template_loader() -> TemplateLoader:
    """Get a TemplateLoader instance configured with user and system template directories."""
    # Create user templates directory if it doesn't exist
    USER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return TemplateLoader(template_dir=str(USER_TEMPLATES_DIR))


def load_all_templates() -> list[dict]:
    """Load all templates from user and system directories."""
    loader = get_template_loader()
    templates = []

    # Load user templates
    if USER_TEMPLATES_DIR.exists():
        try:
            user_templates = loader.load_from_directory(USER_TEMPLATES_DIR)
            for template in user_templates:
                templates.append({
                    "id": template.id,
                    "name": template.name,
                    "description": template.description,
                    "version": template.version,
                    "author": template.author,
                    "source": "user",
                    "core_mechanics": [m.type for m in template.core_mechanics],
                    "semantic_actions": [a.name for a in template.semantic_actions],
                })
        except FileNotFoundError:
            pass

    # Load system templates
    if SYSTEM_TEMPLATES_DIR.exists():
        try:
            system_templates = loader.load_from_directory(SYSTEM_TEMPLATES_DIR)
            for template in system_templates:
                # Check if this template ID already exists from user templates
                existing_ids = {t["id"] for t in templates}
                if template.id not in existing_ids:
                    templates.append({
                        "id": template.id,
                        "name": template.name,
                        "description": template.description,
                        "version": template.version,
                        "author": template.author,
                        "source": "system",
                        "core_mechanics": [m.type for m in template.core_mechanics],
                        "semantic_actions": [a.name for a in template.semantic_actions],
                    })
        except FileNotFoundError:
            pass

    return templates


@get("/")
async def list_scenes() -> list[dict]:
    """List all available scene types including generic_scene."""
    scenes: list[dict] = []
    for key in SCENE_MAP.keys():
        if key not in PUBLIC_SCENE_KEYS:
            continue
        scene_cls = get_scene_class(key)
        if scene_cls is None:
            continue
        scenes.append(scene_config_template(key, scene_cls))
    return scenes


@get("/templates")
async def list_templates() -> dict[str, list[dict]]:
    """List all templates (system + user-defined).

    Returns a dictionary with separate lists for system and user templates.
    """
    templates = load_all_templates()
    return {
        "system": [t for t in templates if t["source"] == "system"],
        "user": [t for t in templates if t["source"] == "user"],
    }


@post("/templates/validate")
async def validate_template(data: dict) -> dict:
    """Validate a template configuration.

    Accepts a template dictionary and validates it against the GenericTemplate schema.
    Returns validation result with any errors found.

    Args:
        data: Template configuration as a dictionary.

    Returns:
        Dictionary with 'valid' boolean and optional 'errors' list.
    """
    try:
        template = GenericTemplate.model_validate(data)
        return {
            "valid": True,
            "template": {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "version": template.version,
                "author": template.author,
            },
        }
    except ValidationError as e:
        return {
            "valid": False,
            "errors": json.loads(e.json()),
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": [{"message": str(e)}],
        }


@post("/templates/build")
async def build_scene_from_template(data: dict) -> dict:
    """Build a scene from a template configuration.

    Accepts a template dictionary and returns the scene configuration
    that can be used to create a simulation.

    Args:
        data: Template configuration as a dictionary.

    Returns:
        Dictionary with scene configuration ready for simulation creation.

    Raises:
        HTTPException: If template validation fails.
    """
    try:
        loader = get_template_loader()
        scene = loader.build_scene_from_template(data)

        return {
            "scene_type": "generic_scene",
            "scene_name": scene.name,
            "description": scene.get_scenario_description(),
            "mechanics_config": scene.serialize_config().get("mechanics_config", []),
            "semantic_actions_config": scene.serialize_config().get("semantic_actions_config", []),
            "environment": scene.serialize_config().get("environment", {}),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=T("api.errors.template_validation_failed", error=json.loads(e.json())),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=T("api.errors.scene_build_failed", error=str(e)))


@get("/templates/schema")
async def get_template_schema() -> dict:
    """Get the JSON schema for template validation.

    Returns the JSON schema that can be used for client-side validation
    of template configurations.

    Returns:
        JSON Schema dictionary for GenericTemplate.
    """
    return export_json_schema()


router = Router(
    path="/scenes",
    route_handlers=[
        list_scenes,
        list_templates,
        validate_template,
        build_scene_from_template,
        get_template_schema,
    ],
)
