# Agent.md Format Guide - VS Code/GitHub Copilot Standards

**Last Updated:** January 30, 2026  
**Status:** ✅ All agent.md files conform to standards

## Correct Format

All agent.md files in this project now follow the official VS Code/GitHub Copilot agent format:

### Structure

```yaml
---
name: Agent Name
description: "Clear description of the agent's purpose"
argument-hint: "Optional hint for users about how to invoke this agent"
model: Claude Opus 4.5  # Optional; omit or use valid LLM name only
tools:
  - tool_name
  - mcp_namespace_tool_name
  - read
  - search
  - edit
  - fetch_webpage
handoffs:
  - label: "Button Label Text"
    agent: agent-name
    prompt: |
      Multi-line prompt template
      Can include instructions
    send: false  # Whether to auto-send or show button
target: vscode  # Required for VS Code integration
---

# Markdown Content

Your markdown content starts here after the closing `---` marker.

## Sections

- No code fence markers around content
- Standard Markdown formatting
```

## Key Rules

### ✅ CORRECT
- Start with `---` (3 hyphens, no backticks)
- YAML frontmatter between first and second `---`
- `target: vscode` field required
- Tools as array of strings: `- tool_name`
- Handoffs as array of objects with label/agent/prompt/send
- Markdown content after closing `---`
- No code fence markers anywhere

### ❌ INCORRECT (Fixed in this update)
- ````chatagent` (4 backticks) - REMOVED
- ````chatagent` (3 backticks) - REMOVED
- Handoffs as simple string array (converted to object structure)
- Model field with invalid values like GPT-5.2 (removed or corrected)
- Tools with inconsistent naming (standardized to mcp_* format)
- Markdown wrapped in code fences (removed)

## Field Reference

### Required Fields
| Field | Type | Description |
|-------|------|-------------|
| name | string | Agent name (appears in UI) |
| description | string | What the agent does (max ~100 characters) |
| tools | array | List of available tools |
| target | string | "vscode" (for VS Code/Copilot) |

### Optional Fields
| Field | Type | Description |
|-------|------|-------------|
| argument-hint | string | Hint text for invoking the agent |
| model | string | Model (use valid LLM names only: Claude Opus 4.5, GPT-4, etc.) |
| handoffs | array | Alternative agents to delegate to |

### Handoff Object Structure
```yaml
handoffs:
  - label: "Display Text"
    agent: agent-id
    prompt: |
      Template for the prompt sent to the agent
    send: false
```

## Tool Naming Conventions

### Standard Tools
```yaml
tools:
  - read                    # Read files
  - search                  # Search codebase
  - search/usages           # Find symbol usages
  - edit                    # Edit files
  - fetch_webpage           # Fetch web content
  - github_repo             # Search GitHub
  - run_in_terminal         # Execute commands
  - get_errors              # Get compilation errors
  - get_project_setup_info  # Project setup info
```

### MCP Tools
```yaml
tools:
  - mcp_memory              # Knowledge graph operations
  - mcp_sequentialthi_sequentialthinking  # Chain of thought reasoning
  - mcp_context7_resolve-library-id       # Resolve library documentation
  - mcp_context7_get-library-docs         # Fetch library documentation
  - mcp_pylance_mcp_s_pylanceRunCodeSnippet  # Run Python code
  - fetch_webpage           # Web fetching (standard)
```

## Files Updated

All 8 agent files have been corrected:

1. ✅ **planner.agent.md** - Complex format issues resolved
2. ✅ **portfolio-assistant.agent.md** - Tool format standardized
3. ✅ **docs-agent.agent.md** - Format markers fixed
4. ✅ **context7.agent.md** - Format markers fixed
5. ✅ **se-ux-ui-designer.agent.md** - Invalid model field removed
6. ✅ **power-bi-data-modeling-expert.agent.md** - Field order corrected
7. ✅ **power-bi-performance-expert.agent.md** - Field order corrected
8. ✅ **power-bi-visualization-expert.agent.md** - Field order corrected

## Validation Checklist

Before committing agent files, verify:

- [ ] File starts with `---` (not ````chatagent or ```chatagent)
- [ ] YAML frontmatter properly formatted between `---` markers
- [ ] `target: vscode` field present
- [ ] Tools array uses proper naming conventions
- [ ] Handoffs (if present) use object structure with label/agent/prompt/send
- [ ] Model field omitted or uses valid LLM name
- [ ] Markdown content after closing `---` has no code fence markers
- [ ] No `````chatagent markers at end of file

## References

- [VS Code API Documentation](https://code.visualstudio.com/api)
- [GitHub Copilot Agent Format](https://github.com/github/copilot-docs)
- Project: [AGENTS.md](../../../AGENTS.md)
