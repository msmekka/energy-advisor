"""etdc -- energy-time decoupling.

Tooling for finding code where energy cost and elapsed time come apart.
Deliberately empty: importing a submodule must not drag in siblings, since a
benchmark child process imports etdc.rig.rapl inside a measured window.
"""
