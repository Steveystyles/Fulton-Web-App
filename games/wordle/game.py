import json
import random
from functools import lru_cache
from pathlib import Path

WORD_LENGTH = 5
MAX_ATTEMPTS = 6
WORDLE_DIR = Path(__file__).resolve().parent
USED_WORDS_FILE = WORDLE_DIR / "used_words.txt"
WORD_LIST_FILE = WORDLE_DIR / "wordle_words.txt"
WORDLE_RATINGS_FILE = WORDLE_DIR / "wordle_difficulty_ratings.json"
MIN_WORDLE_DIFFICULTY = 1
MAX_WORDLE_DIFFICULTY = 20


@lru_cache(maxsize=1)
def _cached_word_list() -> tuple[str, ...]:
    """Load and normalize the immutable Wordle dictionary once per process."""
    try:
        words = [
            line.strip().lower()
            for line in WORD_LIST_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as error:
        raise RuntimeError(f"Word list file not found: {WORD_LIST_FILE}") from error

    return tuple(
        sorted(
            {
            word
            for word in words
            if len(word) == WORD_LENGTH and word.isalpha() and word.isascii()
            }
        )
    )


def load_word_list() -> list[str]:
    """Return a compatibility copy of the cached five-letter dictionary."""
    return list(_cached_word_list())


@lru_cache(maxsize=1)
def valid_word_set() -> frozenset[str]:
    """Return the cached dictionary optimized for request-path membership checks."""
    return frozenset(_cached_word_list())


@lru_cache(maxsize=1)
def load_word_difficulty_ratings() -> dict[str, int]:
    """Return the answer-word difficulty map used for streak-based selection."""
    try:
        payload = json.loads(WORDLE_RATINGS_FILE.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(
            f"Word difficulty ratings file not found: {WORDLE_RATINGS_FILE}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Word difficulty ratings file is invalid JSON: {WORDLE_RATINGS_FILE}"
        ) from error

    raw_ratings = payload.get("ratings")
    if not isinstance(raw_ratings, dict):
        buckets = payload.get("buckets")
        if isinstance(buckets, dict):
            raw_ratings = {}
            for level, words in buckets.items():
                if not isinstance(words, list):
                    continue
                for word in words:
                    raw_ratings[str(word)] = level

    if not isinstance(raw_ratings, dict):
        raise RuntimeError(
            f"Word difficulty ratings file has no ratings or buckets map: {WORDLE_RATINGS_FILE}"
        )

    normalized: dict[str, int] = {}
    for raw_word, raw_rating in raw_ratings.items():
        word = str(raw_word).strip().lower()
        try:
            rating = int(raw_rating)
        except (TypeError, ValueError):
            continue
        if (
            len(word) == WORD_LENGTH
            and word.isalpha()
            and word.isascii()
            and MIN_WORDLE_DIFFICULTY <= rating <= MAX_WORDLE_DIFFICULTY
        ):
            normalized[word] = rating

    if not normalized:
        raise RuntimeError(
            f"Word difficulty ratings file has no usable entries: {WORDLE_RATINGS_FILE}"
        )

    return normalized


@lru_cache(maxsize=1)
def available_difficulty_levels() -> tuple[int, ...]:
    """Return every difficulty value that has at least one answer word."""
    return tuple(sorted(set(load_word_difficulty_ratings().values())))


@lru_cache(maxsize=1)
def answer_words_by_difficulty() -> dict[int, tuple[str, ...]]:
    """Group answer words by difficulty level."""
    grouped: dict[int, list[str]] = {}
    for word, level in sorted(load_word_difficulty_ratings().items()):
        grouped.setdefault(level, []).append(word)
    return {level: tuple(words) for level, words in grouped.items()}


def load_answer_words() -> list[str]:
    """Return the curated answer words used for daily secret selection."""
    return sorted(load_word_difficulty_ratings())


def difficulty_for_streak(streak: int) -> int:
    """Map a correct-solve streak to the next available difficulty bucket."""
    target = max(
        MIN_WORDLE_DIFFICULTY,
        min(MAX_WORDLE_DIFFICULTY, int(streak) + 1),
    )
    for level in available_difficulty_levels():
        if level >= target:
            return level
    return available_difficulty_levels()[-1]


def preferred_difficulty_levels(target_difficulty: int) -> tuple[int, ...]:
    """Prefer the target bucket and then progressively easier fallback levels."""
    target = difficulty_for_streak(target_difficulty - 1)
    levels = available_difficulty_levels()
    higher_or_equal = [level for level in levels if level >= target]
    lower = [level for level in reversed(levels) if level < target]
    return tuple(higher_or_equal + lower)


def choose_secret_for_difficulty(
    target_difficulty: int,
    used_words: set[str] | None = None,
) -> tuple[str, int]:
    """Choose an unused answer word from the target difficulty band or nearest harder pool."""
    normalized_used = {word.lower() for word in used_words or set()}
    grouped_words = answer_words_by_difficulty()

    for level in preferred_difficulty_levels(target_difficulty):
        candidates = [
            word
            for word in grouped_words.get(level, ())
            if word not in normalized_used
        ]
        if candidates:
            return random.choice(candidates), level

    if normalized_used:
        return choose_secret_for_difficulty(target_difficulty, set())

    raise RuntimeError("No Wordle answer words are available for selection.")


def load_used_words() -> set[str]:
    """Read the local used-word tracker stored beside this file."""
    if not USED_WORDS_FILE.exists():
        return set()

    try:
        return {
            line.strip().lower()
            for line in USED_WORDS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError:
        return set()


def reset_used_words() -> None:
    """Reset the local used-word tracker after the word list is exhausted."""
    try:
        USED_WORDS_FILE.write_text("", encoding="utf-8")
    except OSError:
        pass


def save_used_word(word: str) -> None:
    """Append a selected secret word to the local used-word tracker."""
    try:
        with USED_WORDS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{word.lower()}\n")
    except OSError:
        pass


def choose_secret(
    words: list[str] | None = None,
    extra_used_words: set[str] | None = None,
    include_local_used: bool = True,
) -> str:
    """Choose a secret word that has not already been used in the current cycle."""
    word_list = words if words is not None else load_word_list()
    local_used_words = load_used_words() if include_local_used else set()
    used_words = local_used_words | {word.lower() for word in extra_used_words or set()}
    unused_words = [word for word in word_list if word not in used_words]

    if not unused_words:
        reset_used_words()
        unused_words = word_list[:]

    secret = random.choice(unused_words)
    save_used_word(secret)
    return secret


def compute_feedback(secret: str, guess: str) -> list[tuple[str, str]]:
    """Return Wordle feedback tuples of (letter, color) for a submitted guess."""
    normalized_secret = secret.lower()
    normalized_guess = guess.lower()
    secret_unmatched: list[str] = []
    guess_unmatched: list[tuple[int, str]] = []
    colors: list[str | None] = [None] * len(normalized_secret)

    for index, (secret_letter, guess_letter) in enumerate(
        zip(normalized_secret, normalized_guess)
    ):
        if guess_letter == secret_letter:
            colors[index] = "green"
        else:
            secret_unmatched.append(secret_letter)
            guess_unmatched.append((index, guess_letter))

    for index, guess_letter in guess_unmatched:
        if guess_letter in secret_unmatched:
            colors[index] = "yellow"
            secret_unmatched.remove(guess_letter)
        else:
            colors[index] = "grey"

    return [
        (normalized_guess[index], colors[index] or "grey")
        for index in range(len(normalized_guess))
    ]


def serialize_feedback(feedback: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Convert feedback tuples into JSON-friendly dictionaries."""
    return [{"letter": letter, "color": color} for letter, color in feedback]


def valid_guess(guess: str, words: list[str] | None = None) -> bool:
    """Return True if the guess is a valid five-letter word from the word list."""
    word_list = words if words is not None else valid_word_set()
    normalized_guess = guess.lower()
    return (
        normalized_guess.isalpha()
        and len(normalized_guess) == WORD_LENGTH
        and normalized_guess in word_list
    )


def print_feedback(feedback: list[tuple[str, str]]) -> None:
    """Print compact terminal feedback for local manual testing."""
    symbols = {"green": "G", "yellow": "Y", "grey": "-"}
    print(" ".join(f"{letter.upper()}:{symbols[color]}" for letter, color in feedback))


def play_game() -> None:
    """Run a local single-player Wordle session without user accounts."""
    words = load_word_list()
    secret = choose_secret(words)
    attempts_remaining = MAX_ATTEMPTS

    print("\nWordle local test mode")
    print(f"You have {MAX_ATTEMPTS} attempts to guess the five-letter word.\n")

    while attempts_remaining > 0:
        attempt_number = MAX_ATTEMPTS - attempts_remaining + 1
        guess = input(f"Attempt {attempt_number}/{MAX_ATTEMPTS}: ").strip().lower()

        if not valid_guess(guess, words):
            print("Enter a valid five-letter word from the game list.")
            continue

        attempts_remaining -= 1
        feedback = compute_feedback(secret, guess)
        print_feedback(feedback)

        if all(color == "green" for _, color in feedback):
            print(f"\nCorrect. The word was {secret.upper()}.")
            return

    print(f"\nOut of guesses. The word was {secret.upper()}.")


if __name__ == "__main__":
    try:
        play_game()
    except KeyboardInterrupt:
        print("\nGame aborted.")
