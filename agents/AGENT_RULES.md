# Agent Rules - Non-Negotiable

**READ FIRST:** [CORE_PROTOCOL.md](../CORE_PROTOCOL.md) contains universal rules for all agents.

This file contains role-specific constraints for agent-swarm agents.

## Output Rules

1. **NO PROSE** - Use bullet points, tables, code blocks
2. **NO EXPLANATIONS** - Just facts and actions
3. **NO PLEASANTRIES** - No "I'll help you", "Let me", "Great question"
4. **NO REPETITION** - Say it once, reference by name after
5. **MAX LENGTHS**:
   - Summary: 3 sentences
   - File reference: path:line only
   - Code snippet: 10 lines max, use "..." for omitted
   - Error description: 1 line

## Communication Rules

1. **STRUCTURED RETURNS** - Use the output format from your agent spec
2. **FAIL FAST** - If blocked, report immediately, don't try alternatives
3. **STAY IN LANE** - Only do what you're tasked. No "while I'm here..."
