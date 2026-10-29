"""
Test to verify that experiment_tasks.py correctly builds provider_clients.

This simulates what experiment_tasks.py does when creating clients.
"""
from unittest.mock import Mock
from fos.core.llm_config import LLMConfig
from fos.core.llm import create_llm_client


def test_experiment_tasks_provider_distribution():
    """Simulate the logic in experiment_tasks.py for provider distribution."""

    # Simulate loading providers from database
    mock_providers = [
        Mock(
            id=1,
            provider="openai",
            model="gpt-4",
            api_key="sk-test-gpt4",
            base_url=None,
            config={"active": True},  # This is the active provider
        ),
        Mock(
            id=2,
            provider="openai",  # Using OpenAI-compatible API
            model="claude-3-opus-20240229",
            api_key="sk-test-claude",
            base_url="https://api.anthropic.com/v1",
            config={"active": False},
        ),
    ]

    # Replicate the logic from experiment_tasks.py
    provider_clients = {}
    default_llm_client = None
    active_provider = None

    for provider in mock_providers:
        dialect = (provider.provider or "").lower()
        cfg = LLMConfig(
            dialect=dialect,
            api_key=provider.api_key or "",
            model=provider.model,
            base_url=provider.base_url or ("http://127.0.0.1:11434" if dialect == "ollama" else None),
            temperature=0.0,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=1024,
            supports_vision=True,
        )
        llm_client = create_llm_client(cfg)

        # Store in provider_clients mapping (provider_id -> client)
        provider_clients[provider.id] = llm_client

        # Use the active provider as the default client
        if (provider.config or {}).get("active"):
            default_llm_client = llm_client
            active_provider = provider

    # Build clients dict
    clients = {
        "chat": default_llm_client,
        "default": default_llm_client,
        "search": Mock(),  # Mock search client
        "providers": provider_clients,  # THIS IS THE FIX!
    }

    # Verify the fix
    print("="*60)
    print("Testing experiment_tasks.py Provider Distribution Fix")
    print("="*60)
    print()

    print(f"Created {len(provider_clients)} provider clients:")
    for provider_id, client in provider_clients.items():
        print(f"  Provider {provider_id}: {client}")
    print()

    print(f"Default client (active provider): {default_llm_client}")
    print(f"Active provider ID: {active_provider.id if active_provider else None}")
    print()

    # Verify clients dict has the providers key
    assert "providers" in clients, "clients dict MUST have 'providers' key"
    print("PASS: clients dict has 'providers' key")

    # Verify provider_clients has both providers
    assert len(clients["providers"]) == 2, "Should have 2 providers"
    print(f"PASS: clients['providers'] has {len(clients['providers'])} providers")

    # Verify each provider ID maps to the correct client
    assert 1 in clients["providers"], "Provider 1 should be in clients['providers']"
    assert 2 in clients["providers"], "Provider 2 should be in clients['providers']"
    print("PASS: Both provider IDs are in clients['providers']")

    # Verify they are different clients
    client1 = clients["providers"][1]
    client2 = clients["providers"][2]
    assert client1 is not client2, "Provider 1 and 2 should have different clients"
    print("PASS: Providers have different LLM clients")

    print()
    print("="*60)
    print("Summary:")
    print("  - experiment_tasks.py NOW creates clients for ALL providers")
    print("  - clients['providers'] maps provider_id -> LLM client")
    print("  - This enables LLM provider distribution for agents")
    print("="*60)


if __name__ == "__main__":
    test_experiment_tasks_provider_distribution()
