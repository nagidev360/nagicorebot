import unittest
import games

class GameTests(unittest.TestCase):
    def test_coinflip_values(self):
        self.assertIn(games.coinflip(), ("Heads", "Tails"))

    def test_slots_have_three_symbols(self):
        result = games.slots()
        self.assertEqual(len(result), 3)
        self.assertTrue(all(isinstance(x, str) for x in result))

    def test_dice_range(self):
        self.assertIn(games.dice(), range(1, 7))

    def test_rps_values(self):
        self.assertIn(games.rps(), ("rock", "paper", "scissors"))

    def test_guess_range(self):
        self.assertIn(games.guess_number(), range(1, 11))

    def test_wheel_multipliers(self):
        self.assertIn(games.wheel(), (0, 0.5, 1, 1.5, 2, 3, 5))

if __name__ == "__main__":
    unittest.main()
