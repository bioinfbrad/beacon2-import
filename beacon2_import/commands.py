"""The model, stated once: two jobs, two commands.

    command          job                                            status
    beacon2-import   WRITE: load Beacon JSON into a self-hosted     current; the only way to put
                     beacon's MongoDB                               data in
    beacon2-query    READ: search one or many beacons, registered   current; the only way to
                     providers over the Beacon v2 API, or your      search
                     own beacon over MongoDB

beacon2-query replaces the 2.x beacon2-search command, removed in 3.0.0; the
README's migration section maps every 2.x option onto it.

Every --help introduction, and the README's command table, come from here.
"""

from __future__ import annotations

import argparse

#: (command, job, status). The README's table is generated from this.
COMMANDS = (
    ("beacon2-import",
     "WRITE: load Beacon JSON into a self-hosted beacon's MongoDB",
     "Current, supported. The only way to put data in."),
    ("beacon2-query",
     "READ: search one or many beacons: registered providers over the Beacon v2 API, "
     "or your own beacon over MongoDB",
     "Current, supported. The only way to search. Replaces the 2.x beacon2-search command."),
)

#: The opening lines of each command's --help. The first line states the job.
INTRO = {
    "beacon2-query": "beacon2-query \u2014 Search (read) one or many beacons: registered providers "
                     "over the Beacon v2 API, or your own beacon over MongoDB. To load data, "
                     "use beacon2-import.\n"
                     "Replaces the 2.x beacon2-search command.",
    "beacon2-import": "beacon2-import \u2014 Load (write) Beacon JSON into a self-hosted beacon's "
                      "MongoDB. To search, use beacon2-query.",
}


class IntroducedParser(argparse.ArgumentParser):
    """An ArgumentParser whose --help OPENS with the command's job.

    argparse always prints `usage:` first; this puts the statement of what the
    command is for above it, so the first thing a reader sees is the job, and
    which command does the other one. Subcommand parsers are plain
    ArgumentParsers: pass ``parser_class=argparse.ArgumentParser`` to
    add_subparsers, which otherwise reuses this class.
    """

    def __init__(self, *args, command: str, **kwargs) -> None:
        self.intro = INTRO[command]
        super().__init__(*args, **kwargs)
        # Both commands answer --version, and every Galaxy wrapper declares it as
        # its version_command. The job record then carries the version that
        # actually RAN: a stale install on PATH is the one failure mode a test
        # suite cannot see from its own results, and it has cost a planemo cycle.
        from . import __version__

        self.add_argument("--version", action="version",
                          version=f"{command} {__version__}")

    def format_help(self) -> str:
        return f"{self.intro}\n\n{super().format_help()}"
