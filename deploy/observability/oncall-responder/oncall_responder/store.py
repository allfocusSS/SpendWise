"""The report store: a bounded JSONL file, rewritten whole after every change.

At most `keep` reports, each at most MAX_REPORT bytes and all together at most `max_bytes`,
newest last. A report for an incident already stored (same report_id) replaces it. It lives on a
small tmpfs in Compose (room for two copies of the file, as every save writes a new one beside
the old), so it is gone with the container. This file is the only thing the responder writes.
"""

import json
from collections import OrderedDict
from pathlib import Path

from oncall_responder.report import MAX_REPORT

KEEP = 100
MAX_BYTES = 1024 * 1024


class ReportTooLarge(ValueError):
    pass


class ReportStore:
    def __init__(self, path: Path, keep: int = KEEP, max_bytes: int = MAX_BYTES) -> None:
        self.path = path
        self.keep = keep
        self.max_bytes = max_bytes
        self.reports: OrderedDict[str, dict] = OrderedDict()
        self.save()

    def put(self, report: dict) -> None:
        line = encode(report)
        if len(line) > MAX_REPORT:
            raise ReportTooLarge
        self.reports.pop(report["report_id"], None)
        self.reports[report["report_id"]] = report
        while len(self.reports) > self.keep or (
            len(self.reports) > 1 and self.size() > self.max_bytes
        ):
            self.reports.popitem(last=False)
        self.save()

    def size(self) -> int:
        return sum(len(encode(report)) + 1 for report in self.reports.values())

    def save(self) -> None:
        partial = self.path.with_suffix(".partial")
        partial.write_text("".join(encode(r).decode() + "\n" for r in self.reports.values()))
        partial.replace(self.path)


def encode(report: dict) -> bytes:
    return json.dumps(report, sort_keys=True, ensure_ascii=True).encode()
