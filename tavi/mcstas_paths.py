"""The output-folder path McStas receives, and the refusal when none is usable.

McStasScript runs mcrun as one shell line (shell=True) and the direct run passes
--dir= to the binary, so a folder with a space, a character outside the Windows
code page, or a cmd.exe metacharacter cannot go to McStas as typed. Windows 8.3
short names avoid the first two; the metacharacters survive into short names, so
they are refused too. Qt-free.
"""
import ctypes
import os
import sys

SHELL_METACHARACTERS = "&^%"


def _short_path(path):
    """Windows 8.3 short name of an existing path; the long path where none exists."""
    if sys.platform != "win32":
        return path
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.GetShortPathNameW.restype = ctypes.c_uint32
    size = kernel32.GetShortPathNameW(path, None, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size)
        size = kernel32.GetShortPathNameW(path, buffer, size)
    if not size:
        print(f"TAVI: Windows gave no short name for {path}: {ctypes.FormatError(ctypes.get_last_error())}")
        return path
    return buffer.value


def _ansi_encoding():
    """The Windows code page McStas writes in (not the UTF-8 mode-dependent locale)."""
    if sys.platform != "win32":
        return "utf-8"
    return f"cp{ctypes.WinDLL('kernel32').GetACP()}"


def offending_characters(path):
    """Distinct characters that stop McStas taking the path: 'space' for a space, then the rest in first-seen order."""
    encoding = _ansi_encoding()
    found = []
    for char in path:
        if char == " ":
            item = "space"
        elif char in SHELL_METACHARACTERS:
            item = char
        else:
            try:
                char.encode(encoding)
                continue
            except UnicodeEncodeError:
                item = char
        if item not in found:
            found.append(item)
    return found


def is_mcstas_safe(path):
    return not offending_characters(path)


def mcstas_path(path):
    """The form of an output folder McStas receives, or None when no safe form exists. Never touches the folder."""
    if path.isascii() and " " not in path and not any(c in SHELL_METACHARACTERS for c in path):
        return path
    if os.path.exists(path):
        form = _short_path(path)
    else:
        # A point folder McStas creates itself: shorten its existing parent and keep its leaf.
        parent, leaf = os.path.split(path)
        form = os.path.join(_short_path(parent), leaf)
    return form if is_mcstas_safe(form) else None


def _join_words(words):
    return ", ".join(words[:-1]) + ", and " + words[-1] if len(words) > 2 else " and ".join(words)


def refusal_message(folder):
    """The one text TAVI shows, logs and records when a save folder has no safe McStas form."""
    items = offending_characters(folder)
    words = []
    if "space" in items:
        words.append("spaces")
    words.extend(f"the {c} sign" for c in items if c in SHELL_METACHARACTERS)
    chars = [c for c in items if c != "space" and c not in SHELL_METACHARACTERS]
    if chars:
        words.append(("the character " if len(chars) == 1 else "the characters ") + _join_words(chars))
    drive = os.path.splitdrive(folder)[0] or "this drive"
    # A metacharacter is refused on every drive, so neither the drive nor a move to C: helps.
    any_drive = any(c in SHELL_METACHARACTERS for c in items)
    where = "" if any_drive else f" on drive {drive}"
    if any_drive or drive.upper() == "C:":
        advice = "Rename the folder (and the folders above it) without spaces or special characters."
    else:
        advice = ("Rename the folder (and the folders above it) without spaces or special characters, "
                  "or choose a save folder on the C: drive.")
    return (
        "TAVI cannot save this scan in the folder\n"
        f"    {folder}\n"
        f"McStas, the simulation program, cannot use a folder path containing {_join_words(words)}"
        f"{where}.\n"
        f"{advice}"
    )
