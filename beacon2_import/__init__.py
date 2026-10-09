"""beacon2-import: load (write) Beacon JSON into a self-hosted beacon's MongoDB, and search (read) one or many beacons.

Two jobs, two commands (the model is stated once, in commands.py):

    beacon2-import   WRITE  load Beacon JSON into a self-hosted beacon's MongoDB
    beacon2-query    READ   search registered providers over the Beacon v2 API,
                            or your own beacon over MongoDB

beacon2-query replaces the 2.x beacon2-search command, removed in 3.0.0.

The package is called beacon2-import because it began as the import tool;
renaming it would break the PyPI project, the Bioconda recipe and every Galaxy
requirement pin.

Layering (strictly downward; no upward imports):

    cli/         argparse surface, one module per Galaxy tool
    query/       provider-agnostic query model, term expansion, planning
    adapters/    per-STACK dialect translation (spec, bycon, b2pi)
    transport/   HTTP + rate limiting; MongoDB; file:// fixtures for tests
    normalise/   heterogeneous responses -> one tabular schema
    analysis/    segments, statistics, frequency, matrix
    plotting/    figures
    formats/     on-disk formats and the outcomes report
"""

__version__ = "3.0.0"
