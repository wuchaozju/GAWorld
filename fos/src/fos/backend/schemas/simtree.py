from pydantic import BaseModel


class SimulationTreeAdvancePayload(BaseModel):
    parent: int
    turns: int


class SimulationTreeAdvanceFrontierPayload(BaseModel):
    turns: int
    only_max_depth: bool = True


class SimulationTreeAdvanceMultiPayload(BaseModel):
    parent: int
    turns: int
    count: int


class SimulationTreeAdvanceChainPayload(BaseModel):
    parent: int
    turns: int


class SimulationTreeAgentOverride(BaseModel):
    name: str
    language: str | None = None
    llm_config: dict | None = None
    knowledge_base: list | None = None
    documents: dict | None = None
    properties: dict | None = None


class SimulationTreeAgentOverridePayload(BaseModel):
    overrides: list[SimulationTreeAgentOverride]


class SimulationTreeBranchPayload(BaseModel):
    parent: int
    ops: list[dict]


class UpdateAgentLLMConfigRequest(BaseModel):
    """Request payload for updating an agent's LLM configuration."""
    agent_id: str
    llm_config: dict[str, str]  # {"provider": "...", "model": "..."}
    provider_id: int | None = None
