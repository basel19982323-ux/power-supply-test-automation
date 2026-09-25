"""Put the application root on sys.path so tests import the top-level packages
(core, testtypes, reporting) the same way the app does."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
