import unittest
from types import SimpleNamespace

from moviepos.keys import ENTER, has_modifier, key_char, shift_held


def ev(keysym="", char="", state=0):
    return SimpleNamespace(keysym=keysym, char=char, state=state)


class KeyTests(unittest.TestCase):
    def test_real_key_presses_use_their_character(self):
        self.assertEqual(key_char(ev("5", "5")), "5")
        self.assertEqual(key_char(ev("A", "A")), "A")
        self.assertEqual(key_char(ev("space", " ")), " ")
        self.assertEqual(key_char(ev("period", ".")), ".")

    def test_keys_without_a_character_fall_back_to_the_key_name(self):
        self.assertEqual(key_char(ev("KP_7")), "7")
        self.assertEqual(key_char(ev("minus")), "-")
        self.assertEqual(key_char(ev("plus")), "+")
        self.assertEqual(key_char(ev("q")), "q")

    def test_control_keys_are_not_characters(self):
        for keysym, char in (("Return", "\r"), ("Tab", "\t"), ("BackSpace", "\x08"), ("Escape", "\x1b"), ("Delete", "\x7f"), ("Up", ""), ("F1", "")):
            self.assertEqual(key_char(ev(keysym, char)), "", keysym)

    def test_modifiers(self):
        self.assertTrue(has_modifier(ev(state=0x4)))  # Ctrl
        self.assertFalse(has_modifier(ev(state=0)))
        self.assertTrue(shift_held(ev(state=0x1)))
        self.assertFalse(shift_held(ev(state=0)))
        self.assertEqual(ENTER, ("Return", "KP_Enter"))


if __name__ == "__main__":
    unittest.main()
