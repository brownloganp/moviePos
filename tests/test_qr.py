import unittest

from moviepos import qr


def read_format(m, copy):
    n = len(m)
    if copy == 0:
        coords = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    else:
        coords = [(n - 1 - i, 8) for i in range(8)] + [(8, n - 15 + i) for i in range(8, 15)]
    return sum(int(m[y][x]) << i for i, (x, y) in enumerate(coords))


class QrTests(unittest.TestCase):
    def test_size_grows_with_text(self):
        self.assertEqual(len(qr.encode("hi")), 21)  # version 1
        self.assertEqual(len(qr.encode("x" * 100)), 41)  # version 6
        self.assertEqual(len(qr.encode("x" * 213)), 57)  # version 10, full

    def test_too_long_is_rejected(self):
        with self.assertRaises(ValueError):
            qr.encode("x" * 214)

    def test_finder_patterns_and_timing(self):
        m = qr.encode("http://10.0.0.5:8080/?key=abc")
        n = len(m)
        for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
            for dy in range(7):
                for dx in range(7):
                    ring = max(abs(dx - 3), abs(dy - 3))
                    self.assertEqual(m[oy + dy][ox + dx], ring != 2, (ox, oy, dx, dy))
        for i in range(8, n - 8):
            self.assertEqual(m[6][i], i % 2 == 0)
            self.assertEqual(m[i][6], i % 2 == 0)
        self.assertTrue(m[n - 8][8])  # the always-dark module

    def test_format_information_is_valid_and_duplicated(self):
        m = qr.encode("http://10.0.0.5:8080/?key=abc")
        first, second = read_format(m, 0), read_format(m, 1)
        self.assertEqual(first, second)
        valid = {}
        for data in range(32):
            rem = data
            for _ in range(10):
                rem = (rem << 1) ^ ((rem >> 9) * 0x537)
            valid[(data << 10 | rem) ^ 0x5412] = data
        self.assertIn(first, valid)
        self.assertEqual(valid[first] >> 3, 0)  # error correction level M

    def test_deterministic(self):
        self.assertEqual(qr.encode("same"), qr.encode("same"))
        self.assertNotEqual(qr.encode("same"), qr.encode("diff"))


if __name__ == "__main__":
    unittest.main()
