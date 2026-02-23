"""
Sentiment scoring — thin wrapper around vaderSentiment.

Replaces the former TextBlob dependency (which pulled in NLTK, CVE-2025-14009).
VADER is rule-based, requires no corpus downloads, and produces a compound
score in [-1, 1] that is directly comparable to TextBlob's polarity range.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


def sentiment_score(text: str) -> float:
    """Return a sentiment polarity score in [-1.0, 1.0].

    Args:
        text: Input text to analyse.

    Returns:
        VADER compound score: -1 (most negative) … 0 (neutral) … 1 (most positive).
        Returns 0.0 for empty or non-string input.
    """
    if not text or not isinstance(text, str):
        return 0.0
    return float(_analyzer.polarity_scores(text)["compound"])
