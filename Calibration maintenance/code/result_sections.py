"""Result sections shared by the maintenance app's Result tab and the fault-aware app's Calibration review tab.

Each builder takes the dictionaries the maintenance backend saved (appcore.run_info / run_info_at) and returns
ready-made widgets, so the two applications show the same numbers in the same way and there is one
implementation of every section.
"""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt

import appcore as core
from pose_view import CalibrationPosePanel, ComparisonColumns
from ui_common import (BAD, BAD_SOFT, BLUE, BLUE_SOFT, GOOD, GOOD_SOFT, INFO_SOFT, INK, INK2, MUTED, ORANGE, PARAMS,
                       WARN, WARN_SOFT, Gauge, ImageView, button, card, hbox, img_label, label, table)
from ui_widgets import MODE_NAMES, EvidenceColumns
from update_options import rmse_changes

RMSE_TIP = ('Held-out nearest-image-edge RMSE over all tested visible edge points, including unmatched '
            'points. RMSE describes alignment distance; projection shift describes the change from '
            'the previous calibration. Neither is a known-correspondence ground-truth error.')


# ------------------------------------------------------------------ calibrations that can be exported
def export_calibrations(info):
    """{option: calibration dict} the run saved: every fitted option, the existing calibration, and the refined one."""
    s = info["summary"]
    found = dict((s.get('strategy_comparison') or {}).get('calibrations', {}))
    if 'existing' not in found:
        try:
            found['existing'] = core.load_calibration_data(core.resolve(s['existing']))
        except (OSError, ValueError):
            pass
    refined = core.read_json(info['out'] / 'refined_calibration.json')
    if refined:
        found.setdefault(s['mode'], refined)
    return found


# ------------------------------------------------------------------ quality metrics
def metric_row(s, mode=None):
    """Edge RMSE, uncertainty, regions improved and edge alignment, as four cards.

    The RMSE belongs to `mode` (default: the option this run refined). The other three come from the
    refinement leave-one-out analysis, which exists for that option only."""
    mode = mode or s['mode']
    rmse = rmse_changes(s.get('strategy_comparison') or {}).get(mode)
    o, n = s["existing_on_new_data"], s["refined_on_new_data"]
    z = s.get("z")
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(12)
    for title_, value, note in (
            ("Edge RMSE", core.fmt(rmse['after_px'], 2, " px") if rmse else "Not measured",
             (f"Before {rmse['before_px']:.2f} px" +
              (f" · {rmse['reduction_percent']:.1f}% lower" if rmse['reduction_percent'] is not None and rmse['reduction_percent'] >= 0
               else f" · {abs(rmse['reduction_percent']):.1f}% higher" if rmse['reduction_percent'] is not None else ''))
             if rmse else "Run Compare update options to measure RMSE"),
            ("Uncertainty", "± " + core.fmt(s["shift_uncertainty_px"], 2, " px"),
             f'Shift is {core.fmt(z, 1)}× uncertainty' if core.fin(z) else 'More captures needed'),
            ("Regions improved", f"{s['heldout_improved']} / {s['heldout_total']}", "Tested outside the fit"),
            ("Edge alignment", f"{n['on_edge_share'] * 100:.1f} %", f"Previously {o['on_edge_share'] * 100:.1f} %")):
        c, cl = card()
        cl.setSpacing(2)
        cl.addWidget(label(title_, "small"))
        big = label(value)
        big.setStyleSheet("font-size: 18pt; font-weight: 500;")
        cl.addWidget(big)
        cl.addWidget(label(note, "small", wrap=True))
        if title_ == 'Edge RMSE':
            cl.addWidget(label(f"Median projection shift: {s['shift_median_px']:.2f} px", wrap=True))
            cl.addWidget(label(MODE_NAMES.get(mode, mode), 'small'))
            c.setToolTip(RMSE_TIP)
        row.addWidget(c, 1)
    return row


def shift_card(s):
    """How far the refined calibration moves projected LiDAR points, against its uncertainty."""
    c, cl = card("How much did the calibration change?")
    bands = "   ·   ".join(f"{core.fmt(x)} px at {k}" for k, x in (s.get("shift_by_range_px") or {}).items())
    cl.addWidget(label(f"By distance: {bands}", "muted"))
    cl.addWidget(Gauge(s["shift_median_px"], s["shift_uncertainty_px"]))
    return c


# ------------------------------------------------------------------ previous vs new
CANDIDATE_NOTE = {'extrinsic': 'Candidate: alignment only · camera settings kept',
                  'intrinsic': 'Candidate: camera settings only · alignment kept',
                  'full': 'Candidate: camera settings and alignment'}


def parameter_card(s, cmp_):
    """Parameter table (previous, new, change, uncertainty, evidence, pixel effect) next to the 3D pose view."""
    c, cl = card("Previous vs new calibration", CANDIDATE_NOTE.get(s['mode'], 'Review the candidate values'))
    rows, groups, group = [], [], None
    for x in cmp_["rows"]:
        if x["group"] != group:
            group = x["group"]
            groups.append(len(rows))
            rows.append(["Intrinsics (camera)" if group == "intrinsics" else "Extrinsics (LiDAR → camera)"])
        name, unit, nd = PARAMS[x["key"]]
        u = f" {unit}" if unit else ""
        if not x["refined"]:
            rows.append([(name, MUTED), (core.fmt(x["previous"], nd, u), MUTED), (core.fmt(x["new"], nd, u), MUTED), ("—", MUTED),
                         ("—", MUTED), ("kept (not refined)", MUTED), ("—", MUTED)])
            continue
        stat = x["statistical"] or "–"
        sc = {"within noise": (INK2, INFO_SOFT), "borderline": (WARN, WARN_SOFT), "significant": (BLUE, BLUE_SOFT)}.get(stat, (INK2, None))
        pr = x["practical"] or ""
        pc = {"negligible": (GOOD, GOOD_SOFT), "small": (WARN, WARN_SOFT), "large": (BAD, BAD_SOFT)}.get(pr, (INK2, None))
        rows.append([name, core.fmt(x["previous"], nd, u), (core.fmt(x["new"], nd, u), INK, None, True), core.sgn(x["change"], nd, u),
                     "± " + core.fmt(x["uncertainty"], nd, u) if core.fin(x["uncertainty"]) else "–",
                     (stat + (f"  ({core.fmt(x['z'], 1)}×)" if core.fin(x["z"]) else ""), sc[0], sc[1], True),
                     (f"{core.fmt(x['pixel_effect'], 1)} px  {pr}" if core.fin(x["pixel_effect"]) else "–", pc[0], pc[1], True)])
    comparison_table = table(["Parameter", "Previous", "New", "Change", "Uncertainty", "Evidence", "Pixel effect"],
                             rows, numeric=[1, 2, 3, 4], group_rows=groups, stretch=(0, 5, 6))
    comparison_table.setToolTip('Evidence: change divided by uncertainty. Below 2×: within noise; '
                                '2–3×: borderline; above 3×: significant. Pixel effect: that parameter alone, '
                                'with translation evaluated at 3 m.')
    table_column = QtWidgets.QWidget()
    table_layout = QtWidgets.QVBoxLayout(table_column)
    table_layout.setContentsMargins(0, 0, 0, 0)
    table_layout.addWidget(comparison_table)
    table_layout.addWidget(label('Pixel effect: each change on its own. The overall shift above guides the decision.',
                                 'small', wrap=True))
    table_layout.addStretch(1)
    cl.addWidget(ComparisonColumns(table_column, CalibrationPosePanel(cmp_)))
    return c


# ------------------------------------------------------------------ images
class CaptureComparison(QtWidgets.QFrame):
    """Images: previous vs refined, with capture selection, side by side / alternating views and enlargement."""

    def __init__(self, info):
        super().__init__()
        self.setObjectName("card")
        self.info = info
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Images: previous vs refined", "h2"))
        self.views = [(core.capture_display_name(x['name'], index), x['image'], x['flicker'] if x['flicker'].exists() else None)
                      for index, x in enumerate(info['captures'], 1)]
        self.views += [(img_label(p), p, None) for p in info["extra"]]
        self.sel = QtWidgets.QComboBox()
        self.sel.setObjectName('resultCaptureSelector')
        for name, *_ in self.views:
            self.sel.addItem(name)
        for index, capture in enumerate(info['captures']):
            self.sel.setItemData(index, capture['name'], Qt.ToolTipRole)
        self.b_side, self.b_flick = button("Side by side"), button("Alternate views")
        self.b_flick.setObjectName('alternateViews')
        self.b_flick.setToolTip('Alternate between the previous and refined calibration overlays.')
        for b in (self.b_side, self.b_flick):
            b.setCheckable(True)
        self.grp = QtWidgets.QButtonGroup(self)
        self.grp.addButton(self.b_side)
        self.grp.addButton(self.b_flick)
        self.b_side.setChecked(True)
        lay.addWidget(hbox(self.sel, self.b_side, self.b_flick, stretch_at=3))
        self.view = ImageView(self.views[0][1] if self.views else None, caption=self.views[0][0] if self.views else "")
        lay.addWidget(self.view)
        self.legend = label(f"<span style='color:#2fb84f'>●</span> LiDAR edge on an image edge &nbsp; <span style='color:#e8c21e'>●</span> 1-3 px off "
                            f"&nbsp; <span style='color:#d94040'>●</span> further off &nbsp; <span style='color:{BLUE}'>●</span> previous &nbsp; "
                            f"<span style='color:{ORANGE}'>●</span> refined<br>Top: LiDAR edges on image edges with the previous and the refined "
                            "calibration. Bottom: how far the refinement moves each LiDAR point, and zooms. Click the image to enlarge.",
                            "muted", wrap=True, rich=True)
        lay.addWidget(self.legend)
        self.sel.currentIndexChanged.connect(self.show_view)
        self.grp.buttonClicked.connect(lambda *_: self.show_view())
        if self.views:
            self.show_view(0)

    def show_view(self, k=None):
        k = self.sel.currentIndex() if k is None else k
        if k < 0:
            return
        name, img, gif = self.views[k]
        self.b_flick.setEnabled(gif is not None)
        if gif is None:
            self.b_side.setChecked(True)
        self.view.caption = name
        self.view.set_source(gif if self.b_flick.isChecked() and gif else img)
        self.legend.setVisible(k < len(self.info["captures"]))

    def select_capture(self, name):
        """Show the capture whose id (e.g. '185316_547419') is `name`; False when there is no such image."""
        for index, capture in enumerate(self.info['captures']):
            if capture['name'] == name:
                self.sel.setCurrentIndex(index)
                return True
        return False


# ------------------------------------------------------------------ evidence
class EvidenceCard(QtWidgets.QFrame):
    """Leave one capture out / leave one image region out. Rows of the capture table can be clicked."""
    capture_clicked = QtCore.pyqtSignal(str)

    def __init__(self, s):
        super().__init__()
        self.setObjectName("card")
        self.tables = {}
        self.capture_ids = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Evidence: leave one out", "h2"))
        lay.addWidget(label("Fit without each capture or region, then test on the omitted data.", "muted", wrap=True))
        groups = []
        for title, records in (('Captures', s.get('leave_one_out') or []), ('Image regions', s.get('leave_one_region_out') or [])):
            if not records:
                continue
            entries = [[core.capture_display_name(x['left_out'], index) if title == 'Captures' else x['left_out'],
                        core.fmt(x['shift_px'], 2, ' px'), f"{x['heldout_existing_share'] * 100:.1f}%",
                        f"{x['heldout_refined_share'] * 100:.1f}%",
                        ('Yes', GOOD) if x['improved'] else ('No', MUTED)] for index, x in enumerate(records, 1)]
            view = table(['Left out', 'Shift', 'Before', 'After', 'Better?'], entries, numeric=(1, 2, 3), stretch=(0, 1, 2, 3, 4))
            view.setStyleSheet('QTableWidget::item { padding: 3px 7px; } QHeaderView::section { padding: 5px 7px; }')
            for index in range(len(entries)):
                view.setRowHeight(index, 28)
            view.setFixedHeight(view.horizontalHeader().height() + 28 * len(entries) + 20)
            self.tables[title] = view
            groups.append((title, view))
            if title == 'Captures':
                self.capture_ids = [x['left_out'] for x in records]
                view.setCursor(Qt.PointingHandCursor)
                view.setToolTip('Click a row to see that capture’s images.')
                view.cellClicked.connect(self._clicked)
        lay.addWidget(EvidenceColumns(groups))
        self.empty = not groups

    def _clicked(self, row, _column):
        if 0 <= row < len(self.capture_ids):
            self.capture_clicked.emit(self.capture_ids[row])


def evidence_card(s):
    """None when the run has no leave-one-out records."""
    card_ = EvidenceCard(s)
    return None if card_.empty else card_
