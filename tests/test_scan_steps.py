"""The one scan-step rule (tavi/utilities.py): a step that does not divide the range stops short, with a note.

The last point never passes the end. A step a client rounded to six significant
digits (ISAR sends %g) still reaches its end point exactly.
"""
from tavi.utilities import parse_scan_steps, scan_stop_note


def test_a_step_that_does_not_divide_stops_at_the_last_point_inside_the_range():
    name, values = parse_scan_steps("A3 0 10 4")
    assert name == "A3"
    assert list(values) == [0.0, 4.0, 8.0]
    assert scan_stop_note(0.0, 10.0, 4.0) == "Step 4 does not divide 0 to 10; the scan stops at 8."


def test_a_dividing_step_ends_exactly_on_the_end_with_no_note():
    _, values = parse_scan_steps("A3 0 10 2.5")
    assert len(values) == 5 and values[-1] == 10.0
    assert scan_stop_note(0.0, 10.0, 2.5) is None


def test_a_step_rounded_to_six_digits_still_reaches_its_end():
    _, values = parse_scan_steps("deltaE 0 10 0.0502513")
    assert len(values) == 200 and values[-1] == 10.0
    assert scan_stop_note(0.0, 10.0, 0.0502513) is None

    _, descending = parse_scan_steps("deltaE 10 0 -0.0502513")
    assert len(descending) == 200 and descending[-1] == 0.0
    assert scan_stop_note(10.0, 0.0, -0.0502513) is None


def test_rounding_to_three_decimals_never_passes_the_end():
    _, values = parse_scan_steps("A3 0 0.0016 0.0008")
    assert values[-1] <= 0.0016 and max(values) <= 0.0016

    _, descending = parse_scan_steps("A3 0.0016 0 -0.0008")
    assert descending[-1] >= 0.0 and min(descending) >= 0.0


def test_descending_ranges_stop_short_with_a_note():
    _, values = parse_scan_steps("A3 10 0 -4")
    assert list(values) == [10.0, 6.0, 2.0]
    assert scan_stop_note(10.0, 0.0, -4.0) == "Step 4 does not divide 10 to 0; the scan stops at 2."

    _, values = parse_scan_steps("A3 10 0 -2.5")
    assert values[-1] == 0.0
    assert scan_stop_note(10.0, 0.0, -2.5) is None
