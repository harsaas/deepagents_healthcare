import os

class HealthcareWorkspace:
    def __init__(self, patient_id):
        self.root = f"./workspaces/{patient_id}"
        os.makedirs(self.root, exist_ok=True)

    def write_clinical_note(self, filename: str, content: str):
        """Writes detailed clinical observations to the workspace."""
        path = os.path.join(self.root, filename)
        with open(path, "w") as f:
            f.write(content)
        return f"Successfully offloaded context to {filename}"

    def read_clinical_note(self, filename: str):
        """Reads specific data back into the LLM's active context."""
        path = os.path.join(self.root, filename)
        if not os.path.exists(path):
            return "File not found."
        with open(path, "r") as f:
            return f.read()

    def list_files(self):
        """Shows the agent what knowledge it has stored locally."""
        return os.listdir(self.root)