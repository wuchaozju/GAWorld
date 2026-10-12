# Project Conventions

## Reference Documents

- **Environment Agent Design**: `docs/environment-agent-design.md` — 初始设计规范，定义环境代理功能的需求、架构、组件和实现计划。

## File Rules
- Keep all files under 500 lines. If a file grows too large, split it into focused modules.
- Begin every file with a plain-language comment explaining what the file does and what each function in it does. No technical jargon — write it so anyone could understand.

## Testing (TDD)
- Always write tests first. The test must fail before writing any implementation.
- Never write a feature without a failing test that covers it first.
- Run tests after implementation to confirm they pass.
- If you find a failing test at any point — even one unrelated to the current task — surface it. Never dismiss it.
- Name tests in plain, simple language (e.g. `test_user_cannot_login_with_wrong_password`). A five-year-old should be able to read the name and understand what is being checked.

## Error Handling
- Never fail silently. All errors must be logged or raised — no swallowing exceptions.
- Use specific error types, not generic Exception or Error.

## Functions
- One responsibility per function.
- Max 50 lines per function. If longer, break it up.
- Prefer early returns over deeply nested logic.

## Python
- Use type hints on all functions.
- Use dataclasses or pydantic for data structures, not raw dicts.
- Prefer pathlib over os.path.
- Use ruff for linting and formatting.

## TypeScript
- No `any` types.
- Use `unknown` instead of `any` when the type is genuinely uncertain.
- Prefer `interface` over `type` for object shapes.
- Always handle promise rejections — no floating promises.
