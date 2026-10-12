import secrets


def generate_simulation_id() -> str:
    return secrets.token_hex(4).upper()


def generate_simulation_name(sim_id: str | None = None) -> str:
    suffix = sim_id or generate_simulation_id()
    return f"Simulation #{suffix}"
