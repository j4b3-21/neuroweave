import panel as pn

from utils import ImportPythonFile

pn.extension()

# User input widgets
folder_input = pn.widgets.TextInput(
    name="Destination Folder",
    placeholder="Enter folder path",
    value="./my_folder"
)

filename_input = pn.widgets.TextInput(
    name="Save Filename",
    placeholder="Enter filename",
    value="hello.py"
)

upload_container = pn.Column()


def create_uploader(event=None):
    upload_container.clear()

    uploader = ImportPythonFile(
        destination_folder=folder_input.value,
        save_filename=filename_input.value
    )

    upload_container.append(uploader.view())


create_button = pn.widgets.Button(
    name="Create Upload Widget",
    button_type="primary"
)

create_button.on_click(create_uploader)

pn.Column(
    "# Python File Import Tool",
    folder_input,
    filename_input,
    create_button,
    upload_container
).servable()