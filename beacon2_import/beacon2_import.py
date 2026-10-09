"""Compatibility only: the 2.2.4 import path of the `beacon2-import` entry point.

`beacon2_import.beacon2_import:beacon2_import` is what 2.2.4's entry point and
its Bioconda recipe named, so the coverage rule keeps it importable. It is not
the entry point: `beacon2-import` runs beacon2_import.cli.import_command, and
the write path itself is beacon2_import.importer.
"""

from .importer.importer import beacon2_import  # noqa: F401
