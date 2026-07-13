from __future__ import annotations

import unittest

import wordle_game


class WordleGameDifficultyTests(unittest.TestCase):
    def tearDown(self) -> None:
        wordle_game.load_word_difficulty_ratings.cache_clear()
        wordle_game.available_difficulty_levels.cache_clear()
        wordle_game.answer_words_by_difficulty.cache_clear()

    def test_answer_pool_comes_from_ratings_file(self) -> None:
        words = wordle_game.load_answer_words()

        self.assertEqual(len(words), 2315)
        self.assertEqual(words[0], "aback")
        self.assertEqual(words[-1], "zonal")

    def test_difficulty_for_streak_uses_populated_twenty_level_scale(self) -> None:
        self.assertEqual(wordle_game.difficulty_for_streak(0), 1)
        self.assertEqual(wordle_game.difficulty_for_streak(1), 2)
        self.assertEqual(wordle_game.difficulty_for_streak(2), 3)
        self.assertEqual(wordle_game.difficulty_for_streak(5), 6)
        self.assertEqual(wordle_game.difficulty_for_streak(19), 20)
        self.assertEqual(wordle_game.difficulty_for_streak(150), 20)

    def test_choose_secret_for_difficulty_moves_up_when_bucket_is_exhausted(self) -> None:
        bucket_four_words = set(wordle_game.answer_words_by_difficulty()[4])
        bucket_five_words = set(wordle_game.answer_words_by_difficulty()[5])

        word, level = wordle_game.choose_secret_for_difficulty(
            4,
            bucket_four_words,
        )

        self.assertEqual(level, 5)
        self.assertIn(word, bucket_five_words)


if __name__ == "__main__":
    unittest.main()
