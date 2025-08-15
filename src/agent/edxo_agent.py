from __future__ import annotations

from agents import Agent, ModelSettings

from .tools import (
    use_account,
    complete_profile,
    health,
    version,
    list_programmes,
    list_cours,
    find_cours_by_code,
    get_cours_title,
    get_plan_cadre_id_for_cours,
    get_plan_cadre_capacites,
    add_plan_cadre_capacite,
    pdc_generate_all,
    task_status,
    pc_generate,
    pc_apply_replace_all,
)


def build_agents() -> Agent:
    """Build a multi-agent orchestration with handoffs for EDxo tasks."""

    ops_agent = Agent(
        name="Ops",
        handoff_description="Administration tasks: authentication, health, version, listing entities.",
        instructions=(
            "You manage authentication, status checks, and EDxo data retrieval."
            " Always use tools to answer factual questions about EDxo data (courses, titles, IDs)."
            " Never guess or hallucinate values; prefer find_cours_by_code and related tools."
        ),
        model="gpt-5-mini",
        tools=[use_account, complete_profile, health, version, list_programmes, list_cours, find_cours_by_code, get_cours_title],
        model_settings=ModelSettings(tool_choice="required"),
    )

    pdc_agent = Agent(
        name="PlanDeCours",
        handoff_description="Generate and manage plan de cours (course plan) content and tasks.",
        instructions=(
            "You specialize in plan de cours generation."
            " Use tools for all actions; do not produce content without tools unless summarizing tool results."
        ),
        model="gpt-5-mini",
        tools=[pdc_generate_all, task_status],
    )

    pc_agent = Agent(
        name="PlanCadre",
        handoff_description="Generate and apply improvements to plan-cadre.",
        instructions=(
            "You specialize in plan-cadre content. Use tools for reading/updating capacities."
            " Resolve user-provided course codes to IDs using find_cours_by_code before reading plan-cadre."
            " Read existing capacities before proposing changes. Confirm before applying changes."
        ),
        model="gpt-5-mini",
        tools=[
            find_cours_by_code,
            get_cours_title,
            get_plan_cadre_id_for_cours,
            get_plan_cadre_capacites,
            add_plan_cadre_capacite,
            pc_generate,
            pc_apply_replace_all,
            task_status,
        ],
    )

    triage = Agent(
        name="EDxo Orchestrator",
        instructions=(
            "You are an assistant for EDxo."
            " For any question that depends on EDxo data (e.g., course titles, IDs, plans), ALWAYS handoff to Ops to use tools."
            " For plan de cours actions, handoff to PlanDeCours; for plan-cadre actions, handoff to PlanCadre."
            " Never invent database values; prefer tools and then summarize their results."
            " Confirm destructive operations before applying."
        ),
        model="gpt-5-mini",
        handoffs=[ops_agent, pdc_agent, pc_agent],
    )

    return triage
