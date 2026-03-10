# config/

Declarative YAML configuration. All behavior changes start here.

## Files

```
config/
├── personas.yaml          # Agent definitions (who)
├── tools.yaml             # Tool registry (what they can use)
├── routing.yaml           # Model selection + budget (how)
└── litellm_config.yaml    # LLM provider mapping (where)
```

## personas.yaml

Defines all agent personas. PersonaFactory reads this at startup.

```yaml
personas:
  <name>:                    # unique key, used in plan_validator + boss assignments
    name: "Display Name"
    role: orchestrator|specialist
    description: "..."       # shown to Boss during planning
    system_prompt: "..."     # injected as SystemMessage
    model: strong|medium|light  # maps to routing.yaml tiers
    tools: [tool_name, ...]  # must exist in tools.yaml builtin_tools
    max_retries: 2
```

**Current personas**: boss, researcher, writer, analyst.

### Adding a new persona

1. Add entry to `personas.yaml` with unique key
2. Verify `tools` list — every tool name must exist in `tools.yaml` `builtin_tools` AND have an implementation in `backend/core/tool_registry.py` `BUILTIN_TOOL_MAP`
3. Verify `model` value exists as a tier in `routing.yaml` `routing_rules`
4. No code changes needed — PersonaFactory picks it up at next restart

## tools.yaml

```yaml
builtin_tools:
  <tool_name>:
    description: "..."
    permission_level: 1|2|3|4    # L1=read, L2=side-effect, L3=code, L4=system
    requires_approval: false     # if true, HiTL approval before each call
    scope: global|<persona_name> # global = all personas can use

mcp_servers: {}                  # MCP server configs (MVP: empty)
sandbox:
  enabled: false
```

**Implemented tools** (have code in BUILTIN_TOOL_MAP): `web_search`, `knowledge_search`, `file_write`.
**Declared but NOT implemented**: `send_notification` — will log warning, won't crash.

### Adding a new tool

1. Add entry to `tools.yaml` `builtin_tools`
2. Implement the tool function in `backend/core/tool_registry.py` `BUILTIN_TOOL_MAP`
3. Assign to personas in `personas.yaml` `tools` list

## routing.yaml

```yaml
routing_rules:
  <task_type>:              # matches boss.py prompt task_type values
    model: strong|medium|light

budget:
  max_tokens_per_task: 100000
  max_cost_per_task_usd: 0.50
  alert_threshold: 0.8      # triggers HiTL at 80% of max_cost

logging:
  enabled: true
  fields: [task_type, tokens, model, latency, cost, success]
```

**Boss prompt uses these task_types**: planning, research, writing, analysis, summarize.
**routing.yaml also defines**: classification (not in Boss prompt, harmless).

## litellm_config.yaml

```yaml
model_list:
  - model_name: "strong"     # tier name, referenced in routing_rules
    litellm_params:
      model: "anthropic/claude-sonnet-4-20250514"
  - model_name: "medium"
    litellm_params:
      model: "openai/gpt-4o-mini"
  - model_name: "light"
    litellm_params:
      model: "openai/gpt-4o-mini"
```

### Adding a new model tier

1. Add entry to `litellm_config.yaml` `model_list` with unique `model_name`
2. Reference the tier name in `routing.yaml` `routing_rules`
3. Optionally assign to personas in `personas.yaml` `model` field

## Cross-file consistency rules

These names MUST match across files. Mismatch causes silent failures or validation errors:

| Value | Defined in | Referenced by |
|---|---|---|
| persona key (e.g. `researcher`) | personas.yaml | plan_validator checks against this list |
| tool name (e.g. `web_search`) | tools.yaml | personas.yaml `tools` list |
| model tier (e.g. `strong`) | litellm_config.yaml `model_name` | routing.yaml + personas.yaml `model` |
| task_type (e.g. `research`) | Boss prompt in boss.py | routing.yaml `routing_rules` keys |

## Do NOT

- Add a persona without tools that exist in both `tools.yaml` AND `BUILTIN_TOOL_MAP`.
- Change a `model_name` in litellm_config.yaml without updating routing.yaml and personas.yaml.
- Delete a persona that Boss might assign tasks to — Boss uses the persona list from config to generate plans.
- Add `requires_approval: true` to high-frequency tools — every invocation will block on HiTL.
- Put non-YAML files in this directory — config.py glob-loads `*.yaml`.
