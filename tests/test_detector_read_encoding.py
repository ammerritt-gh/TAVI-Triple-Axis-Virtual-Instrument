"""McStas writes the save-folder path into detector.dat's header in the Windows
ANSI code page (cp1252 on German and French machines). The reader must still
return the numbers, whatever bytes the header carries."""
from tavi.data_processing import read_1Ddetector_file

# Escapes keep this source ASCII: u-umlaut (0xfc) and sharp s (0xdf) in cp1252.
HEADER = "# Directory: C:\\M\u00fcller_Stra\u00dfe\n"
BODY = "# variables: I I_err N\n1.5 0.25 400\n"
EXPECTED = (1.5, 0.25, 400.0)


def _scan_folder(tmp_path, header_bytes):
    folder = tmp_path / "scan_0000"
    folder.mkdir()
    (folder / "detector.dat").write_bytes(header_bytes + BODY.encode("ascii"))
    return str(folder)


def test_cp1252_header_path_reads_numbers(tmp_path):
    folder = _scan_folder(tmp_path, HEADER.encode("cp1252"))
    assert read_1Ddetector_file(folder) == EXPECTED


def test_utf8_header_path_reads_same(tmp_path):
    folder = _scan_folder(tmp_path, HEADER.encode("utf-8"))
    assert read_1Ddetector_file(folder) == EXPECTED
