import json
from pathlib import Path
from config.logger_setup import setup_logger

logger = setup_logger()

def load_invoices(json_file_path: str):
    path = Path(json_file_path)
    if not path.is_file():
        logger.error("JSON file not found: %s", json_file_path)
        return []

    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        invoices = data.get("valid_invoices", [])
        if not invoices:
            logger.warning("No valid invoices found in JSON file: %s", json_file_path)
        return invoices
    except Exception as e:
        logger.error("Failed to read JSON file '%s': %s", json_file_path, e)
        return []