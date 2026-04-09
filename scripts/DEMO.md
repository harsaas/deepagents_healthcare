# DeepAgents in Healthcare — Demo & Tracing

This repo has two runnable demos:

- **LangGraph-only workflow demo (offline)**: `scripts/main.py`
- **DeepAgents + MCP tools (needs an LLM key)**: `scripts/deep_agent_healthcare.py`

All commands below assume you run them from the repo root.

## 0) Use the repo venv

PowerShell:

- Run Python: `./.venv/Scripts/python.exe`

Note:

- `./.venv/Scripts/python.exe` is the correct venv Python path.
- `.python.exe` is not a valid command and will fail.

If dependencies are missing, install the project (editable):

- `./.venv/Scripts/python.exe -m pip install -e .`

## 1) Offline demo (no API keys)

Runs a small LangGraph workflow with checkpointing and a conditional “offload memory to disk” step.

- `./.venv/Scripts/python.exe -m scripts.main`

Or use the helper script:

- `./run_main.ps1`

What to look for:

- Console prints only the final assistant message.
- A summary file is created at `workspaces/patient_101/session_summary.txt`.
- A SQLite DB is created at `langgraph_demo.db`.

Note:

- By default, `scripts.main` starts a fresh `thread_id` each run so it doesn’t resume old checkpoints.
- Use `--resume` if you want to continue a prior run for the same patient.

## 2) MCP server (optional: run standalone)

This starts the Medical MCP server that serves EHR tools from the Synthea CSVs.

- `./.venv/Scripts/python.exe -m scripts.medical_mcp`

Note: The DeepAgents demo below spawns this MCP server automatically via stdio, so you don’t need to start it manually unless you’re debugging.

## 3) DeepAgents + MCP tools demo (with tracing)

### 3.1 Required env vars

The script auto-loads environment variables from the repo-root `.env` file (via `python-dotenv`).
If your keys are already in `.env`, you can skip manually exporting them.

PowerShell:

- `$env:OPENAI_API_KEY = "<your key>"`

Optional:

- `$env:DEEPAGENTS_MODEL = "openai:gpt-4o"`
- `$env:DEEPAGENTS_DEBUG = "1"` (more internal debug)

### 3.2 MCP smoke test (proves EHR toolchain works)

Enable the smoke test (it will call the MCP tools once and print the results):

- `$env:RUN_MCP_SMOKE_TEST = "1"`

### 3.3 Event stream tracing

By default, the script prints events from `agent.astream(...)`.

- To **disable** event printing: `$env:TRACE_EVENTS = "0"`

### 3.4 Run

- `./.venv/Scripts/python.exe -m scripts.deep_agent_healthcare`

Interactive mode:

- Provide a patient explicitly: `./.venv/Scripts/python.exe -m scripts.deep_agent_healthcare --patient-id <UUID>`
- Provide a query without prompts: `./.venv/Scripts/python.exe -m scripts.deep_agent_healthcare --query "Summarize discharge plan and follow-up"`
- Provide both: `./.venv/Scripts/python.exe -m scripts.deep_agent_healthcare --patient-id <UUID> --query "Analyze meds and conditions, write discharge summary"`

Useful flags:

- Test MCP retrieval only (no LLM call): `$env:DRY_RUN = "1"`
- Enable MCP tool loading (optional): `$env:USE_MCP = "1"`
- Require approval before file writes: `$env:HITL_WRITE_APPROVAL = "1"`
- Resume an existing checkpoint thread: add `--resume`

What to look for:

- If `RUN_MCP_SMOKE_TEST=1`, you should see output for:
  - `MCP smoke_test get_patient_profile`
  - `MCP smoke_test search_clinical_history`
- Then you’ll see the event stream (unless `TRACE_EVENTS=0`).
- Agent output files go under `patient_workspace/`.
- Discharge reports are written per patient under `patient_workspace/<patient_id>/discharge_summary_<patient_id>.md`.
- Checkpoint DB is `healthcare_agent.db`.

## 4) Optional: LangSmith tracing (cloud)

If you use LangSmith, enable tracing:

- `$env:LANGCHAIN_TRACING_V2 = "true"`
- `$env:LANGCHAIN_API_KEY = "<your langsmith key>"`
- `$env:LANGCHAIN_PROJECT = "deepagents_in_healthcare"`

Then rerun the DeepAgents demo. (Exact trace content depends on your LangChain/LangGraph versions and configured callbacks.)
