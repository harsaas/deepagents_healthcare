import sqlite3
import os
import argparse
import warnings
import uuid
from pathlib import Path

# The LangChain/LangSmith stack may emit a noisy warning about UUIDv7 when
# message/run identifiers are custom strings. It's harmless for this demo.
warnings.filterwarnings(
    "ignore",
    message=r"LangSmith now uses UUID v7 for run and trace identifiers\..*",
    category=UserWarning,
)

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

try:
    # Supports: python -m scripts.main
    from .agent_memory_tools import HealthcareWorkspace
    from .state import AdvancedClinicalState
except ImportError:
    # Supports: python scripts/main.py
    from agent_memory_tools import HealthcareWorkspace
    from state import AdvancedClinicalState


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {var_name}. "
            "Add it to .env (repo root) or set it in your shell."
        )
    return value


def _coerce_message(message: object) -> BaseMessage:
    if isinstance(message, BaseMessage):
        return message
    if isinstance(message, tuple) and len(message) == 2:
        role, content = message
        role = str(role).lower()
        content = "" if content is None else str(content)
        if role in {"user", "human"}:
            return HumanMessage(content=content)
        if role in {"assistant", "ai"}:
            return AIMessage(content=content)
        if role == "system":
            return SystemMessage(content=content)
        return HumanMessage(content=content)
    return HumanMessage(content=str(message))

# 1. The Planner Node: Decides which files to read/write
def planner_node(state: AdvancedClinicalState):
    # Logic: If workspace_files is empty, 'Plan' to fetch EHR data.
    # If a conflict was found, 'Plan' to write a 'Conflict_Report.md'.
    return {"current_plan": ["Fetch EHR", "Analyze Meds", "Write Summary"]}


def call_llm_node(state: AdvancedClinicalState):
    """Call a real OpenAI chat model using keys from `.env`."""
    existing_messages = [_coerce_message(m) for m in state.get("messages", [])]

    # Allow this demo to run without keys (deterministic stub), but prefer real calls
    # when OPENAI_API_KEY is present.
    if not os.getenv("OPENAI_API_KEY"):
        last_user_text = ""
        for msg in reversed(existing_messages):
            if isinstance(msg, HumanMessage) and msg.content:
                last_user_text = msg.content
                break
        response = AIMessage(
            content=(
                "(demo) OPENAI_API_KEY is not set. "
                + (f"Your request was: {last_user_text}" if last_user_text else "")
            ).strip()
        )
        return {"messages": [*existing_messages, response]}

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
    llm = ChatOpenAI(model=model_name, temperature=0)

    history = [
        SystemMessage(
            content=(
                "You are a clinical assistant. Use the message history to respond concisely. "
                "If the user request is ambiguous, ask 1 clarifying question."
            )
        ),
        *existing_messages,
    ]

    response = llm.invoke(history)
    return {"messages": [*existing_messages, response]}

# 2. The Context Offload Node: Summarizes and writes to Disk
def offload_memory_node(state: AdvancedClinicalState):
    workspace = HealthcareWorkspace(state["patient_id"])
    
    def _summarize_messages(messages, max_messages: int = 10, max_chars: int = 800) -> str:
        tail = list(messages)[-max_messages:]
        lines: list[str] = []
        for msg in tail:
            role = getattr(msg, "type", None) or msg.__class__.__name__
            content = getattr(msg, "content", None)
            if content is None:
                content = str(msg)
            lines.append(f"- {role}: {content}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    messages = list(state.get("messages", []))
    summary = _summarize_messages(messages)
    
    # Write to local file system
    workspace.write_clinical_note("session_summary.txt", summary)
    
    # Keep only the last couple messages so the user still sees the latest answer,
    # while trimming history to prevent token growth.
    trimmed_messages = messages[-2:]
    return {
        "messages": trimmed_messages,
        "summary_file_path": "session_summary.txt",
    }


def should_offload(state: AdvancedClinicalState):
    return "offload" if len(state.get("messages", [])) > 10 else "continue"


def build_app():
    base_dir = Path(__file__).resolve().parents[1]
    conn = sqlite3.connect(str(base_dir / "langgraph_demo.db"), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    workflow = StateGraph(AdvancedClinicalState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("offloader", offload_memory_node)
    workflow.add_node("clinical_expert", call_llm_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "clinical_expert")
    workflow.add_edge("clinical_expert", "offloader")
    workflow.add_edge("offloader", END)

    return workflow.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangGraph healthcare workflow demo")
    parser.add_argument("--patient-id", dest="patient_id", default=None)
    parser.add_argument("--query", dest="user_query", default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last checkpoint for this patient_id (thread_id=patient_id).",
    )
    parser.add_argument(
        "--thread-id",
        dest="thread_id",
        default=None,
        help="Override the LangGraph thread_id (advanced).",
    )
    args = parser.parse_args()

    patient_id = args.patient_id or os.getenv("PATIENT_ID")
    if not patient_id:
        patient_id = input("Enter patient_id: ").strip()
    if not patient_id:
        raise ValueError("patient_id cannot be empty")

    user_query = args.user_query or os.getenv("USER_QUERY")
    if not user_query:
        user_query = input("Enter your question/request: ").strip()
    if not user_query:
        raise ValueError("query cannot be empty")

    # Important: If thread_id is stable (e.g., patient_id), the SqliteSaver will resume
    # previous state. For a clean demo run, default to a fresh thread_id per invocation.
    thread_id = args.thread_id
    if not thread_id:
        thread_id = patient_id if args.resume else f"{patient_id}:{uuid.uuid4().hex[:8]}"

    app = build_app()
    initial_state: AdvancedClinicalState = {
        "patient_id": patient_id,
        "messages": [("user", user_query)],
        "workspace_files": [],
        "current_plan": [],
        "active_subagent": "",
        "summary_file_path": "",
    }
    result = app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})

    # Keep output small: show only the final assistant message and where the summary was written.
    final_message = None
    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", None)
        if content:
            final_message = content
            break

    print("\n=== Result ===")
    if final_message:
        print(final_message)
    else:
        print("(no assistant message found)")
    print("\nSummary file:", result.get("summary_file_path") or "(none)")