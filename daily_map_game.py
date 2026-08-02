from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DIFFICULTIES = ("easy", "medium", "hard")

MAP_CLUE_SCORES = {
    0: 10,
    1: 7,
    2: 5,
    3: 2,
}

MAP_MAX_SCORE = MAP_CLUE_SCORES[0]

SCORE_CONFIG = {
    "easy": {"max_points": MAP_MAX_SCORE, "lambda_km": 1800.0},
    "medium": {"max_points": MAP_MAX_SCORE, "lambda_km": 450.0},
    "hard": {"max_points": MAP_MAX_SCORE, "lambda_km": 80.0},
}

DEFAULT_SCORING_RADIUS_M = {
    "easy": 25_000,
    "medium": 10_000,
    "hard": 1_000,
}

SNAP_RADIUS_FLOOR_M = {
    "easy": 90_000,
    "medium": 35_000,
    "hard": 30_000,
}

SNAP_TOUCH_RADIUS_PX = 56

SNAP_TOUCH_RADIUS_CAP_M = {
    "easy": 200_000,
    "medium": 120_000,
    "hard": 75_000,
}

MAX_SNAP_ALTERNATIVES = 5
PLAYABLE_PLACE_SAMPLE_LIMIT = 250
MAP_EXCLUDED_CANONICAL_NAMES = frozenset(
    {
        "aflaj irrigation systems of oman",
        "ancient thebes with its necropolis",
        "ancient villages of northern syria",
        "baekje historic areas",
        "bagrati cathedral and gelati monastery",
    }
)

REVERSE_GEOCODE_URL = os.environ.get(
    "FULTONS_REVERSE_GEOCODE_URL",
    "https://nominatim.openstreetmap.org/reverse",
)
FORWARD_GEOCODE_URL = os.environ.get(
    "FULTONS_FORWARD_GEOCODE_URL",
    "https://nominatim.openstreetmap.org/search",
)
REVERSE_GEOCODE_USER_AGENT = os.environ.get(
    "FULTONS_REVERSE_GEOCODE_USER_AGENT",
    "FultonsQuiz/0.1 (+https://fultons-quiz.co.uk)",
)
REVERSE_GEOCODE_LANGUAGE = os.environ.get("FULTONS_REVERSE_GEOCODE_LANGUAGE", "en").strip() or "en"
REVERSE_GEOCODE_TIMEOUT_SEC = float(os.environ.get("FULTONS_REVERSE_GEOCODE_TIMEOUT_SEC", "3"))
REVERSE_GEOCODE_ENABLED = os.environ.get("FULTONS_REVERSE_GEOCODE_ENABLED", "1") != "0"
REVERSE_GEOCODE_MIN_INTERVAL_SEC = 1.1
REVERSE_GEOCODE_LOCK = threading.Lock()
REVERSE_GEOCODE_NEXT_REQUEST_AT = 0.0

RECENT_USE_DAYS = 30

MAP_CLUE_REQUIRED_FIELDS = ("hard", "medium", "easy", "reveal")
MAP_CLUE_CRITIC_THRESHOLDS = {
    "correctness": 9,
    "distinctiveness": 8,
    "difficulty_ladder": 8,
    "non_spoiler": 9,
    "interestingness": 7,
}
MAP_CLUE_TEXT_LIMITS = {
    "hard": 320,
    "medium": 220,
    "easy": 220,
    "reveal": 240,
}
MAP_CLUE_COMPRESSION_FILLERS = (
    "historic",
    "grand",
    "immense",
    "enormous",
    "meticulous",
    "meticulously",
    "great",
    "tall",
    "massive",
    "primary",
    "major",
)
MAP_CLUE_TEMPLATE_PHRASES = (
    "mapped urban centre",
    "mapped urban center",
    "mapped urban centres",
    "mapped urban centers",
    "national-map setting",
    "combine that national-map position",
    "within the wider",
    "wider national-map",
    "urban settlement in",
    "major metropolitan settlement",
    "medium-sized urban settlement",
    "large urban settlement",
    "very large metropolitan settlement",
)
MAP_CLUE_PLACEHOLDER_PHRASES = (
    "tower of the place",
    "of the place",
    "the target place",
    "target place",
    "the answer",
)
MAP_CLUE_REVEAL_PLACEHOLDER_PHRASES = (
    "the target place",
    "target place",
    "the correct place",
    "the pin",
    "fits because",
    "matches because",
    "ties together",
)
MAP_CLUE_SUPPORT_STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "again",
    "against",
    "along",
    "also",
    "ancient",
    "another",
    "around",
    "because",
    "before",
    "below",
    "beside",
    "between",
    "broad",
    "built",
    "centre",
    "centred",
    "center",
    "city",
    "clue",
    "clues",
    "code",
    "compact",
    "country",
    "direct",
    "during",
    "every",
    "famous",
    "features",
    "found",
    "from",
    "given",
    "great",
    "greek",
    "historic",
    "history",
    "large",
    "listed",
    "location",
    "major",
    "mapped",
    "metropolitan",
    "near",
    "nearby",
    "northern",
    "other",
    "place",
    "places",
    "point",
    "popular",
    "reveal",
    "settlement",
    "short",
    "site",
    "southern",
    "specific",
    "this",
    "target",
    "through",
    "urban",
    "using",
    "where",
    "which",
    "while",
    "with",
    "world",
}
MAP_CLUE_SUPPORT_SHORT_TERMS = {
    "dam",
    "dams",
    "fort",
    "kop",
    "keep",
    "rock",
    "span",
}
MAP_PLACE_REQUIRED_PERSUADING_FACTS = 1
MAP_PLACE_PERSUADING_FACT_SCORE = 6
MAP_PLACE_REQUIRED_WORKOUTABILITY_SCORE = 6
MAP_PLACE_LOW_INTEREST_FACT_RE = re.compile(
    r"\b(?:geonames|wikidata lists|wikidata records|time zone|iso country code|"
    r"coordinates?|latitude|longitude|mapped urban|populated place|population of about|"
    r"country name|admin(?:istrative)? region)\b",
    re.IGNORECASE,
)
MAP_PLACE_HOOK_CATEGORY_PATTERNS = (
    (
        "visual_landmark",
        re.compile(
            r"\b(?:big ben|parliament|castle|fort|fortress|palace|cathedral|abbey|mosque|temple|"
            r"bridge|tower|clock|lighthouse|statue|monument|pyramid|amphitheatre|gate|"
            r"skyscraper|building|viewing deck|glass-bottomed|balcony|facade|roof|arch|spheres?|"
            r"lighting|leds?|illuminations?|sail-shaped|palm-shaped|date palm|visible from space|"
            r"waterfront|harbou?r|skyline|mountain|peak|beach|shoreline|coastline|"
            r"lagoon|reef|bungalows?|public park|green corridor|interior|gold leaf)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "history",
        re.compile(
            r"\b(?:roman|ancient|medieval|historic|royal|imperial|dynastic|pharaoh|mughal|ottoman|"
            r"byzantine|founded|built|construction began|saved from demolition|derelict|war|prison|holocaust|nazi|"
            r"persecution|battle|revolution|civil rights|1[0-9]{3}|20[0-2][0-9])\b",
            re.IGNORECASE,
        ),
    ),
    (
        "culture_event",
        re.compile(
            r"\b(?:festival|carnival|parade|theatre|theater|opera|museum|library|music|art|"
            r"art installations?|fashion|literary|writers?|film|university|scholarship|"
            r"ceremony|anthem|community campaign|decorated|luxury design|gold leaf)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_industry",
        re.compile(
            r"\b(?:railway|underground|metro|subway|shipyard|shipbuilding|industry|mills?|"
            r"industrial|freight rail|rail line|elevated|quarrying|irrigation|aqueduct|canals?|"
            r"bridge|suspension|span|steel|bundled tubes?|wind resistance|"
            r"land reclamation|dredged|dredging|man-made island|artificial island|artificial archipelago|"
            r"earthquakes?|winds?|vault|seeds?|backup|catastrophes?|freezing|crystal|unit cell|"
            r"exposition|research|technology|commerce|trade)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sport",
        re.compile(
            r"\b(?:stadiums?|football|rugby|cricket|club|supporters|kop|terrace|stand|"
            r"matches|cup|league|sporting events?|national team|qualifying|capacity|olympic|olympics|games)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "natural_setting",
        re.compile(
            r"\b(?:volcanic|geological|basalt|columns?|hexagonal|gorge|canyon|sandstone|"
            r"hot-spring|thermal|river|coast|island|bay|waterfall|lagoon|reef|islets?|"
            r"motus|arctic|ice|frozen|freezing|native plants|green corridor|persian gulf|"
            r"offshore|sea floor|seafloor|beachfront|shoreline|coastline)\b",
            re.IGNORECASE,
        ),
    ),
)
MAP_WORKOUTABILITY_VAGUE_RE = re.compile(
    r"^\s*(?:easy|medium|hard|high|low|moderate|good|poor|yes|no|findable|guessable)\s*$",
    re.IGNORECASE,
)
MAP_WORKOUTABILITY_ANCHOR_RE = re.compile(
    r"\b(?:city|town|district|neighbou?rhood|country|region|state|coast|river|bay|"
    r"harbou?r|waterfront|island|seafront|station|rail|line|route|road|canal|"
    r"bridge|park|stadium|arena|airport|downtown|centre|center|landmark|"
    r"skyline|tower|skyscraper|street|avenue|boulevard)\b",
    re.IGNORECASE,
)
MAP_CLUE_EASY_ANCHOR_RE = re.compile(
    r"\b(?:river|bay|bridge|road|route|island|park|district|neighbou?rhood|"
    r"coast|coastal|coastline|harbou?r|waterfront|seafront|station|railway|"
    r"metro|canal|lake|mountain|hill|valley|peninsula|old town|city centre|"
    r"city center|stadium|airport|port|landmark|tower|palace|museum|"
    r"cathedral|fort|castle|citadel|square)\b",
    re.IGNORECASE,
)
MAP_WORKOUTABILITY_ACTION_RE = re.compile(
    r"\b(?:map|pin|target|tap|label|labelled|labeled|search|visible|shape|outline|"
    r"follow|trace|zoom|look for|work from|narrow)\b",
    re.IGNORECASE,
)
MAP_CLUE_COORDINATE_OR_CODE_RE = re.compile(
    r"\b(?:latitude|longitude|degrees north|degrees south|degrees east|degrees west|"
    r"iso country code|coordinates?|time zone|located at\s+-?\d)",
    re.IGNORECASE,
)
MAP_CLUE_COORDINATE_PAIR_RE = re.compile(r"\b-?\d{1,2}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}\b")
MAP_CLUE_LOCATION_FRAMING_RE = re.compile(
    r"\b(?:look in|located in|located on|situated in|situated on|"
    r"sits (?:in|on|near|beside|below|above|between)|lies (?:in|on|near|beside|below|above|between)|"
    r"stands (?:in|on|near|beside|below|above|between|at)|"
    r"near|nearby|beside|around|between|north of|south of|east of|west of|"
    r"short distance from|proximity to|grew around|found on|found in|connects .* to)\b",
    re.IGNORECASE,
)
MAP_CLUE_GENERIC_GEO_RE = re.compile(
    r"\b(?:capital city of|capital of|largest (?:and most famous )?city|major .* destination|"
    r"global .* hub|urban hub|coastal metropolis|historic settlement|large settlement|"
    r"sprawling capital|busy .* station|broad river|low hills|within this dense urban grid)\b",
    re.IGNORECASE,
)
MAP_CLUE_KNOWN_FOR_RE = re.compile(
    r"\b(?:known for|known as|famous for|renowned for|celebrated for|home to|site of|birthplace|"
    r"founded by|founded as|served as|hosted|headquarters|associated with|construction began|silk road|trade hub|"
    r"unesco|world heritage|wonder of the ancient world|seven wonders|palace|fort|fortress|castle|keep|"
    r"cathedral|abbey|church|churches|mosque|temple|shrine|museum|library|lighthouse|bridge|bridges|"
    r"tower|towers|clock|market|markets|bazaar|big ben|parliament|"
    r"festival|festivals|carnival|parade|industry|distiller|monument|statue|statues|sculpture|opera house|theatre|theater|"
    r"nickname|royal|imperial|mughal|byzantine|ottoman|roman|ancient|medieval|islamic|nasrid|palatine|"
    r"thracian|hellenic|phoenician|numidian|assyrian|hammadid|khmer|nabat[a-z]+|"
    r"architecture|architectural|cultural|commercial|financial|trade|commerce|cocoa|agave|tequila|coffee|music|art|fashion|"
    r"university|scholarship|writers|writer|writing|literary|philosophy|democracy|research|technology|film|bands|"
    r"olympic|olympics|games|beach|waterfront|harbour|harbor|waterway|canal|canals|park|garden|gardens|observation wheel|"
    r"public park|green corridor|elevated freight rail|rail line|art installations?|tallest building|"
    r"viewing deck|glass-bottomed|sail-shaped|palm-shaped|visible from space|land reclamation|"
    r"artificial island|artificial archipelago|man-made island|dredged|beachfront|gold leaf|dhow|"
    r"bundled tubes?|vertical city|wind resistance|"
    r"skyline|defensive|roofline|rooflines|plastered|carving|carvings|courtyard|courtyards|tile|tiles|geometric|"
    r"volcanic|geological|basalt|column|columns|hexagonal|pharaoh|ramesses|tomb|funerary|necropolis|"
    r"mountain|peak|prison|memorial|holocaust|nazi|persecution|barracks|bookcase|annex|diary|"
    r"amphitheatre|amphitheater|citadel|pyramid|pyramids|parthenon|athena|sacred hill|"
    r"sanctuary|sanctuaries|colossal|ancestors|stone platform|temples|"
    r"suspension|span|paint shade|orange towers|fog|facade|facades|facade|gorge|canyon|sandstone|rock-cut|"
    r"pylon|pylons|cable|cables|bronze|soldier|soldiers|diamond-shaped|panels|arch|arches|roof|shell|"
    r"exposition|crystal|unit cell|sphere|spheres|steel|"
    r"stadium|ground|grounds|venue|football|rugby|cricket|club|clubs|supporters|anthem|kop|terrace|terraces|"
    r"stand|stands|seats|match|matches|cup|final|finals|league|manager|managers|pitch|bowl|"
    r"trading post|trading platform|city-state|settlers|traders|colony|empire|"
    r"shipyard|shipyards|shipbuilding|railroad|civil rights|government|dynastic|cotton|mills|quarrying|"
    r"hot-spring|thermal|crescents|georgian|"
    r"irrigation|channel|channels|cistern|cisterns|gravity|spring|springs|agriculture|astronomical|watchtower|watchtowers|"
    r"underground railway|metro|subway|red buses|taxicabs|black cabs|aqueduct|bath|baths)\b",
    re.IGNORECASE,
)
MAP_CLUE_HISTORIC_YEAR_RE = re.compile(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b")
MAP_CLUE_GENERIC_ORIGIN_RE = re.compile(
    r"\b(?:construction (?:of [^.!?]{1,45} )?(?:began|started)|"
    r"building work (?:began|started)|commissioned by|"
    r"(?:was|were) (?:built|commissioned|founded|opened|completed) (?:by|in|under)|"
    r"ordered [^.!?]{0,45} (?:built|constructed)|founded by)\b",
    re.IGNORECASE,
)
MAP_CLUE_DISTINCTIVE_ORIGIN_DETAIL_RE = re.compile(
    r"\b(?:only|first|last|oldest|longest|tallest|largest|smallest|world record|"
    r"collapsed|destroyed|moved|relocated|stolen|escaped|siege|fire|flood|earthquake|"
    r"assassination|accident|disaster|upset|ritual|tradition|legend|myth|nickname|"
    r"controversy|protest|hidden|secret|unfinished|abandoned|reused|survived)\b",
    re.IGNORECASE,
)
MAP_CLUE_GENERIC_UNNAMED_IDENTITY_RE = re.compile(
    r"\b(?:named (?:after|for)|honou?rs?|dedicated to|associated with)\s+"
    r"(?:a|an)\s+(?:(?:prominent|famous|celebrated|local|national|"
    r"brazilian|british|american|european|sports?)\s+){0,4}"
    r"(?:journalist|architect|writer|artist|politician|ruler|engineer|"
    r"scientist|athlete|footballer|player|person)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_EVENT_ACTION_RE = re.compile(
    r"\b(?:beat|defeated|stunned|shocked|won|lost|scored|set|broke|"
    r"clinched|secured|assassinat\w*|murder\w*|kill\w*|slew|slain|shot|"
    r"attack\w*|bomb\w*|besieged|siege|"
    r"escaped?|fled|vanish\w*|disappear\w*|collaps\w*|destroy\w*|"
    r"burn\w*|demolish\w*|devastat\w*|"
    r"flatten\w*|razed|reduc\w*.{0,50}\bto rubble|explod\w*|crash\w*|"
    r"protest\w*|delivered .{0,30} speech|signed|crown\w*|coronation|"
    r"trial|imprison\w*|discover\w*|invent\w*|perform\w*|filmed|"
    r"recorded|launched|landed|erupt\w*|debut\w*|premier\w*|"
    r"wrote|composed|unveil\w*|hosted .{0,40}"
    r"(?:final|match|games?))\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_RECOGNITION_SIGNAL_RE = re.compile(
    MAP_HARD_HOOK_EVENT_ACTION_RE.pattern
    + r"|"
    r"\b(?:world record|record holder|holds? the record|set the record|"
    r"first(?:-ever)?|only|last surviving|oldest|largest|smallest|longest|"
    r"highest|deepest|fastest|most visited|birthplace|discovery|invention|"
    r"ritual|tradition|pilgrimage|legend|myth|annual race|cultural movement|"
    r"natural phenomenon|mass migration)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_DISTINCTIVE_MARKER_RE = re.compile(
    r"\b(?:world record|record holder|holds? the record|set the record|"
    r"first(?:-ever)?|only|last surviving|oldest|largest|smallest|longest|"
    r"highest|deepest|fastest|decisive|upset|turning point|"
    r"assassination|murder|uprising|revolution|discovery|invention|"
    r"ritual|tradition|legend|myth|collapsed|destroyed|escaped|survived)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_NAMED_EVENT_RE = re.compile(
    r"\b(?:world cup|european cup|champions league|european championship|"
    r"olympic|commonwealth games|uprising|revolution|maracanazo|"
    r"atomic bomb|goal of the century|hand of god|hundred years[’'] war|"
    r"second world war|first world war|civil rights|moon landing)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_STATIC_DESCRIPTION_RE = re.compile(
    r"\b(?:architect|architecture|architectural|designed by|built by|"
    r"construction|baroque|gothic|renaissance style|facade|roof|"
    r"height|metres?|meters?|capacity|dimensions?)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_GENERIC_INCIDENT_RE = re.compile(
    r"\b(?:a conflict|the conflict|during conflict|during tensions|"
    r"(?:in|during) (?:the )?(?:19|20)\d0s conflict|"
    r"damaged during|destroyed during|attacked during|war damage|"
    r"destroyed in \d{4}|discovered in \d{4}|resist\w* attacks during|"
    r"bombed during (?:the )?(?:first|second) world war|"
    r"destroyed in the war of \d{4})\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_FORMER_RECORD_RE = re.compile(
    r"\b(?:once|formerly|previously|used to be)\b.{0,80}"
    r"\b(?:record|oldest|largest|smallest|longest|highest|deepest|fastest)\b|"
    r"\b(?:had|held|was|were)\b.{0,80}"
    r"\b(?:world(?:'s)?\s+)?(?:record|oldest|largest|smallest|longest|"
    r"highest|deepest|fastest)\b.{0,40}\b(?:when|until|from)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_WEAK_SUPERLATIVE_RE = re.compile(
    r"\bone of (?:the )?[^.!?]{0,50}\b"
    r"(?:oldest|largest|smallest|longest|highest|deepest|fastest)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_WEAK_ASSOCIATION_RE = re.compile(
    r"\b(?:honou?rs?|named after|named for|dedicated to|associated with)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_NONQUALIFYING_ORIGIN_RE = re.compile(
    r"\b(?:first )?(?:opened|built|completed|created|inaugurated)\s+"
    r"(?:for|to host)\s+(?:the\s+)?(?:19|20)\d{2}\s+"
    r"(?:olympic|commonwealth|world|european|asian|pan american).{0,30}"
    r"(?:games|cup|championship|expo|exposition)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_WEAK_ORIGIN_RE = re.compile(
    r"\b(?:first\s+(?:[a-z]+\s+){0,3}(?:monks?|settlers?|residents?)\s+(?:settled|arrived)|"
    r"first\s+(?:shrine\s+buildings?|church|temple|building|structure)s?.{0,35}\b(?:was |were )?"
    r"(?:built|erected|completed|opened|founded)|"
    r"(?:was|were)\s+first\s+(?:built|erected|completed|opened|founded))\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_WEAK_COMMISSION_RE = re.compile(
    r"\b(?:king|queen|ruler|monarch|emperor|government|city)\b.{0,45}"
    r"\b(?:ordered|commissioned)\b.{0,35}"
    r"\b(?:construction|built|building|bridge|church|palace|monument)\b",
    re.IGNORECASE,
)
MAP_HARD_HOOK_ARCHITECT_LED_RE = re.compile(
    r"\b(?:commissioned|hired|appointed)\b.{0,55}\barchitect\b|"
    r"\barchitect\b.{0,55}\b(?:designed?|rebuilt|reconstructed?|built|constructed?)\b",
    re.IGNORECASE,
)
MAP_HARD_EVENT_PARTICIPANT_RE = re.compile(
    r"\b(?:beat|defeated|against|between|by (?:four|three|two|\d+)|"
    r"by [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+(?:troops|forces|knights|players))?|"
    r"host nation|visiting team|rebels?|protesters?|troops|forces|knights)\b",
    re.IGNORECASE,
)
MAP_HARD_EVENT_NAMED_ACTOR_RE = re.compile(
    r"\b[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){0,2}\s+"
    r"(?:beat|defeated|won|lost|scored|clinched|secured|"
    r"assassinat\w*|murder\w*|kill\w*|shot|attack\w*|"
    r"destroy\w*|burn\w*|signed|crown\w*)\b"
)
MAP_HARD_TEAM_EVENT_RE = re.compile(
    r"\b(?:world cup|european cup|champions league|"
    r"cup final|championship final|football match|soccer match)\b",
    re.IGNORECASE,
)
MAP_HARD_TEAM_NAME_PATTERN = (
    r"[A-Z][^\W\d_]*(?:['’\-][^\W\d_]+)*"
    r"(?:\s+[A-Z][^\W\d_]*(?:['’\-][^\W\d_]+)*){0,3}"
)
MAP_HARD_TEAM_SIDES_RE = re.compile(
    rf"\b(?:{MAP_HARD_TEAM_NAME_PATTERN}\s+"
    rf"(?:beat|defeated)\s+(?:the\s+|host nation\s+)?"
    rf"{MAP_HARD_TEAM_NAME_PATTERN}|"
    rf"{MAP_HARD_TEAM_NAME_PATTERN}\s+"
    rf"(?:secured|claimed|won|lifted)\b.{{0,100}}?\b"
    rf"(?:by\s+)?defeating\s+(?:the\s+|host nation\s+)?"
    rf"{MAP_HARD_TEAM_NAME_PATTERN}|"
    rf"(?:between|against)\s+{MAP_HARD_TEAM_NAME_PATTERN}\s+"
    rf"(?:and|against)\s+(?:the\s+|host nation\s+)?"
    rf"{MAP_HARD_TEAM_NAME_PATTERN})\b"
)
MAP_HARD_TEAM_INDIRECT_SIDES_RE = re.compile(
    r"\b(?:(?:national\s+)?team\s+of\s+"
    r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2}|"
    r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2}\s+"
    r"(?:national\s+)?(?:football\s+)?team)"
    r".{0,100}?\b(?:beat|defeated|defeating)\s+(?:the\s+)?"
    r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2}\b"
)
MAP_HARD_PLACE_LINK_RE = re.compile(
    r"\b(?:here|"
    r"this (?:[a-z-]+ ){0,2}(?:site|ground|venue|stadium|arena|church|cathedral|building|"
    r"bridge|tower|district|quarter|neighbourhood|neighborhood|island|park|"
    r"mountain|monument|fort|fortress|castle|palace|museum|prison|penitentiary|"
    r"temple|mosque|monastery|ruin|cave)|"
    r"at this (?:site|ground|venue|stadium|arena|church|building|bridge|"
    r"prison|penitentiary|temple|mosque|monastery|fort|fortress)|"
    r"on this (?:pitch|court|track|stage|site)|"
    r"inside this (?:church|cathedral|building|venue|ground|district|quarter|"
    r"prison|penitentiary|temple|mosque|monastery|fort|fortress|cave)|"
    r"within this (?:site|building|venue|ground|district|quarter|"
    r"neighbourhood|neighborhood|prison|penitentiary|temple|mosque|"
    r"monastery|fort|fortress|cave))\b",
    re.IGNORECASE,
)
MAP_HARD_TARGET_IDENTITY_TERMS = {
    "arena": (r"\barena\b", r"\bvenue\b"),
    "bridge": (r"\bbridge\b", r"\bcrossing\b"),
    "castle": (r"\bcastle\b", r"\bfort(?:ress)?\b"),
    "cathedral": (r"\bcathedral\b", r"\bchurch\b"),
    "church": (r"\bchurch\b", r"\bcathedral\b"),
    "fort": (r"\bfort(?:ress)?\b", r"\bcastle\b"),
    "fortress": (r"\bfort(?:ress)?\b", r"\bcastle\b"),
    "island": (r"\bisland\b",),
    "museum": (r"\bmuseum\b", r"\bbuilding\b"),
    "palace": (r"\bpalace\b", r"\broyal residence\b"),
    "prison": (r"\bprison\b", r"\bpenitentiary\b", r"\bimprison\w*\b"),
    "stadium": (
        r"\bstadium\b",
        r"\bground\b",
        r"\bpitch\b",
        r"\bvenue\b",
        r"\barena\b",
    ),
    "temple": (r"\btemple\b", r"\bshrine\b"),
    "tower": (r"\btower\b", r"\bstructure\b"),
}
MAP_HARD_SECONDARY_IDENTITY_SIGNALS = {
    "prison": re.compile(r"\b(?:prison|penitentiary|imprison\w*)\b", re.IGNORECASE),
}
MAP_MEDIUM_FILLER_RE = re.compile(
    r"\b(?:(?:draws?|attracts?) (?:enormous|huge|large|many) crowds|"
    r"(?:popular|prestigious|historic|iconic|famous) venue)\b",
    re.IGNORECASE,
)
MAP_MEDIUM_VAGUE_CULTURE_RE = re.compile(
    r"\b(?:a |the )?(?:famous|well-known|celebrated|important)\s+"
    r"(?:collection|book|novel|poem|play|story|stories|tales|work|works|"
    r"writer|author|artist|film|song|painting)\b",
    re.IGNORECASE,
)
MAP_MEDIUM_AMBIGUOUS_FICTION_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)['’]s\s+"
    r"(?:pilgrims?|characters?|detectives?|heroes?|villains?|protagonists?)\b"
)
MAP_MEDIUM_FICTION_CONTEXT_RE = re.compile(
    r"\b(?:fiction|fictional|imaginary|in (?:his|her|the) "
    r"(?:book|novel|poem|play|story|tale|work))\b",
    re.IGNORECASE,
)
MAP_HARD_EVENT_SIGNIFICANCE_RE = re.compile(
    r"\b(?:after|because|following|in retaliation|trigger\w*|spark\w*|prompt\w*|"
    r"led to|resulted in|bringing|making|forcing|allowing|first(?:-ever)?|record|decisive|extra time|"
    r"consequence|controversy|turning point|stoppage time|comeback|treble|"
    r"(?:by )?using .{4,100}\bto\b|"
    r"\d+\s*[-–—]\s*\d+|"
    r"remains?.{0,80}\b(?:unsolved|famous|notorious|mystery|symbol)\b|"
    r"to (?:suppress|crush|prevent|retaliate|avenge)|"
    r"reduc\w*.{0,50}\bto rubble)\b",
    re.IGNORECASE,
)
MAP_HARD_GEO_SCOPE_RE = re.compile(
    r"\b(?:[a-z]+(?:['’]s)?\s+capital(?:['’]s)?|"
    r"capital city|located|situated|geographically|"
    r"in (?:african|american|argentinian|asian|australian|brazilian|british|"
    r"canadian|chinese|egyptian|english|european|french|german|greek|indian|"
    r"irish|italian|japanese|mexican|polish|portuguese|russian|scottish|"
    r"south african|spanish|welsh).{0,30}\bhistory|"
    r"north(?:ern)?(?!\s+(?:ireland|korea|macedonia))|"
    r"south(?:ern)?(?!\s+(?:africa|korea|sudan))|"
    r"east(?:ern)?(?!\s+(?:germany|timor))|"
    r"west(?:ern)?(?!\s+(?:germany|indies)))\b",
    re.IGNORECASE,
)
MAP_HARD_NAMED_GEOGRAPHIC_FEATURE_RE = re.compile(
    r"\b[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,3}\s+"
    r"(?:Bay|Beach|Borough|City|Coast|District|Harbou?r|Island|Lake|"
    r"Mountain|Neighbourhood|Neighborhood|Peninsula|Point|Quarter|River|"
    r"Road|Sea|Station|Street|Valley|Waterfront)\b"
)
MAP_MEDIUM_GEO_NARROWING_RE = re.compile(
    r"\b(?:country|nation|national|region|state|province|county|city|capital|"
    r"language|community|island group|coast|river basin|"
    r"african|american|argentinian|australian|austrian|belgian|brazilian|"
    r"british|canadian|chilean|chinese|croatian|danish|dutch|egyptian|"
    r"english|european|finnish|french|german|greek|hungarian|indian|"
    r"indonesian|irish|italian|japanese|kenyan|mexican|moroccan|"
    r"new zealand|norwegian|peruvian|polish|portuguese|scottish|"
    r"south african|spanish|swedish|swiss|thai|turkish|welsh)\b",
    re.IGNORECASE,
)
MAP_EASY_LOCAL_AREA_RE = re.compile(
    r"\b(?:borough|district|quarter|neighbou?rhood|suburb|ward|old town|"
    r"city centre|city center|downtown|docklands?|waterfront|harbou?rfront|"
    r"university quarter|museum quarter|historic centre|historic center)\b",
    re.IGNORECASE,
)
MAP_EASY_LOCAL_RELATION_RE = re.compile(
    r"\b(?:inside|within|between|beside|along|across|opposite|next to|near|around|"
    r"above|below|"
    r"north(?:ern)?|south(?:ern)?|east(?:ern)?|west(?:ern)?|central|"
    r"at the edge of|on the bank of|on the shore of)\b",
    re.IGNORECASE,
)
MAP_EASY_CITY_SECTOR_RE = re.compile(
    r"\b(?:north(?:ern)?|south(?:ern)?|east(?:ern)?|west(?:ern)?|central|"
    r"city centre|city center|downtown|inner city|outer city|"
    r"on the (?:north|south|east|west) side)\b",
    re.IGNORECASE,
)
MAP_HARD_EVENT_ACTION_FAMILIES = {
    "sport": re.compile(
        r"\b(?:beat|defeated|won|lost|scored|clinched|secured|final|match)\b",
        re.IGNORECASE,
    ),
    "killing": re.compile(
        r"\b(?:assassinat\w*|murder\w*|kill\w*|slew|slain|shot)\b",
        re.IGNORECASE,
    ),
    "attack": re.compile(
        r"\b(?:attack\w*|bomb\w*|besieged|siege|destroy\w*|burn\w*|"
        r"demolish\w*|devastat\w*|flatten\w*|explod\w*|razed|uprising|"
        r"reduc\w*.{0,50}\bto rubble)\b",
        re.IGNORECASE,
    ),
    "political": re.compile(
        r"\b(?:protest\w*|speech|signed|crown\w*|coronation|revolution)\b",
        re.IGNORECASE,
    ),
    "disaster": re.compile(
        r"\b(?:collaps\w*|crash\w*|earthquake|flood\w*|erupt\w*)\b",
        re.IGNORECASE,
    ),
}
MAP_HARD_GENERIC_TARGET_TOKENS = frozenset(
    {
        "ancient",
        "archaeological",
        "area",
        "bridge",
        "castle",
        "cathedral",
        "centre",
        "center",
        "city",
        "district",
        "estadio",
        "historic",
        "island",
        "monument",
        "monumental",
        "museum",
        "national",
        "old",
        "palace",
        "park",
        "site",
        "stadium",
        "town",
    }
)

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MAP_LEARNING_PROFILE_PATH = (
    os.environ.get("MAP_LEARNING_PROFILE_PATH", "").strip()
    or str(PROJECT_DIR / "data" / "training" / "map_learning_profile_latest.json")
)
DEFAULT_MAP_SELECTOR_PROFILE_PATH = (
    os.environ.get("MAP_SELECTOR_PROFILE_PATH", "").strip()
    or str(PROJECT_DIR / "data" / "training" / "map_selector_profile_latest.json")
)
DEFAULT_MAP_CLUE_QUALITY_MODEL_PATH = (
    os.environ.get("MAP_CLUE_QUALITY_MODEL_PATH", "").strip()
    or str(PROJECT_DIR / "data" / "training" / "map_clue_quality_model_latest.json")
)
MAP_CLUE_LEARNED_PASS_THRESHOLDS = {
    "hard": 0.58,
    "medium": 0.55,
    "easy": 0.55,
}


@dataclass(frozen=True)
class MapClueConfig:
    learning_profile_path: str = DEFAULT_MAP_LEARNING_PROFILE_PATH
    clue_quality_model_path: str = ""
    max_attempts_per_place: int = max(1, int(os.environ.get("MAP_CLUE_MAX_ATTEMPTS", "6")))
    require_ai_critic: bool = os.environ.get("MAP_CLUE_REQUIRE_AI_CRITIC", "1") != "0"


class MapClueProvider(Protocol):
    name: str

    def generate_clue_ladder(
        self,
        *,
        place: dict[str, Any],
        recent_places: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        ...

    def critique_clue_ladder(
        self,
        *,
        place: dict[str, Any],
        clue_ladder: dict[str, Any],
        recent_places: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

STARTER_PLACES: tuple[dict[str, object], ...] = (
    {
        "slug": "easy-london",
        "name": "London",
        "country": "GB",
        "admin": "England",
        "difficulty": "easy",
        "lat": 51.5074,
        "lng": -0.1278,
        "clue": "Royal ceremony, parliament buildings, red buses, and black cabs define this global capital.",
        "medium_clue": "It is home to Westminster Abbey, Tower Bridge, and the world's oldest underground railway.",
        "easy_clue": "Famous for Big Ben, Buckingham Palace, and red double-decker buses.",
        "reveal": "London is known for royal landmarks, Westminster, and the Underground.",
    },
    {
        "slug": "easy-paris",
        "name": "Paris",
        "country": "FR",
        "admin": "Ile-de-France",
        "difficulty": "easy",
        "lat": 48.8566,
        "lng": 2.3522,
        "clue": "A European capital of cafes, grand boulevards, and a famous iron tower rising above the Seine.",
        "reveal": "Paris is the French capital, centred on the Seine.",
    },
    {
        "slug": "easy-rome",
        "name": "Rome",
        "country": "IT",
        "admin": "Lazio",
        "difficulty": "easy",
        "lat": 41.9028,
        "lng": 12.4964,
        "clue": "Ancient ruins, fountains, and a tiny independent state point to this historic Italian capital.",
        "reveal": "Rome combines ancient landmarks with the modern capital of Italy.",
    },
    {
        "slug": "easy-new-york",
        "name": "New York City",
        "country": "US",
        "admin": "New York",
        "difficulty": "easy",
        "lat": 40.7128,
        "lng": -74.0060,
        "clue": "A harbour city of skyscrapers, yellow taxis, Broadway theatres, and a statue holding a torch.",
        "reveal": "New York City anchors a famous natural harbour on the US east coast.",
    },
    {
        "slug": "easy-tokyo",
        "name": "Tokyo",
        "country": "JP",
        "admin": "Tokyo",
        "difficulty": "easy",
        "lat": 35.6762,
        "lng": 139.6503,
        "clue": "Neon crossings, bullet trains, imperial gardens, and a vast bay mark this Japanese capital.",
        "reveal": "Tokyo is Japan's capital and largest metropolitan area.",
    },
    {
        "slug": "easy-sydney",
        "name": "Sydney",
        "country": "AU",
        "admin": "New South Wales",
        "difficulty": "easy",
        "lat": -33.8688,
        "lng": 151.2093,
        "clue": "A harbour bridge and sail-like performance venue make this Australian city instantly recognisable.",
        "reveal": "Sydney wraps around one of Australia's best-known harbours.",
    },
    {
        "slug": "easy-cairo",
        "name": "Cairo",
        "country": "EG",
        "admin": "Cairo Governorate",
        "difficulty": "easy",
        "lat": 30.0444,
        "lng": 31.2357,
        "clue": "A sprawling capital by the Nile, close to desert monuments that have watched over the plateau for millennia.",
        "reveal": "Cairo is Egypt's capital and sits near the Giza plateau.",
    },
    {
        "slug": "easy-rio-de-janeiro",
        "name": "Rio de Janeiro",
        "country": "BR",
        "admin": "Rio de Janeiro",
        "difficulty": "easy",
        "lat": -22.9068,
        "lng": -43.1729,
        "clue": "A coastal city of steep granite peaks, carnival rhythm, long beaches, and a hilltop statue with open arms.",
        "reveal": "Rio de Janeiro is framed by mountains, bays, and Atlantic beaches.",
    },
    {
        "slug": "easy-cape-town",
        "name": "Cape Town",
        "country": "ZA",
        "admin": "Western Cape",
        "difficulty": "easy",
        "lat": -33.9249,
        "lng": 18.4241,
        "clue": "A port city beneath a flat-topped mountain near the meeting routes of two great oceans.",
        "reveal": "Cape Town sits below Table Mountain on South Africa's southwest coast.",
    },
    {
        "slug": "easy-edinburgh",
        "name": "Edinburgh",
        "country": "GB",
        "admin": "Scotland",
        "difficulty": "easy",
        "lat": 55.9533,
        "lng": -3.1883,
        "clue": "A Scottish capital of volcanic hills, festival crowds, medieval lanes, and a castle above the city.",
        "reveal": "Edinburgh is Scotland's capital and is overlooked by its castle rock.",
    },
    {
        "slug": "medium-bath",
        "name": "Bath",
        "country": "GB",
        "admin": "England",
        "difficulty": "medium",
        "lat": 51.3811,
        "lng": -2.3590,
        "clue": "Thermal springs, honey-coloured Georgian terraces, and Roman-era bathing culture point to this west-country city.",
        "reveal": "Bath is known for Roman baths and Georgian architecture.",
    },
    {
        "slug": "medium-york",
        "name": "York",
        "country": "GB",
        "admin": "England",
        "difficulty": "medium",
        "lat": 53.9590,
        "lng": -1.0815,
        "clue": "City walls, Viking heritage, a vast Gothic minster, and narrow timber-framed lanes mark this northern city.",
        "reveal": "York is a historic walled city in North Yorkshire.",
    },
    {
        "slug": "medium-bruges",
        "name": "Bruges",
        "country": "BE",
        "admin": "West Flanders",
        "difficulty": "medium",
        "lat": 51.2093,
        "lng": 3.2247,
        "clue": "Canals, stepped gables, lace shops, and a compact medieval core point to this Flemish city.",
        "reveal": "Bruges is a canal city in Belgium's Flemish region.",
    },
    {
        "slug": "medium-salzburg",
        "name": "Salzburg",
        "country": "AT",
        "admin": "Salzburg",
        "difficulty": "medium",
        "lat": 47.8095,
        "lng": 13.0550,
        "clue": "Alpine views, baroque church domes, a hill fortress, and a famous classical composer suggest this Austrian city.",
        "reveal": "Salzburg lies near the Alps and is closely associated with Mozart.",
    },
    {
        "slug": "medium-porto",
        "name": "Porto",
        "country": "PT",
        "admin": "Norte",
        "difficulty": "medium",
        "lat": 41.1579,
        "lng": -8.6291,
        "clue": "Steep streets, tiled facades, river warehouses, and fortified wine cellars point to this Portuguese city.",
        "reveal": "Porto stands beside the Douro River in northern Portugal.",
    },
    {
        "slug": "medium-bergen",
        "name": "Bergen",
        "country": "NO",
        "admin": "Vestland",
        "difficulty": "medium",
        "lat": 60.3913,
        "lng": 5.3221,
        "clue": "Colourful wooden wharf buildings, mountain rain, and fjord gateways mark this Norwegian port.",
        "reveal": "Bergen is a historic Norwegian port between mountains and fjords.",
    },
    {
        "slug": "medium-krakow",
        "name": "Krakow",
        "country": "PL",
        "admin": "Lesser Poland",
        "difficulty": "medium",
        "lat": 50.0647,
        "lng": 19.9450,
        "clue": "A huge market square, royal hill, university history, and southern Polish setting point to this city.",
        "reveal": "Krakow is a major historic city in southern Poland.",
    },
    {
        "slug": "medium-tallinn",
        "name": "Tallinn",
        "country": "EE",
        "admin": "Harju",
        "difficulty": "medium",
        "lat": 59.4370,
        "lng": 24.7536,
        "clue": "Baltic ferries, preserved towers, digital-government fame, and a walled old town suggest this capital.",
        "reveal": "Tallinn is Estonia's capital on the Gulf of Finland.",
    },
    {
        "slug": "medium-granada",
        "name": "Granada",
        "country": "ES",
        "admin": "Andalusia",
        "difficulty": "medium",
        "lat": 37.1773,
        "lng": -3.5986,
        "clue": "Moorish palace gardens, Sierra Nevada views, and Andalusian lanes identify this southern Spanish city.",
        "reveal": "Granada sits below the Sierra Nevada and is known for the Alhambra.",
    },
    {
        "slug": "medium-cardiff",
        "name": "Cardiff",
        "country": "GB",
        "admin": "Wales",
        "difficulty": "medium",
        "lat": 51.4816,
        "lng": -3.1791,
        "clue": "A castle, a redeveloped bay, and a national rugby stadium point to this Welsh capital.",
        "reveal": "Cardiff is the capital of Wales.",
    },
    {
        "slug": "hard-london-eye",
        "name": "London Eye",
        "country": "GB",
        "admin": "England",
        "difficulty": "hard",
        "lat": 51.5033,
        "lng": -0.1195,
        "clue": "Pin the riverside observation wheel opposite the parliamentary bank, just downstream from a major rail terminus.",
        "reveal": "The London Eye stands on the South Bank of the Thames.",
    },
    {
        "slug": "hard-tower-bridge",
        "name": "Tower Bridge",
        "country": "GB",
        "admin": "England",
        "difficulty": "hard",
        "lat": 51.5055,
        "lng": -0.0754,
        "clue": "Find the bascule bridge with twin towers beside a historic fortress on a bend of the Thames.",
        "reveal": "Tower Bridge crosses the Thames near the Tower of London.",
    },
    {
        "slug": "hard-trevi-fountain",
        "name": "Trevi Fountain",
        "country": "IT",
        "admin": "Lazio",
        "difficulty": "hard",
        "lat": 41.9009,
        "lng": 12.4833,
        "clue": "Place the pin on the ornate Baroque fountain tucked into a small square east of the ancient river bend.",
        "reveal": "The Trevi Fountain sits in a compact square in central Rome.",
    },
    {
        "slug": "hard-sagrada-familia",
        "name": "Sagrada Familia",
        "country": "ES",
        "admin": "Catalonia",
        "difficulty": "hard",
        "lat": 41.4036,
        "lng": 2.1744,
        "clue": "Pin the unfinished basilica with forest-like columns in the gridded district north of the old city.",
        "reveal": "Sagrada Familia is Gaudi's still-unfinished basilica in Barcelona.",
    },
    {
        "slug": "hard-brandenburg-gate",
        "name": "Brandenburg Gate",
        "country": "DE",
        "admin": "Berlin",
        "difficulty": "hard",
        "lat": 52.5163,
        "lng": 13.3777,
        "clue": "Find the neoclassical gate at the end of a grand boulevard, close to a large urban park and parliament buildings.",
        "reveal": "Brandenburg Gate stands near Tiergarten in central Berlin.",
    },
    {
        "slug": "hard-edinburgh-castle",
        "name": "Edinburgh Castle",
        "country": "GB",
        "admin": "Scotland",
        "difficulty": "hard",
        "lat": 55.9486,
        "lng": -3.1999,
        "clue": "Pin the fortress on the volcanic rock at the upper end of the medieval ridge.",
        "reveal": "Edinburgh Castle dominates Castle Rock above the Old Town.",
    },
    {
        "slug": "hard-stonehenge",
        "name": "Stonehenge",
        "country": "GB",
        "admin": "England",
        "difficulty": "hard",
        "lat": 51.1789,
        "lng": -1.8262,
        "clue": "Place the pin on the prehistoric stone circle in open chalk country west of a cathedral city.",
        "reveal": "Stonehenge stands on Salisbury Plain in Wiltshire.",
    },
    {
        "slug": "hard-clifton-suspension-bridge",
        "name": "Clifton Suspension Bridge",
        "country": "GB",
        "admin": "England",
        "difficulty": "hard",
        "lat": 51.4555,
        "lng": -2.6276,
        "clue": "Find the suspension bridge crossing a deep limestone gorge on the western edge of a harbour city.",
        "reveal": "Clifton Suspension Bridge crosses the Avon Gorge in Bristol.",
    },
    {
        "slug": "hard-falkirk-wheel",
        "name": "Falkirk Wheel",
        "country": "GB",
        "admin": "Scotland",
        "difficulty": "hard",
        "lat": 56.0003,
        "lng": -3.8416,
        "clue": "Pin the rotating boat lift linking two canals in central Scotland.",
        "reveal": "The Falkirk Wheel connects the Forth and Clyde Canal with the Union Canal.",
    },
    {
        "slug": "hard-angel-of-the-north",
        "name": "Angel of the North",
        "country": "GB",
        "admin": "England",
        "difficulty": "hard",
        "lat": 54.9141,
        "lng": -1.5895,
        "clue": "Place the pin on the huge steel-winged sculpture beside a major road south of Tyneside.",
        "reveal": "The Angel of the North stands near Gateshead.",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def valid_game_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError("Map game date must use YYYY-MM-DD format.") from error


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def normalized_scoring_radius_m(level_slug: str, value: object | None = None) -> int:
    try:
        radius_m = int(value) if value is not None else 0
    except (TypeError, ValueError):
        radius_m = 0
    if radius_m > 0:
        return radius_m
    return DEFAULT_SCORING_RADIUS_M[level_slug]


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS map_place_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            canonical_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            country_name TEXT NOT NULL DEFAULT '',
            continent TEXT NOT NULL DEFAULT '',
            admin1 TEXT,
            place_type TEXT NOT NULL DEFAULT 'place',
            difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            coordinate_precision TEXT NOT NULL DEFAULT '',
            suggested_map_zoom INTEGER,
            map_search_anchors_json TEXT NOT NULL DEFAULT '[]',
            clue_text TEXT NOT NULL,
            medium_clue_text TEXT NOT NULL DEFAULT '',
            easy_clue_text TEXT NOT NULL DEFAULT '',
            reveal_text TEXT NOT NULL DEFAULT '',
            acceptable_aliases TEXT NOT NULL DEFAULT '',
            nearby_context TEXT NOT NULL DEFAULT '',
            verified_facts_json TEXT NOT NULL DEFAULT '[]',
            sources_json TEXT NOT NULL DEFAULT '[]',
            coordinate_source_name TEXT NOT NULL DEFAULT '',
            coordinate_source_url TEXT NOT NULL DEFAULT '',
            avoid_in_clues TEXT NOT NULL DEFAULT '',
            deconflict_group TEXT NOT NULL DEFAULT '',
            fact_stability TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'approved',
            review_notes TEXT NOT NULL DEFAULT '',
            reviewed_on TEXT NOT NULL DEFAULT '',
            clue_generation_source TEXT NOT NULL DEFAULT '',
            clue_profile_hash TEXT NOT NULL DEFAULT '',
            clue_critic_mode TEXT NOT NULL DEFAULT '',
            validation_grade REAL,
            validation_reasoning TEXT NOT NULL DEFAULT '',
            scoring_radius_m INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            cooldown_until TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_map_puzzles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            puzzle_date TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('generating', 'published', 'failed')),
            generated_at TEXT,
            published_at TEXT,
            failure_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_map_levels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            puzzle_id INTEGER NOT NULL,
            level_slug TEXT NOT NULL CHECK (level_slug IN ('easy', 'medium', 'hard')),
            place_id INTEGER NOT NULL,
            max_points INTEGER NOT NULL DEFAULT 1000,
            lambda_km REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (puzzle_id) REFERENCES daily_map_puzzles(id) ON DELETE CASCADE,
            FOREIGN KEY (place_id) REFERENCES map_place_pool(id) ON DELETE RESTRICT,
            UNIQUE (puzzle_id, level_slug)
        );

        CREATE TABLE IF NOT EXISTS daily_map_guesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            level_id INTEGER NOT NULL,
            guessed_lat REAL NOT NULL,
            guessed_lng REAL NOT NULL,
            selected_name TEXT,
            revealed_hint_count INTEGER NOT NULL DEFAULT 0,
            distance_m INTEGER NOT NULL,
            score INTEGER NOT NULL,
            band TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (level_id) REFERENCES daily_map_levels(id) ON DELETE CASCADE,
            UNIQUE (user_id, level_id)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_map_levels_puzzle
        ON daily_map_levels (puzzle_id, level_slug);

        CREATE INDEX IF NOT EXISTS idx_daily_map_guesses_user_level
        ON daily_map_guesses (user_id, level_id);

        CREATE TABLE IF NOT EXISTS map_reverse_geocode_cache (
            cache_key TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            reverse_zoom INTEGER NOT NULL,
            provider TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            point_lat REAL NOT NULL,
            point_lng REAL NOT NULL,
            country_code TEXT,
            admin1 TEXT,
            display_name TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    ensure_column(conn, "map_place_pool", "scoring_radius_m", "INTEGER")
    ensure_column(conn, "map_place_pool", "country_name", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "continent", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "place_type", "TEXT NOT NULL DEFAULT 'place'")
    ensure_column(conn, "map_place_pool", "coordinate_precision", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "suggested_map_zoom", "INTEGER")
    ensure_column(conn, "map_place_pool", "map_search_anchors_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "map_place_pool", "medium_clue_text", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "easy_clue_text", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "acceptable_aliases", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "nearby_context", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "verified_facts_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "map_place_pool", "sources_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "map_place_pool", "coordinate_source_name", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "coordinate_source_url", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "avoid_in_clues", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "deconflict_group", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "fact_stability", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "review_status", "TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "map_place_pool", "review_notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "reviewed_on", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "clue_generation_source", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "clue_profile_hash", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "clue_critic_mode", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "map_place_pool", "validation_grade", "REAL")
    ensure_column(conn, "map_place_pool", "validation_reasoning", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "daily_map_guesses", "selected_name", "TEXT")
    ensure_column(
        conn,
        "daily_map_guesses",
        "revealed_hint_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    seed_starter_places(conn)
    backfill_missing_scoring_radii(conn)
    backfill_daily_map_guess_scores(conn)


def seed_starter_places(conn: sqlite3.Connection) -> None:
    now = utc_now()
    for place in STARTER_PLACES:
        difficulty = str(place["difficulty"])
        scoring_radius_m = normalized_scoring_radius_m(difficulty, place.get("radius_m"))
        place_type = str(
            place.get("place_type")
            or ("landmark" if difficulty == "hard" else "place")
        )
        verified_facts = place.get("verified_facts") or []
        sources = place.get("sources") or []
        conn.execute(
            """
            INSERT INTO map_place_pool (
                slug, canonical_name, country_code, admin1, place_type, difficulty, lat, lng,
                clue_text, medium_clue_text, easy_clue_text, reveal_text,
                acceptable_aliases, nearby_context, verified_facts_json, sources_json,
                avoid_in_clues, review_status, review_notes, scoring_radius_m, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(slug) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                country_code = excluded.country_code,
                admin1 = excluded.admin1,
                place_type = excluded.place_type,
                difficulty = excluded.difficulty,
                lat = excluded.lat,
                lng = excluded.lng,
                clue_text = excluded.clue_text,
                medium_clue_text = CASE
                    WHEN excluded.medium_clue_text <> '' THEN excluded.medium_clue_text
                    ELSE map_place_pool.medium_clue_text
                END,
                easy_clue_text = CASE
                    WHEN excluded.easy_clue_text <> '' THEN excluded.easy_clue_text
                    ELSE map_place_pool.easy_clue_text
                END,
                reveal_text = excluded.reveal_text,
                acceptable_aliases = excluded.acceptable_aliases,
                nearby_context = excluded.nearby_context,
                verified_facts_json = CASE
                    WHEN excluded.verified_facts_json <> '[]' THEN excluded.verified_facts_json
                    ELSE map_place_pool.verified_facts_json
                END,
                sources_json = CASE
                    WHEN excluded.sources_json <> '[]' THEN excluded.sources_json
                    ELSE map_place_pool.sources_json
                END,
                avoid_in_clues = excluded.avoid_in_clues,
                review_status = map_place_pool.review_status,
                review_notes = CASE
                    WHEN excluded.review_notes <> '' THEN excluded.review_notes
                    ELSE map_place_pool.review_notes
                END,
                scoring_radius_m = excluded.scoring_radius_m
            """,
            (
                place["slug"],
                place["name"],
                place["country"],
                place["admin"],
                place_type,
                difficulty,
                place["lat"],
                place["lng"],
                place["clue"],
                str(place.get("medium_clue") or ""),
                str(place.get("easy_clue") or ""),
                place["reveal"],
                str(place.get("aliases") or ""),
                str(place.get("nearby_context") or ""),
                json.dumps(verified_facts if isinstance(verified_facts, list) else []),
                json.dumps(sources if isinstance(sources, list) else []),
                str(place.get("avoid_in_clues") or ""),
                str(place.get("review_status") or "approved"),
                str(place.get("review_notes") or ""),
                scoring_radius_m,
                now,
            ),
        )


def backfill_missing_scoring_radii(conn: sqlite3.Connection) -> None:
    for difficulty, radius_m in DEFAULT_SCORING_RADIUS_M.items():
        conn.execute(
            """
            UPDATE map_place_pool
            SET scoring_radius_m = ?
            WHERE difficulty = ?
              AND (scoring_radius_m IS NULL OR scoring_radius_m <= 0)
            """,
            (radius_m, difficulty),
        )


def commit_if_needed(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.commit()


def get_or_create_puzzle(conn: sqlite3.Connection, puzzle_date: str) -> sqlite3.Row:
    conn.execute(
        """
        INSERT OR IGNORE INTO daily_map_puzzles (puzzle_date, status)
        VALUES (?, 'generating')
        """,
        (puzzle_date,),
    )
    return conn.execute(
        "SELECT * FROM daily_map_puzzles WHERE puzzle_date = ?",
        (puzzle_date,),
    ).fetchone()


def set_puzzle_status(
    conn: sqlite3.Connection,
    puzzle_date: str,
    status: str,
    *,
    failure_reason: str | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE daily_map_puzzles
        SET status = ?,
            generated_at = CASE WHEN ? = 'published' THEN COALESCE(generated_at, ?) ELSE generated_at END,
            published_at = CASE WHEN ? = 'published' THEN ? ELSE published_at END,
            failure_reason = ?
        WHERE puzzle_date = ?
        """,
        (status, status, now, status, now, failure_reason, puzzle_date),
    )


def recent_cutoff(puzzle_date: str) -> str:
    current = datetime.strptime(puzzle_date, "%Y-%m-%d").date()
    return (current - timedelta(days=RECENT_USE_DAYS)).isoformat()


def select_place(conn: sqlite3.Connection, puzzle_date: str, difficulty: str) -> sqlite3.Row | None:
    params = (difficulty, puzzle_date, recent_cutoff(puzzle_date), puzzle_date)
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE difficulty = ?
          AND active = 1
          AND clue_text <> ''
          AND reveal_text <> ''
          AND (cooldown_until IS NULL OR cooldown_until < ?)
          AND id NOT IN (
              SELECT daily_map_levels.place_id
              FROM daily_map_levels
              INNER JOIN daily_map_puzzles
                  ON daily_map_puzzles.id = daily_map_levels.puzzle_id
              WHERE daily_map_puzzles.puzzle_date >= ?
                AND daily_map_puzzles.puzzle_date <= ?
        )
        ORDER BY COALESCE(validation_grade, 0) DESC, id
        """,
        params,
    ).fetchall()
    row = best_quality_place(rows, puzzle_date=puzzle_date)
    if row is not None:
        return row
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE difficulty = ?
          AND active = 1
          AND clue_text <> ''
          AND reveal_text <> ''
        ORDER BY COALESCE(validation_grade, 0) DESC, id
        """,
        (difficulty,),
    ).fetchall()
    return best_quality_place(rows, puzzle_date=puzzle_date)


def select_daily_place(conn: sqlite3.Connection, puzzle_date: str) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE active = 1
          AND clue_text <> ''
          AND reveal_text <> ''
          AND (cooldown_until IS NULL OR cooldown_until < ?)
          AND id NOT IN (
              SELECT daily_map_levels.place_id
              FROM daily_map_levels
              INNER JOIN daily_map_puzzles
                  ON daily_map_puzzles.id = daily_map_levels.puzzle_id
              WHERE daily_map_puzzles.puzzle_date >= ?
                AND daily_map_puzzles.puzzle_date <= ?
        )
        ORDER BY COALESCE(validation_grade, 0) DESC, id
        """,
        (puzzle_date, recent_cutoff(puzzle_date), puzzle_date),
    ).fetchall()
    row = best_quality_place(rows, puzzle_date=puzzle_date)
    if row is not None:
        return row
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE active = 1
          AND clue_text <> ''
          AND reveal_text <> ''
        ORDER BY COALESCE(validation_grade, 0) DESC, id
        """,
    ).fetchall()
    return best_quality_place(rows, puzzle_date=puzzle_date)


def map_learning_profile_hash(path: str = DEFAULT_MAP_LEARNING_PROFILE_PATH) -> str:
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(payload).hexdigest()[:16]


def selected_qa_place(
    conn: sqlite3.Connection,
    place_id: int,
    *,
    require_current_profile: bool = True,
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE id = ?
          AND active = 1
          AND clue_text <> ''
          AND reveal_text <> ''
        """,
        (place_id,),
    ).fetchone()
    if row is None or not row_passes_map_clue_quality(row):
        return None
    if require_current_profile:
        current_profile_hash = map_learning_profile_hash()
        if not current_profile_hash or str(row["clue_profile_hash"] or "") != current_profile_hash:
            return None
    return row


def generate_daily_map_game(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    force: bool = False,
    preferred_place_id: int | None = None,
    require_current_profile_for_qa: bool = True,
    log: Any | None = None,
) -> dict[str, Any]:
    puzzle_date = valid_game_date(puzzle_date)
    initialize_database(conn)
    puzzle = get_or_create_puzzle(conn, puzzle_date)
    if puzzle["status"] == "published" and not force:
        return puzzle_status(conn, puzzle_date)

    if force:
        conn.execute(
            """
            DELETE FROM daily_map_guesses
            WHERE level_id IN (
                SELECT daily_map_levels.id
                FROM daily_map_levels
                INNER JOIN daily_map_puzzles
                    ON daily_map_puzzles.id = daily_map_levels.puzzle_id
                WHERE daily_map_puzzles.puzzle_date = ?
            )
            """,
            (puzzle_date,),
        )
        conn.execute(
            """
            DELETE FROM daily_map_levels
            WHERE puzzle_id = ?
            """,
            (puzzle["id"],),
        )

    conn.execute(
        """
        UPDATE daily_map_puzzles
        SET status = 'generating', failure_reason = NULL
        WHERE id = ?
        """,
        (puzzle["id"],),
    )

    place = (
        selected_qa_place(
            conn,
            preferred_place_id,
            require_current_profile=require_current_profile_for_qa,
        )
        if preferred_place_id is not None
        else select_daily_place(conn, puzzle_date)
    )
    if place is None:
        reason = (
            f"Requested QA map place {preferred_place_id} is unavailable or fails the clue quality gate."
            if preferred_place_id is not None
            else "No active map-game place is available."
        )
        set_puzzle_status(conn, puzzle_date, "failed", failure_reason=reason)
        if log is not None:
            log(reason)
        return puzzle_status(conn, puzzle_date)

    now = utc_now()
    difficulty = place["difficulty"]
    config = SCORE_CONFIG[difficulty]
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_map_levels (
            puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            puzzle["id"],
            difficulty,
            place["id"],
            config["max_points"],
            config["lambda_km"],
            now,
        ),
    )

    set_puzzle_status(conn, puzzle_date, "published")
    if log is not None:
        log(f"Published daily map game for {puzzle_date}")
    return puzzle_status(conn, puzzle_date)


def puzzle_status(conn: sqlite3.Connection, puzzle_date: str) -> dict[str, Any]:
    puzzle_date = valid_game_date(puzzle_date)
    row = conn.execute(
        """
        SELECT *
        FROM daily_map_puzzles
        WHERE puzzle_date = ?
        """,
        (puzzle_date,),
    ).fetchone()
    if row is None:
        return {
            "date": puzzle_date,
            "status": "missing",
            "acceptedLevels": 0,
            "failureReason": None,
            "updatedAt": None,
        }
    accepted = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM daily_map_levels
        WHERE puzzle_id = ?
        """,
        (row["id"],),
    ).fetchone()["count"]
    return {
        "date": row["puzzle_date"],
        "status": row["status"],
        "acceptedLevels": accepted,
        "failureReason": row["failure_reason"],
        "updatedAt": row["published_at"] or row["generated_at"],
    }


def level_rows(conn: sqlite3.Connection, puzzle_date: str, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            daily_map_levels.id AS level_id,
            daily_map_levels.level_slug,
            daily_map_levels.max_points,
            daily_map_levels.lambda_km,
            map_place_pool.canonical_name,
            map_place_pool.country_code,
            map_place_pool.admin1,
            map_place_pool.lat AS answer_lat,
            map_place_pool.lng AS answer_lng,
            map_place_pool.clue_text,
            map_place_pool.medium_clue_text,
            map_place_pool.easy_clue_text,
            map_place_pool.map_search_anchors_json,
            map_place_pool.reveal_text,
            map_place_pool.scoring_radius_m,
            daily_map_guesses.id AS guess_id,
            daily_map_guesses.guessed_lat,
            daily_map_guesses.guessed_lng,
            daily_map_guesses.selected_name,
            daily_map_guesses.revealed_hint_count,
            daily_map_guesses.distance_m,
            daily_map_guesses.score,
            daily_map_guesses.band,
            daily_map_guesses.completed_at
        FROM daily_map_puzzles
        INNER JOIN daily_map_levels
            ON daily_map_levels.puzzle_id = daily_map_puzzles.id
        INNER JOIN map_place_pool
            ON map_place_pool.id = daily_map_levels.place_id
        LEFT JOIN daily_map_guesses
            ON daily_map_guesses.level_id = daily_map_levels.id
            AND daily_map_guesses.user_id = ?
        WHERE daily_map_puzzles.puzzle_date = ?
          AND daily_map_puzzles.status = 'published'
        ORDER BY
            CASE daily_map_levels.level_slug
                WHEN 'easy' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END
        """,
        (user_id, puzzle_date),
    ).fetchall()


def daily_bundle_payload(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    user_id: int,
) -> dict[str, Any]:
    puzzle_date = valid_game_date(puzzle_date)
    puzzle = conn.execute(
        """
        SELECT *
        FROM daily_map_puzzles
        WHERE puzzle_date = ? AND status = 'published'
        """,
        (puzzle_date,),
    ).fetchone()
    if puzzle is None:
        raise LookupError("No published map game exists for that date.")

    rows = level_rows(conn, puzzle_date, user_id)
    rows = rows[:1]
    return {
        "date": puzzle_date,
        "status": "published",
        "maxScore": MAP_MAX_SCORE if rows else 0,
        "completedLevels": sum(1 for row in rows if row["guess_id"] is not None),
        "levels": [serialize_level(row) for row in rows],
    }


COUNTRY_NAMES = {
    "AT": "Austria",
    "AU": "Australia",
    "BE": "Belgium",
    "BR": "Brazil",
    "DE": "Germany",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FR": "France",
    "GB": "the United Kingdom",
    "IT": "Italy",
    "JP": "Japan",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "US": "the United States",
    "ZA": "South Africa",
}


def country_name(country_code: object) -> str:
    code = str(country_code or "").upper()
    return COUNTRY_NAMES.get(code, code or "the world")


def mask_answer_name(text: object, answer_name: object) -> str:
    value = str(text or "").strip()
    name = str(answer_name or "").strip()
    if not value:
        return ""
    if not name:
        return value
    return re.sub(re.escape(name), "This place", value, flags=re.IGNORECASE)


def parse_json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def split_list_text(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def place_is_explicitly_excluded(row: sqlite3.Row | dict[str, Any]) -> bool:
    try:
        name = row["canonical_name"]  # type: ignore[index]
    except (KeyError, IndexError):
        return False
    return str(name or "").casefold().strip() in MAP_EXCLUDED_CANONICAL_NAMES


def public_place_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    def get(key: str, default: Any = "") -> Any:
        try:
            value = row[key]  # type: ignore[index]
        except (KeyError, IndexError):
            return default
        return default if value is None else value

    return {
        "canonical_name": str(get("canonical_name")).strip(),
        "place_type": str(get("place_type", "place")).strip() or "place",
        "country_code": str(get("country_code")).strip(),
        "country_name": str(get("country_name")).strip() or country_name(get("country_code")),
        "continent": str(get("continent")).strip(),
        "admin1": str(get("admin1")).strip(),
        "difficulty": str(get("difficulty")).strip(),
        "lat": float(get("lat", 0)),
        "lng": float(get("lng", 0)),
        "coordinate_precision": str(get("coordinate_precision")).strip(),
        "suggested_map_zoom": get("suggested_map_zoom", None),
        "map_search_anchors": parse_json_list(get("map_search_anchors_json")),
        "acceptable_aliases": split_list_text(get("acceptable_aliases")),
        "nearby_context": str(get("nearby_context")).strip(),
        "verified_facts": [str(item).strip() for item in parse_json_list(get("verified_facts_json")) if str(item).strip()],
        "sources": parse_json_list(get("sources_json")),
        "coordinate_source": {
            "name": str(get("coordinate_source_name")).strip(),
            "url": str(get("coordinate_source_url")).strip(),
        },
        "avoid_in_clues": str(get("avoid_in_clues")).strip(),
        "deconflict_group": str(get("deconflict_group")).strip(),
        "fact_stability": str(get("fact_stability")).strip(),
        "validation_grade": get("validation_grade", None),
        "validation_reasoning": str(get("validation_reasoning")).strip(),
        "reveal_text": str(get("reveal_text")).strip(),
    }


def fact_hook_categories(text: object) -> set[str]:
    value = str(text or "")
    return {
        category
        for category, pattern in MAP_PLACE_HOOK_CATEGORY_PATTERNS
        if pattern.search(value)
    }


def fact_interest_score(text: object) -> int:
    value = str(text or "").strip()
    if not value:
        return 0
    categories = fact_hook_categories(value)
    score = 0
    score += min(4, len(clue_support_terms(value)) // 2)
    score += min(8, len(categories) * 3)
    if MAP_CLUE_KNOWN_FOR_RE.search(value):
        score += 3
    if MAP_CLUE_HISTORIC_YEAR_RE.search(value):
        score += 2
    if MAP_PLACE_LOW_INTEREST_FACT_RE.search(value):
        score -= 5
    if clue_uses_coordinate_or_code_targeting(value):
        score -= 6
    if clue_is_location_or_generic_geo_framed(value) and not categories:
        score -= 4
    return max(0, score)


def facts_are_distinct(left: object, right: object) -> bool:
    left_terms = clue_support_terms(left)
    right_terms = clue_support_terms(right)
    if not left_terms or not right_terms:
        return True
    overlap = len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))
    return overlap < 0.62


def persuading_place_facts(place: dict[str, Any]) -> list[dict[str, Any]]:
    facts = place.get("verified_facts")
    if not isinstance(facts, list):
        return []
    scored = [
        {
            "text": str(fact).strip(),
            "score": fact_interest_score(fact),
            "categories": sorted(fact_hook_categories(fact)),
        }
        for fact in facts
        if str(fact).strip()
    ]
    scored.sort(key=lambda item: (int(item["score"]), len(item["categories"]), item["text"]), reverse=True)
    selected: list[dict[str, Any]] = []
    for item in scored:
        if int(item["score"]) < MAP_PLACE_PERSUADING_FACT_SCORE:
            continue
        if all(facts_are_distinct(item["text"], existing["text"]) for existing in selected):
            selected.append(item)
    return selected


def map_workoutability_score(row: sqlite3.Row | dict[str, Any]) -> int:
    place = public_place_payload(row)
    context = str(place.get("nearby_context") or "").strip()
    if not context or MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0

    score = 0
    anchors = {
        match.group(0).casefold()
        for match in MAP_WORKOUTABILITY_ANCHOR_RE.finditer(context)
    }
    score += min(6, len(anchors) * 2)
    if MAP_WORKOUTABILITY_ACTION_RE.search(context):
        score += 3
    if len(context.split()) >= 10:
        score += 1
    if any(character.isupper() for character in context[1:]):
        score += 1
    return min(12, score)


def map_place_interest_profile(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    place = public_place_payload(row)
    persuading_facts = persuading_place_facts(place)
    workoutability_score = map_workoutability_score(row)
    categories = sorted(
        {
            category
            for fact in persuading_facts
            for category in fact["categories"]
        }
    )
    try:
        validation_grade = float(place.get("validation_grade") or 0)
    except (TypeError, ValueError):
        validation_grade = 0
    validation_grade = max(0.0, min(10.0, validation_grade))
    persuading_count = len(persuading_facts)
    score = int(round(validation_grade * 2))
    score += min(MAP_PLACE_REQUIRED_PERSUADING_FACTS, persuading_count) * 18
    score += min(4, len(categories)) * 5
    score += 5 if "visual_landmark" in categories else 0
    score += min(8, workoutability_score)
    if persuading_count < MAP_PLACE_REQUIRED_PERSUADING_FACTS:
        score -= (MAP_PLACE_REQUIRED_PERSUADING_FACTS - persuading_count) * 20
    return {
        "score": max(0, score),
        "persuadingFactCount": persuading_count,
        "persuadingFacts": persuading_facts[:MAP_PLACE_REQUIRED_PERSUADING_FACTS],
        "categories": categories,
        "validationGrade": validation_grade,
        "workoutabilityScore": workoutability_score,
    }


def load_map_selector_profile(path: str = DEFAULT_MAP_SELECTOR_PROFILE_PATH) -> dict[str, Any]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return profile if isinstance(profile, dict) else {}


def map_selector_feedback_adjustment(
    place: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    categories: list[str],
) -> int:
    if not isinstance(profile, dict) or not profile:
        return 0
    adjustment = 0
    type_adjustments = profile.get("type_adjustments")
    if isinstance(type_adjustments, dict):
        try:
            adjustment += int(round(float(type_adjustments.get(place["place_type"], 0))))
        except (TypeError, ValueError):
            pass
    category_adjustments = profile.get("category_adjustments")
    if isinstance(category_adjustments, dict):
        for category in categories:
            try:
                adjustment += int(round(float(category_adjustments.get(category, 0))))
            except (TypeError, ValueError):
                continue
    return adjustment


def map_place_selection_profile(
    row: sqlite3.Row | dict[str, Any],
    selector_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = map_place_interest_profile(row)
    place = public_place_payload(row)
    adjustment = map_selector_feedback_adjustment(
        place,
        selector_profile,
        categories=[str(category) for category in profile["categories"]],
    )
    return {
        **profile,
        "baseScore": profile["score"],
        "score": max(0, int(profile["score"]) + adjustment),
        "feedbackAdjustment": adjustment,
    }


def map_clue_schema() -> dict[str, Any]:
    return {
        "hard": "A clear answer-safe rendering of the locked recognition hook; no answer name or geography.",
        "medium": "A different clue that materially narrows the broad geographic scope; no answer name.",
        "easy": "A practical local-area map route using anchors visible by map zoom 11; no answer name.",
        "reveal": "One or two player-facing sentences that name the place, say what it is, and explain a memorable fact.",
    }


def map_clue_critic_schema() -> dict[str, Any]:
    return {
        "passed": True,
        "scores": {field: 10 for field in MAP_CLUE_CRITIC_THRESHOLDS},
        "failure_reasons": [],
        "feedback_to_generator": [],
    }


def merge_feedback_entries(*groups: list[str], limit: int = 8) -> list[str]:
    feedback: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            text = str(value or "").strip()
            normalized = re.sub(r"\s+", " ", text).casefold()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            feedback.append(text)
            if len(feedback) >= limit:
                return feedback
    return feedback


def map_clue_learning_profile_feedback(
    profile_path: str,
    *,
    place_type: str,
    difficulty: str,
    limit: int = 6,
) -> list[str]:
    if not profile_path:
        return []
    try:
        with open(profile_path, "r", encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(profile, dict):
        return []
    by_slot = profile.get("feedback_by_slot")
    if not isinstance(by_slot, dict):
        return []
    groups: list[list[str]] = []
    for key in ("global", f"{place_type}/*", f"*/{difficulty}", f"{place_type}/{difficulty}"):
        values = by_slot.get(key)
        if isinstance(values, list):
            groups.append([str(value) for value in values if str(value).strip()])
    return merge_feedback_entries(*groups, limit=limit)


def map_clue_learning_profile_ladder_feedback(
    profile_path: str,
    *,
    place_type: str,
    common_limit: int = 2,
    per_level_limit: int = 2,
    examples_per_level: int = 2,
    complete_ladder_examples: int = 1,
) -> list[str]:
    if not profile_path:
        return []
    try:
        with open(profile_path, "r", encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(profile, dict):
        return []
    by_slot = profile.get("feedback_by_slot")
    if not isinstance(by_slot, dict):
        return []

    global_values = by_slot.get("global")
    common = merge_feedback_entries(
        [str(value) for value in global_values] if isinstance(global_values, list) else [],
        limit=common_limit,
    )
    feedback = list(common)
    examples_by_level = profile.get("approved_examples_by_level")
    if not isinstance(examples_by_level, dict):
        examples_by_level = {}
    for level in ("hard", "medium", "easy"):
        exact_values = by_slot.get(f"{place_type}/{level}")
        wildcard_values = by_slot.get(f"*/{level}")
        level_feedback = merge_feedback_entries(
            [str(value) for value in exact_values] if isinstance(exact_values, list) else [],
            [str(value) for value in wildcard_values] if isinstance(wildcard_values, list) else [],
            limit=per_level_limit,
        )
        for item in level_feedback:
            feedback.append(f"{level.upper()}: {item}")
        examples = examples_by_level.get(level)
        if not isinstance(examples, list):
            continue
        normalized_place_type = re.sub(r"[\s_-]+", " ", place_type).strip().casefold()
        ordered_examples = sorted(
            [item for item in examples if isinstance(item, dict)],
            key=lambda item: (
                0
                if re.sub(r"[\s_-]+", " ", str(item.get("place_type") or "")).strip().casefold()
                == normalized_place_type
                else 1,
                -float(item.get("training_weight") or 0),
                str(item.get("example_id") or ""),
            ),
        )
        for example in ordered_examples[:examples_per_level]:
            clue = str(example.get("clue") or "").strip()
            if not clue:
                continue
            example_type = str(example.get("place_type") or "place").strip()
            why = str(example.get("why_it_passed") or "").strip()
            suffix = f" Review: {why}" if why else ""
            feedback.append(
                f"{level.upper()} APPROVED EXAMPLE ({example_type}): {clue}{suffix}"
            )

    approved_ladders = profile.get("approved_ladders")
    if isinstance(approved_ladders, list) and complete_ladder_examples > 0:
        normalized_place_type = re.sub(r"[\s_-]+", " ", place_type).strip().casefold()
        ordered_ladders = sorted(
            [item for item in approved_ladders if isinstance(item, dict)],
            key=lambda item: (
                0
                if re.sub(
                    r"[\s_-]+",
                    " ",
                    str(item.get("place_type") or ""),
                ).strip().casefold()
                == normalized_place_type
                else 1,
                str(item.get("example_id") or ""),
            ),
        )
        for example in ordered_ladders[:complete_ladder_examples]:
            ladder = example.get("clue_ladder")
            if not isinstance(ladder, dict):
                continue
            hard = str(ladder.get("hard") or "").strip()
            medium = str(ladder.get("medium") or "").strip()
            easy = str(ladder.get("easy") or "").strip()
            if not hard or not medium or not easy:
                continue
            example_type = str(example.get("place_type") or "place").strip()
            why = str(example.get("why_the_ladder_passed") or "").strip()
            generalisation = str(example.get("generalisation_note") or "").strip()
            review = " ".join(value for value in (why, generalisation) if value)
            suffix = f" Review: {review}" if review else ""
            feedback.append(
                f"GOLD COMPLETE LADDER ({example_type}): "
                f"HARD: {hard} MEDIUM: {medium} EASY: {easy}{suffix}"
            )
    return merge_feedback_entries(
        feedback,
        limit=common_limit
        + (3 * (per_level_limit + examples_per_level))
        + complete_ladder_examples,
    )


def map_clue_generator_prompt(
    place: dict[str, Any],
    recent_places: list[dict[str, Any]],
    feedback: list[str],
) -> str:
    required_hard_hook = str(place.get("required_hard_hook") or "").strip()
    locked_hook_section = (
        f"""
Locked verified recognition hook:
{required_hard_hook}

The hard clue must be an answer-safe rendering of this exact hook. Do not replace it with another fact.
Preserve the details that make the hook distinctive: its incident, story, record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment.
"""
        if required_hard_hook
        else ""
    )
    return f"""You are generating clue ladders for a daily map quiz.

Create exactly one four-step clue ladder for the target place.

Target place:
{json.dumps(place, indent=2)}
{locked_hook_section}

Rules:
- Each clue must add new information; do not repeat the same fact with more explicit wording.
- Write for an adult player reading on a phone: concise, natural, concrete sentences without childish wording.
- Prefer one clear sentence per field, but retain the information needed to make a clue fair.
- Avoid long clause chains, semicolons, and formal filler such as "serving as", "situated within", or "prominent".
- Use only details supported by the target place's verified_facts, nearby_context, or validation_reasoning.
- Do not invent landmarks, industries, products, museums, events, or historical claims absent from the target data.
- Build a fair solving path: the player should feel challenged but still be able to beat the game.
- Hard is a recognition hook that could identify this place to somebody who knows the story.
- Prefer a unique, specific incident or story. A genuinely distinctive record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment is also valid.
- Do not manufacture a hook from architecture, an architect, construction, appearance, age, dimensions, generic destruction, or a broad association.
- When a locked verified hook is supplied, preserve the people, action, defining method, outcome, record, consequence, or other details that make it recognisable.
- An event hook must contain enough of the event to be memorable rather than reducing it to a headline. A concrete defining method can provide that detail even when the event has no settled outcome.
- For a team match or final, name both teams and the result; do not substitute a scorer or attendance figure for the competing sides.
- Keep hard to one coherent event, record, or story. Never merge separate matches or incidents, or imply that an event happened during a different match.
- Verify the exact competition stage, date, participants, result, and relationship between claims. A record may cite the events that establish it, but must omit unrelated anecdotes.
- Country names are allowed in hard only when they are the proper names of teams or other essential participants in the event. Do not anonymise a national team as "the host nation" to avoid its name.
- Tie the hook to the target with an answer-safe phrase such as "here", "on this pitch", "inside this church", or "at this site".
- Preserve the target's answer-safe functional identity. Say "this island prison", "on this pitch", "inside this church", or "this bridge" when supported. Do not replace a useful identity such as prison, island, stadium, bridge, or church with only "this site" or "here".
- Hard must contain only the recognition hook. Do not add country, nationality, capital, region, river, direction, or nearby-place hints; those belong later.
- A date, founder, commissioner, ruler, architect, construction fact, or former record is not enough by itself.
- Medium must materially reduce the geographic search area from the world to a useful country, region, culture, language, city, or equivalent scope.
- Medium may use a place-owned story, person, naming link, institution, record, or other fact to give that narrowing character, but the extra fact is optional and geographic progress is mandatory.
- State medium's useful relationship directly. Remove generic padding about crowds, popularity, prestige, fame, or being a historic venue.
- Never write "a famous collection", "a well-known writer", or a similar vague cultural label. Naming a creator beside that vague label does not fix it. State the concrete answer-safe relationship instead: what the creator, characters, or work did with this place. If a title leaks the target, omit the title but keep that specific relationship.
- Clearly identify fictional or imaginary people and events as fiction. Do not phrase an author's characters as though they were historical people.
- Valid medium mechanisms include regional or national identity, local language, a club or institution that exposes its city, an answer-safe naming story with geographic identity, or another relationship that clearly reduces plausible areas.
- Do not force every medium clue into the same template. A named person, naming fact, and nationality worked together in one approved example, but other mechanisms are valid when they provide comparable solving value.
- A second incident, ritual, person, record, or story does not qualify as medium unless it also narrows the geography.
- Generic narrowing such as cliffs, coast, hills, countryside, or a nearby city is not enough when it could describe many places.
- Do not anonymise the medium clue's distinctive detail as "a famous journalist", "a prominent architect", or another unnamed role. Name the person when answer-safe, or use a different precise fact.
- Easy continues from medium rather than repeating its country, region, or city.
- The target includes locality_name when a city, town, or municipality is available from reverse geocoding at zoom 10. By the end of easy, medium or easy must explicitly name that locality unless the locality itself is the answer.
- Never introduce an unnamed place with "the city", "this city", "the town", or "the area". If medium has only reached a region or culture, easy must explicitly name the locality before giving smaller directions.
- Easy must also give a broad route within that locality, such as northern, southern, eastern, western, central, or the city centre. Merely naming the locality and then relying on a district, road, or station is not enough.
- Easy must narrow to a local area inside that scope: for example a borough, district, quarter, neighbourhood, city sector, river crossing, park, station, or named nearby landmark.
- The easy clue's essential local anchor must be visible or labelled by zoom 11 or earlier on the quiz's Esri World Topographic Map. The player may zoom further to place the pin, but should not need a label that first appears at zoom 12 or later.
- Prefer persistent visible geography such as a city centre, cardinal city sector, major river, coast, or large park over motorway and road numbers. A road number may only be supplementary after a complete route and must be visibly labelled on the quiz map.
- A later neighbourhood or district label may only supplement a lower-zoom route. Base the route on a larger visible anchor such as the city, municipality, major river or coast, major park, transport feature, or similarly useful map feature, then give a practical direction or relationship within it.
- Verify that a claimed borough, district, quarter, or neighbourhood is the target's technical location. Do not use a place's popular association with a nearby district as though the target were inside it.
- Easy must work on the quiz's street map at normal playable zoom; do not rely on roof colours, seat colours, interior details, or aerial imagery.
- A city or country name alone is not an easy clue. It must tell the player where to work within that area.
- Use different information at each level; do not write three rewordings of the same feature.
- Never include the canonical_name or aliases before the final reveal.
- Never use latitude, longitude, coordinates, ISO country codes, database-like labels, or time zones as clues.
- Avoid formulaic dataset wording such as "mapped urban centre", "national-map setting", and "located at".
- Do not use a clue that merely says the place is a capital, large city, coastal city, near something, beside something, or on a river.
- Do not use awkward placeholders such as "the place", "the target place", or "the answer" inside clue text.
- Do not write a proper-noun clue that only works by hiding the answer name, such as "Tower of [answer]"; choose another known-for hook or describe the landmark naturally.
- Prefer source-backed, stable facts. State whether a record is current or former when that distinction matters.
- Keep each clue comfortable to read on a phone without deleting essential information merely to meet a count.
- The reveal is shown after scoring. Write one or two player-facing sentences, not a validation note about the clues.
- Begin the reveal with the exact canonical_name and plainly say what kind of place it is or why it matters.
- Explain one memorable fact and, when useful, its geographic connection. The player should learn something even after the round ends.
- Do not write "fits because", "matches because", "ties together", "the clues point to", or discuss why the clue ladder is valid.
- The reveal may name the answer, but must not use coordinate metadata or database language.

Recent map places to avoid repeating:
{json.dumps(recent_places[-12:], indent=2)}

Previous failed attempts and learning-profile feedback:
The APPROVED EXAMPLE entries demonstrate clue purpose and style only. Never copy their facts, names, or proper nouns into this target's clues.
{json.dumps(feedback[-14:], indent=2)}

Return JSON only using this structure:
{json.dumps(map_clue_schema(), indent=2)}
"""


def map_clue_critic_prompt(
    place: dict[str, Any],
    clue_ladder: dict[str, Any],
    recent_places: list[dict[str, Any]],
) -> str:
    return f"""You are a strict critic for a daily map quiz clue ladder.

Target place:
{json.dumps(place, indent=2)}

Clue ladder:
{json.dumps(clue_ladder, indent=2)}

Recent map places:
{json.dumps(recent_places[-12:], indent=2)}

Fail the ladder if:
- Any clue before reveal includes the answer name or an accepted alias.
- Hard, medium, and easy all say substantially the same thing.
- Hard lacks a memorable recognition hook: preferably a specific incident or story, or otherwise a distinctive record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment.
- Hard is technically true but too generic to associate with one place.
- Hard substitutes architecture, an architect, construction, appearance, age, dimensions, generic destruction, broad history, or a former record for a recognisable place-owned hook.
- A locked verified hook is supplied but hard changes or omits the details that make it distinctive.
- An event hook merely says that something happened without the people, action, defining method, outcome, consequence, record, or significance needed to make it memorable.
- A team match or final anonymises either competing side as "the host nation", "the visitors", or another generic label instead of naming both teams.
- Hard merges separate matches or incidents, misstates a competition stage, or implies that one event happened during another.
- Hard does not make clear that its hook belongs to this target.
- Hard hides a supported answer-safe target identity such as island, prison, stadium, bridge, or church behind only "this site" or "here".
- Hard includes a distinctive word from the target name, even when it avoids the full canonical name.
- Hard only gives a construction date, founder, commissioner, ruler, architect, or opening date without an unusual one-place detail.
- Medium does not materially reduce the geographic search area to a useful country, region, culture, language, city, or equivalent scope.
- Medium is merely another event, ritual, person, record, or story without geographic progress.
- Medium uses generic scenery or proximity that could fit many areas.
- Medium pads a useful name or relationship with generic crowd, popularity, prestige, fame, or "historic venue" wording instead of stating the solving fact directly.
- Medium uses "a famous collection", "a well-known writer", or another vague cultural label, even if a creator is named beside it, instead of stating the concrete answer-safe relationship.
- Medium presents fictional characters or events as though they were historical facts.
- Medium replaces its distinctive detail with an unnamed generic role such as "a famous journalist" or "a prominent architect".
- Easy does not continue from medium into a local area such as a borough, district, quarter, neighbourhood, city sector, river crossing, park, station, or named nearby landmark.
- A locality_name is supplied, but neither medium nor easy explicitly names it before referring to "the city", a district, a road, or another smaller feature.
- Easy names the locality but gives no broad city-sector route before relying on a district, road, station, or other potentially deep-zoom detail.
- Easy merely repeats a country, region, or city without saying where to work inside it.
- Easy's essential local anchor first appears after zoom 11 on the quiz's Esri World Topographic Map. A later district label is acceptable only as supplementary information beside a usable lower-zoom route.
- Easy depends on a motorway or road number that is absent, localised differently, or only visible at deep zoom on the quiz map.
- Easy claims that the target is inside a borough, district, quarter, or neighbourhood based only on popular association rather than its verified technical location.
- Easy relies on colour, interior detail, or another feature that is not visible on the quiz's street map.
- A clue gives generic geography without helping the player narrow or pin the answer.
- A clue is bland, generic, unverifiable, or could fit many places.
- A clue introduces a landmark, industry, product, institution, event, or historical claim not supported by the target data.
- The difficulty progression is wrong.
- The reveal does not explain the answer.
- The reveal does not spell the canonical_name exactly.
- The reveal discusses how the clues fit, match, or validate the answer instead of teaching the player what the place is and why it matters.
- A clue uses coordinates, ISO codes, time zones, or formulaic dataset phrasing.
- A clue uses placeholder wording such as "the place", "the target place", or "the answer".
- The reveal reads like database metadata instead of a short explanation.
- The ladder repeats recent clue hooks too closely.

Score every dimension with an integer from 0 to 10.
Set passed to true only if every score meets these thresholds:
{json.dumps(MAP_CLUE_CRITIC_THRESHOLDS, indent=2)}

Return JSON only using this structure:
{json.dumps(map_clue_critic_schema(), indent=2)}
"""


def normalize_generated_clue_ladder(payload: dict[str, Any]) -> dict[str, str]:
    ladder: dict[str, str] = {}
    for field in MAP_CLUE_REQUIRED_FIELDS:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ValueError(f"Generated map clue ladder is missing {field!r}.")
        ladder[field] = value
    return ladder


def normalized_words(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return {word for word in words if len(word) > 3}


def clue_word_count(value: str) -> int:
    return len(
        re.findall(
            r"[a-z0-9]+(?:['’-][a-z0-9]+)*",
            value.casefold(),
        )
    )


def compress_clue_text_to_word_limit(text: object, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if clue_word_count(value) <= limit:
        return value
    if re.search(r"\bfiction\b", value, re.IGNORECASE):
        value = re.sub(r"\bfictional\s+", "", value, count=1, flags=re.IGNORECASE)
    for filler in MAP_CLUE_COMPRESSION_FILLERS:
        if clue_word_count(value) <= limit:
            break
        value, _count = re.subn(
            rf"\b{re.escape(filler)}\b\s*",
            "",
            value,
            count=1,
            flags=re.IGNORECASE,
        )
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def copyedit_generated_clue_ladder(payload: dict[str, Any]) -> dict[str, str]:
    return normalize_generated_clue_ladder(payload)


def hard_hook_specificity_score(text: object) -> int:
    value = str(text or "").strip()
    if not value or not MAP_HARD_HOOK_RECOGNITION_SIGNAL_RE.search(value):
        return 0
    if MAP_HARD_HOOK_NONQUALIFYING_ORIGIN_RE.search(value):
        return 0
    if MAP_HARD_HOOK_WEAK_ORIGIN_RE.search(value):
        return 0
    if MAP_HARD_HOOK_WEAK_COMMISSION_RE.search(value):
        return 0
    if MAP_HARD_HOOK_ARCHITECT_LED_RE.search(value):
        return 0
    if MAP_HARD_HOOK_GENERIC_INCIDENT_RE.search(value):
        return 0
    if (
        MAP_HARD_HOOK_FORMER_RECORD_RE.search(value)
        and not MAP_HARD_HOOK_EVENT_ACTION_RE.search(value)
    ):
        return 0
    if (
        MAP_HARD_HOOK_WEAK_SUPERLATIVE_RE.search(value)
        and not MAP_HARD_HOOK_EVENT_ACTION_RE.search(value)
    ):
        return 0
    if (
        MAP_HARD_HOOK_WEAK_ASSOCIATION_RE.search(value)
        and not MAP_HARD_HOOK_EVENT_ACTION_RE.search(value)
        and not MAP_HARD_HOOK_NAMED_EVENT_RE.search(value)
        and not re.search(
            r"\b(?:world record|record holder|discovery|invention|ritual|"
            r"tradition|survived|escaped|collapsed|destroyed)\b",
            value,
            re.IGNORECASE,
        )
    ):
        return 0
    score = 4
    if re.search(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b", value):
        score += 2
    if MAP_HARD_HOOK_NAMED_EVENT_RE.search(value):
        score += 3
    if MAP_HARD_HOOK_DISTINCTIVE_MARKER_RE.search(value):
        score += 3
    if re.search(r"\b\d+\s*[-–—]\s*\d+\b", value):
        score += 2
    if re.search(
        r"\b(?:still|remains|current|unbroken)\b.{0,40}\brecord\b|"
        r"\brecord\b.{0,40}\b(?:still|remains|current|unbroken)\b",
        value,
        re.IGNORECASE,
    ):
        score += 2
    proper_names = re.findall(
        r"\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+"
        r"(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+)+\b",
        value,
    )
    if proper_names:
        score += 2
    if re.search(r"\b\d+(?:\.\d+)?(?:%| percent)?\b", value):
        score += 1
    if MAP_HARD_EVENT_SIGNIFICANCE_RE.search(value):
        score += 1
    if (
        MAP_HARD_HOOK_STATIC_DESCRIPTION_RE.search(value)
        and not MAP_HARD_HOOK_DISTINCTIVE_MARKER_RE.search(value)
    ):
        score -= 5
    return max(0, score)


def hard_hook_is_qualifying_recognition_hook(text: object) -> bool:
    return hard_hook_specificity_score(text) >= 7


def hard_hook_is_qualifying_event(text: object) -> bool:
    return hard_hook_is_qualifying_recognition_hook(text)


def hard_event_information_score(text: object) -> int:
    value = str(text or "").strip()
    if not MAP_HARD_HOOK_RECOGNITION_SIGNAL_RE.search(value):
        return 0
    score = 1
    if MAP_CLUE_HISTORIC_YEAR_RE.search(value):
        score += 1
    if MAP_HARD_HOOK_NAMED_EVENT_RE.search(value):
        score += 1
    if re.search(
        r"\b(?:\d+\s*[-–—]\s*\d+|\d+(?:\.\d+)?%|over \d+%|"
        r"(?:over\s+)?[a-z]+(?:-[a-z]+)?\s+percent)\b",
        value,
        re.IGNORECASE,
    ):
        score += 1
    if re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", value):
        score += 1
    if MAP_HARD_EVENT_PARTICIPANT_RE.search(value):
        score += 1
    if MAP_HARD_EVENT_SIGNIFICANCE_RE.search(value):
        score += 1
    if len(clue_support_terms(value)) >= 6:
        score += 1
    return score


def hard_event_has_enough_information(text: object) -> bool:
    return not hard_hook_missing_requirements(text)


def required_hard_target_identities(place: dict[str, Any]) -> list[str]:
    place_type = re.sub(
        r"[\s-]+",
        "_",
        str(place.get("place_type") or "").strip().casefold(),
    )
    identities: list[str] = []
    if place_type in MAP_HARD_TARGET_IDENTITY_TERMS:
        identities.append(place_type)
    support_parts = [
        str(place.get("validation_reasoning") or ""),
        str(place.get("nearby_context") or ""),
        *[
            str(fact)
            for fact in (
                place.get("verified_facts")
                if isinstance(place.get("verified_facts"), list)
                else []
            )
        ],
    ]
    support = " ".join(support_parts)
    for identity, signal in MAP_HARD_SECONDARY_IDENTITY_SIGNALS.items():
        if signal.search(support) and identity not in identities:
            identities.append(identity)
    return identities


def hard_missing_target_identities(
    text: object,
    place: dict[str, Any],
) -> list[str]:
    value = str(text or "")
    missing: list[str] = []
    for identity in required_hard_target_identities(place):
        patterns = MAP_HARD_TARGET_IDENTITY_TERMS[identity]
        if not any(re.search(pattern, value, re.IGNORECASE) for pattern in patterns):
            missing.append(identity)
    return missing


def hard_nonparticipant_geographic_names(
    text: object,
    place: dict[str, Any],
) -> list[str]:
    value = str(text or "")
    geographic_names = [
        str(place.get(key) or "").strip()
        for key in ("locality_name", "admin1", "country_name", "continent")
        if str(place.get(key) or "").strip()
    ]
    found: list[str] = []
    for name in geographic_names:
        if re.search(
            rf"\b(?:in|inside|within|near|outside|across|from|located in|"
            rf"situated in|based in)\s+(?:the\s+)?{re.escape(name)}\b",
            value,
            re.IGNORECASE,
        ):
            found.append(name)
    return list(dict.fromkeys(found))


def hard_hook_missing_requirements(text: object) -> list[str]:
    value = str(text or "").strip()
    is_event = bool(MAP_HARD_HOOK_EVENT_ACTION_RE.search(value))
    has_participant = bool(
        MAP_HARD_EVENT_PARTICIPANT_RE.search(value)
        or MAP_HARD_EVENT_NAMED_ACTOR_RE.search(value)
    )
    needs_human_participant = bool(
        is_event
        and re.search(
            r"\b(?:beat|defeated|won|lost|scored|assassinat\w*|murder\w*|"
            r"kill\w*|shot|attack\w*|bomb\w*|besieged|protest\w*|"
            r"signed|crown\w*|imprison\w*)\b",
            value,
            re.IGNORECASE,
        )
    )
    team_event_has_sides = bool(
        not MAP_HARD_TEAM_EVENT_RE.search(value)
        or MAP_HARD_TEAM_SIDES_RE.search(value)
        or MAP_HARD_TEAM_INDIRECT_SIDES_RE.search(value)
    )
    missing: list[str] = []
    if not hard_hook_is_qualifying_recognition_hook(value):
        missing.append("a distinctive place-owned recognition hook")
    if needs_human_participant and not has_participant:
        missing.append("useful named or specific participants")
    if not team_event_has_sides:
        missing.append("both competing sides")
    if not MAP_HARD_PLACE_LINK_RE.search(value):
        missing.append("an answer-safe link showing the hook belongs to this target")
    if is_event and not MAP_HARD_EVENT_SIGNIFICANCE_RE.search(value):
        missing.append(
            "a trigger, consequence, result, record, defining method, or reason the event mattered"
        )
    if is_event and hard_event_information_score(value) < 5:
        missing.append("enough concrete event information")
    if not is_event and len(clue_support_terms(value)) < 5:
        missing.append("enough concrete information to make the hook recognisable")
    return list(dict.fromkeys(missing))


def hard_event_missing_requirements(text: object) -> list[str]:
    return hard_hook_missing_requirements(text)


def medium_uses_unnamed_cultural_reference(text: object) -> bool:
    value = str(text or "").strip()
    return bool(MAP_MEDIUM_VAGUE_CULTURE_RE.search(value))


def medium_blurs_fiction_and_history(text: object) -> bool:
    value = str(text or "").strip()
    return bool(
        MAP_MEDIUM_AMBIGUOUS_FICTION_RE.search(value)
        and not MAP_MEDIUM_FICTION_CONTEXT_RE.search(value)
    )


def map_critic_has_only_length_failures(critic: dict[str, Any]) -> bool:
    reasons = [
        str(reason).strip()
        for reason in critic.get("failure_reasons", [])
        if str(reason).strip()
    ]
    return bool(reasons) and all(
        reason.startswith("One or more clue texts are too long")
        for reason in reasons
    )


def hard_clue_reveals_target_token(text: str, place: dict[str, Any]) -> bool:
    clue_tokens = set(re.findall(r"[a-z0-9]+", str(text or "").casefold()))
    names = [
        str(place.get("canonical_name") or ""),
        *[
            str(alias)
            for alias in (
                place.get("acceptable_aliases")
                if isinstance(place.get("acceptable_aliases"), list)
                else []
            )
        ],
    ]
    protected: set[str] = set()
    for name in names:
        protected.update(
            token
            for token in re.findall(r"[a-z0-9]+", name.casefold())
            if len(token) >= 5 and token not in MAP_HARD_GENERIC_TARGET_TOKENS
        )
    return bool(clue_tokens & protected)


def qualifying_hard_hook_candidates(
    place: dict[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    facts = place.get("verified_facts")
    if not isinstance(facts, list):
        return []
    candidates = [
        {
            "text": str(fact).strip(),
            "specificity_score": hard_hook_specificity_score(fact),
        }
        for fact in facts
        if str(fact).strip() and hard_hook_is_qualifying_recognition_hook(fact)
    ]
    candidates.sort(
        key=lambda item: (
            int(item["specificity_score"]),
            len(clue_support_terms(item["text"])),
            item["text"],
        ),
        reverse=True,
    )
    return candidates[: max(1, limit)]


def clue_preserves_required_hard_hook(clue: str, required_hook: str) -> bool:
    source_terms = clue_support_terms(required_hook)
    clue_terms = clue_support_terms(clue)
    if not source_terms or not clue_terms:
        return False
    overlap = len(source_terms & clue_terms)
    required_overlap = max(2, math.ceil(min(len(source_terms), 8) * 0.38))
    if overlap >= required_overlap:
        return True

    source_years = set(re.findall(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b", required_hook))
    clue_years = set(re.findall(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b", clue))
    if source_years and not source_years.issubset(clue_years):
        return False

    source_events = {
        match.group(0).casefold()
        for match in MAP_HARD_HOOK_NAMED_EVENT_RE.finditer(required_hook)
    }
    clue_events = {
        match.group(0).casefold()
        for match in MAP_HARD_HOOK_NAMED_EVENT_RE.finditer(clue)
    }
    if source_events and not (source_events & clue_events):
        uprising_is_answer_safely_preserved = bool(
            any("uprising" in event for event in source_events)
            and re.search(r"\b(?:uprising|rebellion|insurgency)\b", clue, re.IGNORECASE)
        )
        if not uprising_is_answer_safely_preserved:
            return False

    source_families = {
        family
        for family, pattern in MAP_HARD_EVENT_ACTION_FAMILIES.items()
        if pattern.search(required_hook)
    }
    clue_families = {
        family
        for family, pattern in MAP_HARD_EVENT_ACTION_FAMILIES.items()
        if pattern.search(clue)
    }
    return bool(source_families & clue_families)


def normalize_support_term(value: str) -> str:
    word = value.casefold().strip("'")
    if word.endswith("'s"):
        word = word[:-2]
    if len(word) > 5 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 4 and word.endswith("s"):
        return word[:-1]
    return word


def clue_support_terms(value: object) -> set[str]:
    terms: set[str] = set()
    for raw_word in re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(value or "").casefold()):
        word = normalize_support_term(raw_word)
        if word in MAP_CLUE_SUPPORT_STOPWORDS:
            continue
        if len(word) < 5 and word not in MAP_CLUE_SUPPORT_SHORT_TERMS:
            continue
        terms.add(word)
    return terms


def dataset_support_terms(place: dict[str, Any]) -> set[str]:
    support_texts: list[str] = []
    verified_facts = place.get("verified_facts")
    if isinstance(verified_facts, list):
        support_texts.extend(str(fact) for fact in verified_facts if str(fact).strip())
    for key in (
        "nearby_context",
        "validation_reasoning",
        "country_name",
        "admin1",
        "continent",
        "locality_name",
    ):
        value = str(place.get(key) or "").strip()
        if value:
            support_texts.append(value)
    return clue_support_terms(" ".join(support_texts))


def dataset_known_for_terms(place: dict[str, Any]) -> set[str]:
    verified_facts = place.get("verified_facts")
    if not isinstance(verified_facts, list):
        return set()
    return clue_support_terms(" ".join(str(fact) for fact in verified_facts if str(fact).strip()))


def clue_has_dataset_support(text: str, support_terms: set[str]) -> bool:
    if not support_terms:
        return True
    clue_terms = clue_support_terms(text)
    return bool(clue_terms & support_terms)


def clue_texts_are_repetitive(left: str, right: str) -> bool:
    left_words = normalized_words(left)
    right_words = normalized_words(right)
    if not left_words or not right_words:
        return False
    overlap = len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))
    return overlap >= 0.72


def clue_contains_answer(text: str, place: dict[str, Any]) -> bool:
    candidates = [place.get("canonical_name"), *place.get("acceptable_aliases", [])]
    normalized = normalized_place_name(text)
    return any(normalized_place_name(candidate) in normalized for candidate in candidates if candidate)


def clue_uses_template_phrase(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").casefold())
    return any(phrase in normalized for phrase in MAP_CLUE_TEMPLATE_PHRASES)


def clue_uses_placeholder_phrase(text: str, *, reveal: bool = False) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").casefold())
    phrases = MAP_CLUE_REVEAL_PLACEHOLDER_PHRASES if reveal else MAP_CLUE_PLACEHOLDER_PHRASES
    return any(phrase in normalized for phrase in phrases)


def clue_uses_coordinate_or_code_targeting(text: str) -> bool:
    return bool(
        MAP_CLUE_COORDINATE_OR_CODE_RE.search(str(text or ""))
        or MAP_CLUE_COORDINATE_PAIR_RE.search(str(text or ""))
    )


def clue_is_generic_origin_fact(text: str) -> bool:
    value = str(text or "")
    return bool(
        MAP_CLUE_GENERIC_ORIGIN_RE.search(value)
        and not MAP_CLUE_DISTINCTIVE_ORIGIN_DETAIL_RE.search(value)
    )


def clue_uses_generic_unnamed_identity(text: str) -> bool:
    return bool(MAP_CLUE_GENERIC_UNNAMED_IDENTITY_RE.search(str(text or "")))


def clue_has_known_for_hook(text: str, known_for_terms: set[str] | None = None) -> bool:
    value = str(text or "")
    if clue_is_generic_origin_fact(value) or clue_uses_generic_unnamed_identity(value):
        return False
    if MAP_CLUE_KNOWN_FOR_RE.search(value) or MAP_CLUE_HISTORIC_YEAR_RE.search(value):
        return True
    if known_for_terms and not clue_is_location_or_generic_geo_framed(value):
        return len(clue_support_terms(value) & known_for_terms) >= 2
    return False


def clue_is_location_or_generic_geo_framed(text: str) -> bool:
    value = str(text or "")
    return bool(MAP_CLUE_LOCATION_FRAMING_RE.search(value) or MAP_CLUE_GENERIC_GEO_RE.search(value))


def clue_is_location_framed_without_hook(text: str) -> bool:
    value = str(text or "")
    return clue_is_location_or_generic_geo_framed(value) and not clue_has_known_for_hook(value)


def clue_has_easy_map_anchor(text: str) -> bool:
    return bool(MAP_CLUE_EASY_ANCHOR_RE.search(str(text or "")))


def context_geographic_names(place: dict[str, Any]) -> set[str]:
    values = [
        str(place.get("country_name") or ""),
        str(place.get("admin1") or ""),
        str(place.get("continent") or ""),
        str(place.get("locality_name") or ""),
        str(place.get("nearby_context") or ""),
    ]
    names: set[str] = set()
    for value in values:
        for candidate in re.findall(
            r"\b[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){0,3}\b",
            value,
        ):
            normalized = candidate.strip().casefold()
            if len(normalized) >= 4:
                names.add(normalized)
    return names


def medium_materially_narrows_geography(text: str, place: dict[str, Any]) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if MAP_MEDIUM_GEO_NARROWING_RE.search(value):
        return True
    folded = value.casefold()
    return any(name in folded for name in context_geographic_names(place))


def easy_has_local_map_route(text: str, place: dict[str, Any]) -> bool:
    value = str(text or "").strip()
    if not value or not clue_has_easy_map_anchor(value):
        return False
    folded = value.casefold()
    named_context = any(name in folded for name in context_geographic_names(place))
    has_local_area = bool(MAP_EASY_LOCAL_AREA_RE.search(value))
    has_local_relation = bool(MAP_EASY_LOCAL_RELATION_RE.search(value))
    has_directional_local_area = bool(has_local_area and has_local_relation)
    has_named_local_feature = bool(named_context and has_local_relation)
    return has_directional_local_area or has_named_local_feature or bool(
        re.search(r"\b(?:old town|city centre|city center|downtown)\b", value, re.IGNORECASE)
    )


def clue_ladder_reaches_required_locality(
    ladder: dict[str, str],
    place: dict[str, Any],
) -> bool:
    locality = str(place.get("locality_name") or "").strip()
    if not locality:
        return True
    locality_key = normalized_place_name(locality)
    answer_names = [
        str(place.get("canonical_name") or ""),
        *[
            str(alias)
            for alias in (
                place.get("acceptable_aliases")
                if isinstance(place.get("acceptable_aliases"), list)
                else []
            )
        ],
    ]
    if any(
        locality_key == normalized_place_name(answer)
        for answer in answer_names
        if answer
    ):
        return True
    progression = normalized_place_name(
        f"{ladder.get('medium', '')} {ladder.get('easy', '')}"
    )
    return bool(locality_key and locality_key in progression)


def easy_has_broad_locality_route(
    ladder: dict[str, str],
    place: dict[str, Any],
) -> bool:
    locality = str(place.get("locality_name") or "").strip()
    if not locality:
        return True
    if not clue_ladder_reaches_required_locality(ladder, place):
        return False
    locality_key = normalized_place_name(locality)
    answer_names = [
        str(place.get("canonical_name") or ""),
        *[
            str(alias)
            for alias in (
                place.get("acceptable_aliases")
                if isinstance(place.get("acceptable_aliases"), list)
                else []
            )
        ],
    ]
    if any(
        locality_key == normalized_place_name(answer)
        for answer in answer_names
        if answer
    ):
        return True
    return bool(MAP_EASY_CITY_SECTOR_RE.search(str(ladder.get("easy") or "")))


def generation_avoid_in_clues(place: dict[str, Any]) -> str:
    geographic_names = {
        normalized_place_name(place.get(key))
        for key in ("locality_name", "country_name", "admin1", "continent")
        if str(place.get(key) or "").strip()
    }
    return "; ".join(
        value
        for value in split_list_text(place.get("avoid_in_clues"))
        if normalized_place_name(value) not in geographic_names
    )


def local_map_clue_critique(
    place: dict[str, Any],
    clue_ladder: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    feedback: list[str] = []
    try:
        ladder = normalize_generated_clue_ladder(clue_ladder)
    except ValueError as error:
        return {
            "passed": False,
            "scores": {field: 0 for field in MAP_CLUE_CRITIC_THRESHOLDS},
            "failure_reasons": [str(error)],
            "feedback_to_generator": ["Return every required clue-ladder field with non-empty text."],
        }

    required_hard_hook = str(place.get("required_hard_hook") or "").strip()
    if required_hard_hook:
        if not hard_hook_is_qualifying_recognition_hook(required_hard_hook):
            reasons.append("The selected hard hook is not a qualifying recognition hook.")
            feedback.append(
                "Choose a verified place-owned incident, story, record, achievement, discovery, tradition, natural occurrence, or cultural moment that is genuinely recognisable."
            )
        elif not clue_preserves_required_hard_hook(ladder["hard"], required_hard_hook):
            reasons.append("Hard clue does not preserve the locked verified recognition hook.")
            feedback.append(
                "Rewrite the locked hook while retaining the details that make it distinctive and recognisable."
            )
        if not hard_event_has_enough_information(ladder["hard"]):
            reasons.append("Hard clue does not contain enough information to make the locked hook recognisable.")
            feedback.append(
                "Retain the useful people, action, outcome, consequence, record, or significance; do not reduce the hook to a headline."
            )
        if hard_clue_reveals_target_token(ladder["hard"], place):
            reasons.append("Hard clue reveals a distinctive word from the target name.")
            feedback.append(
                "Remove distinctive target-name words from hard while preserving the incident details."
            )
        if MAP_HARD_GEO_SCOPE_RE.search(ladder["hard"]):
            reasons.append("Hard clue borrows geographic scope that belongs in medium or easy.")
            feedback.append(
                "Keep hard focused on the recognition hook; remove country, capital, region, direction, river, and nearby-place hints."
            )
        if MAP_HARD_NAMED_GEOGRAPHIC_FEATURE_RE.search(ladder["hard"]):
            reasons.append("Hard clue names a geographic map feature that belongs in medium or easy.")
            feedback.append(
                "Remove named points, bays, rivers, districts, roads, stations, and other map locations from hard; preserve only the event and answer-safe target identity."
            )
        hard_geographic_names = hard_nonparticipant_geographic_names(
            ladder["hard"],
            place,
        )
        if hard_geographic_names:
            reasons.append(
                "Hard clue names geographic scope that belongs in medium or easy: "
                f"{', '.join(hard_geographic_names)}."
            )
            feedback.append(
                "Remove country, region, city, and continent locations from hard unless the name is an essential event participant such as a national team."
            )
        if not MAP_HARD_PLACE_LINK_RE.search(ladder["hard"]):
            reasons.append("Hard clue does not make clear that the recognition hook belongs to the target.")
            feedback.append(
                "Tie the hook to the target with an answer-safe phrase such as 'here', 'on this pitch', 'inside this building', or 'at this site'."
            )
        missing_identities = hard_missing_target_identities(ladder["hard"], place)
        if missing_identities:
            reasons.append(
                "Hard clue replaces the target's answer-safe identity with a generic site reference: "
                f"{', '.join(missing_identities)}."
            )
            feedback.append(
                "State what the target is without naming it. Preserve these answer-safe identities: "
                f"{', '.join(missing_identities)}; do not reduce them to 'this site' or 'here'."
            )

    for field in ("hard", "medium", "easy"):
        if clue_contains_answer(ladder[field], place):
            reasons.append(f"{field} clue reveals the answer name or an alias.")
            feedback.append("Do not include the answer name or aliases before the final name reveal.")
        if clue_uses_coordinate_or_code_targeting(ladder[field]):
            reasons.append(f"{field} clue uses coordinates, ISO codes, time zones, or database-like targeting.")
            feedback.append("Do not use latitude, longitude, coordinates, ISO codes, time zones, or database-like identifiers as clues.")
        if clue_uses_template_phrase(ladder[field]):
            reasons.append(f"{field} clue uses formulaic map-dataset phrasing.")
            feedback.append("Avoid formulaic dataset wording; write natural clues built around specific visible or historic hooks.")
        if clue_uses_placeholder_phrase(ladder[field]):
            reasons.append(f"{field} clue uses awkward placeholder wording.")
            feedback.append("Do not use placeholders such as 'the place', 'the target place', or 'the answer' inside clues.")
    if MAP_MEDIUM_FILLER_RE.search(ladder["medium"]):
        reasons.append("Medium clue uses generic crowd, popularity, prestige, fame, or historic-venue filler.")
        feedback.append(
            "State medium's useful place-owned relationship directly; remove generic crowd, popularity, prestige, fame, and historic-venue padding."
        )
    if medium_uses_unnamed_cultural_reference(ladder["medium"]):
        reasons.append("Medium clue hides a useful cultural reference behind a vague famous or well-known label.")
        feedback.append(
            "Do not write 'a famous collection' or a similar label. State what the named creator, characters, or work specifically did with this place; omit only a title that would reveal the answer."
        )
    if medium_blurs_fiction_and_history(ladder["medium"]):
        reasons.append("Medium clue presents fictional characters as though they were historical people.")
        feedback.append(
            "Explicitly label fictional or imaginary characters and events as fiction while retaining their concrete connection to this place."
        )

    playable_fields = ("hard", "medium", "easy")
    known_for_terms = dataset_known_for_terms(place)
    known_for_fields = [
        field
        for field in playable_fields
        if clue_has_known_for_hook(ladder[field], known_for_terms)
    ]
    weak_role_fields: list[str] = []
    if not required_hard_hook and "hard" not in known_for_fields:
        weak_role_fields.append("hard")
    if not medium_materially_narrows_geography(ladder["medium"], place):
        weak_role_fields.append("medium")
    if not easy_has_local_map_route(ladder["easy"], place):
        weak_role_fields.append("easy")
    reaches_required_locality = clue_ladder_reaches_required_locality(ladder, place)
    if not reaches_required_locality and "easy" not in weak_role_fields:
        weak_role_fields.append("easy")
    has_broad_locality_route = easy_has_broad_locality_route(ladder, place)
    if not has_broad_locality_route and "easy" not in weak_role_fields:
        weak_role_fields.append("easy")
    support_terms = dataset_support_terms(place)
    unsupported_fields = [
        field
        for field in playable_fields
        if not clue_has_dataset_support(ladder[field], support_terms)
    ]
    geo_first_fields = [
        "hard"
        if clue_is_location_or_generic_geo_framed(ladder["hard"])
        and not clue_has_known_for_hook(ladder["hard"], known_for_terms)
        else ""
    ]
    geo_first_fields = [field for field in geo_first_fields if field]
    if weak_role_fields:
        reasons.append(
            "Each clue must fulfil its role: hard recognition hook, medium geographic narrowing, and easy local-area map route; weak fields: "
            f"{', '.join(weak_role_fields)}."
        )
        feedback.append(
            "Use a memorable hard recognition hook, make medium reduce the broad geography, and make easy identify a local area or feature within that scope."
        )
    if not reaches_required_locality:
        locality = str(place.get("locality_name") or "").strip()
        reasons.append(
            f"The ladder has not explicitly reached the required low-zoom locality {locality} by the end of easy."
        )
        feedback.append(
            f"Name {locality} in medium or easy before referring to 'the city', a district, a road, or a smaller local feature."
        )
    elif not has_broad_locality_route:
        locality = str(place.get("locality_name") or "").strip()
        reasons.append(
            f"Easy does not give a broad city-sector route within {locality} before relying on smaller map details."
        )
        feedback.append(
            f"Give a broad route such as northern, southern, eastern, western, or central {locality}; use districts, roads, or stations only as supplementary detail."
        )
    if clue_is_generic_origin_fact(ladder["hard"]):
        reasons.append(
            "Hard clue only gives a construction, founder, commissioner, ruler, architect, or date fact without an unusual one-place detail."
        )
        feedback.append(
            "A construction date or person responsible is not distinctive by itself; use an unusual event, consequence, record, ritual, story, or oddity tied to this place."
        )
    if clue_uses_generic_unnamed_identity(ladder["medium"]):
        reasons.append(
            "Medium clue anonymises its distinctive detail as an unnamed generic role."
        )
        feedback.append(
            "Do not write 'a famous journalist' or another unnamed role; name the answer-safe person or use a different precise place-owned fact."
        )
    if unsupported_fields:
        reasons.append(
            "One or more playable clues are not supported by the row's verified facts/context: "
            f"{', '.join(unsupported_fields)}."
        )
        feedback.append(
            "Use only details found in verified_facts, nearby_context, or validation_reasoning; do not invent landmarks, industries, products, institutions, or events."
        )
    if geo_first_fields:
        reasons.append(
            "Hard uses generic location or broad geography instead of its recognition hook: "
            f"{', '.join(geo_first_fields)}."
        )
        feedback.append("Reserve geography for medium and easy; hard should contain only its place-owned recognition hook.")

    comparisons = (("hard", "medium"), ("medium", "easy"), ("hard", "easy"))
    for left, right in comparisons:
        if clue_texts_are_repetitive(ladder[left], ladder[right]):
            reasons.append(f"{left} and {right} clues repeat the same information.")
            feedback.append("Make each clue level introduce a genuinely different verified hook.")
            break

    long_fields = [
        field
        for field, limit in MAP_CLUE_TEXT_LIMITS.items()
        if len(ladder[field]) > limit
    ]
    if long_fields:
        reasons.append(f"One or more clue texts are too long for mobile: {', '.join(long_fields)}.")
        feedback.append("Keep each clue concise enough to read comfortably on a phone.")

    if clue_uses_coordinate_or_code_targeting(ladder["reveal"]):
        reasons.append("Reveal uses coordinates, time zone, or database metadata.")
        feedback.append("Make the reveal a natural explanation; do not mention coordinates, time zones, or database metadata.")
    if clue_uses_template_phrase(ladder["reveal"]):
        reasons.append("Reveal uses formulaic map-dataset phrasing.")
        feedback.append("Make the reveal sound like a human explanation, not a dataset summary.")
    if clue_uses_placeholder_phrase(ladder["reveal"], reveal=True):
        reasons.append("Reveal uses awkward placeholder wording.")
        feedback.append("Make the reveal name the answer naturally rather than using placeholder wording.")
    canonical_name = str(place.get("canonical_name") or "").strip()
    if canonical_name and canonical_name.casefold() not in ladder["reveal"].casefold():
        reasons.append("Reveal does not spell the canonical place name exactly.")
        feedback.append("Begin the reveal with the exact canonical_name supplied in the target data.")

    passed = not reasons
    scores = {
        "correctness": 9 if passed else 6,
        "distinctiveness": 9 if passed else 5,
        "difficulty_ladder": 9 if passed else 6,
        "non_spoiler": 9 if passed else 4,
        "interestingness": 8 if passed else 6,
    }
    return {
        "passed": passed,
        "scores": scores,
        "failure_reasons": reasons,
        "feedback_to_generator": merge_feedback_entries(feedback, limit=5),
    }


def map_clue_critic_passed(critic: dict[str, Any]) -> bool:
    if not bool(critic.get("passed")):
        return False
    scores = critic.get("scores")
    if not isinstance(scores, dict):
        return False
    return all(int(scores.get(field, 0)) >= threshold for field, threshold in MAP_CLUE_CRITIC_THRESHOLDS.items())


def apply_learned_map_clue_quality_gate(
    place: dict[str, Any],
    clue_ladder: dict[str, Any],
    critic: dict[str, Any],
    *,
    model_path: str,
) -> dict[str, Any]:
    if not model_path:
        return critic
    from tools import map_clue_quality_model

    model = map_clue_quality_model.load_model(Path(model_path))
    if not model:
        return critic
    ladder = normalize_generated_clue_ladder(clue_ladder)
    predictions = {
        level: map_clue_quality_model.predict_level(
            model,
            level,
            ladder[level],
            place_type=place.get("place_type"),
        )
        for level in ("hard", "medium", "easy")
    }
    advisory_levels = [
        level
        for level, prediction in predictions.items()
        if prediction
        and float(prediction.get("pass_probability") or 0)
        < MAP_CLUE_LEARNED_PASS_THRESHOLDS[level]
    ]
    result = {
        **critic,
        "scores": dict(critic.get("scores") or {}),
        "failure_reasons": list(critic.get("failure_reasons") or []),
        "feedback_to_generator": list(critic.get("feedback_to_generator") or []),
        "learned_quality": predictions,
        "learned_advisories": [
            {
                "level": level,
                "pass_probability": predictions[level].get("pass_probability"),
                "confidence": predictions[level].get("confidence"),
                "negative_signals": predictions[level].get("negative_signals") or [],
            }
            for level in advisory_levels
        ],
    }
    result["feedback_to_generator"] = merge_feedback_entries(
        [str(item) for item in result["feedback_to_generator"]],
        limit=8,
    )
    return result


def clue_ladder_dict_for_row(row: sqlite3.Row) -> dict[str, str]:
    clues = clue_ladder_for_row(row)
    return {
        "hard": str(clues[0]["text"] or ""),
        "medium": str(clues[1]["text"] or ""),
        "easy": str(clues[2]["text"] or ""),
        "reveal": str(row["reveal_text"] or ""),
    }


def row_passes_map_clue_quality(row: sqlite3.Row) -> bool:
    try:
        if place_is_explicitly_excluded(row):
            return False
        if not str(row["clue_text"] or "").strip() or not str(row["reveal_text"] or "").strip():
            return False
        critic = local_map_clue_critique(
            public_place_payload(row),
            clue_ladder_dict_for_row(row),
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return map_clue_critic_passed(critic)


def first_quality_place(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    for row in rows:
        if row_passes_map_clue_quality(row):
            return row
    return None


def stable_place_tiebreaker(row: sqlite3.Row | dict[str, Any], puzzle_date: str) -> int:
    try:
        place_id = row["id"]  # type: ignore[index]
    except (KeyError, IndexError):
        place_id = public_place_payload(row)["canonical_name"]
    digest = hashlib.sha256(f"{puzzle_date}:{place_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def best_quality_place(
    rows: list[sqlite3.Row],
    *,
    puzzle_date: str,
    selector_profile: dict[str, Any] | None = None,
) -> sqlite3.Row | None:
    if selector_profile is None:
        selector_profile = load_map_selector_profile()
    candidates: list[tuple[tuple[int, int, int, int, int], sqlite3.Row]] = []
    for row in rows:
        if not row_passes_map_clue_quality(row):
            continue
        profile = map_place_selection_profile(row, selector_profile)
        persuading_count = int(profile["persuadingFactCount"])
        sort_key = (
            1 if persuading_count >= MAP_PLACE_REQUIRED_PERSUADING_FACTS else 0,
            int(profile["score"]),
            min(4, len(profile["categories"])),
            int(round(float(profile["validationGrade"]) * 10)),
            stable_place_tiebreaker(row, puzzle_date),
        )
        candidates.append((sort_key, row))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def recent_map_places(
    conn: sqlite3.Connection,
    *,
    history_days: int = RECENT_USE_DAYS,
    exclude_puzzle_date: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    cutoff_clause = ""
    if exclude_puzzle_date is not None:
        cutoff = (datetime.strptime(valid_game_date(exclude_puzzle_date), "%Y-%m-%d") - timedelta(days=history_days)).date().isoformat()
        cutoff_clause = "WHERE daily_map_puzzles.puzzle_date >= ? AND daily_map_puzzles.puzzle_date <> ?"
        params.extend([cutoff, exclude_puzzle_date])
    rows = conn.execute(
        f"""
        SELECT
            map_place_pool.canonical_name,
            map_place_pool.place_type,
            map_place_pool.country_code,
            map_place_pool.admin1,
            map_place_pool.difficulty
        FROM daily_map_levels
        INNER JOIN daily_map_puzzles
            ON daily_map_puzzles.id = daily_map_levels.puzzle_id
        INNER JOIN map_place_pool
            ON map_place_pool.id = daily_map_levels.place_id
        {cutoff_clause}
        ORDER BY daily_map_puzzles.puzzle_date DESC
        LIMIT 20
        """,
        params,
    ).fetchall()
    return [
        {
            "canonical_name": row["canonical_name"],
            "place_type": row["place_type"],
            "country_code": row["country_code"],
            "admin1": row["admin1"],
            "difficulty": row["difficulty"],
        }
        for row in rows
    ]


def save_reviewed_clue_ladder(
    conn: sqlite3.Connection,
    *,
    place_id: int,
    clue_ladder: dict[str, Any],
    review_notes: str = "",
    generation_source: str = "",
    learning_profile_path: str = "",
    critic_mode: str = "",
) -> dict[str, str]:
    place = conn.execute(
        "SELECT * FROM map_place_pool WHERE id = ?",
        (place_id,),
    ).fetchone()
    if place is None:
        raise LookupError("Map place was not found.")
    place_payload = public_place_payload(place)
    ladder = normalize_generated_clue_ladder(clue_ladder)
    local_critic = local_map_clue_critique(place_payload, ladder)
    if not map_clue_critic_passed(local_critic):
        raise ValueError("; ".join(local_critic["failure_reasons"]) or "Map clue ladder was rejected.")
    now_notes = str(review_notes or "").strip()
    profile_hash = map_learning_profile_hash(learning_profile_path) if learning_profile_path else ""
    conn.execute(
        """
        UPDATE map_place_pool
        SET clue_text = ?,
            medium_clue_text = ?,
            easy_clue_text = ?,
            reveal_text = ?,
            review_status = 'machine_validated',
            review_notes = ?,
            reviewed_on = ?,
            clue_generation_source = ?,
            clue_profile_hash = ?,
            clue_critic_mode = ?
        WHERE id = ?
        """,
        (
            mask_answer_name(ladder["hard"], place_payload["canonical_name"]),
            mask_answer_name(ladder["medium"], place_payload["canonical_name"]),
            mask_answer_name(ladder["easy"], place_payload["canonical_name"]),
            ladder["reveal"],
            now_notes,
            utc_now(),
            str(generation_source or "").strip(),
            profile_hash,
            str(critic_mode or "").strip(),
            place_id,
        ),
    )
    return ladder


def generate_reviewed_clue_ladder(
    conn: sqlite3.Connection,
    *,
    place_id: int,
    provider: MapClueProvider,
    config: MapClueConfig | None = None,
    save: bool = True,
    required_hard_hook: str = "",
    locality_name: str = "",
) -> dict[str, Any]:
    config = config or MapClueConfig()
    place = conn.execute("SELECT * FROM map_place_pool WHERE id = ?", (place_id,)).fetchone()
    if place is None:
        raise LookupError("Map place was not found.")
    place_payload = public_place_payload(place)
    generation_place = {
        **place_payload,
        "required_hard_hook": str(required_hard_hook or "").strip(),
        "locality_name": str(locality_name or "").strip(),
    }
    generation_place["avoid_in_clues"] = generation_avoid_in_clues(generation_place)
    if generation_place["required_hard_hook"] and not hard_hook_is_qualifying_recognition_hook(
        generation_place["required_hard_hook"]
    ):
        raise ValueError("The selected hard hook is not a qualifying recognition hook.")
    recent = recent_map_places(conn)
    profile_feedback = map_clue_learning_profile_ladder_feedback(
        config.learning_profile_path,
        place_type=place_payload["place_type"],
    )
    feedback = profile_feedback
    attempts: list[dict[str, Any]] = []
    for _attempt in range(config.max_attempts_per_place):
        generated = normalize_generated_clue_ladder(
            provider.generate_clue_ladder(
                place=generation_place,
                recent_places=recent,
                feedback=feedback,
            )
        )
        local_critic = local_map_clue_critique(generation_place, generated)
        if map_critic_has_only_length_failures(local_critic):
            copyedited = copyedit_generated_clue_ladder(generated)
            if copyedited != generated:
                generated = copyedited
                local_critic = local_map_clue_critique(generation_place, generated)
        local_critic = apply_learned_map_clue_quality_gate(
            generation_place,
            generated,
            local_critic,
            model_path=config.clue_quality_model_path,
        )
        if not map_clue_critic_passed(local_critic):
            feedback = merge_feedback_entries(
                feedback,
                [str(item) for item in local_critic.get("feedback_to_generator", [])],
                limit=14,
            )
            attempts.append({"generated": generated, "critic": local_critic, "critic_source": "local"})
            continue
        if not config.require_ai_critic:
            attempts.append({"generated": generated, "critic": local_critic, "critic_source": "local"})
            ladder = normalize_generated_clue_ladder(generated)
            if not save:
                return {
                    "status": "accepted",
                    "clue_ladder": ladder,
                    "attempts": attempts,
                    "saved": False,
                    "critic_mode": "local",
                }
            saved_ladder = save_reviewed_clue_ladder(
                conn,
                place_id=place_id,
                clue_ladder=ladder,
                review_notes=f"Generated by {provider.name}; accepted by local map clue critic.",
                generation_source=provider.name,
                learning_profile_path=config.learning_profile_path,
                critic_mode="local",
            )
            return {
                "status": "accepted",
                "clue_ladder": saved_ladder,
                "attempts": attempts,
                "saved": True,
                "critic_mode": "local",
            }
        critic = provider.critique_clue_ladder(
            place=generation_place,
            clue_ladder=generated,
            recent_places=recent,
        )
        attempts.append({"generated": generated, "critic": critic, "local_critic": local_critic, "critic_source": "ai"})
        if map_clue_critic_passed(critic):
            if not save:
                return {
                    "status": "accepted",
                    "clue_ladder": normalize_generated_clue_ladder(generated),
                    "attempts": attempts,
                    "saved": False,
                    "critic_mode": "ai",
                }
            ladder = save_reviewed_clue_ladder(
                conn,
                place_id=place_id,
                clue_ladder=generated,
                review_notes=f"Generated by {provider.name}.",
                generation_source=provider.name,
                learning_profile_path=config.learning_profile_path,
                critic_mode="ai",
            )
            return {"status": "accepted", "clue_ladder": ladder, "attempts": attempts, "saved": True, "critic_mode": "ai"}
        feedback = merge_feedback_entries(
            feedback,
            [str(item) for item in critic.get("feedback_to_generator", [])],
            limit=14,
        )
    return {"status": "rejected", "attempts": attempts}


def clue_ladder_for_row(row: sqlite3.Row) -> list[dict[str, Any]]:
    place_name = row["canonical_name"]
    region = str(row["admin1"] or "").strip()
    country = country_name(row["country_code"])
    region_text = f"{region}, {country}" if region else country
    medium_text = str(row["medium_clue_text"] or "").strip()
    if not medium_text:
        medium_text = f"The answer is in {region_text}."
    easy_text = str(row["easy_clue_text"] or "").strip()
    if not easy_text:
        easy_text = mask_answer_name(row["reveal_text"], place_name)
    if not easy_text:
        easy_text = f"This place is in {region_text}."
    return [
        {
            "id": "hard",
            "title": "Hard clue",
            "text": row["clue_text"],
            "maxPoints": MAP_CLUE_SCORES[0],
        },
        {
            "id": "medium",
            "title": "Medium clue",
            "text": mask_answer_name(medium_text, place_name),
            "maxPoints": MAP_CLUE_SCORES[1],
        },
        {
            "id": "easy",
            "title": "Easy clue",
            "text": easy_text,
            "maxPoints": MAP_CLUE_SCORES[2],
        },
        {
            "id": "name",
            "title": "Place name",
            "text": place_name,
            "maxPoints": MAP_CLUE_SCORES[3],
            "revealsName": True,
        },
    ]


def serialize_level(row: sqlite3.Row) -> dict[str, Any]:
    clues = clue_ladder_for_row(row)
    payload: dict[str, Any] = {
        "id": row["level_id"],
        "slug": row["level_slug"],
        "title": "Daily Place",
        "clueText": clues[0]["text"],
        "clues": clues,
        "mapAnchors": serialize_map_search_anchors(row["map_search_anchors_json"]),
        "maxPoints": MAP_MAX_SCORE,
        "submitted": row["guess_id"] is not None,
    }
    if row["guess_id"] is not None:
        payload["result"] = reveal_payload_from_row(row)
    return payload


def reveal_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    distance_m = int(row["distance_m"])
    target_radius_m = normalized_scoring_radius_m(
        row["level_slug"],
        row["scoring_radius_m"],
    )
    outside_target_m = graded_distance_m(distance_m, target_radius_m)
    correct = row["band"] != "Wrong place"
    revealed_hint_count = normalized_revealed_hint_count(row["revealed_hint_count"])
    selected_name = row["selected_name"]
    return {
        "guessedPoint": {"lat": row["guessed_lat"], "lng": row["guessed_lng"]},
        "answerPoint": {"lat": row["answer_lat"], "lng": row["answer_lng"]},
        "distanceMeters": distance_m,
        "distanceKm": round(float(distance_m) / 1000.0, 1),
        "distanceFromCentreMeters": distance_m,
        "gradedDistanceMeters": outside_target_m,
        "gradedDistanceKm": round(float(outside_target_m) / 1000.0, 1),
        "targetRadiusMeters": target_radius_m,
        "insideTargetArea": correct,
        "correct": correct,
        "revealedHintCount": revealed_hint_count,
        "score": row["score"],
        "maxPoints": MAP_CLUE_SCORES[revealed_hint_count],
        "band": row["band"],
        "completedAt": row["completed_at"],
        "selectedPlace": {
            "name": selected_name,
        },
        "place": {
            "name": row["canonical_name"],
            "countryCode": row["country_code"],
            "admin1": row["admin1"],
            "revealText": row["reveal_text"],
        },
    }


def valid_coordinate(lat: object, lng: object) -> tuple[float, float]:
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise ValueError("Guess coordinates must be numbers.")
    lat_value = float(lat)
    lng_value = float(lng)
    if not math.isfinite(lat_value) or not math.isfinite(lng_value):
        raise ValueError("Guess coordinates must be finite numbers.")
    if lat_value < -90 or lat_value > 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if lng_value < -180 or lng_value > 180:
        raise ValueError("Longitude must be between -180 and 180.")
    return lat_value, lng_value


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    earth_radius_m = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return int(round(earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))))


def place_snap_radius_m(place: sqlite3.Row) -> int:
    difficulty = place["difficulty"]
    return max(
        normalized_scoring_radius_m(difficulty, place["scoring_radius_m"]),
        SNAP_RADIUS_FLOOR_M[difficulty],
    )


def normalized_zoom(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(zoom):
        return None
    return min(19.0, max(1.0, zoom))


def touch_snap_radius_m(lat: float, zoom: float | None, difficulty: str) -> int:
    if zoom is None:
        return 0
    metres_per_pixel = (
        156_543.03392
        * abs(math.cos(math.radians(lat)))
        / (2 ** zoom)
    )
    radius_m = int(round(metres_per_pixel * SNAP_TOUCH_RADIUS_PX))
    return min(radius_m, SNAP_TOUCH_RADIUS_CAP_M[difficulty])


def effective_snap_radius_m(
    place: sqlite3.Row,
    *,
    clicked_lat: float,
    zoom: float | None,
) -> int:
    difficulty = place["difficulty"]
    return max(
        place_snap_radius_m(place),
        touch_snap_radius_m(clicked_lat, zoom, difficulty),
    )


def place_kind(place: sqlite3.Row | None) -> str:
    if place is None:
        return "coordinate"
    if place["difficulty"] == "hard":
        return "landmark"
    return "place"


def selection_payload(
    *,
    point_lat: float,
    point_lng: float,
    clicked_lat: float,
    clicked_lng: float,
    snapped: bool,
    name: str,
    kind: str,
    distance_m: int = 0,
    snap_radius_m: int = 0,
    country_code: str | None = None,
    admin1: str | None = None,
    alternatives: list[dict[str, Any]] | None = None,
    selected_index: int | None = None,
) -> dict[str, Any]:
    payload = {
        "point": {"lat": point_lat, "lng": point_lng},
        "clickedPoint": {"lat": clicked_lat, "lng": clicked_lng},
        "snapped": snapped,
        "name": name,
        "kind": kind,
        "distanceMeters": distance_m,
        "snapRadiusMeters": snap_radius_m,
        "countryCode": country_code,
        "admin1": admin1,
    }
    if alternatives is not None:
        payload["alternatives"] = alternatives
    if selected_index is not None:
        payload["selectedIndex"] = selected_index
    return payload


def serialize_map_boundary(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    geometry_type = str(value.get("type") or "").strip()
    coordinates = value.get("coordinates")

    def position(item: object) -> list[float] | None:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        try:
            lng = float(item[0])
            lat = float(item[1])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat) or not math.isfinite(lng):
            return None
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            return None
        return [lng, lat]

    def ring(item: object) -> list[list[float]] | None:
        if not isinstance(item, list) or not 4 <= len(item) <= 10_000:
            return None
        normalized = [position(point) for point in item]
        if any(point is None for point in normalized):
            return None
        return [point for point in normalized if point is not None]

    def polygon(item: object) -> list[list[list[float]]] | None:
        if not isinstance(item, list) or not 1 <= len(item) <= 500:
            return None
        normalized = [ring(candidate) for candidate in item]
        if any(candidate is None for candidate in normalized):
            return None
        return [candidate for candidate in normalized if candidate is not None]

    if geometry_type == "Polygon":
        normalized_coordinates: object = polygon(coordinates)
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        normalized_polygons = [polygon(candidate) for candidate in coordinates]
        normalized_coordinates = (
            None
            if any(candidate is None for candidate in normalized_polygons)
            else [candidate for candidate in normalized_polygons if candidate is not None]
        )
    else:
        return None
    if not normalized_coordinates:
        return None
    boundary = {"type": geometry_type, "coordinates": normalized_coordinates}
    try:
        encoded = json.dumps(boundary, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return boundary if len(encoded) <= 250_000 else None


def serialize_map_search_anchors(value: object) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for item in parse_json_list(value):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        try:
            lat, lng = valid_coordinate(item.get("lat"), item.get("lng"))
            min_hint_count = int(item.get("min_hint_count", 1))
            min_zoom = int(item.get("min_zoom", 4))
            max_zoom = int(item.get("max_zoom", min_zoom))
        except (TypeError, ValueError):
            continue
        if not name:
            continue
        normalized_min_zoom = min(19, max(1, min_zoom))
        normalized_max_zoom = min(19, max(normalized_min_zoom, max_zoom))
        anchor = {
            "name": name,
            "point": {"lat": lat, "lng": lng},
            "minHintCount": min(2, max(0, min_hint_count)),
            "minZoom": normalized_min_zoom,
            "maxZoom": normalized_max_zoom,
        }
        boundary = serialize_map_boundary(item.get("boundary"))
        if boundary is not None:
            try:
                boundary_min_zoom = int(item.get("boundary_min_zoom", 6))
            except (TypeError, ValueError):
                boundary_min_zoom = 6
            anchor["boundary"] = boundary
            anchor["boundaryMinZoom"] = min(19, max(1, boundary_min_zoom))
        anchors.append(anchor)
    return anchors[:3]


def reverse_geocode_zoom_for_level(level_slug: str, map_zoom: float | None) -> int:
    if level_slug == "easy":
        return 10
    if level_slug == "medium":
        return 12
    if map_zoom is not None and map_zoom >= 13:
        return 18
    return 16


def reverse_geocode_cache_key(lat: float, lng: float, reverse_zoom: int) -> str:
    return f"{REVERSE_GEOCODE_LANGUAGE}:{reverse_zoom}:{lat:.3f}:{lng:.3f}"


def reverse_geocode_snap_radius_m(lat: float, zoom: float | None, level_slug: str) -> int:
    return max(
        SNAP_RADIUS_FLOOR_M[level_slug],
        touch_snap_radius_m(lat, zoom, level_slug),
    )


def selection_from_reverse_row(
    row: sqlite3.Row,
    *,
    clicked_lat: float,
    clicked_lng: float,
    snap_radius_m: int,
) -> dict[str, Any] | None:
    point_lat = float(row["point_lat"])
    point_lng = float(row["point_lng"])
    distance_m = haversine_m(clicked_lat, clicked_lng, point_lat, point_lng)
    if distance_m > snap_radius_m:
        return None
    option = selection_payload(
        point_lat=point_lat,
        point_lng=point_lng,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snapped=True,
        name=row["name"],
        kind=row["kind"],
        distance_m=distance_m,
        snap_radius_m=snap_radius_m,
        country_code=row["country_code"],
        admin1=row["admin1"],
    )
    return selection_payload(
        point_lat=point_lat,
        point_lng=point_lng,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snapped=True,
        name=row["name"],
        kind=row["kind"],
        distance_m=distance_m,
        snap_radius_m=snap_radius_m,
        country_code=row["country_code"],
        admin1=row["admin1"],
        alternatives=[option],
        selected_index=0,
    )


def cached_reverse_geocode_selection(
    conn: sqlite3.Connection,
    *,
    cache_key: str,
    clicked_lat: float,
    clicked_lng: float,
    snap_radius_m: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            name,
            kind,
            point_lat,
            point_lng,
            country_code,
            admin1
        FROM map_reverse_geocode_cache
        WHERE cache_key = ?
        """,
        (cache_key,),
    ).fetchone()
    if row is None:
        return None
    return selection_from_reverse_row(
        row,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snap_radius_m=snap_radius_m,
    )


def reverse_geocode_name(result: dict[str, Any], level_slug: str) -> str | None:
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    name_candidates: tuple[str, ...]
    if level_slug == "hard":
        name_candidates = (
            "name",
            "tourism",
            "attraction",
            "historic",
            "amenity",
            "building",
            "man_made",
            "city",
            "town",
            "village",
            "municipality",
            "suburb",
        )
    else:
        name_candidates = (
            "city",
            "town",
            "village",
            "municipality",
            "hamlet",
            "suburb",
            "county",
            "state_district",
            "name",
        )

    for field in name_candidates:
        value = result.get(field) if field == "name" else address.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip().split(",")[0]

    display_name = result.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip().split(",")[0]
    return None


def reverse_geocode_kind(result: dict[str, Any], level_slug: str) -> str:
    result_class = str(result.get("class") or "").lower()
    result_type = str(result.get("type") or "").lower()
    if level_slug == "hard" or result_class in {"tourism", "historic", "amenity", "man_made"}:
        return "landmark"
    if result_type in {"attraction", "monument", "memorial", "castle", "museum"}:
        return "landmark"
    return "place"


def reverse_geocode_point(result: dict[str, Any]) -> tuple[float, float] | None:
    try:
        lat = float(result["lat"])
        lng = float(result["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if lat < -90 or lat > 90 or lng < -180 or lng > 180:
        return None
    return lat, lng


def reverse_geocode_admin(result: dict[str, Any]) -> tuple[str | None, str | None]:
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    country_code = address.get("country_code")
    if isinstance(country_code, str) and country_code.strip():
        country = country_code.strip().upper()
    else:
        country = None
    for field in ("state", "province", "region", "county", "state_district"):
        value = address.get(field)
        if isinstance(value, str) and value.strip():
            return country, value.strip()
    return country, None


def fetch_reverse_geocode(lat: float, lng: float, reverse_zoom: int) -> dict[str, Any] | None:
    if not REVERSE_GEOCODE_ENABLED or not REVERSE_GEOCODE_URL.strip():
        return None

    global REVERSE_GEOCODE_NEXT_REQUEST_AT
    with REVERSE_GEOCODE_LOCK:
        now = time.monotonic()
        if REVERSE_GEOCODE_NEXT_REQUEST_AT > now:
            time.sleep(REVERSE_GEOCODE_NEXT_REQUEST_AT - now)
        REVERSE_GEOCODE_NEXT_REQUEST_AT = time.monotonic() + REVERSE_GEOCODE_MIN_INTERVAL_SEC

        query = urlencode(
            {
                "format": "jsonv2",
                "lat": f"{lat:.6f}",
                "lon": f"{lng:.6f}",
                "zoom": str(reverse_zoom),
                "addressdetails": "1",
                "accept-language": REVERSE_GEOCODE_LANGUAGE,
            }
        )
        separator = "&" if "?" in REVERSE_GEOCODE_URL else "?"
        request = Request(
            f"{REVERSE_GEOCODE_URL}{separator}{query}",
            headers={
                "Accept": "application/json",
                "Accept-Language": REVERSE_GEOCODE_LANGUAGE,
                "User-Agent": REVERSE_GEOCODE_USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=REVERSE_GEOCODE_TIMEOUT_SEC) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None


def fetch_forward_geocode(
    query_text: str,
    *,
    country_code: str = "",
    limit: int = 5,
    include_boundary_geometry: bool = False,
) -> list[dict[str, Any]]:
    query_value = str(query_text or "").strip()
    if (
        not query_value
        or not REVERSE_GEOCODE_ENABLED
        or not FORWARD_GEOCODE_URL.strip()
    ):
        return []

    global REVERSE_GEOCODE_NEXT_REQUEST_AT
    with REVERSE_GEOCODE_LOCK:
        now = time.monotonic()
        if REVERSE_GEOCODE_NEXT_REQUEST_AT > now:
            time.sleep(REVERSE_GEOCODE_NEXT_REQUEST_AT - now)
        REVERSE_GEOCODE_NEXT_REQUEST_AT = time.monotonic() + REVERSE_GEOCODE_MIN_INTERVAL_SEC

        params = {
            "format": "jsonv2",
            "q": query_value,
            "limit": str(min(8, max(1, int(limit)))),
            "addressdetails": "1",
            "accept-language": REVERSE_GEOCODE_LANGUAGE,
        }
        if include_boundary_geometry:
            params["polygon_geojson"] = "1"
            params["polygon_threshold"] = "0.002"
        country_value = str(country_code or "").strip().lower()
        if country_value:
            params["countrycodes"] = country_value
        separator = "&" if "?" in FORWARD_GEOCODE_URL else "?"
        request = Request(
            f"{FORWARD_GEOCODE_URL}{separator}{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Accept-Language": REVERSE_GEOCODE_LANGUAGE,
                "User-Agent": REVERSE_GEOCODE_USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=REVERSE_GEOCODE_TIMEOUT_SEC) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
            return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def store_reverse_geocode_selection(
    conn: sqlite3.Connection,
    *,
    cache_key: str,
    clicked_lat: float,
    clicked_lng: float,
    reverse_zoom: int,
    name: str,
    kind: str,
    point_lat: float,
    point_lng: float,
    country_code: str | None,
    admin1: str | None,
    display_name: str | None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO map_reverse_geocode_cache (
            cache_key,
            lat,
            lng,
            reverse_zoom,
            provider,
            name,
            kind,
            point_lat,
            point_lng,
            country_code,
            admin1,
            display_name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            clicked_lat,
            clicked_lng,
            reverse_zoom,
            "nominatim",
            name,
            kind,
            point_lat,
            point_lng,
            country_code,
            admin1,
            display_name,
            utc_now(),
        ),
    )
    commit_if_needed(conn)


def reverse_geocode_candidate(
    conn: sqlite3.Connection,
    *,
    level_slug: str,
    clicked_lat: float,
    clicked_lng: float,
    zoom: float | None,
) -> dict[str, Any] | None:
    reverse_zoom = reverse_geocode_zoom_for_level(level_slug, zoom)
    cache_key = reverse_geocode_cache_key(clicked_lat, clicked_lng, reverse_zoom)
    snap_radius_m = reverse_geocode_snap_radius_m(clicked_lat, zoom, level_slug)
    cached = cached_reverse_geocode_selection(
        conn,
        cache_key=cache_key,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snap_radius_m=snap_radius_m,
    )
    if cached is not None:
        return cached

    result = fetch_reverse_geocode(clicked_lat, clicked_lng, reverse_zoom)
    if result is None or result.get("error"):
        return None
    point = reverse_geocode_point(result)
    name = reverse_geocode_name(result, level_slug)
    if point is None or name is None:
        return None

    point_lat, point_lng = point
    distance_m = haversine_m(clicked_lat, clicked_lng, point_lat, point_lng)
    if distance_m > snap_radius_m:
        return None

    country_code, admin1 = reverse_geocode_admin(result)
    kind = reverse_geocode_kind(result, level_slug)
    display_name = result.get("display_name")
    store_reverse_geocode_selection(
        conn,
        cache_key=cache_key,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        reverse_zoom=reverse_zoom,
        name=name,
        kind=kind,
        point_lat=point_lat,
        point_lng=point_lng,
        country_code=country_code,
        admin1=admin1,
        display_name=display_name if isinstance(display_name, str) else None,
    )
    option = selection_payload(
        point_lat=point_lat,
        point_lng=point_lng,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snapped=True,
        name=name,
        kind=kind,
        distance_m=distance_m,
        snap_radius_m=snap_radius_m,
        country_code=country_code,
        admin1=admin1,
    )
    return selection_payload(
        point_lat=point_lat,
        point_lng=point_lng,
        clicked_lat=clicked_lat,
        clicked_lng=clicked_lng,
        snapped=True,
        name=name,
        kind=kind,
        distance_m=distance_m,
        snap_radius_m=snap_radius_m,
        country_code=country_code,
        admin1=admin1,
        alternatives=[option],
        selected_index=0,
    )


def snap_guess(
    conn: sqlite3.Connection,
    *,
    level_id: int,
    lat: object,
    lng: object,
    today: str,
    zoom: object | None = None,
    allow_reverse_geocode: bool = True,
) -> tuple[dict[str, Any], int]:
    guess_lat, guess_lng = valid_coordinate(lat, lng)
    click_zoom = normalized_zoom(zoom)
    level = load_level_for_submission(conn, level_id)
    if level is None or level["status"] != "published":
        return {"error": "Map-game level was not found."}, HTTPStatus.NOT_FOUND
    if level["puzzle_date"] != today:
        return {"error": "Only today's map game can be selected."}, HTTPStatus.BAD_REQUEST

    candidates = conn.execute(
        """
        SELECT
            id,
            canonical_name,
            country_code,
            admin1,
            difficulty,
            lat,
            lng,
            scoring_radius_m
        FROM map_place_pool
        WHERE active = 1
        """
    ).fetchall()
    nearby_places: list[tuple[int, int, sqlite3.Row]] = []
    for place in candidates:
        if place_is_explicitly_excluded(place):
            continue
        distance_m = haversine_m(
            guess_lat,
            guess_lng,
            float(place["lat"]),
            float(place["lng"]),
        )
        snap_radius_m = effective_snap_radius_m(
            place,
            clicked_lat=guess_lat,
            zoom=click_zoom,
        )
        if distance_m > snap_radius_m:
            continue
        nearby_places.append((distance_m, snap_radius_m, place))

    if not nearby_places and allow_reverse_geocode:
        reverse_selection = reverse_geocode_candidate(
            conn,
            level_slug=level["level_slug"],
            clicked_lat=guess_lat,
            clicked_lng=guess_lng,
            zoom=click_zoom,
        )
        if reverse_selection is not None:
            return reverse_selection, HTTPStatus.OK

    if not nearby_places:
        return {
            "error": "No nearby place found. Try tapping closer to a town, city, or landmark."
        }, HTTPStatus.UNPROCESSABLE_ENTITY

    nearby_places.sort(
        key=lambda candidate: (
            candidate[0],
            0 if candidate[2]["difficulty"] == level["level_slug"] else 1,
            candidate[2]["canonical_name"],
        )
    )
    unique_nearby_places: list[tuple[int, int, sqlite3.Row]] = []
    seen_place_names: set[str] = set()
    for candidate in nearby_places:
        normalized_name = normalized_place_name(candidate[2]["canonical_name"])
        if normalized_name in seen_place_names:
            continue
        seen_place_names.add(normalized_name)
        unique_nearby_places.append(candidate)
        if len(unique_nearby_places) >= MAX_SNAP_ALTERNATIVES:
            break
    nearby_places = unique_nearby_places
    alternatives = [
        selection_payload(
            point_lat=float(place["lat"]),
            point_lng=float(place["lng"]),
            clicked_lat=guess_lat,
            clicked_lng=guess_lng,
            snapped=True,
            name=place["canonical_name"],
            kind=place_kind(place),
            distance_m=distance_m,
            snap_radius_m=snap_radius_m,
            country_code=place["country_code"],
            admin1=place["admin1"],
        )
        for distance_m, snap_radius_m, place in nearby_places
    ]

    best = nearby_places[0]
    distance_m, snap_radius_m, place = best
    return selection_payload(
        point_lat=float(place["lat"]),
        point_lng=float(place["lng"]),
        clicked_lat=guess_lat,
        clicked_lng=guess_lng,
        snapped=True,
        name=place["canonical_name"],
        kind=place_kind(place),
        distance_m=distance_m,
        snap_radius_m=snap_radius_m,
        country_code=place["country_code"],
        admin1=place["admin1"],
        alternatives=alternatives,
        selected_index=0,
    ), HTTPStatus.OK


def normalized_revealed_hint_count(value: object | None) -> int:
    try:
        count = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
    return min(3, max(0, count))


def normalized_place_name(value: object | None) -> str:
    text = str(value or "").lower()
    return "".join(character for character in text if character.isalnum())


def selected_place_matches_answer(selected_name: object | None, answer_name: object | None) -> bool:
    selected = normalized_place_name(selected_name)
    answer = normalized_place_name(answer_name)
    return bool(selected and answer and selected == answer)


def score_for_revealed_hint_count(revealed_hint_count: int, *, correct: bool) -> int:
    if not correct:
        return 0
    return MAP_CLUE_SCORES[normalized_revealed_hint_count(revealed_hint_count)]


def result_band(*, correct: bool, revealed_hint_count: int) -> str:
    if not correct:
        return "Wrong place"
    if revealed_hint_count <= 0:
        return "Solved from hard clue"
    if revealed_hint_count == 1:
        return "Solved with medium clue"
    if revealed_hint_count == 2:
        return "Solved with easy clue"
    return "Solved after name reveal"


def score_guess(distance_m: int, level_slug: str) -> int:
    target_radius_m = normalized_scoring_radius_m(level_slug)
    return MAP_MAX_SCORE if distance_m <= target_radius_m else 0


def graded_distance_m(distance_m: int, target_radius_m: int) -> int:
    return max(0, int(distance_m) - int(target_radius_m))


def accuracy_band(
    distance_m: int,
    *,
    inside_target_area: bool = False,
    raw_distance_m: int | None = None,
) -> str:
    if inside_target_area:
        if raw_distance_m is not None and raw_distance_m <= 1_000:
            return "Bullseye"
        return "Correct area"
    distance_km = distance_m / 1000.0
    if distance_km <= 1:
        return "Bullseye"
    if distance_km <= 10:
        return "Excellent"
    if distance_km <= 50:
        return "Close"
    if distance_km <= 200:
        return "Nearby"
    return "Far"


def score_components(
    *,
    distance_m: int,
    level_slug: str,
    scoring_radius_m: object | None,
    revealed_hint_count: object | None = None,
    selected_name: object | None = None,
    answer_name: object | None = None,
) -> dict[str, int | str | bool]:
    target_radius_m = normalized_scoring_radius_m(level_slug, scoring_radius_m)
    outside_target_m = graded_distance_m(distance_m, target_radius_m)
    revealed_count = normalized_revealed_hint_count(revealed_hint_count)
    correct = distance_m <= target_radius_m or selected_place_matches_answer(selected_name, answer_name)
    return {
        "target_radius_m": target_radius_m,
        "graded_distance_m": outside_target_m,
        "inside_target_area": correct,
        "correct": correct,
        "revealed_hint_count": revealed_count,
        "score": score_for_revealed_hint_count(revealed_count, correct=correct),
        "band": result_band(correct=correct, revealed_hint_count=revealed_count),
    }


def backfill_daily_map_guess_scores(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            daily_map_guesses.id AS guess_id,
            daily_map_guesses.distance_m,
            daily_map_guesses.score,
            daily_map_guesses.band,
            daily_map_guesses.selected_name,
            daily_map_guesses.revealed_hint_count,
            daily_map_levels.level_slug,
            map_place_pool.canonical_name,
            map_place_pool.scoring_radius_m
        FROM daily_map_guesses
        INNER JOIN daily_map_levels
            ON daily_map_levels.id = daily_map_guesses.level_id
        INNER JOIN map_place_pool
            ON map_place_pool.id = daily_map_levels.place_id
        """
    ).fetchall()
    now = utc_now()
    for row in rows:
        components = score_components(
            distance_m=int(row["distance_m"]),
            level_slug=row["level_slug"],
            scoring_radius_m=row["scoring_radius_m"],
            revealed_hint_count=row["revealed_hint_count"],
            selected_name=row["selected_name"],
            answer_name=row["canonical_name"],
        )
        score = int(components["score"])
        band = str(components["band"])
        if int(row["score"]) == score and row["band"] == band:
            continue
        conn.execute(
            """
            UPDATE daily_map_guesses
            SET score = ?, band = ?, updated_at = ?
            WHERE id = ?
            """,
            (score, band, now, row["guess_id"]),
        )


def load_level_for_submission(conn: sqlite3.Connection, level_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            daily_map_levels.id AS level_id,
            daily_map_levels.place_id AS answer_place_id,
            daily_map_levels.level_slug,
            daily_map_levels.max_points,
            daily_map_puzzles.puzzle_date,
            daily_map_puzzles.status,
            map_place_pool.canonical_name,
            map_place_pool.country_code,
            map_place_pool.admin1,
            map_place_pool.lat AS answer_lat,
            map_place_pool.lng AS answer_lng,
            map_place_pool.clue_text,
            map_place_pool.medium_clue_text,
            map_place_pool.easy_clue_text,
            map_place_pool.reveal_text,
            map_place_pool.scoring_radius_m
        FROM daily_map_levels
        INNER JOIN daily_map_puzzles
            ON daily_map_puzzles.id = daily_map_levels.puzzle_id
        INNER JOIN map_place_pool
            ON map_place_pool.id = daily_map_levels.place_id
        WHERE daily_map_levels.id = ?
        """,
        (level_id,),
    ).fetchone()


def submitted_level_row(conn: sqlite3.Connection, user_id: int, level_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            daily_map_levels.id AS level_id,
            daily_map_levels.level_slug,
            daily_map_levels.max_points,
            map_place_pool.canonical_name,
            map_place_pool.country_code,
            map_place_pool.admin1,
            map_place_pool.lat AS answer_lat,
            map_place_pool.lng AS answer_lng,
            map_place_pool.clue_text,
            map_place_pool.medium_clue_text,
            map_place_pool.easy_clue_text,
            map_place_pool.reveal_text,
            map_place_pool.scoring_radius_m,
            daily_map_guesses.id AS guess_id,
            daily_map_guesses.guessed_lat,
            daily_map_guesses.guessed_lng,
            daily_map_guesses.selected_name,
            daily_map_guesses.revealed_hint_count,
            daily_map_guesses.distance_m,
            daily_map_guesses.score,
            daily_map_guesses.band,
            daily_map_guesses.completed_at
        FROM daily_map_guesses
        INNER JOIN daily_map_levels
            ON daily_map_levels.id = daily_map_guesses.level_id
        INNER JOIN map_place_pool
            ON map_place_pool.id = daily_map_levels.place_id
        WHERE daily_map_guesses.user_id = ?
          AND daily_map_guesses.level_id = ?
        """,
        (user_id, level_id),
    ).fetchone()


def submit_guess(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    level_id: int,
    lat: object,
    lng: object,
    selected_name: object | None = None,
    revealed_hint_count: object | None = None,
    today: str,
) -> tuple[dict[str, Any], int]:
    guess_lat, guess_lng = valid_coordinate(lat, lng)
    selected_name_value = str(selected_name).strip() if selected_name is not None else None
    if selected_name_value == "":
        selected_name_value = None
    revealed_count = normalized_revealed_hint_count(revealed_hint_count)
    level = load_level_for_submission(conn, level_id)
    if level is None or level["status"] != "published":
        return {"error": "Map-game level was not found."}, HTTPStatus.NOT_FOUND
    if level["puzzle_date"] != today:
        return {"error": "Only today's map game can be scored."}, HTTPStatus.BAD_REQUEST

    existing = submitted_level_row(conn, user_id, level_id)
    if existing is not None:
        return {"result": reveal_payload_from_row(existing)}, HTTPStatus.OK

    distance_m = haversine_m(
        guess_lat,
        guess_lng,
        float(level["answer_lat"]),
        float(level["answer_lng"]),
    )
    components = score_components(
        distance_m=distance_m,
        level_slug=level["level_slug"],
        scoring_radius_m=level["scoring_radius_m"],
        revealed_hint_count=revealed_count,
        selected_name=selected_name_value,
        answer_name=level["canonical_name"],
    )
    score = int(components["score"])
    band = str(components["band"])
    now = utc_now()
    try:
        conn.execute(
            """
            INSERT INTO daily_map_guesses (
                user_id, level_id, guessed_lat, guessed_lng, selected_name,
                revealed_hint_count, distance_m, score, band, completed_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                level_id,
                guess_lat,
                guess_lng,
                selected_name_value,
                revealed_count,
                distance_m,
                score,
                band,
                now,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        pass

    row = submitted_level_row(conn, user_id, level_id)
    if row is None:
        return {"error": "Map-game guess could not be saved."}, HTTPStatus.INTERNAL_SERVER_ERROR
    return {"result": reveal_payload_from_row(row)}, HTTPStatus.CREATED
