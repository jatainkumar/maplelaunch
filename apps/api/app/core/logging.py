"""Structured logging with automatic PII redaction."""

import logging

import structlog

from app.core.crypto import redact_obj


def _redact(_, __, event_dict):
    return redact_obj(event_dict)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


log = structlog.get_logger("maplelaunch")
