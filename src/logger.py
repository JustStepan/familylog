import sys
from loguru import logger

logger.remove()

logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>{file}</cyan> -> <cyan>{function}:{line}</cyan> | <level>{message}</level>",
    level="INFO"
)

# format="<green>{time:HH:mm:ss}</green> | <cyan>{file}</cyan> -> <cyan>{function}:{line}</cyan> | <level>{message}</level>"


logger.add(
    "logs/app.log",
    rotation="10:00",
    retention="30 days",
    compression="zip",
    level="DEBUG"
)