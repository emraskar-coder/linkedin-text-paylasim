import logging
import sys

def setup_logging():
    """Antigravity V2 standart loglama — traceback kaybetmez."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(fmt)

    if not root.handlers:
        root.addHandler(handler)
