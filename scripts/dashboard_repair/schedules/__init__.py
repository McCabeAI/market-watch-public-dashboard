"""Per-country release schedule adapters live in sibling modules.

The integrator owns registration of country adapters into the release pipeline.
Country modules must not import each other; share types only via
``scripts.dashboard_repair.release_contract``.
"""
