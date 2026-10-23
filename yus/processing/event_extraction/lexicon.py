"""Words and phrases of indoor Ultimate play-by-play, and the tagger that finds them in transcript words.

The tagger turns words into `Item`s: phrases the extractor acts on ("picked up by", "deed by", "in the end zone"), team references
("for dark"), and the spans between them, which become player NAMEs as spoken ("close crop", "the kid"). Known names (roster names,
nicknames and mondegreens, and names the commentator announced) are matched as whole spans first, so "kaia mann" stays one name,
also with a possessive ("adam federbusch's huck"). Common words that are not names (STOPWORDS: "the disc", "alright", "team") are
fillers.
Punctuation from the ASR splits names and marks clause boundaries: "." "?" "!" and ";" end a sentence, "," and ":" are weak.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import enum
import re
import unicodedata
from collections.abc import Iterable

import yus
from yus.sports.ultimate import ThrowDirection, ThrowType


class Tag(enum.Enum):
    TYPE = "throw type"  # value: ThrowType
    DIR = "throw direction"  # value: ThrowDirection
    TO = "to"
    THROWV = "throw verb"
    CAUGHT = "caught"
    SCORE = "score"
    NOSCORE = "no score"
    NOT_IN = "not in"  # takes a score back: "not in the end zone", "not a score"
    DROP = "dropped"
    THROWAWAY = "throws it away"
    DEFENSE = "defense"
    INTERCEPT = "interception"
    EZ_IN = "in the end zone"
    EZ_TO = "to the end zone"
    WALL = "off the wall"
    NET = "off the net"
    PICKUP = "picked up"
    CHECKIN = "checked in"
    PULL = "pull"
    HAS = "has it"
    LINEUP = "line-up"
    IS = "is"  # "red shorts is kaia"
    CORRECT = "correction"  # "to tristan, sorry, to joe", "nope", "that wasn't joe"
    UNK = "unknown player"
    NUM = "number"
    TEAM = "team"  # value: team index
    TEAMREF = "for team"  # value: team index
    NAME = "name"  # value: the name as spoken
    BOUNDARY = "boundary"  # value: True for a sentence end, False for a comma
    FILLER = "filler"


@dataclasses.dataclass(slots=True)
class Token:
    """One lower-case word piece of a transcript word, and the strongest punctuation right after it (None, "weak" or "strong")."""

    text: str
    start: dt.datetime
    end: dt.datetime
    boundary: str | None = None


@dataclasses.dataclass(slots=True)
class Item:
    tag: Tag
    value: object
    text: str
    start: dt.datetime
    end: dt.datetime


def _phrases() -> list[tuple[Tag, str, object]]:
    table: list[tuple[Tag, str, object]] = []

    def add(tag: Tag, phrases: str, value: object = None) -> None:
        table.extend((tag, phrase.strip(), value) for phrase in phrases.split("|") if phrase.strip())

    add(Tag.TYPE, "flick|flicks|flicked|flick it|forehand|forehands", ThrowType.FLICK)
    add(Tag.TYPE, "backhand|backhands|backhanded|backhand it|back hand|back hands", ThrowType.BACKHAND)
    add(Tag.TYPE, "hammer|hammers|hammered", ThrowType.HAMMER)
    add(Tag.TYPE, "scoober|scoobers|scooper|scoopers", ThrowType.SCOOBER)
    add(Tag.TYPE, "blade|blades|bladed", ThrowType.BLADE)
    add(Tag.TYPE, "chicken wing|chicken wings", ThrowType.CHICKEN_WING)
    add(Tag.DIR, "dump|dumps|dumped|dumping|dump it|dumps it", ThrowDirection.DUMP)
    add(Tag.DIR, "swing|swings|swung|swinging|swings it|swing it", ThrowDirection.SWING)
    add(Tag.DIR, "huck|hucks|hucked|hucking|put|puts|puts it|bomb|bombs", ThrowDirection.HUCK)  # "put" is a long throw: "hammer put"
    add(Tag.DIR, "up the line|up line|upline|up the sideline", ThrowDirection.UP_LINE)
    add(Tag.DIR, "cross field|crossfield|across the field", ThrowDirection.CROSS_FIELD)
    add(Tag.TO, "to|over to|into")
    add(Tag.THROWV, "throws|throws it|passes|passes it|finds|hits|looks to|looking to|looks for|looking for")
    add(Tag.CAUGHT, "caught by|catch by|caught|catches|grabbed by|grab by|hauled in by|reeled in by|received by|makes the catch|make the catch|with the catch")
    add(Tag.SCORE, "for a score|for the score|for a goal|for the goal|for a point|for the point|scores|score|goal|touchdown")
    add(Tag.NOSCORE, "no score|no goal|not caught|no catch")
    add(Tag.NOT_IN, "not in the end zone|not in the endzone|not in end zone|not in endzone|not in the zone|not in|wasn't in|was not in|isn't in")
    add(Tag.NOT_IN, "not a score|not a goal|not for a score|not for the score|not a point|out of the end zone|short of the end zone")
    add(Tag.DROP, "dropped|drops|drop|drop it|dropped it|turfed|turf|turfs|turfs it|out of bounds|out the back")
    add(Tag.THROWAWAY, "throwaway|throw away|thrown away|throws it away|throw it away|threw it away")
    add(Tag.DROP, "incomplete|missed|misses|overthrown|overthrows|stalled|stalled out|stall|turnover|turn over")
    add(Tag.DEFENSE, "deed by|deed|deeded by|d by|d'd by|d'd|dee'd by|dee'd|d'ed by|d'ed|dee by|dead by|d|blocked by|block by|blocked")
    add(Tag.DEFENSE, "defense by|defended by|gets a hand on it|got a hand on it|a hand on it")
    add(Tag.DEFENSE, "knocked down by|knocked down|point block by|hand block by|foot block by|layout d by|layout block by|swatted by|broken up by")
    add(Tag.DEFENSE, "with the d|with the deed|with the block|gets the d|gets the block|gets a d|gets a block|the d|a d|gets the deed|gets a deed|with a d|with a block")
    add(Tag.INTERCEPT, "stolen by|stolen|intercepted by|intercepted|picked off by|picked off|interception by|stole it|steals it|callahan by|callahan")
    add(Tag.INTERCEPT, "with the interception|with the steal|picks it off|picks off")
    add(Tag.EZ_IN, "in the end zone|in the endzone|in end zone|in endzone|in the zone")
    add(Tag.EZ_TO, "to the end zone|into the end zone|to the endzone|into the endzone|toward the end zone|towards the end zone|to end zone")
    add(Tag.EZ_TO, "the end zone|end zone|the endzone|endzone")
    add(Tag.WALL, "off the wall|off a wall|off the glass|hits the wall|hit the wall|wall|glass")
    add(Tag.NET, "off the net|off the netting|into the net|hits the net|net|netting")
    add(Tag.PICKUP, "picked up by|picks it up|picks up|picked it up|picking it up|pick it up|picked up|pick up|picks it|picked|picks")
    add(Tag.PICKUP, "picks it right up|picks it back up|picks up the disc|picked up the disc")
    add(Tag.CHECKIN, "taps it in|tapped in|tap it in|taps in|tapped it in|checks it in|checked in|check it in|checks in|checked it in|check in")
    add(Tag.CHECKIN, "check|checks|checked")
    add(Tag.PULL, "pulls|pull|pulled|pulling")
    add(Tag.HAS, "gets it|has it|grabs it|got it|has the disc|gets the disc")
    add(Tag.LINEUP, "we have|we've got|we got|on the line|line up|lineup|here's the line")
    add(Tag.LINEUP, "d line|o line|d lines|o lines|the d line|the o line|with the d line|on the d line|on d line|on o line|on the o line")  # not "the d"
    add(Tag.CORRECT, "sorry|i mean|no wait|wait no|correction|or rather|my bad|my mistake|scratch that|nope|no|actually|er|wait|oops|whoops")
    add(Tag.IS, "is|is actually|is really|is named|is called|name is")
    add(Tag.UNK, "somebody|someone|some one|some body|i dunno|i don't know|dunno|don't know|unknown|who knows|not sure|nobody")
    add(Tag.NUM, "zero|nothing|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|all|apiece|each|game point")
    fillers = "and|a|an|uh|um|oh|okay|ok|so|then|now|big|nice|great|huge|quick|little|long|good|beautiful|lovely|easy|it|that|that's"
    add(Tag.FILLER, fillers + "|there|here|goes|was|with|by|of|just|again|another|yeah|yes|well|wow|like|for")
    return table


PHRASES = _phrases()

STOPWORDS = frozenset(
    """
i me my myself we our ours you your yours he him his himself she her hers herself it its itself they them their theirs
what which who whom this that these those am are was were be been being have has had having do does did doing
but if or because as until while of at about against between through during before after above below from up down
in out on off over under again further then once here there when where why how both each few more most other some
such no nor not only own same than too very can will just don should now would could also still really even
he's she's it's they're that's there's what's let's i'm we're you're we've i've isn't wasn't don't doesn't didn't
go goes going gone see look looks looking got get gets getting make makes made for nope wait sorry actually
back deep away thank thanks watching bye ready open almost target fast tricky smooth awesome amazing sweet solid perfect moving catching finding
throw pass catch play move block defense
disc frisbee team teams point points line lines game ball alright allright right ah ahh aah hmm hm mm huh whoa woah yep yup nah oops
ooh ohh guys folks everybody everyone tonight today time comes coming came come cut cuts cutting mark marker stack force zone
corner corners sideline middle field side space lane area air ground hand hands
""".split()
)

_NUMBER_WORDS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten"}
_PIECE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")  # letters (any script) and digits, with inner apostrophes: "d'd", "josé"
_STRONG = re.compile(r"[.!?;…]")
_WEAK = re.compile(r"[,:—–]")


def clean(text: str) -> str:
    """Lower-case text with typographic quotes made plain and "&" spelled "and"."""
    return unicodedata.normalize("NFKC", text).casefold().replace("’", "'").replace("‘", "'").replace("ʼ", "'").replace("&", " and ")


def pieces(text: str) -> tuple[str, ...]:
    """The word pieces of a phrase as the tagger sees them ("Knappe-Butler," -> ("knappe", "butler"))."""
    return tuple(_PIECE.findall(clean(text)))


def _boundary(gap: str) -> str | None:
    return "strong" if _STRONG.search(gap) else "weak" if _WEAK.search(gap) else None


def tokenize(words: Iterable[yus.Word]) -> list[Token]:
    """Word pieces of ASR words ("Kaia Mann," -> "kaia", "mann" + weak boundary; "-huck" -> "huck"; "D'd" -> "d'd")."""
    tokens: list[Token] = []
    for word in words:
        text = clean(word.text)
        found = list(_PIECE.finditer(text))
        lead = _boundary(text[: found[0].start()] if found else text)
        if lead and tokens:
            tokens[-1].boundary = "strong" if "strong" in (lead, tokens[-1].boundary) else "weak"
        end = word.start + word.duration
        for k, match in enumerate(found):
            gap = text[match.end() : found[k + 1].start() if k + 1 < len(found) else len(text)]
            tokens.append(Token(match.group(), word.start, end, _boundary(gap)))
    return tokens


class Tagger:
    """Tags tokens with the phrase table, the teams' names, and known player names (which can grow during a game)."""

    def __init__(self, team_names: list[list[str]], known_names: Iterable[str] = ()):
        self.phrases: dict[tuple[str, ...], tuple[Tag, object]] = {}
        for tag, phrase, value in PHRASES:
            self.phrases.setdefault(pieces(phrase), (tag, value))
        for index, names in enumerate(team_names):
            for name in names:
                for variant in _team_variants(pieces(name)):
                    self.phrases[variant] = (Tag.TEAM, index)
                    for prefix in (("for",), ("on",), ("for", "the"), ("on", "the")):
                        self.phrases[prefix + variant] = (Tag.TEAMREF, index)
        self.longest_phrase = max(len(key) for key in self.phrases)
        self.names: set[tuple[str, ...]] = set()
        self.longest_name = 1
        for name in known_names:
            self.add_name(name)

    def copy(self) -> Tagger:
        """A copy whose known names can grow apart from this one's (the phrase table is shared: it never changes)."""
        new = copy.copy(self)
        new.names = set(self.names)
        return new

    def add_name(self, name: str) -> None:
        """Treat `name` as one player name wherever it is said, unless it is a phrase or a stopword."""
        key = pieces(name)
        if key and key not in self.phrases and not (len(key) == 1 and (key[0] in STOPWORDS or len(key[0]) < 2)):
            self.names.add(key)
            self.longest_name = max(self.longest_name, len(key))

    def tag(self, tokens: list[Token]) -> list[Item]:
        """Items for tokens: the longest phrase or known name at each position (phrases win ties); runs of other words become NAMEs."""
        items: list[Item] = []
        pending: list[Token] = []
        i = 0
        while i < len(tokens):
            length, tag, value = self._match(tokens, i)
            if length == 0:
                pending.append(tokens[i])
                i += 1
            else:
                _flush_name(pending, items)
                span = tokens[i : i + length]
                items.append(Item(tag, value, " ".join(t.text for t in span), span[0].start, span[-1].end))
                i += length
            if tokens[i - 1].boundary:
                _flush_name(pending, items)
                items.append(Item(Tag.BOUNDARY, tokens[i - 1].boundary == "strong", tokens[i - 1].boundary or "", tokens[i - 1].end, tokens[i - 1].end))
        _flush_name(pending, items)
        return items

    def _match(self, tokens: list[Token], i: int) -> tuple[int, Tag, object]:
        texts = tuple(t.text for t in tokens[i : i + max(self.longest_phrase, self.longest_name)])
        limit = next((k + 1 for k, t in enumerate(tokens[i : i + len(texts) - 1]) if t.boundary), len(texts))  # never span a boundary
        for length in range(limit, 0, -1):
            key = texts[:length]
            for candidate in (key, key[:-1] + (key[-1][:-2],)) if key[-1].endswith("'s") else (key,):  # "federbusch's", "score's"
                if candidate in self.phrases:
                    return length, *self.phrases[candidate]
                if candidate in self.names:
                    return length, Tag.NAME, " ".join(candidate)
        word = texts[0]
        if word in ("number", "numero") and limit > 1 and (texts[1].isdigit() or self.phrases.get(texts[1:2], (None,))[0] is Tag.NUM):
            return 2, Tag.NAME, " ".join(texts[:2])  # a jersey number: "number twelve"
        if word.isdigit():
            return 1, Tag.NUM, int(word)
        if word in STOPWORDS:
            return 1, Tag.FILLER, None
        return 0, Tag.NAME, None


def _team_variants(key: tuple[str, ...]) -> list[tuple[str, ...]]:
    spelled = tuple(_NUMBER_WORDS.get(piece, piece) for piece in key)
    return [key] if spelled == key else [key, spelled]


def _flush_name(pending: list[Token], items: list[Item]) -> None:
    if not pending:
        return
    texts = [t.text for t in pending]
    tag = Tag.FILLER if all(t in ("the", "a", "an") for t in texts) else Tag.NAME
    name = " ".join(texts).removesuffix("'s")  # "kaia's huck": kaia
    items.append(Item(tag, name if tag is Tag.NAME else None, " ".join(texts), pending[0].start, pending[-1].end))
    pending.clear()
