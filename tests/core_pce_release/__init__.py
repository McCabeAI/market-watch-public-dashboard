"""unittest discovery for core PCE release tests."""

from __future__ import annotations

import pathlib
import unittest


def load_tests(loader: unittest.TestLoader, standard_tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    start_dir = pathlib.Path(__file__).resolve().parent
    return loader.discover(str(start_dir), pattern="test_*.py")
