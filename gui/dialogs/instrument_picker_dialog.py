"""Startup instrument picker dialog for TAVI.

Shown by ``main()`` only when more than one instrument is registered and no
``--instrument`` CLI flag was given (``docs/CONFIGURABLE_INSTRUMENTS.md`` §7.1,
§17.1). The selected instrument is fixed for the session.
"""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout)
from PySide6.QtCore import Qt


class InstrumentPickerDialog(QDialog):
    """Modal list of registered instruments; returns the chosen instrument id."""

    def __init__(self, instrument_infos, parent=None):
        """Args:
            instrument_infos: iterable of ``InstrumentInfo`` (id, display_name)
                from ``instruments.registry.available_instruments()``.
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setObjectName("instrument_picker_dialog")
        self.setWindowTitle("Select Instrument")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose the instrument for this session:"))

        self.instrument_list = QListWidget(self)
        self.instrument_list.setObjectName("instrument_picker_list")
        for info in instrument_infos:
            item = QListWidgetItem(info.display_name)
            item.setData(Qt.ItemDataRole.UserRole, info.id)
            self.instrument_list.addItem(item)
        if self.instrument_list.count():
            self.instrument_list.setCurrentRow(0)
        self.instrument_list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.instrument_list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_instrument_id(self):
        """Return the id of the highlighted instrument, or ``None``."""
        item = self.instrument_list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    @classmethod
    def pick(cls, instrument_infos, parent=None):
        """Show the dialog modally; return the chosen id, or ``None`` on cancel."""
        dialog = cls(instrument_infos, parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_instrument_id()
        return None
