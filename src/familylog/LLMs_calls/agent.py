import re
from datetime import datetime, timedelta
from typing import Annotated, Sequence, TypedDict

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.config import settings
from src.constants import NOISE_TAGS, RUSSIAN_MONTHS
from src.logger import logger
from ..processor.obsidian.general_data import parse_current_context


def _obsidian_get_sync(path: str) -> str | None:
    try:
        r = httpx.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{path}",
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
            verify=False,
            timeout=10,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"_obsidian_get_sync({path}) failed: {e}")
        return None


def _obsidian_list_files_sync(folder: str) -> list[str]:
    try:
        r = httpx.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{folder}/",
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
            verify=False,
            timeout=10,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        files = data.get("files", [])
        result = []
        for item in files:
            path = item if isinstance(item, str) else item.get("path", "")
            if path.endswith(".md"):
                if not path.startswith(f"{folder}/"):
                    path = f"{folder}/{path}"
                result.append(path)
        return result
    except Exception as e:
        logger.warning(f"_obsidian_list_files_sync({folder}) failed: {e}")
        return []



# ─── Sync context loader (month-based) ───────────────────────────────────────

def _load_context_for_period_sync() -> str:
    """Загружает контекст из месячных файлов за CONTEXT_MEMORY_DAYS (синхронно)."""
    now = datetime.now()
    cutoff = now - timedelta(days=settings.CONTEXT_MEMORY_DAYS)
    seen: set[tuple[int, int]] = set()
    parts: list[str] = []

    current = now
    while current >= cutoff:
        ym = (current.year, current.month)
        if ym not in seen:
            seen.add(ym)
            mname = f"{current.month:02d}-{RUSSIAN_MONTHS[current.month - 1]}"
            path = f"_system/context/{current.year}/{mname}.md"
            content = _obsidian_get_sync(path)
            if content:
                parts.append(content)
        current = current.replace(day=1) - timedelta(days=1)

    if not parts:
        return "(no recent context)"
    return parse_current_context("\n\n".join(parts))


@tool
def get_tags_glossary() -> str:
    """Get the tags glossary — list of all existing tags in the vault with descriptions."""
    content = _obsidian_get_sync("_system/TAGS_GLOSSARY.md")
    return content or "(Tags glossary not found)"


@tool
def get_family_memory() -> str:
    """Get information about family members — names, Telegram IDs, roles."""
    content = _obsidian_get_sync("_system/FAMILY_MEMORY.md")
    return content or "(Family memory not found)"


@tool
def get_current_context() -> str:
    """Get recent notes context — brief descriptions of notes created in the last N days.
    Use this to find related notes and understand recent activity."""
    return _load_context_for_period_sync()


@tool
def get_intent_rules(intent: str) -> str:
    """Get content formatting rules for a specific intent type.
    Allowed values: note, diary, calendar, task."""
    content = _obsidian_get_sync(f"_system/intents/{intent}.md")
    return content or f"(No specific rules for intent: {intent})"


@tool
def search_related_notes(tags: str) -> str:
    """Search recent notes with overlapping tags using the context index.
    Input: comma-separated tag names without # (e.g. 'здоровье,дети,планы').
    Returns up to 5 most relevant note paths sorted by tag overlap count."""
    tag_list = [t.strip().lstrip("#") for t in tags.split(",") if t.strip()]
    if not tag_list:
        return "No tags provided"

    tags_set = set(tag_list) - NOISE_TAGS
    if not tags_set:
        return "No meaningful tags to search"

    context_text = _load_context_for_period_sync()
    candidates: list[tuple[str, int]] = []

    entry_re = re.compile(r"^- \[([^\]]+\.md)\]\s*(?:\(([^)]*)\))?", re.MULTILINE)
    for m in entry_re.finditer(context_text):
        filepath = m.group(1)
        tags_str = m.group(2) or ""
        file_tags = set(
            t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()
        ) - NOISE_TAGS
        overlap = len(tags_set & file_tags)
        if overlap > 1:
            candidates.append((filepath, overlap))

    if not candidates:
        return "No related notes found in recent context"

    candidates.sort(key=lambda x: x[1], reverse=True)
    lines = [f"- {path} (совпадений тегов: {count})" for path, count in candidates[:5]]
    return "Related notes:\n" + "\n".join(lines)


@tool
def read_note(path: str) -> str:
    """Read content of a specific note from the vault.
    Use path exactly as returned by search_related_notes or get_current_context.
    Example: notes/My_note_01-mar-26.md"""
    content = _obsidian_get_sync(path)
    if content is None:
        return f"Note not found: {path}"
    return content[:2000] if len(content) > 2000 else content


TOOLS = [
    get_tags_glossary,
    get_family_memory,
    get_current_context,
    get_intent_rules,
    search_related_notes,
    read_note,
]
_tools_dict = {t.name: t for t in TOOLS}

_llm = ChatOpenAI(
    model=settings.llm_model,
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    temperature=0.1,
    # json_object: гарантирует валидный JSON на выходе и убирает <think>-теги
    model_kwargs={"response_format": {"type": "json_object"}},
)
_llm_with_tools = _llm.bind_tools(TOOLS)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    agent_config: str


def _call_llm(state: AgentState) -> AgentState:
    messages = list(state["messages"])
    system_content = state.get("agent_config", "You are a helpful assistant.")
    messages = [SystemMessage(content=system_content)] + messages
    message = _llm_with_tools.invoke(messages)
    return {"messages": [message]}


def _take_action(state: AgentState) -> AgentState:
    tool_calls = state["messages"][-1].tool_calls
    results = []
    for t in tool_calls:
        tool_name = t["name"]
        tool_args = t["args"]
        logger.debug(f"Agent tool: {tool_name}({tool_args})")
        if tool_name not in _tools_dict:
            result = f"Tool '{tool_name}' not found."
        else:
            result = _tools_dict[tool_name].invoke(tool_args)
        results.append(
            ToolMessage(tool_call_id=t["id"], name=tool_name, content=str(result))
        )
    logger.info(f"Agent executed {len(results)} tool(s): {[t['name'] for t in tool_calls]}")
    return {"messages": results}


def _should_continue(state: AgentState) -> bool:
    last = state["messages"][-1]
    return hasattr(last, "tool_calls") and bool(last.tool_calls)


def _build_agent():
    graph = StateGraph(AgentState)
    graph.add_node("llm", _call_llm)
    graph.add_node("tools", _take_action)
    graph.add_edge(START, "llm")
    graph.add_edge("tools", "llm")
    graph.add_conditional_edges("llm", _should_continue, {True: "tools", False: END})
    return graph.compile()


_agent = _build_agent()
logger.info("FamilyLog session agent initialized.")


_TOOL_INSTRUCTIONS = """
---
## Инструкции для агента

У тебя есть инструменты для получения контекста из vault. Используй их в таком порядке:

1. `get_intent_rules("{intent}")` — получи правила форматирования для данного интента
2. `get_tags_glossary` — получи список существующих тегов, выбери подходящие
3. `get_current_context` — получи последние записи (нужно для поля `related`)
4. `search_related_notes` — найди похожие записи по тегам (вызови ПОСЛЕ определения тегов)
5. `get_family_memory` — если в тексте упомянуты незнакомые люди

После сбора всего необходимого контекста — сгенерируй финальный JSON ответ.
Отвечай ТОЛЬКО валидным JSON, без markdown-обёртки и пояснений.
"""


def process_session_with_agent(
    assembled_content: str,
    intent: str,
    author_name: str,
    created_at,
) -> str:
    """Drop-in replacement for llm_process_session. Returns JSON string."""
    now_str = (
        created_at.strftime("%Y-%m-%d %H:%M")
        if created_at
        else datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    agent_config_raw = _obsidian_get_sync("_system/AGENT_CONFIG.md") or ""
    system_prompt = agent_config_raw + _TOOL_INSTRUCTIONS.format(intent=intent)

    user_message = (
        f"Интент: {intent}\n"
        f"Автор: {author_name}\n"
        f"Дата и время: {now_str}\n\n"
        f"Содержание для обработки:\n{assembled_content}"
    )

    logger.info(f"Agent processing session: intent={intent}, author={author_name}")
    result = _agent.invoke({
        "messages": [HumanMessage(content=user_message)],
        "agent_config": system_prompt,
    })

    final_content = result["messages"][-1].content
    logger.info(f"Agent finished: intent={intent}, output_len={len(final_content)}")
    return final_content
