# src/aura_ide/panels/ide_panel/log_viewer_widget.py

from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtCore import Slot


class LogViewerWidget(QPlainTextEdit):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setReadOnly(True)
        self.setMaximumBlockCount(1000)  # Prevent memory leak

        # Connect to the raw_event_received signal for logs
        self.bridge.raw_event_received.connect(self.on_raw_event)

    @Slot(dict)
    def on_raw_event(self, event: dict):
        event_name = event.get('name', 'unknown.event')
        if event_name == 'log.emitted' and 'log_record' in event.get('payload', {}):
            record = event['payload']['log_record']
            level = record.get('level', 'INFO')
            message = record.get('message', '')

            # Simple color coding
            color = "black"
            if level == "WARNING":
                color = "orange"
            elif level == "ERROR" or level == "CRITICAL":
                color = "red"

            formatted_message = f'<span style="color: {color};">[{record.get("timestamp")}] [{level:<8}] {message}</span>'
            self.appendHtml(formatted_message)
