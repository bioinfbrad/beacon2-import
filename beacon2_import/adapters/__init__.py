"""Search engine behind beacon2-query (READ): dialect adapters, one per STACK -- never one per provider.

Three adapters cover every provider we ship. Adding a provider that runs an
existing stack is a registry row, not code. This is the "never one tool per
provider" rule applied one level down.
"""
