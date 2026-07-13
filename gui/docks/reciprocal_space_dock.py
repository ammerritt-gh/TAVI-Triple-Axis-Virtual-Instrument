"""Interactive vTAS-style reciprocal-space view.

Painting is deliberately native Qt rather than matplotlib, which keeps drag
feedback responsive and lets the widget be a normal floating dock.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QCursor
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from gui.docks.base_dock import BaseDockWidget
from tavi.reciprocal_interaction import LockState, ReciprocalInteractionModel, ReciprocalState
from tavi.neutron_conversions import k2energy


def _number(text: str, fallback: float = 0.0) -> float:
    try:
        return float(text)
    except ValueError:
        return fallback


class ReciprocalCanvas(QWidget):
    """Small paint widget; all physics lives in ``ReciprocalInteractionModel``."""
    preview_changed = Signal(object)
    move_committed = Signal(object)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self.model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.66, 1.0, 0.0))
        self.reflections = []
        self.snap_grid = 0.1
        self.snap_grid_enabled = False
        self.snap_reflections_enabled = False
        self._drag = None
        self._last = None
        self._space_pan = False
        self.unsnapped = None
        self.snapped = None

    def set_snapshot(self, snapshot: dict) -> None:
        p2 = snapshot.get("p2") or (None, None)
        state = ReciprocalState(snapshot["ki"], snapshot["kf"], snapshot["qx"],
                                snapshot["qy"], snapshot["qz"], p2[0], p2[1], snapshot.get("basis_u", (1., 0.)), snapshot.get("basis_v", (0., 1.)))
        if self._drag is None:
            self.model.set_state(state)
        self.update()

    def set_reflections(self, reflections) -> None:
        """Install projected centres as ``(qx, qy, F²|None)``."""
        self.reflections = list(reflections)
        self.update()

    def centre(self):
        return (self.width() / 2.0, self.height() / 2.0)

    def _point(self, value):
        return self.model.world_to_screen(value, self.centre())

    def _world(self, value):
        return self.model.screen_to_world(value, self.centre())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#fcfcfc"))
        painter.setRenderHint(QPainter.Antialiasing)
        centre = self._point((0, 0))
        painter.setPen(QPen(QColor("#c8c8c8"), 1))
        painter.drawLine(0, round(centre[1]), self.width(), round(centre[1]))
        painter.drawLine(round(centre[0]), 0, round(centre[0]), self.height())
        # Reflections: filled means table-backed F2, hollow means fallback.
        used_labels = []
        for reflection in self.reflections:
            x, y, f2, label = reflection.qx, reflection.qy, reflection.f_squared, reflection.hkl_label
            px, py = self._point((x, y))
            radius = 5 if f2 is None else max(3, min(12, 2 + math.sqrt(max(f2, 0))))
            painter.setPen(QPen(QColor("#6c757d"), 1.2))
            if f2 is None:
                painter.setBrush(Qt.NoBrush)
            else:
                painter.setBrush(QColor("#a8dadc"))
            painter.drawEllipse(round(px-radius), round(py-radius), round(radius*2), round(radius*2))
            # Typed HKL labels are intentionally decluttered in screen space.
            if radius >= 5 and 12 < px < self.width()-35 and 12 < py < self.height()-12 and all(math.dist((px, py), other) > 22 for other in used_labels):
                painter.setPen(QPen(QColor("#58636b"), 1))
                painter.drawText(round(px+radius+2), round(py-radius-2), label)
                used_labels.append((px, py))
        state = self.model.preview
        p0 = self._point((0, 0))
        p1 = self._point((state.qx, state.qy))
        # Canonical local drawing puts ki endpoint at P2; preserve the current
        # incident orientation only for interaction, so the triangle is legible.
        p2 = self._point((state.p2x, state.p2y))
        painter.setPen(QPen(QColor("#1d3557"), 2.5))
        painter.drawLine(*map(round, (*p0, *p2)))
        painter.setPen(QPen(QColor("#e76f51"), 2.5))
        painter.drawLine(*map(round, (*p2, *p1)))
        painter.setPen(QPen(QColor("#457b9d"), 2.5))
        painter.drawLine(*map(round, (*p0, *p1)))
        # Small arrowheads make the vTAS vector direction unambiguous.
        def arrowhead(start, end, colour):
            angle = math.atan2(end[1]-start[1], end[0]-start[0])
            wing = 0.48
            points = [QPointF(*end),
                      QPointF(end[0]-10*math.cos(angle-wing), end[1]-10*math.sin(angle-wing)),
                      QPointF(end[0]-10*math.cos(angle+wing), end[1]-10*math.sin(angle+wing))]
            painter.setBrush(colour); painter.setPen(Qt.NoPen); painter.drawPolygon(points)
        arrowhead(p2, p0, QColor("#1d3557")); arrowhead(p2, p1, QColor("#e76f51")); arrowhead(p0, p1, QColor("#457b9d"))
        # vTAS-style leg annotations keep the triangle readable at a glance.
        painter.setPen(QPen(QColor("#1d3557"), 1))
        painter.drawText(round((p0[0]+p2[0])/2), round((p0[1]+p2[1])/2)-6, "ki")
        painter.setPen(QPen(QColor("#e76f51"), 1))
        painter.drawText(round((p2[0]+p1[0])/2), round((p2[1]+p1[1])/2)-6, "kf")
        painter.setPen(QPen(QColor("#457b9d"), 1))
        painter.drawText(round((p0[0]+p1[0])/2), round((p0[1]+p1[1])/2)-6, "Q")
        painter.setBrush(QColor("#457b9d")); painter.setPen(QPen(QColor("#1d3557"), 1))
        for point in (p1, p2):
            painter.drawEllipse(round(point[0]-6), round(point[1]-6), 12, 12)
        if self.unsnapped is not None and self.snapped is not None:
            ghost = self._point(self.unsnapped); target = self._point(self.snapped)
            painter.setBrush(Qt.NoBrush); painter.setPen(QPen(QColor("#999999"), 1, Qt.DashLine))
            painter.drawEllipse(round(ghost[0]-5), round(ghost[1]-5), 10, 10)
            painter.setPen(QPen(QColor("#2a9d8f"), 2)); painter.drawEllipse(round(target[0]-7), round(target[1]-7), 14, 14)
        painter.setPen(QPen(QColor("#222222"), 1))
        painter.drawText(8, 18, f"ki {state.ki:.3f}  kf {state.kf:.3f}  |Q| {state.q:.3f} Å⁻¹")

    def _hit(self, pos):
        state = self.model.preview
        p1, p2 = self._point((state.qx, state.qy)), self._point((state.p2x, state.p2y))
        if math.dist(pos, p1) <= 12: return "p1"
        if math.dist(pos, p2) <= 12: return "p2"
        return None

    def mousePressEvent(self, event):
        position = (event.position().x(), event.position().y())
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_pan):
            self._drag, self._last = "pan", position
            return
        if event.button() == Qt.LeftButton:
            hit = self._hit(position)
            if hit:
                self._drag = hit; self._last = position; self.model.begin_drag()
            else:
                self._drag, self._last = "pan", position

    def mouseMoveEvent(self, event):
        pos = (event.position().x(), event.position().y())
        if self._drag == "pan":
            self.model.pan((pos[0]-self._last[0], pos[1]-self._last[1])); self._last = pos; self.update(); return
        if self._drag not in {"p1", "p2"}:
            self.setCursor(Qt.OpenHandCursor if self._hit(pos) is None else Qt.CrossCursor)
            nearest = min(self.reflections, key=lambda item: math.dist(pos, self._point((item.qx, item.qy))), default=None)
            if nearest and math.dist(pos, self._point((nearest.qx, nearest.qy))) < 10:
                self.status_changed.emit(f"Reflection {nearest.hkl_label}" + (f", F²={nearest.f_squared:.3g}" if nearest.f_squared is not None else " (centering fallback)"))
            return
        candidate = self._world(pos)
        if self._drag == "p1":
            reflections = [(item.qx, item.qy) for item in self.reflections] if self.snap_reflections_enabled else []
            result = self.model.drag_p1(candidate, snap_grid=self.snap_grid if self.snap_grid_enabled else None,
                                        reflections=reflections, capture=10 / self.model.scale)
        else:
            result = self.model.drag_p2(candidate)
        if result.valid:
            self.unsnapped, self.snapped = result.unsnapped, result.snapped
            self.preview_changed.emit(result.state)
            self.status_changed.emit("Preview" + (" (snapped)" if result.snapped else ""))
            self.update()
        else:
            self.status_changed.emit(result.reason or "No solution")

    def mouseReleaseEvent(self, event):
        if self._drag in {"p1", "p2"}:
            self.move_committed.emit(self.model.preview)
        self._drag = None
        self.setCursor(Qt.ArrowCursor)
        self.unsnapped = self.snapped = None

    def wheelEvent(self, event):
        self.model.zoom_at(1.15 if event.angleDelta().y() > 0 else 1/1.15,
                           (event.position().x(), event.position().y()), self.centre())
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space: self._space_pan = True

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space: self._space_pan = False


class ReciprocalSpaceDock(BaseDockWidget):
    """Persistent dock wrapping the canvas and vTAS-style scalar controls."""
    move_requested = Signal(object)
    values_requested = Signal(dict)
    plane_requested = Signal(object, object)

    def __init__(self, parent=None):
        # The canvas is the primary workspace; a dock-level scroll area would
        # consume vertical room and leave a large floating window cramped.
        super().__init__("Reciprocal Space", parent, use_scroll_area=False)
        self.setObjectName("ReciprocalSpaceDock")
        self.canvas = ReciprocalCanvas(self)
        self._updating = False
        self._last_k_fixed = None
        self._build_controls()
        self.content_layout.addWidget(self.canvas, 1)
        self.canvas.move_committed.connect(self.move_requested)
        self.canvas.preview_changed.connect(self._preview)
        self.canvas.status_changed.connect(self.status.setText)

    def _field(self, text=""):
        field = QLineEdit(text); field.setMaximumWidth(85); return field

    def _build_controls(self):
        controls = QGroupBox("Triangle constraints")
        grid = QGridLayout(controls)
        self.fields = {}
        self.energy_readouts = {}
        self.locks = {}
        for row, (key, label) in enumerate((("ki", "ki"), ("kf", "kf"), ("q", "|Q|"), ("delta_e", "ΔE"))):
            grid.addWidget(QLabel(label), row, 0)
            edit = self._field(); self.fields[key] = edit; grid.addWidget(edit, row, 1)
            lock = QToolButton(); lock.setText("Lock"); lock.setCheckable(True); self.locks[key] = lock; grid.addWidget(lock, row, 2)
            if key in {"ki", "kf"}:
                grid.addWidget(QLabel("Å⁻¹"), row, 3)
                energy = QLineEdit(); energy.setMaximumWidth(85)
                self.energy_readouts[key] = energy; grid.addWidget(QLabel("E" + key[1:] + ":"), row, 4); grid.addWidget(energy, row, 5)
                energy.editingFinished.connect(self._request_values)
            elif key == "q": grid.addWidget(QLabel("Å⁻¹"), row, 3)
            else: grid.addWidget(QLabel("meV"), row, 3)
            edit.editingFinished.connect(self._request_values)
            lock.toggled.connect(self._apply_locks)
        # Compact one-line constraint strip: retain the existing controls but
        # remap each former row into a horizontal group before it is shown.
        items = []
        for index in range(grid.count()):
            row, column, _rows, _columns = grid.getItemPosition(index)
            item = grid.itemAt(index)
            widget = item.widget()
            if widget is not None:
                items.append((widget, row, column))
        for widget, row, column in items:
            grid.addWidget(widget, 0, column + row * 6)
        self.content_layout.addWidget(controls)
        self.advanced_toggle = QToolButton(); self.advanced_toggle.setText("U/V plane and snapping"); self.advanced_toggle.setCheckable(True); self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.content_layout.addWidget(self.advanced_toggle)
        self.advanced_widget = QWidget(); advanced_layout = QVBoxLayout(self.advanced_widget); advanced_layout.setContentsMargins(0, 0, 0, 0)
        plane = QGroupBox("Display plane (HKL)"); form = QFormLayout(plane)
        self.u_fields, self.v_fields = [self._field() for _ in range(3)], [self._field() for _ in range(3)]
        for label, fields in (("U", self.u_fields), ("V", self.v_fields)):
            row = QHBoxLayout(); [row.addWidget(field) for field in fields]; form.addRow(label, row)
            for field in fields: field.editingFinished.connect(self._validate_plane)
        advanced_layout.addWidget(plane)
        snap = QGroupBox("Snapping"); snap_layout = QGridLayout(snap)
        self.snap_reflections = QCheckBox("Snap to reflections")
        self.snap_grid = QCheckBox("Snap to HKL grid")
        self.grid_step = self._field("0.1")
        snap_layout.addWidget(self.snap_reflections, 0, 0, 1, 2); snap_layout.addWidget(self.snap_grid, 1, 0); snap_layout.addWidget(self.grid_step, 1, 1)
        self.snap_reflections.toggled.connect(lambda value: setattr(self.canvas, "snap_reflections_enabled", value))
        self.snap_grid.toggled.connect(lambda value: setattr(self.canvas, "snap_grid_enabled", value))
        self.grid_step.editingFinished.connect(lambda: setattr(self.canvas, "snap_grid", max(0.001, _number(self.grid_step.text(), .1))))
        advanced_layout.addWidget(snap)
        self.advanced_widget.setVisible(False); self.advanced_toggle.toggled.connect(lambda visible: (self.advanced_widget.setVisible(visible), self.advanced_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)))
        self.content_layout.addWidget(self.advanced_widget)
        self.status = QLabel("Ready")
        self.content_layout.addWidget(self.status)
        self.qz_label = QLabel("")
        self.provenance_label = QLabel("")
        self.content_layout.addWidget(self.qz_label)
        self.content_layout.addWidget(self.provenance_label)
        reset = QToolButton(); reset.setText("Fit"); reset.setToolTip("Fit reciprocal-space view"); reset.clicked.connect(lambda: (self.canvas.model.fit(4.0, (self.canvas.width(), self.canvas.height())), self.canvas.update()))
        self.content_layout.addWidget(reset)

    def _apply_locks(self):
        self.canvas.model.locks = LockState(**{key: button.isChecked() for key, button in self.locks.items()})

    def _request_values(self):
        if not self._updating:
            values = {key: _number(field.text()) for key, field in self.fields.items()}
            values["ei"] = _number(self.energy_readouts["ki"].text())
            values["ef"] = _number(self.energy_readouts["kf"].text())
            self.values_requested.emit(values)

    def _validate_plane(self):
        u = [_number(field.text()) for field in self.u_fields]; v = [_number(field.text()) for field in self.v_fields]
        cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        if math.sqrt(sum(x*x for x in cross)) < 1e-8:
            self.status.setText("Display plane is invalid: U and V must be non-zero and non-collinear")
        else:
            self.status.setText("Checking display plane…")
            self.plane_requested.emit(tuple(u), tuple(v))

    def set_plane_status(self, message: str) -> None:
        """Receive controller-side UB projection validation feedback."""
        self.status.setText(message)

    def set_provenance(self, message: str) -> None:
        self.provenance_label.setText(message)

    def _preview(self, state):
        self.fields["ki"].setText(f"{state.ki:.4g}"); self.fields["kf"].setText(f"{state.kf:.4g}")
        self.energy_readouts["ki"].setText(f"{k2energy(state.ki):.4g}")
        self.energy_readouts["kf"].setText(f"{k2energy(state.kf):.4g}")
        self.fields["q"].setText(f"{state.q:.4g}"); self.fields["delta_e"].setText(f"{state.delta_e:.4g}")

    def set_snapshot(self, snapshot: dict):
        self._updating = True
        try:
            self.canvas.set_snapshot(snapshot)
            mode = snapshot.get("K_fixed")
            if mode and mode != self._last_k_fixed:
                self.locks["ki"].setChecked(mode == "Ki Fixed")
                self.locks["kf"].setChecked(mode == "Kf Fixed")
                self._last_k_fixed = mode
            if not any(field.text() for field in self.u_fields):
                for field, value in zip(self.u_fields, snapshot.get("plane_u_hkl", (1., 0., 0.))): field.setText(f"{value:.4g}")
                for field, value in zip(self.v_fields, snapshot.get("plane_v_hkl", (0., 1., 0.))): field.setText(f"{value:.4g}")
            state = self.canvas.model.committed
            self._preview(state)
            self.qz_label.setText(f"qz = {state.qz:.4g} Å⁻¹ preserved outside display plane" if abs(state.qz) > 1e-7 else "qz = 0 (display plane)")
        finally:
            self._updating = False
