"""The routine run leaves installer-marked tests out unless asked (conftest.installer_tests_wanted)."""
from conftest import installer_tests_wanted


def test_routine_run_leaves_installer_tests_out():
    assert not installer_tests_wanted(["tests"], False)
    assert not installer_tests_wanted(["tests/test_tas_geometry.py"], False)


def test_flag_includes_installer_tests():
    assert installer_tests_wanted(["tests"], True)


def test_naming_the_installer_file_includes_it():
    assert installer_tests_wanted(["tests/test_installer_launchers.py"], False)
    assert installer_tests_wanted(["tests", "tests/test_installer_launchers.py"], False)
    assert installer_tests_wanted(["tests/test_installer_launchers.py::test_x"], False)
    assert installer_tests_wanted([r"C:\repo\tests\test_installer_launchers.py"], False)
