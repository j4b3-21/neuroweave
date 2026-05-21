from pathlib import Path
import panel as pn

pn.extension()


class ImportPythonFile:
    def __init__(self, destination_folder: str, save_filename: str):
        self.destination_folder = Path(destination_folder)
        self.save_filename = save_filename

        # Create destination folder if it does not exist
        self.destination_folder.mkdir(parents=True, exist_ok=True)

        self.file_input = pn.widgets.FileInput(
            accept=".py",
            multiple=False
        )

        self.status = pn.pane.Markdown("")

        self.file_input.param.watch(self.save_file, "value")

    def save_file(self, event):
        if self.file_input.value is None:
            return

        save_path = self.destination_folder / self.save_filename

        with open(save_path, "wb") as f:
            f.write(self.file_input.value)

        self.status.object = f"""
**Saved as:** `{self.save_filename}`

**Saved at:** `{save_path}`
"""

        print(f"Saved file to: {save_path}")

    def view(self):
        return pn.Column(
            "# Upload Python File",
            self.file_input,
            self.status
        )
