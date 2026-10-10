"""Secretary's backend services and API routers."""

import os

from logging_config import setup_logging

# In production, systemd provides environment variables.
if os.getenv("ENVIRONMENT") != "production":
    from dotenv import load_dotenv

    load_dotenv()

setup_logging()
