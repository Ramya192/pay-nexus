"""
A confidence-gated logistic regression tier, inserted between rules.py's
keyword match and categorize.py's LLM fallback.

**Why this doesn't persist a model, and why that's deliberate, not a
shortcut**: PayNexus's bank-statement data is ciphertext-only at rest (see
db/models.py's docstring) — the server never retains a user's plaintext
transaction history, so it has nothing durable to train a per-user model
from. categorize.py's own docstring already documents that a sister
project's online-learning classifier was deliberately NOT ported here for
exactly this reason (no persistence pattern, and a fresh model has nothing
to learn from at cold start).

The design that actually works within that constraint: the FRONTEND already
holds the user's own decrypted transaction history in its own store (it has
to, to render the UI) — so it sends a sample of that history's
(description, category) pairs alongside each new categorization request.
This function fits a model from that data, uses it immediately, and returns
— the model and vectorizer are local variables, garbage collected the
moment this call returns. Nothing about this changes PayNexus's storage
contract: the server already handles plaintext transaction descriptions
transiently during parsing (see statement.py's own "plaintext in, plaintext
out, nothing persisted" comment) — this reuses that exact trust boundary,
just with more plaintext in the same already-transient request.
"""

from __future__ import annotations

from sklearn.exceptions import NotFittedError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

# Below this many labeled examples, or with only one distinct category
# represented, a freshly-fit model is more likely to overfit noise than
# generalize -- skip the tier entirely rather than return a confident-looking
# but meaningless prediction. Both thresholds are conservative starting
# points, not tuned against real usage data (there isn't any yet).
MIN_TRAINING_EXAMPLES = 20
MIN_DISTINCT_CATEGORIES = 2

# Below this predicted probability, the model itself isn't confident enough
# to trust over the (slower, costlier, but generally reliable) LLM fallback.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


def predict_categories(
    descriptions: list[str],
    historical_labels: list[tuple[str, str]],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[tuple[str | None, float]]:
    """Returns one (category, confidence) pair per input description, in
    order. `category` is None (confidence 0.0) whenever the tier should be
    skipped for that row -- either because there isn't enough historical
    data to train on at all, or because this specific prediction fell below
    `confidence_threshold`. A None here means "fall through to the LLM
    tier," exactly like a rules.py miss does today.
    """
    if not descriptions:
        return []

    distinct_categories = {category for _, category in historical_labels}
    if len(historical_labels) < MIN_TRAINING_EXAMPLES or len(distinct_categories) < MIN_DISTINCT_CATEGORIES:
        return [(None, 0.0) for _ in descriptions]

    # char_wb n-grams (not word-level) deliberately -- transaction
    # descriptions are short, noisy, and often have no natural word
    # boundaries in the useful part ("SWIGGY*ORDR8817X2"), so character
    # subsequences generalize better than whole-word matching here. Same
    # underlying intuition as rules.py's substring match, generalized into
    # a trainable model instead of a fixed keyword list.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    historical_descriptions = [d for d, _ in historical_labels]
    historical_categories = [c for _, c in historical_labels]

    try:
        X_train = vectorizer.fit_transform(historical_descriptions)
        model = LogisticRegression(max_iter=1000)
        model.fit(X_train, historical_categories)
        X_predict = vectorizer.transform(descriptions)
        probabilities = model.predict_proba(X_predict)
    except (ValueError, NotFittedError):
        # A real but rare edge case (e.g. every historical description is
        # identical, or some other degenerate input) -- fail safe to "skip
        # this tier" rather than let an unexpected sklearn error surface as
        # a 500 on what's meant to be an optional optimization, not a
        # required step.
        return [(None, 0.0) for _ in descriptions]

    results: list[tuple[str | None, float]] = []
    for row in probabilities:
        best_index = row.argmax()
        best_confidence = float(row[best_index])
        best_category = model.classes_[best_index]
        if best_confidence >= confidence_threshold:
            results.append((best_category, best_confidence))
        else:
            results.append((None, best_confidence))
    return results
