MediFlow: Autonomous Clinical Discharge CoordinatorBuilt with LangGraph + DeepAgents + FastMCPMediFlow is an agentic healthcare system designed to solve the "Goldfish Memory" problem in clinical AI. While standard chatbots struggle with context limits and hallucinate when reading long medical histories, MediFlow uses a Deep Agent architecture to decompose tasks, offload memory to a virtual workspace, and maintain safety via human-in-the-loop checkpoints.🚀 



The Core Problem: Context BloatIn healthcare, context is a double-edged sword.The Risk: Stuffer 10 years of patient history into a prompt, and the model misses the Penicillin allergy on page 4.The Solution: MediFlow doesn't "read" everything at once. It uses a Virtual Filesystem to offload data, reading only what it needs for the specific sub-task at hand.


✨ Key "Deep Agent" Features1. 🧠 Autonomous Planning & DelegationThe agent doesn't just "chat." It uses a Supervisor to write a task-list (via the write_todos tool). It then spawns specialized sub-agents:EHR Miner: Queries the Synthea database via FastMCP.Pharmacy Auditor: An isolated sub-agent dedicated only to drug-to-drug interaction checks.

2. 📁 Virtual Filesystem (Context Offloading)To keep the LLM sharp and costs low, the agent offloads heavy context to a local workspace.Write: Large patient records are summarized and stored as .txt or .json files.Read: The agent "picks up" these files only when necessary, keeping the active context window lean.Artifacts: Final discharge summaries are generated as Markdown files: patient_workspace/<id>/discharge_summary.md.

3. 💾 State PersistenceUsing a SQLite Checkpointer, the state is never lost.If the system crashes or the user closes the app, the agent resumes from the exact node where it left off.This allows for "Multi-day workflows" common in clinical settings.

4. 🛑 Human-in-the-Loop (HITL)Safety is mandatory. The graph includes a Breakpoint before any final medical report is generated.Note: The agent pauses for an "MD Signature" (User Approval) before committing the final discharge file to the workspace.


 "Discharge Decision" is backed by both qualitative reasoning and quantitative modeling.
<img width="150" height="306" alt="image" src="https://github.com/user-attachments/assets/456d0a59-5a58-4efd-ad76-d886161c54a8" />

