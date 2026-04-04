# logger_setup.py
import logging

LOG_FILE = "logs/app.log"

# Basic config is global
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def get_logger(name: str = None) -> logging.Logger:
    """
    Returns a logger with the specified name.
    If no name is provided, uses the caller module's __name__.
    """
    import inspect
    if name is None:
        # Get the calling module's name
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        name = module.__name__ if module else "__main__"
    return logging.getLogger(name)