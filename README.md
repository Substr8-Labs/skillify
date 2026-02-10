# Skillify

**Transform any codebase into an OpenClaw skill.**

Skillify analyzes repositories and generates the wrapper files needed to run them as OpenClaw skills — complete with documentation, entry points, and the standard I/O contract.

## Why

OpenClaw skills are the unit of integration. But wrapping an arbitrary codebase into a skill requires:

1. **Structure analysis** — detect project type, entry points, dependencies
2. **Documentation extraction** — pull README, API docs into `references/`
3. **SKILL.md generation** — frontmatter, usage instructions, command patterns
4. **Wrapper contract** — standard JSON input/output for orchestration

Skillify automates this. Point it at a repo, get a working skill.

## Installation

```bash
git clone https://github.com/Substr8-Labs/skillify.git
cd skillify
```

No dependencies — pure Python 3.10+ stdlib.

## Usage

```bash
# From a GitHub URL
python3 skillify.py https://github.com/org/repo

# From a local path
python3 skillify.py /path/to/repo

# With custom output
python3 skillify.py /path/to/repo --output ./skills/my-skill

# Generate with wrapper contract (for orchestration)
python3 skillify.py /path/to/repo --with-wrapper
```

## What It Generates

```
my-skill/
├── SKILL.md              # Agent instructions + frontmatter
├── references/           # Extracted documentation
│   ├── README.md
│   └── API.md
├── scripts/              # Wrapper scripts (with --with-wrapper)
│   ├── entrypoint.py     # Standard I/O contract
│   └── init.sh           # Setup script
└── vendor/               # Original codebase (optional)
```

## The Wrapper Contract

For orchestrated execution, skills follow a standard contract:

**Input:** `input/request.json`
```json
{
  "command": "build",
  "args": { "spec": "Build a todo app" },
  "project_dir": "/workspace/projects/todo-app"
}
```

**Output:** `output/result.json`
```json
{
  "status": "ok",
  "artifacts": [
    { "type": "file", "path": "src/App.tsx" }
  ],
  "summary": "Built React todo app."
}
```

This enables any codebase to be invoked uniformly by OpenClaw or other orchestrators.

## Project Detection

| Type | Detection |
|------|-----------|
| Python | pyproject.toml, setup.py, requirements.txt |
| Node | package.json |
| Rust | Cargo.toml |
| Go | go.mod |
| Ruby | Gemfile |
| Docker | Dockerfile |

## Roadmap

- [x] Basic SKILL.md generation
- [x] Project type detection
- [x] Documentation extraction
- [x] Wrapper contract generation (`--vendor`)
- [x] Dependency vendoring
- [x] `sessions_spawn` integration pattern
- [ ] ClawHub publishing

## sessions_spawn Integration

Skills that need LLM capabilities can't call models directly (no API keys in sandbox). Instead, they return a "pending" status with the required action:

```python
def sessions_spawn(task: str, label: str, timeout: int = 300) -> dict:
    """Request a sub-agent - orchestrator executes this."""
    return {
        "status": "pending",
        "action": {
            "tool": "sessions_spawn",
            "params": {
                "task": task,
                "label": label,
                "runTimeoutSeconds": timeout
            }
        }
    }
```

The orchestrating agent:
1. Runs the skill, gets `status: pending` with `action_required`
2. Executes `sessions_spawn` with those params
3. Passes result back to skill or handles directly

See `examples/autoforge/entrypoint.py` for a full implementation.

## Part of Substr8 Labs

Skillify is part of our mission to build **provable agent infrastructure** — where agent work is transparent, auditable, and verifiable.

- [Control Tower](https://github.com/Substr8-Labs/control-tower) — AI Executive Team for solo founders
- [Skillify](https://github.com/Substr8-Labs/skillify) — Turn any repo into an OpenClaw skill

## License

MIT
