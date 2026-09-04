"""
Surfaces responses that more than one registered inverter schema accepts.

An ambiguous response is not automatically a bug to be fixed. These
schemas are reverse-engineered from observed payloads -- Solax publishes
neither a protocol spec nor a model-identifying field -- so some models
are genuinely indistinguishable from a single response, and no amount of
schema tightening changes that. discover() reflects this by returning
every model that matched and letting the caller resolve it.

What this module enforces is that ambiguity stays *documented*:
collisions we've concluded are inherent go in KNOWN_INHERENT_COLLISIONS,
and any collision outside that list fails, since an undocumented one is
most likely a schema that drifted too permissive (see
test_schema_strictness.py for the structural invariants that prevent
that). test_no_stale_known_collisions guards the other direction, so a
collision that later becomes resolvable doesn't linger on the list.

Also runnable standalone to print inverter schemas ranked from most to
least permissive:

    python -m tests.test_schema_ambiguity
"""

from collections import defaultdict

import pytest
import voluptuous as vol
from voluptuous import Invalid, MultipleInvalid

import solaxng.inverters as inverter
from solaxng.discovery import REGISTRY
from solaxng.response_parser import GENERIC_RESPONSE_SCHEMA
from tests import fixtures

# Sets of inverter models whose schemas accept each other's responses and
# that we've concluded cannot be told apart from a single payload. Each
# entry is the *complete* match set a response produces. Adding an entry
# is a decision that the collision is inherent rather than a
# too-permissive schema -- prefer tightening the schema first; use
# `python -m tests.test_schema_ambiguity` to see which side is permissive.
KNOWN_INHERENT_COLLISIONS = frozenset(
    {
        frozenset({inverter.X1Boost, inverter.X1MiniV34}),
        frozenset({inverter.QVOLTHYBG33P, inverter.X3HybridG4}),
    }
)


def _matching_inverters(response):
    normalized = {key.lower(): value for key, value in response.items()}
    matches = set()
    for inverter_class in REGISTRY:
        combined_schema = vol.And(GENERIC_RESPONSE_SCHEMA, inverter_class.schema())
        try:
            combined_schema(dict(normalized))
        except (Invalid, MultipleInvalid):
            continue
        matches.add(inverter_class)
    return matches


def _permissiveness_scores():
    """
    Count, for each inverter class, how many fixture responses (belonging
    to any inverter) its schema accepts. A schema that accepts more
    unrelated responses is less specific (more permissive) than one that
    accepts fewer.
    """
    scores = defaultdict(int)
    for case in fixtures.INVERTERS_UNDER_TEST:
        for inverter_class in _matching_inverters(case.response):
            scores[inverter_class] += 1
    return scores


_PERMISSIVENESS_SCORES = _permissiveness_scores()


def _most_permissive_first(inverter_classes):
    return sorted(
        inverter_classes,
        key=lambda c: (-_PERMISSIVENESS_SCORES[c], c.__name__),
    )


def _observed_collisions():
    return {
        frozenset(matches)
        for case in fixtures.INVERTERS_UNDER_TEST
        for matches in [_matching_inverters(case.response)]
        if len(matches) > 1
    }


@pytest.mark.parametrize(
    "case",
    fixtures.INVERTERS_UNDER_TEST,
    ids=[
        f"{i}-{case.inverter.__name__}"
        for i, case in enumerate(fixtures.INVERTERS_UNDER_TEST)
    ],
)
def test_response_is_unambiguous_or_a_known_collision(case):
    matches = _matching_inverters(case.response)
    if matches == {case.inverter}:
        return

    names = sorted(c.__name__ for c in matches)
    literal = ", ".join(f"inverter.{name}" for name in names)
    assert frozenset(matches) in KNOWN_INHERENT_COLLISIONS, (
        f"{case.inverter.__name__}'s response also validated against "
        f"{[c.__name__ for c in _most_permissive_first(matches - {case.inverter})]} "
        "(most to least permissive), and this collision isn't documented. "
        "Tighten the permissive schema -- see test_schema_strictness.py -- "
        "or, if these models genuinely cannot be told apart from one "
        f"response, record it in KNOWN_INHERENT_COLLISIONS as "
        f"frozenset({{{literal}}})"
    )


def test_no_stale_known_collisions():
    """
    Every documented collision must still be observable. If a schema gets
    tightened enough to resolve one, its entry has to go, so the list
    stays an accurate record of what's actually indistinguishable rather
    than accumulating collisions nothing produces anymore.
    """
    stale = KNOWN_INHERENT_COLLISIONS - _observed_collisions()
    assert not stale, (
        "these collisions no longer occur in any fixture; remove them "
        "from KNOWN_INHERENT_COLLISIONS: "
        f"{[sorted(c.__name__ for c in entry) for entry in stale]}"
    )


def _print_permissiveness_ranking():
    ambiguous = [c for c in REGISTRY if _PERMISSIVENESS_SCORES[c] > 1]
    ordered = _most_permissive_first(ambiguous)
    width = max(len(c.__name__) for c in ordered)
    for rank, inverter_class in enumerate(ordered, start=1):
        name = inverter_class.__name__
        matches = _PERMISSIVENESS_SCORES[inverter_class]
        print(f"{rank:>2}. {name:<{width}}  matches={matches}")


if __name__ == "__main__":
    _print_permissiveness_ranking()
