from pathlib import Path

import pandas as pd
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MedicalRecordServer")

# Load your Synthea Data
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "synthea_sample_data_csv_latest"

patients = pd.read_csv(DATA_DIR / "patients.csv")
conditions = pd.read_csv(DATA_DIR / "conditions.csv")
meds = pd.read_csv(DATA_DIR / "medications.csv")

@mcp.tool()
def get_patient_profile(patient_id: str) -> str:
    """Fetch demographic and basic info for a patient."""
    data = patients[patients['Id'] == patient_id].to_dict('records')
    return str(data[0]) if data else "Patient not found."

@mcp.tool()
def search_clinical_history(patient_id: str) -> str:
    """Fetch all known medical conditions and active medications."""
    p_conds = conditions[conditions['PATIENT'] == patient_id]['DESCRIPTION'].tolist()
    p_meds = meds[meds['PATIENT'] == patient_id]['DESCRIPTION'].tolist()
    return f"Conditions: {p_conds}\nMedications: {p_meds}"

if __name__ == "__main__":
    mcp.run()
