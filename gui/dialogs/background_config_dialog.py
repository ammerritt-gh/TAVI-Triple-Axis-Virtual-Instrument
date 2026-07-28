"""Modal editor for TAVI's independently scaled background sources."""
import sys
from collections import OrderedDict

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QCheckBox,
)

from tavi import background


class BackgroundConfigDialog(QDialog):
    """Stage source enable/scale edits until the user accepts the dialog."""

    CATEGORY_LABELS = OrderedDict(
        (category, background.CATEGORY_LABELS[category])
        for category in background.CATEGORIES
    )

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.setObjectName("background_config_dialog")
        self.setWindowTitle("Background configuration")
        self.setMinimumWidth(520)
        self._global_enabled = bool(spec.get("enabled", False))
        self._source_widgets = OrderedDict()
        self._original_scales = {}
        self._edited_scale_sources = set()

        catalog = background.source_catalog()
        configured = spec.get("sources", {})
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Enable and scale each assumed source independently. "
            "These settings are remembered even while the global Background "
            "checkbox is off."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for category, heading in self.CATEGORY_LABELS.items():
            group = QGroupBox(heading)
            grid = QGridLayout(group)
            entries = [
                (source_id, item)
                for source_id, item in catalog.items()
                if item["category"] == category
            ]
            if not entries:
                empty = QLabel(
                    "No instrument background options are available yet."
                    if category == "instrument"
                    else "No background options are available in this category."
                )
                empty.setStyleSheet("color: #666666; font-style: italic;")
                grid.addWidget(empty, 0, 0, 1, 3)
            for row, (source_id, item) in enumerate(entries):
                state = configured.get(source_id, {})
                enabled = bool(state.get("enabled", False))
                try:
                    scale = float(state.get("scale", 1.0))
                except (TypeError, ValueError) as exc:
                    print(
                        f"Background source {source_id!r} has an invalid saved "
                        f"scale ({exc}); showing x 1"
                    )
                    scale = 1.0
                self._original_scales[source_id] = scale

                check = QCheckBox(item["label"])
                check.setChecked(enabled)
                tooltip = (
                    item["description"]
                    + "\n\n"
                    + item["scale_meaning"]
                )
                check.setToolTip(tooltip)
                grid.addWidget(check, row, 0)

                multiplier = QLabel("×")
                multiplier.setToolTip(tooltip)
                grid.addWidget(multiplier, row, 1)

                scale_spin = QDoubleSpinBox()
                scale_spin.setObjectName(f"background_scale_{source_id}")
                # Preserve valid API/persisted scales when the user opens and
                # applies the dialog without editing them. Three decimals
                # silently turned values such as 0.0004 into zero.
                scale_spin.setDecimals(12)
                scale_spin.setRange(0.0, sys.float_info.max)
                scale_spin.setSingleStep(0.1)
                scale_spin.setValue(scale)
                scale_spin.valueChanged.connect(
                    lambda _value, source_id=source_id: (
                        self._edited_scale_sources.add(source_id)
                    )
                )
                scale_spin.setKeyboardTracking(False)
                scale_spin.setToolTip(
                    tooltip
                    + "\n\nScale ×1 uses the catalog reference setting."
                )
                grid.addWidget(scale_spin, row, 2)
                self._source_widgets[source_id] = (check, scale_spin)

            grid.setColumnStretch(0, 1)
            layout.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Apply
        ).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def background_spec(self):
        """Return the complete canonical configuration represented by the dialog."""
        return {
            "catalog_version": background.CATALOG_VERSION,
            "enabled": self._global_enabled,
            "sources": {
                source_id: {
                    "enabled": bool(check.isChecked()),
                    "scale": (
                        float(scale_spin.value())
                        if source_id in self._edited_scale_sources
                        else self._original_scales[source_id]
                    ),
                }
                for source_id, (check, scale_spin) in self._source_widgets.items()
            },
        }

    @classmethod
    def configure(cls, spec, parent=None):
        """Return staged edits on Apply, or ``None`` when cancelled."""
        dialog = cls(spec, parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.background_spec()
        return None
