"""Pytest configuration for shared config tests.

This conftest ensures the tests can be discovered and run from within
the Docker container where the shared module is mounted at /app/shared.
"""

import sys
from pathlib import Path

# Ensure shared module can be imported
# When running in Docker, /app/shared is the shared module root
shared_dir = Path(__file__).parent.parent.parent
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))
