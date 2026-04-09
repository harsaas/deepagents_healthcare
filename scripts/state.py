from typing import TypedDict, List

from langchain_core.messages import BaseMessage

class AdvancedClinicalState(TypedDict):
    patient_id: str
    # Standard conversation history
    messages: List[BaseMessage]
    
    # Track which files exist in the patient's 'Virtual Folder'
    workspace_files: List[str] 
    
    # Metadata for the current 'Deep Task'
    current_plan: List[str]
    active_subagent: str
    
    # Memory Summary (Offloaded context)
    summary_file_path: str