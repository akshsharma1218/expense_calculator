import json
import logging


class ContextAwareFormatter(logging.Formatter):
    """Append non-standard LogRecord attributes as structured context."""

    _RESERVED_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
        "message",
        "asctime",
    }

    def format(self, record):
        rendered = super().format(record)

        context = {}
        for key, value in record.__dict__.items():
            if key in self._RESERVED_KEYS or key.startswith("_"):
                continue
            context[key] = value

        if not context:
            return rendered

        return f"{rendered} | ctx={json.dumps(context, default=str, sort_keys=True, ensure_ascii=True)}"