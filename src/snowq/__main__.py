"""Support ``python -m snowq``.

Useful where a package index is unreachable and the ``snowq`` console
script cannot be installed: set ``PYTHONPATH=src`` and run this module
against any Python that already has ``requests``.
"""

import sys

from snowq.cli import main

if __name__ == "__main__":
    sys.exit(main())
