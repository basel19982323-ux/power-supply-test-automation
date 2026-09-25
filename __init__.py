"""Dynamic Load Test — desktop application package.

A PySide6 desktop app that automates bench instrument test sequences. The first
built-in test type is the USB-C PD "Dynamic Output Response" test, but the core
is a pluggable TestType framework so new tests slot in without touching the GUI.
"""

__version__ = "0.1.0"
