"""Re-scanning a JSONL file must not duplicate or lose rows.

When Claude Code writes the same `.jsonl` in place (log compaction, crash
recovery, or simply a touched mtime with the same content), the scanner
falls through to a full rescan from offset 0. Messages use INSERT OR REPLACE
on uuid so those rows stay correct, but tool_calls has no unique key and
INSERTs blindly — so every rescan inflates tool counts.
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest

from token_dashboard.db import init_db
from token_dashboard.scanner import scan_dir


def _assistant_with_tool_use(uuid: str, msg_id: str, ts: str, output_tokens: int) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": "u1",
        "sessionId": "s1",
        "timestamp": ts,
        "isSidechain": False,
        "message": {
            "id": msg_id,
            "model": "claude-opus-4-7",
            "content": [
                {"type": "tool_use", "id": f"tu-{uuid}", "name": "Read",
                 "input": {"file_path": "foo.py"}},
            ],
            "usage": {"input_tokens": 10, "output_tokens": output_tokens},
        },
    }


def _user_record() -> dict:
    return {
        "type": "user", "uuid": "u1", "sessionId": "s1",
        "timestamp": "2026-04-10T00:00:00Z", "isSidechain": False,
        "message": {"role": "user", "content": "hi"},
    }


def _write_jsonl(path: str, records) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class RescanIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.proj_root = os.path.join(self.tmp, "projects")
        self.proj_dir = os.path.join(self.proj_root, "C--work-sample")
        os.makedirs(self.proj_dir)
        init_db(self.db)

    def _jsonl_path(self) -> str:
        return os.path.join(self.proj_dir, "s1.jsonl")

    def _count_tools(self) -> int:
        with sqlite3.connect(self.db) as c:
            return c.execute(
                "SELECT COUNT(*) FROM tool_calls WHERE tool_name='Read'"
            ).fetchone()[0]

    def test_partial_line_at_eof_is_not_skipped_on_next_scan(self):
        """A record mid-flush (no trailing newline yet) must be picked up
        on the next scan once the line completes — we cannot advance the
        byte offset past a line we haven't successfully parsed."""
        path = self._jsonl_path()

        # Scan 1: complete record A, then a partial line for record B with no
        # trailing newline (simulating Claude Code mid-flush).
        rec_a = _assistant_with_tool_use("a1", "msg_A", "2026-04-10T00:00:01Z", 10)
        partial_b = json.dumps(
            _assistant_with_tool_use("a2", "msg_B", "2026-04-10T00:00:02Z", 20)
        )
        half = len(partial_b) // 2
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(_user_record()) + "\n")
            f.write(json.dumps(rec_a) + "\n")
            f.write(partial_b[:half])  # truncated, no "\n"

        scan_dir(self.proj_root, self.db)

        with sqlite3.connect(self.db) as c:
            uuids_after_scan1 = sorted(
                r[0] for r in c.execute("SELECT uuid FROM messages")
            )
        self.assertEqual(
            uuids_after_scan1, ["a1", "u1"],
            "partial line must be skipped on first scan (JSON decode fails)",
        )

        # Scan 2: complete record B's line + append a brand-new record C.
        rec_c = _assistant_with_tool_use("a3", "msg_C", "2026-04-10T00:00:03Z", 30)
        with open(path, "a", encoding="utf-8") as f:
            f.write(partial_b[half:] + "\n")
            f.write(json.dumps(rec_c) + "\n")
        future = time.time() + 10
        os.utime(path, (future, future))

        scan_dir(self.proj_root, self.db)

        with sqlite3.connect(self.db) as c:
            uuids_after_scan2 = sorted(
                r[0] for r in c.execute("SELECT uuid FROM messages")
            )
        self.assertEqual(
            uuids_after_scan2, ["a1", "a2", "a3", "u1"],
            "record whose line was partial on scan 1 must be loaded on scan 2",
        )

    def test_rescan_with_same_content_does_not_duplicate_tool_calls(self):
        """Full rescan (mtime changed, content unchanged) must not grow tool_calls."""
        _write_jsonl(self._jsonl_path(), [
            _user_record(),
            _assistant_with_tool_use("a1", "msg_X", "2026-04-10T00:00:01Z", 42),
        ])

        scan_dir(self.proj_root, self.db)
        self.assertEqual(self._count_tools(), 1, "first scan inserts one tool_call")

        # Force mtime to move forward without changing content — triggers a
        # full rescan from offset 0 (the scan_dir "else" branch).
        future = time.time() + 10
        os.utime(self._jsonl_path(), (future, future))

        scan_dir(self.proj_root, self.db)
        self.assertEqual(
            self._count_tools(), 1,
            "rescan must not duplicate tool_calls — INSERT needs to clear per-message first",
        )

    def test_replaced_larger_file_removes_rows_from_old_content(self):
        path = self._jsonl_path()
        _write_jsonl(path, [
            _user_record(),
            _assistant_with_tool_use("a1", "msg-old", "2026-04-10T00:00:01Z", 42),
        ])
        scan_dir(self.proj_root, self.db)
        old_size = os.path.getsize(path)

        replacement = [
            {
                "type": "user", "uuid": "u2", "sessionId": "s2",
                "timestamp": "2026-04-11T00:00:00Z", "isSidechain": False,
                "message": {"role": "user", "content": "replacement " * 100},
            },
            {
                "type": "assistant", "uuid": "a2", "parentUuid": "u2",
                "sessionId": "s2", "timestamp": "2026-04-11T00:00:01Z",
                "isSidechain": False,
                "message": {
                    "id": "msg-new", "model": "gpt-5.5",
                    "usage": {"input_tokens": 20, "output_tokens": 30},
                },
            },
        ]
        _write_jsonl(path, replacement)
        self.assertGreater(os.path.getsize(path), old_size)
        future = time.time() + 10
        os.utime(path, (future, future))

        scan_dir(self.proj_root, self.db)

        with sqlite3.connect(self.db) as c:
            uuids = [row[0] for row in c.execute("SELECT uuid FROM messages ORDER BY uuid")]
            tool_count = c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
            source_paths = {row[0] for row in c.execute("SELECT source_path FROM messages")}
            content_sig = c.execute("SELECT content_sig FROM files WHERE path=?", (path,)).fetchone()[0]
        self.assertEqual(uuids, ["a2", "u2"])
        self.assertEqual(tool_count, 0)
        self.assertEqual(source_paths, {path})
        self.assertTrue(content_sig)

    def test_growing_file_with_rewritten_middle_is_fully_replaced(self):
        path = self._jsonl_path()
        records = [_user_record()]
        records.extend(
            _assistant_with_tool_use(
                f"a{i}", f"msg-{i}", f"2026-04-10T00:00:{i:02d}Z", i
            )
            for i in range(1, 40)
        )
        _write_jsonl(path, records)
        scan_dir(self.proj_root, self.db)
        self.assertEqual(self._count_tools(), 39)

        records[20]["message"]["content"] = []
        records.append(
            _assistant_with_tool_use("a40", "msg-40", "2026-04-10T00:01:00Z", 40)
        )
        _write_jsonl(path, records)
        future = time.time() + 10
        os.utime(path, (future, future))

        scan_dir(self.proj_root, self.db)

        self.assertEqual(
            self._count_tools(), 39,
            "a middle rewrite plus append must replace stale tool rows",
        )

    def test_deleted_file_removes_its_messages_and_tools(self):
        path = self._jsonl_path()
        _write_jsonl(path, [
            _user_record(),
            _assistant_with_tool_use("a1", "msg-old", "2026-04-10T00:00:01Z", 42),
        ])
        scan_dir(self.proj_root, self.db)

        os.remove(path)
        scan_dir(self.proj_root, self.db)

        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
