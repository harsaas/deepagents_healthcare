# MediFlow — Autonomous Clinical Discharge & Follow-up Coordinator

Built with **LangGraph + DeepAgents + FastMCP**.

MediFlow is an agentic healthcare system designed to address the “Goldfish Memory” problem in clinical AI: long medical histories don’t fit cleanly into a single prompt, and critical facts (e.g., allergies) can be missed. This project demonstrates a “deep agent” approach that decomposes work into steps, offloads context to a patient-scoped workspace, and optionally gates final report writing with human approval.

“Discharge decision” is backed by both qualitative reasoning and quantitative modeling.

<img width="150" height="306" alt="image" src="https://github.com/user-attachments/assets/456d0a59-5a58-4efd-ad76-d886161c54a8" />

## Architecture

```mermaid
flowchart LR
  U[User]

  subgraph Repo[deepagents_healthcare repo]
    subgraph Scripts[scripts/]
      MAIN[scripts/main.py\nLangGraph-only demo]
      DA[scripts/deep_agent_healthcare.py\nDeepAgents discharge workflow]
      MCP[scripts/medical_mcp.py\nFastMCP server (optional)]
    end

    subgraph Data[Local data]
      CSV[synthea_sample_data_csv_latest/*.csv\n(patients, conditions, meds, ...)]
    end

    subgraph Persistence[Persistence]
      DB1[(langgraph_demo.db\nSQLite checkpointer)]
      DB2[(healthcare_agent.db\nSQLite checkpointer)]
    end

    subgraph Outputs[Generated artifacts]
      WS1[workspaces/<patient_id>/session_summary.txt\n(LangGraph demo output)]
      WS2[patient_workspace/<patient_id>/discharge_summary_<patient_id>.md\n(DeepAgents output)]
    end

    subgraph AgentInternals[DeepAgents internals]
      AG[Deep Agent\n(planning + tools)]
      SUB[Sub-agent: pharmacy_expert\n(med safety checks)]
      FS[FilesystemBackend\n(patient-scoped)]
    end
  end

  %% LangGraph demo path
  U -->|patient_id + query| MAIN
  MAIN -->|checkpoint state| DB1
  MAIN -->|offload summary| WS1

  %% DeepAgents discharge path
  U -->|patient_id + discharge query| DA

  %% EHR context retrieval
  DA -->|reads EHR context| CSV

  %% Optional MCP path (tool transport)
  DA -. optional USE_MCP=1 .-> MCP
  MCP -->|reads CSV| CSV

  %% Agent execution + outputs
  DA --> AG
  AG --> SUB
  AG --> FS
  FS --> WS2
  DA -->|checkpoint state| DB2
```

## Demos & tracing

See `scripts/DEMO.md` for run instructions, tracing, and environment flags.
