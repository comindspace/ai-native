import tempfile
import unittest
from pathlib import Path

from agent_platform.validation import _files_equal


class ValidationTests(unittest.TestCase):
    def test_text_comparison_ignores_only_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left.txt"
            right = root / "right.txt"
            left.write_bytes(b"first\r\nsecond\r\n")
            right.write_bytes(b"first\nsecond\n")

            self.assertTrue(_files_equal(left, right))

            right.write_bytes(b"first\nchanged\n")
            self.assertFalse(_files_equal(left, right))


if __name__ == "__main__":
    unittest.main()
