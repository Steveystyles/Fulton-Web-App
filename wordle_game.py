import random
from pathlib import Path

WORD_LENGTH = 5
MAX_ATTEMPTS = 6
WORDLE_DIR = Path(__file__).resolve().parent
USED_WORDS_FILE = WORDLE_DIR / "used_words.txt"
WORD_LIST_FILE = WORDLE_DIR / "wordle_words.txt"


def load_word_list() -> list[str]:
    """Return the valid five-letter words used by the daily game."""
    try:
        words = [
            line.strip().lower()
            for line in WORD_LIST_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as error:
        raise RuntimeError(f"Word list file not found: {WORD_LIST_FILE}") from error

    return sorted(
        {
            word
            for word in words
            if len(word) == WORD_LENGTH and word.isalpha() and word.isascii()
        }
    )


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
    word_list = words if words is not None else load_word_list()
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
