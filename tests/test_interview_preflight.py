import unittest

from interview_preflight import scan_tracked_files


class InterviewPreflightTest(unittest.TestCase):
    def test_tracked_files_pass_sensitive_value_scan(self):
        self.assertTrue(scan_tracked_files())


if __name__ == "__main__":
    unittest.main()
