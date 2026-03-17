"""
Usami — Boss Persona (Supervisor Agent)
Core orchestrator: intent understanding -> task decomposition -> DAG scheduling -> aggregation

Pre-mortem fixes incorporated:
- F2: Plan Validator validates Boss output
- F3: Structured message passing (envelope pattern)

Node implementations live in agents/nodes.py.
This file builds and compiles the StateGraph.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

import structlog
from langgraph.graph import END, START, StateGraph

from agents.nodes import (
    aggregate_node,
    execute_node,
    planning_node,
    validate_node,
)
from core.hitl import HiTLGateway
from core.persona_factory import PersonaFactory
from core.plan_validator import PlanValidator

logger = structlog.get_logger()


# ============================================
# Boss Graph Builder
# ============================================

def build_boss_graph(
    persona_factory: PersonaFactory,
    hitl_gateway: HiTLGateway,
    checkpointer=None,
    on_event: Callable | None = None,
) -> StateGraph:
    """
    Build Boss Supervisor Graph

    Flow:
    init -> planning -> validate -> [hitl_preview] -> execute -> aggregate -> done
    """

    available_personas = persona_factory.list_personas()
    validator = PlanValidator(available_personas=list(available_personas.keys()))

    async def emit(event_type: str, data: dict) -> None:
        """Emit event via SSE (if on_event callback is registered)"""
        if on_event:
            try:
                await on_event(event_type, data)
            except Exception as e:
                logger.warning("event_emit_failed", event_type=event_type, error=str(e))

    # --- Bind dependencies to node functions via partial ---
    _planning = partial(
        planning_node,
        emit=emit,
        persona_factory=persona_factory,
        available_personas=available_personas,
    )
    _validate = partial(
        validate_node,
        emit=emit,
        hitl_gateway=hitl_gateway,
        validator=validator,
    )
    _execute = partial(
        execute_node,
        emit=emit,
        persona_factory=persona_factory,
        hitl_gateway=hitl_gateway,
    )
    _aggregate = partial(
        aggregate_node,
        emit=emit,
        persona_factory=persona_factory,
    )

    # --- Router ---
    def route_next(state: dict) -> str:
        """Route to next node based on current phase"""
        phase = state.get("current_phase", "init")

        route_map = {
            "init": "planning",
            "planning": "planning",
            "validating": "validate",
            "executing": "execute",
            "hitl_waiting": END,
            "aggregating": "aggregate",
            "done": END,
            "error": END,
        }
        return route_map.get(phase, END)

    # --- Build Graph ---
    graph = StateGraph(dict)

    graph.add_node("planning", _planning)
    graph.add_node("validate", _validate)
    graph.add_node("execute", _execute)
    graph.add_node("aggregate", _aggregate)

    graph.add_edge(START, "planning")
    graph.add_edge("planning", "validate")
    graph.add_conditional_edges("validate", route_next)
    graph.add_conditional_edges("execute", route_next)
    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)
