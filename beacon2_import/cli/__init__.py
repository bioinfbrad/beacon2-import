"""Command entry points: main.py is beacon2-query (READ), import_command.py is beacon2-import (WRITE).

These modules hold argparse wiring and nothing else. All logic lives below, so
that the same behaviour is reachable from a script, a notebook or a test
without going through a command line.
"""
