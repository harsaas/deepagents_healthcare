import os
import argparse
import ast
import datetime as dt
from pathlib import Path
import sys
import uuid
import warnings
import asyncio

import pandas as pd
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_mcp_adapters.tools import load_mcp_tools

# Silence a noisy warning emitted by the LangChain/LangSmith stack about UUIDv7.
warnings.filterwarnings(
    "ignore",
    message=r"LangSmith now uses UUID v7 for run and trace identifiers\..*",
    category=UserWarning,
)

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
DATA_DIR = BASE_DIR / "synthea_sample_data_csv_latest"
PATIENTS_CSV = DATA_DIR / "patients.csv"
DB_PATH = BASE_DIR / "healthcare_agent.db"
WORKSPACE_DIR = BASE_DIR / "patient_workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# 4. Defining the Sub-agents (Specialized clinical logic)
# This will be passed in the system prompt or via the sub-agent tool
pharmacy_auditor = {
    "name": "pharmacy_expert",
    "description": "Specialized in identifying drug-to-drug interactions.",
    "system_prompt": "You are a senior pharmacist. Only review medication lists for safety. Report risks clearly.",
}

# 5. Run a Discharge Workflow

def _choose_thread_id(patient_id: str, *, resume: bool, override: str | None) -> str:
    if override:
        return override
    # If thread_id is stable, the sqlite checkpointer will resume prior state.
    # Default to a fresh thread per invocation unless the user explicitly requests resume.
    return patient_id if resume else f"{patient_id}:{uuid.uuid4().hex[:8]}"


async def run_discharge(
    patient_id: str | None = None,
    user_query: str | None = None,
    *,
    resume: bool = False,
    thread_id: str | None = None,
):
    # NOTE: MCP tool loading can hang depending on installed MCP/LangChain adapter versions.
    # For reliability, default to local CSV retrieval unless explicitly enabled.
    use_mcp = os.getenv("USE_MCP", "0") == "1"
    mcp_timeout_s = int(os.getenv("MCP_TIMEOUT_SECONDS", "20"))
    mcp_tools = []
    if use_mcp:
        print("Loading MCP tools (stdio)...", flush=True)
        try:
            mcp_tools = await asyncio.wait_for(
                load_mcp_tools(
                    None,
                    connection={
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "scripts.medical_mcp"],
                        "cwd": str(BASE_DIR),
                    },
                    server_name="medical_mcp",
                ),
                timeout=mcp_timeout_s,
            )
            print(f"Loaded MCP tools: {len(mcp_tools)}", flush=True)
        except Exception as e:
            # If MCP tool loading hangs or fails, we can still proceed using local CSVs.
            print(f"WARNING: MCP tools unavailable (falling back to local CSVs): {e}", flush=True)
            mcp_tools = []

    if patient_id is None:
        patient_id = os.getenv("PATIENT_ID")
    if patient_id is None:
        patient_id = str(pd.read_csv(PATIENTS_CSV, usecols=["Id"], nrows=1).iloc[0]["Id"])

    # Patient-scoped workspace: all files the agent writes land under this directory.
    patient_workspace_dir = WORKSPACE_DIR / patient_id
    patient_workspace_dir.mkdir(parents=True, exist_ok=True)
    backend = FilesystemBackend(root_dir=str(patient_workspace_dir))

    config = {"configurable": {"thread_id": _choose_thread_id(patient_id, resume=resume, override=thread_id)}}

    run_smoke_test = os.getenv("RUN_MCP_SMOKE_TEST", "0") == "1"
    trace_events = os.getenv("TRACE_EVENTS", "1") == "1"
    debug = os.getenv("DEEPAGENTS_DEBUG", "0") == "1"
    suppress_final_print = os.getenv("SUPPRESS_FINAL_PRINT", "0") == "1"

    # If you want human-in-the-loop approval before file writes, set HITL_WRITE_APPROVAL=1.
    hitl_write_approval = os.getenv("HITL_WRITE_APPROVAL", "0") == "1"

    print_ehr = os.getenv("PRINT_EHR_CONTEXT", "1") == "1"

    profile = None
    history = None
    if mcp_tools:
        tools_by_name = {t.name: t for t in mcp_tools}
        profile_tool = tools_by_name.get("get_patient_profile")
        history_tool = tools_by_name.get("search_clinical_history")
        if profile_tool is not None and history_tool is not None:
            profile = (
                print("Fetching patient profile...", flush=True)
                or (
                    await profile_tool.ainvoke({"patient_id": patient_id})
                    if hasattr(profile_tool, "ainvoke")
                    else profile_tool.invoke({"patient_id": patient_id})
                )
            )
            history = (
                print("Fetching clinical history...", flush=True)
                or (
                    await history_tool.ainvoke({"patient_id": patient_id})
                    if hasattr(history_tool, "ainvoke")
                    else history_tool.invoke({"patient_id": patient_id})
                )
            )

    if profile is None or history is None:
        # Local fallback (no MCP): read from the same code the MCP server uses.
        print("Using local CSV fallback for EHR context...", flush=True)
        from scripts.medical_mcp import get_patient_profile as _local_profile
        from scripts.medical_mcp import search_clinical_history as _local_history

        profile = _local_profile(patient_id)
        history = _local_history(patient_id)

    def _maybe_parse_profile(value: object) -> object:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    parsed = ast.literal_eval(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return value
        return value

    profile_obj = _maybe_parse_profile(profile)

    def _parse_list_from_history(label: str, text: str) -> list[str]:
        idx = text.find(label)
        if idx == -1:
            return []
        start = text.find("[", idx)
        end = text.find("]", start)
        if start == -1 or end == -1:
            return []
        try:
            value = ast.literal_eval(text[start : end + 1])
        except Exception:
            return []
        return [str(item) for item in value] if isinstance(value, list) else []

    conditions_list = _parse_list_from_history("Conditions:", str(history))
    meds_list = _parse_list_from_history("Medications:", str(history))

    # Deterministic readmission-risk components for verification.
    # We keep this simple and transparent: each condition has weight 1.
    birthdate = None
    if isinstance(profile_obj, dict):
        birthdate = profile_obj.get("BIRTHDATE")
    age_years = None
    if birthdate:
        try:
            birth = dt.date.fromisoformat(str(birthdate).strip())
            today = dt.date.today()
            age_years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        except Exception:
            age_years = None
    age_factor = (age_years / 100.0) if isinstance(age_years, int) else None
    readmission_risk = (len(conditions_list) * age_factor) if isinstance(age_factor, float) else None

    if print_ehr:
        source_label = "MCP" if mcp_tools else "local CSV fallback"
        print(f"\n=== EHR Context ({source_label}) ===")
        print("Patient:", patient_id)
        print("\nProfile:\n", profile)
        print("\nHistory (conditions/meds):\n", history)
        if age_years is not None:
            print(f"\nDerived age_years: {age_years}")
        if readmission_risk is not None:
            print(f"Derived risk inputs: conditions={len(conditions_list)}, age_factor={age_factor:.2f}")
            print(f"Derived readmission risk R = conditions * age_factor = {readmission_risk:.2f}")

    if os.getenv("DRY_RUN", "0") == "1":
        print("\nDRY_RUN=1: stopping before model call.")
        return

    def _fallback_discharge_markdown(error: str | None = None) -> str:
        lines: list[str] = []
        lines.append(f"# Discharge Summary Report ({patient_id})")
        lines.append("")
        lines.append("## Patient")
        lines.append(f"- Patient ID: {patient_id}")
        if isinstance(profile_obj, dict):
            name = " ".join(
                [
                    str(profile_obj.get(k))
                    for k in ("PREFIX", "FIRST", "MIDDLE", "LAST", "SUFFIX")
                    if profile_obj.get(k) is not None and str(profile_obj.get(k)).lower() != "nan"
                ]
            ).strip()
            if name:
                lines.append(f"- Name: {name}")
            if profile_obj.get("BIRTHDATE") is not None:
                lines.append(f"- DOB: {str(profile_obj.get('BIRTHDATE')).strip()}")
        lines.append("")
        lines.append("## Conditions")
        if conditions_list:
            lines.extend([f"- {c}" for c in conditions_list])
        else:
            lines.append("- (none found)")
        lines.append("")
        lines.append("## Medications")
        if meds_list:
            lines.extend([f"- {m}" for m in meds_list])
        else:
            lines.append("- (none found)")
        lines.append("")
        lines.append("## Readmission Risk (Simple)")
        lines.append(f"- age_years: {age_years}")
        lines.append(f"- age_factor: {age_factor}")
        lines.append(f"- count(conditions): {len(conditions_list)}")
        lines.append(f"- R ≈ {readmission_risk}")
        if error:
            lines.append("")
            lines.append("## Note")
            lines.append(
                "This report was generated using a fallback template because the agent run did not complete cleanly."
            )
            lines.append(f"- Error: {error}")
        return "\n".join(lines) + "\n"

    # Smoke test: prove MCP tools work with a real patient ID
    if run_smoke_test:
        print("\nMCP smoke_test get_patient_profile:")
        print(profile)
        print("\nMCP smoke_test search_clinical_history:")
        print(history)

    if user_query is None:
        user_query = os.getenv("USER_QUERY")
    if user_query is None:
        user_query = input("\nEnter your discharge question/request: ").strip()
    if not user_query:
        raise ValueError("User query cannot be empty.")

    tool_note = (
        "EHR context (retrieved via MCP tools `get_patient_profile` and `search_clinical_history`):"
        if mcp_tools
        else "EHR context (retrieved via local CSV fallback; MCP tools unavailable):"
    )

    prompt = rf"""
Conduct a full discharge review for Patient {patient_id}.

{tool_note}
- Profile: {profile_obj}
- Conditions: {conditions_list}
- Medications: {meds_list}

User request:
{user_query}

1. Use the available tools as needed to confirm history.
2. Spawn a `pharmacy_expert` sub-agent to check for medication conflicts and safety issues.
3. Write a `discharge_summary_{patient_id}.md` to the filesystem.
4. Calculate the re-admission risk using:
   $R = \sum (conditions \times age\_factor)$
   Use `age_factor = age_years / 100`.
   Use each condition weight = 1 (so $R = count(conditions) \times age\_factor$).
   Derived (from current EHR parse):
   - age_years = {age_years}
   - age_factor = {age_factor}
   - count(conditions) = {len(conditions_list)}
   - R ≈ {readmission_risk}

Return the discharge summary text in your final answer.
"""
    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        agent = create_deep_agent(
            model=os.getenv("DEEPAGENTS_MODEL", "openai:gpt-4o"),
            tools=mcp_tools,
            backend=backend,
            checkpointer=checkpointer,
            subagents=[pharmacy_auditor],
            interrupt_on={"write_file": True} if hitl_write_approval else None,
            debug=debug,
        )

        # Prefer a single-shot invoke so we can always capture final output
        # and write the report file deterministically.
        if trace_events:
            print("\nTRACE_EVENTS=1 (note: events can be verbose)", flush=True)
            async for event in agent.astream({"messages": [("user", prompt)]}, config):
                print(event)

        report_path = patient_workspace_dir / f"discharge_summary_{patient_id}.md"

        def _extract_final_text(result_obj: object) -> str:
            if isinstance(result_obj, dict):
                maybe_output = result_obj.get("output")
                if isinstance(maybe_output, str) and maybe_output.strip():
                    return maybe_output.strip()
                maybe_final = result_obj.get("final")
                if isinstance(maybe_final, str) and maybe_final.strip():
                    return maybe_final.strip()
                for msg in reversed(result_obj.get("messages", []) or []):
                    content = getattr(msg, "content", None)
                    if content:
                        return str(content)
            return ""

        try:
            result = await agent.ainvoke({"messages": [("user", prompt)]}, config)
            final_text = _extract_final_text(result)
        except Exception as e:
            final_text = ""
            report_path.write_text(_fallback_discharge_markdown(error=str(e)), encoding="utf-8")
            print(f"\nWARNING: agent run failed; wrote fallback report to {report_path}")
            raise

        # Some models occasionally hallucinate that they "can't write files".
        # If that happens, keep only the actual markdown report section.
        lowered = final_text.lower()
        header_idx = final_text.find("#")
        if header_idx != -1 and not final_text.lstrip().startswith("#"):
            final_text = final_text[header_idx:].lstrip()
        elif "don't have the necessary permissions" in lowered or "do not have the necessary permissions" in lowered:
            # Back-compat with earlier behavior; kept for clarity.
            if header_idx != -1:
                final_text = final_text[header_idx:].lstrip()

        if not final_text.strip():
            final_text = _fallback_discharge_markdown(error="No final text produced by agent")
        report_path.write_text(final_text, encoding="utf-8")

        if final_text and not suppress_final_print:
            print("\n=== Discharge Summary (final) ===\n")
            print(final_text)
        print(f"\nWrote: {report_path}")

if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="DeepAgents healthcare discharge demo")
    parser.add_argument("--patient-id", dest="patient_id", default=None)
    parser.add_argument("--query", dest="user_query", default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the checkpointed thread for this patient_id (thread_id=patient_id).",
    )
    parser.add_argument(
        "--thread-id",
        dest="thread_id",
        default=None,
        help="Override the LangGraph thread_id (advanced).",
    )
    args = parser.parse_args()

    asyncio.run(
        run_discharge(
            patient_id=args.patient_id,
            user_query=args.user_query,
            resume=args.resume,
            thread_id=args.thread_id,
        )
    )