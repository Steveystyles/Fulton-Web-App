# Map Clue Grading Matrix

Use this matrix when grading `geography_quiz_clues_1000_cleaned_for_grading.csv`.

Grade the player-facing `clue_text`, not the model's `expected_quality`. The model's label is only a prompt hint and can be wrong.

## Output Columns

Fill these columns:

| Column | Values | Use |
| --- | --- | --- |
| `pass_fail` | `pass` or `fail` | Whether you would accept this clue for the game. |
| `grader_reason` | short reason, ideally with a code below | Why it passed or failed. |
| `known_good_rewrite` | optional improved clue | Fill this when a clue is close but needs a better version. |

Use `pass` only when the clue would be acceptable in the game, or when it is a near-pass with wording problems only.

For a near-pass, write `QUALIFIED:` at the start of `grader_reason`. Example:

`QUALIFIED: good incident, but wording should say "this bridge" instead of "it".`

Use `fail` when the idea itself needs replacing.

## Overall Test

| Grade | Meaning |
| --- | --- |
| Strong pass | I would happily use this clue with little or no edit. |
| Qualified pass | The core idea is usable, but wording, focus, or specificity needs improvement. |
| Fail | I would not use this clue. It teaches the wrong pattern or would frustrate the player. |

The game should be fun but beatable for an adult general-knowledge player. The aim is not to trick him with obscure facts; it is to give him a satisfying route to the answer.

## Hard Clues

Hard clues should be the first hook.

| Pass If | Fail If |
| --- | --- |
| It uses one specific incident, event, story, mystery, famous match, disaster, scandal, invention, or memorable person-linked moment. | It is just broad fame: "This place is famous and visited by many tourists." |
| The fact is clearly owned by this place, not merely true of many similar places. | It could fit many places of the same type. |
| It is interesting enough that knowing the fact could help someone work toward the place. | It is just static data: height, age, capacity, year built, old record, or "home of X". |
| It is about the place itself, even if a person is involved. | It is mainly about the designer, owner, club, monarch, or artist rather than the location. |
| The wording is plain and gives the target type when helpful, such as "this bridge" or "this stadium". | It starts with a vague pronoun and hides too much, or the grammar feels awkward. |
| It does not leak the answer name or a near-alias. | It contains the answer, a near-alias, or a unique place-name token. |

Examples of strong hard clue styles:

| Style | Example Pattern |
| --- | --- |
| Named sporting moment | `This stadium hosted Maradona's "Hand of God" and "Goal of the Century" in the same match.` |
| Memorable incident | `A fatal opening-week panic began after rumours spread that this bridge was collapsing.` |
| Place-owned mystery | `Three prisoners vanished from this island prison in a raft escape that remains disputed.` |
| Famous historical story | `Two young princes disappeared after being lodged inside this fortress.` |

## Medium Clues

Medium clues should narrow the search area while staying a fact about the place.

| Pass If | Fail If |
| --- | --- |
| It points toward the right country, city, region, culture, community, or setting. | It is generic: "It is in a major city" or "It is one of the country's most famous places." |
| It remains a clue, not a full map instruction. | It becomes an easy clue by saying exactly where to look. |
| It gives useful context without leaking the answer. | It leaks the answer, a near-alias, or a unique name token. |
| It is distinct from the hard clue. | It repeats the hard clue in different words. |
| It helps the player progress from knowing the hook to knowing where to look. | It adds trivia but no location or narrowing value. |

Good medium clue patterns:

| Pattern | Example |
| --- | --- |
| Cultural setting | `It is closely tied to Catalan football culture in Spain's second-largest city.` |
| City/region narrowing | `This fortress crowns a volcanic rock above Scotland's capital.` |
| Place type plus area | `This island prison sits in a cold bay off a major West Coast city.` |

## Easy Clues

Easy clues should help final map placement.

| Pass If | Fail If |
| --- | --- |
| It gives a practical map anchor: river, coast, district, harbour, road, bridge, park, visible shape, mountain, or nearby landmark. | It says only "look near the city centre" or "it is easy to find." |
| It helps the player tap the right target on a phone map. | It still leaves several plausible pins. |
| It is accurate at normal map zoom. | It depends on obscure local labels or a specialist database. |
| It does not leak the answer name unless this is the final name reveal clue. | It names the answer or a near-alias. |

Good easy clue patterns:

| Pattern | Example |
| --- | --- |
| River/water anchor | `Look on the north bank of the Thames beside Tower Bridge.` |
| District anchor | `Look in the Les Corts district, west of central Barcelona.` |
| Nearby landmark | `Find the small island between the city waterfront and the bay's famous bridge.` |
| Visible shape | `Look for the large oval stadium footprint south of the city centre.` |

## Reason Codes

Use these codes in `grader_reason` when helpful.

| Code | Meaning |
| --- | --- |
| `STRONG_EVENT` | Strong specific event or incident. |
| `STRONG_STORY` | Strong memorable story or mystery. |
| `STRONG_MAP` | Strong map-placement value. |
| `QUALIFIED_WORDING` | Good idea, but wording or grammar needs work. |
| `QUALIFIED_CONTEXT` | Good idea, but needs a bit more context. |
| `QUALIFIED_FOCUS` | Good idea, but part of the clue is off-target or padded. |
| `FAIL_GENERIC` | Too broad or generic. |
| `FAIL_STATIC_DATA` | Just data: height, age, capacity, year built, former record. |
| `FAIL_NOT_PLACE_OWNED` | Fact is not clearly owned by the target place. |
| `FAIL_DESIGNER_ONLY` | Mainly about the designer/person, not the place. |
| `FAIL_COLOUR_ONLY` | Colour/appearance only, not an interesting hook. |
| `FAIL_REPEAT` | Repeats another clue. |
| `FAIL_MAP_TOO_BROAD` | Does not help locate the place on a map. |
| `FAIL_ANSWER_LEAK` | Leaks the answer or near-alias. |
| `FAIL_NICHE` | Too obscure for the intended player. |
| `FAIL_UNCLEAR` | Awkward, confusing, or ambiguous wording. |

## Quick Decision Rules

| Situation | Grade |
| --- | --- |
| Good incident, but extra filler sentence weakens it | `pass`, reason starts `QUALIFIED_FOCUS` |
| Good incident, but vague pronoun makes it harder than intended | `pass`, reason starts `QUALIFIED_WORDING` |
| Interesting fact, but mostly about the architect/designer | usually `fail`, or `pass` with `QUALIFIED_FOCUS` if still strongly identifies the place |
| Old record or "once the tallest" | usually `fail`, `FAIL_STATIC_DATA` |
| Exact answer or unique answer token appears in `clue_text` | `fail`, `FAIL_ANSWER_LEAK` |
| Easy clue gives a clear river/district/nearby landmark | `pass`, `STRONG_MAP` |
| Easy clue says only "central city" | `fail`, `FAIL_MAP_TOO_BROAD` |

## Suggested Grading Style

Keep reasons short and consistent:

`STRONG_EVENT: specific, famous incident tied to the stadium.`

`QUALIFIED_WORDING: good event, but "it" should be "this bridge".`

`FAIL_STATIC_DATA: old record only, not interesting enough.`

`FAIL_MAP_TOO_BROAD: does not help place the pin on a phone map.`
