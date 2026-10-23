"""Optional LLM help for the rule-based extractor: a second reading of the groups the rules may have misread.

`AssistedExtractor` wraps an `EventExtractor` and has the same interface. The rules parse every group first, as always. A group
that looks uncertain (see `reasons`) is also sent, with a little context, to a local Ollama model, which may revise that group's
events:

- a correction ("nope, not in the end zone", "sorry");
- a player name that is no known name and is said for the first time ("bobbled", "across");
- a throw that seems restated ("flick put huck close crop" gives a throw without a receiver, then one without a thrower);
- a name that no event used ("dropped by hat");
- throw words that changed nothing.

The rule events show at once and stay provisional until the answer arrives or `budget` seconds pass. On a timeout, an error, or
an answer that does not check out (an unknown team, a name nobody said), the rule events stand. A revision replaces the group's
events; later groups are parsed again from there, so a retracted score gives the disc back. Answers are applied by `poll()`,
`feed()`, `advance()` and `finish()`, never by a background thread, so the extractor needs no lock of its own. See
docs/extraction.md for when it helps.
"""

from __future__ import annotations

import collections
import concurrent.futures
import dataclasses
import datetime as dt
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import yus
from yus.processing.event_extraction.extractor import EventExtractor
from yus.processing.event_extraction.lexicon import Item, Tag
from yus.processing.event_unification.players import normalize
from yus.sports import ultimate
from yus.sports.ultimate import ThrowDirection, ThrowType, indoor

log = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_BUDGET = 10.0  # seconds a group's events wait for the model before the rule events stand
CORRECTIONS = frozenset("nope no not sorry actually wait oops scratch correction rather".split())
THROW_WORDS = frozenset({Tag.TYPE, Tag.DIR, Tag.TO, Tag.THROWV, Tag.CAUGHT, Tag.DEFENSE, Tag.INTERCEPT, Tag.SCORE, Tag.DROP, Tag.THROWAWAY})
RESULTS = ("caught", "incomplete", "score")
UNKNOWN = frozenset(normalize(name) for name in ("", "somebody", "someone", "unknown", "nobody", "none", "null", "i don't know", "i dunno", "dunno", "don't know", "not sure"))
CORRECTION = "a correction"
NEW_NAME = "new name"
RESTATED = "a throw without a receiver, then one without a thrower"
UNUSED = "name not in any event"
NO_EVENT = "throw words but no event"

Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


class InvalidAnswer(ValueError):
    """The model's answer is not usable: not JSON, not the schema, or naming someone nobody said."""


@dataclasses.dataclass(slots=True)
class Call:
    """One group sent to the model. `outcome`: "revised", "confirmed" (the rule events stand), "invalid" (an answer that did not
    check out), "error", "timeout" (no answer within the budget), "late" (an answer after the budget), or "skipped" (the budget
    ran out while earlier groups were being answered)."""

    group: int
    reasons: list[str]
    outcome: str = "waiting"
    latency: float | None = None  # seconds from sending to the answer
    error: str | None = None


@dataclasses.dataclass(slots=True)
class Request:
    """What the model is shown for one group."""

    text: str
    earlier: list[str]  # the texts of a few earlier groups, oldest first
    teams: list[list[str]]  # each team's names, the event label first
    possession: str | None  # label of the team with the disc before the group
    holder: str | None  # who had the disc before the group, as spoken
    events: list[yus.Event]  # the rules' events for the group; the first may be a throw still open from before it
    open_before: bool  # events[0] started before this group
    open_after: bool  # the last event is a throw the next group may still finish
    reasons: list[str]
    defense_words: int = 0  # how many defense phrases the group has ("deed by", "stolen")
    span: tuple[dt.datetime, dt.datetime] | None = None  # the group's first and last word's start


@dataclasses.dataclass
class LLMAssistant:
    """How to reach the model, and how long a group may wait for it. `post` does the HTTP call (replaced in tests)."""

    model: str
    url: str = DEFAULT_URL
    budget: float = DEFAULT_BUDGET
    keep_alive: str = "30m"
    max_tokens: int = 300
    context: int = 2  # earlier groups shown with each request
    num_ctx: int = 4096
    post: Post | None = None

    def ask(self, request: Request, timeout: float) -> list[yus.Event] | None:
        """The model's events for the request's group, or None if it says the rules got it right. Raises InvalidAnswer, OSError."""
        labels = [names[0] for names in request.teams]
        body = {
            "model": self.model,
            "messages": messages(request),
            "stream": False,
            "format": answer_schema(labels),
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_predict": self.max_tokens, "num_ctx": self.num_ctx},
        }
        reply = (self.post or post_json)(self.url.rstrip("/") + "/api/chat", body, timeout)
        try:
            content = reply["message"]["content"]
        except (KeyError, TypeError) as error:
            raise InvalidAnswer(f"no message in the reply: {str(reply)[:200]}") from error
        return parse_answer(content, request)

    def warm(self, timeout: float = 120.0) -> None:
        """Load the model and its fixed prompt now, so the first group does not wait for that. Raises OSError."""
        body = {"model": self.model, "messages": messages(None), "stream": False, "keep_alive": self.keep_alive, "options": {"num_predict": 1, "num_ctx": self.num_ctx}}
        (self.post or post_json)(self.url.rstrip("/") + "/api/chat", body, timeout)


def post_json(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST JSON, return the JSON reply. Raises OSError (urllib.error.URLError, TimeoutError) or ValueError."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=max(timeout, 0.1)) as response:
        return json.load(response)


# ---------------------------------------------------------------------------------------------------------- which groups to send


def reasons(items: list[Item], before: list[yus.Event], after: list[yus.Event], holder: str | None, knows: Callable[[str], bool], seen: set[str]) -> list[str]:
    """Why the rules' reading of a group may be wrong (empty: send nothing). `items` are the group's parsed items, `before` the
    open events before it (the open throw, if any), `after` its events (the open throw first), `holder` who has the disc after
    it, `seen` the names of earlier groups' events (normalized)."""
    found: list[str] = []
    if any(item.tag is Tag.CORRECT or (item.tag is Tag.FILLER and item.text in CORRECTIONS) for item in items):
        found.append(CORRECTION)
    names = [name for event in after for name in _names(event)]
    new = [name for name in names if normalize(name) not in seen and not knows(name)]
    if new:
        found.append(f"{NEW_NAME} " + ", ".join(f'"{name}"' for name in dict.fromkeys(new)))
    if _restated(items, [event for event in after[len(before) :] if isinstance(event, ultimate.Throw)]):
        found.append(RESTATED)
    used = {normalize(name) for name in names} | ({normalize(holder)} if holder else set())
    unused = [str(item.value) for item in items if item.tag is Tag.NAME and normalize(str(item.value)) not in used]
    if unused:
        found.append(f"{UNUSED} " + ", ".join(f'"{name}"' for name in dict.fromkeys(unused)))
    if after == before and any(item.tag in THROW_WORDS for item in items):
        found.append(NO_EVENT)
    return found


def _restated(items: list[Item], throws: list[ultimate.Throw]) -> bool:
    """Did the group say a throw without a receiver and then one without a thrower ("flick put huck close crop"), with no sentence
    end between them? Not when a receiver was said to be unknown ("backhand to i don't know. backhand.")."""
    if any(item.tag is Tag.UNK for item in items):
        return False
    ends = [item.start for item in items if item.tag is Tag.BOUNDARY and item.value]
    return any(_split(a, b) and not any(a.when <= end < b.when for end in ends) for a, b in zip(throws, throws[1:]))


def _names(event: yus.Event) -> list[str]:
    return [name for name in (getattr(event, "player", None), getattr(event, "receiver", None)) if name]


# ------------------------------------------------------------------------------------------------------------- prompt and answer

SYSTEM = """\
You check how a rule-based parser read one utterance of live play-by-play commentary of an indoor Ultimate (frisbee) game, and \
correct it when it is wrong.

Events, as compact JSON:
- throw: {"kind":"throw","team":T,"player":THROWER,"receiver":R,"type":TYPE,"direction":DIR,"result":RESULT,"wall":false}
  - type: "flick" (forehand), "backhand", "hammer", "scoober", "blade", "chicken_wing", or null
  - direction: "dump", "swing", "up_line", "cross_field" ("across the field"), "huck" ("bomb"), or null
  - result: "caught"; "incomplete" (dropped, turfed, out of bounds, thrown away, blocked); "score" (caught in the end zone)
  - wall: true when the disc hit the wall
- defense: {"kind":"defense","team":T,"player":DEFENDER,"intercepted":false} for "deed by X" or "blocked by X"; intercepted is \
true only for "stolen by X", "intercepted", "picked off". It follows the throw it stopped, which is incomplete; the defender is \
not that throw's receiver.

How this commentary works:
- A throw is said as its type or direction, then its receiver: "flick to sam", "backhand swing lee", "huck red shorts". The \
thrower is whoever has the disc, usually the previous receiver. Players are named by names, nicknames or descriptions ("the \
kid", "red shorts").
- After an incomplete throw, a defense or a score, the other team gets the disc ("picked up by X").
- Write each name exactly as said, in lower case. Use null for an unknown player ("somebody", "i don't know"). Only a person \
can be a player: verbs, adjectives and words describing the throw ("tipped", "lofted", "quick", "deep") are never names.
- When the commentator corrects himself ("for the goal, wait, no, it was turfed"; "to sam, sorry, to lee"), the later words win: \
change the event, do not add another.
- The same throw said twice ("backhand, backhand swing to lee") is one throw.
- The thrower may be named after the receiver, or in a passive: "lee catches sam's hammer" and "sam's hammer is caught by lee" \
are both sam to lee.
- Score lines ("five four white"), line-ups and chatter are no events.

You get the teams, who had the disc before the utterance, the utterances just before it, the utterance, and the parser's events \
for it, numbered.
- An event marked "started before" is the throw that was still open: the utterance may finish or change it.
- An event marked "unfinished" is a throw the utterance stops in the middle of ("flick to", "backhand"): the next utterance \
finishes it. Keep it.
- Events of the earlier utterances are already recorded: never repeat them. Words like "for a score" or "dropped" with no \
parser events are about such an earlier throw: answer {"correct":true}.
If the parser's events are right, answer {"correct":true}. Otherwise answer {"correct":false,"events":[...]}: the corrected list \
of events for the utterance, in order, where {"same":N} keeps the parser's event N unchanged."""

_TEAMS = 'Teams: "white" (also light), "dark" (also black)'
EXAMPLES = [
    (
        f'{_TEAMS}\nDisc before: white, held by sam\nEarlier: "picked up by sam for white"\nUtterance: "backhand swing to red shorts. flick"\n'
        "Parser's events:\n"
        '1. {"kind":"throw","team":"white","player":"sam","receiver":"red shorts","type":"backhand","direction":"swing","result":"caught","wall":false}\n'
        '2. {"kind":"throw","team":"white","player":"red shorts","receiver":null,"type":"flick","direction":null,"result":"caught","wall":false} '
        "(unfinished)\n"
        'Checked because: new name "red shorts"',
        '{"correct":true}',
    ),
    (
        f'{_TEAMS}\nDisc before: dark, held by alex\nEarlier: "flick to alex"\nUtterance: "hammer to jo for the goal, wait, no, it was turfed"\n'
        "Parser's events:\n"
        '1. {"kind":"throw","team":"dark","player":"alex","receiver":"jo","type":"hammer","direction":null,"result":"score","wall":false}\n'
        "Checked because: a correction",
        '{"correct":false,"events":[{"kind":"throw","team":"dark","player":"alex","receiver":"jo","type":"hammer","direction":null,"result":"incomplete","wall":false}]}',
    ),
    (
        f'{_TEAMS}\nDisc before: white, held by lee\nEarlier: "dump to sam" / "backhand to lee"\nUtterance: "flick bomb, huck to blue hat"\n'
        "Parser's events:\n"
        '1. {"kind":"throw","team":"white","player":"lee","receiver":null,"type":"flick","direction":"huck","result":"caught","wall":false}\n'
        '2. {"kind":"throw","team":"white","player":null,"receiver":"blue hat","type":null,"direction":"huck","result":"caught","wall":false}\n'
        'Checked because: new name "blue hat"; a throw without a receiver, then one without a thrower',
        '{"correct":false,"events":[{"kind":"throw","team":"white","player":"lee","receiver":"blue hat","type":"flick","direction":"huck","result":"caught","wall":false}]}',
    ),
    (
        f'{_TEAMS}\nDisc before: dark, held by jo\nEarlier: "backhand to jo"\nUtterance: "scoober tipped by max dropped. sam picks it up. dump to lee"\n'
        "Parser's events:\n"
        '1. {"kind":"throw","team":"dark","player":"jo","receiver":"tipped","type":"scoober","direction":null,"result":"incomplete","wall":false}\n'
        '2. {"kind":"throw","team":"white","player":"sam","receiver":"lee","type":null,"direction":"dump","result":"caught","wall":false}\n'
        'Checked because: new name "tipped"; name not in any event "max"',
        '{"correct":false,"events":[{"kind":"throw","team":"dark","player":"jo","receiver":"max","type":"scoober","direction":null,'
        '"result":"incomplete","wall":false},{"same":2}]}',
    ),
    (
        f'{_TEAMS}\nDisc before: white, held by lee\nEarlier: "flick to lee in the end zone"\nUtterance: "caught."\nParser\'s events: none\n'
        "Checked because: throw words but no event",
        '{"correct":true}',
    ),
]


def messages(request: Request | None) -> list[dict[str, str]]:
    """The chat messages for a request: the fixed system prompt and examples (which Ollama keeps cached), then the request."""
    result = [{"role": "system", "content": SYSTEM}]
    for question, answer in EXAMPLES:
        result += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    if request is not None:
        result.append({"role": "user", "content": describe(request)})
    return result


def describe(request: Request) -> str:
    """The request as the model reads it."""
    teams = ", ".join(f'"{names[0]}"' + (" (also " + ", ".join(names[1:]) + ")" if names[1:] else "") for names in request.teams)
    disc = (request.possession or "unknown") + (f", held by {request.holder}" if request.holder else "")
    lines = [f"Teams: {teams}", f"Disc before: {disc}"]
    if request.earlier:
        lines.append("Earlier: " + " / ".join(f'"{text}"' for text in request.earlier))
    lines.append(f'Utterance: "{request.text}"')
    lines.append("Parser's events:" if request.events else "Parser's events: none")
    for k, event in enumerate(request.events):
        unfinished = k == len(request.events) - 1 and request.open_after and getattr(event, "receiver", "") is None
        marks = [mark for mark, on in (("started before", k == 0 and request.open_before), ("unfinished", unfinished)) if on]
        lines.append(f"{k + 1}. {_compact(event_json(event))}" + (f" ({', '.join(marks)})" if marks else ""))
    lines.append("Checked because: " + "; ".join(request.reasons))
    return "\n".join(lines)


def event_json(event: yus.Event) -> dict[str, Any]:
    """An event in the model's format."""
    if isinstance(event, ultimate.Defense):
        return {"kind": "defense", "team": event.team, "player": event.player, "intercepted": event.intercepted}
    assert isinstance(event, ultimate.Throw)
    result = "score" if event.scored else "caught" if event.completed else "incomplete"
    return {
        "kind": "throw",
        "team": event.team,
        "player": event.player,
        "receiver": event.receiver,
        "type": event.type and event.type.value,
        "direction": event.direction and event.direction.value,
        "result": result,
        "wall": bool(getattr(event, "hit_wall", False)),
    }


def answer_schema(labels: list[str]) -> dict[str, Any]:
    """The JSON schema Ollama holds the answer to."""
    name = {"type": ["string", "null"]}
    event = {
        "type": "object",
        "properties": {
            "kind": {"enum": ["throw", "defense"]},
            "team": {"enum": labels},
            "player": name,
            "receiver": name,
            "type": {"enum": [t.value for t in ThrowType] + [None]},
            "direction": {"enum": [d.value for d in ThrowDirection] + [None]},
            "result": {"enum": list(RESULTS)},
            "wall": {"type": "boolean"},
            "intercepted": {"type": "boolean"},
        },
        "required": ["kind", "team", "player"],
    }
    same = {"type": "object", "properties": {"same": {"type": "integer"}}, "required": ["same"]}
    return {
        "type": "object",
        "properties": {"correct": {"type": "boolean"}, "events": {"type": "array", "items": {"anyOf": [same, event]}}},
        "required": ["correct"],
    }


def parse_answer(content: str, request: Request) -> list[yus.Event] | None:
    """The events an answer gives (None: the rule events are right). Raises InvalidAnswer."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise InvalidAnswer(f"not JSON: {content[:200]!r}") from error
    if not isinstance(data, dict) or not isinstance(data.get("correct"), bool):
        raise InvalidAnswer(f"no 'correct': {content[:200]!r}")
    if data["correct"]:
        return None
    raw = data.get("events")
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise InvalidAnswer(f"no 'events' list: {content[:200]!r}")
    labels = {normalize(name): names[0] for names in request.teams for name in names}
    spoken = _spoken(request)
    events: list[yus.Event] = []
    kept = 0  # parser events up to this number may no longer be referred to
    for k, item in enumerate(raw):
        if "same" in item:
            number = item["same"]
            if not isinstance(number, int) or not kept < number <= len(request.events):
                raise InvalidAnswer(f"bad reference {number!r}")
            kept = number
            events.append(request.events[number - 1])
        else:
            events.append(_event(item, _time(request, k, events), labels, spoken, request))
    if events == request.events:
        return None
    _check_edit(events, request)
    return events


def _check_edit(events: list[yus.Event], request: Request) -> None:
    """Raise InvalidAnswer unless the answer changes only what the reasons for asking allow. A correction allows anything. A name
    no event used, or throw words that made none, allows changing any event but not dropping one; only throw words that made
    none allow adding events. A new name allows changing the events that name it, and dropping one it threw ("flick wobbles to
    joe" made two throws). A restated throw allows merging the pair. Every other event must stay as it was, and no defense may
    appear without a defense word."""
    parser = request.events
    kinds = {reason.split('"')[0].strip() for reason in request.reasons}
    new = {normalize(name) for reason in request.reasons if reason.startswith(NEW_NAME) for name in reason.split('"')[1::2]}
    if CORRECTION in kinds:
        editable, droppable = set(range(len(parser))), set(range(len(parser)))
    else:
        editable = set(range(len(parser))) if kinds & {UNUSED, NO_EVENT} else set()
        editable |= {k for k, event in enumerate(parser) if {normalize(name) for name in _names(event)} & new}
        droppable = {k for k, event in enumerate(parser) if normalize(getattr(event, "player", None) or "") in new}
        if RESTATED in kinds:
            pairs = [k for k in range(len(parser) - 1) if _split(parser[k], parser[k + 1])]
            editable |= {j for k in pairs for j in (k, k + 1)}
            droppable |= {k + 1 for k in pairs}
    answered = [event_json(event) for event in events]
    for k, event in enumerate(parser):
        if k not in editable and event_json(event) not in answered:
            raise InvalidAnswer(f"changed event {k + 1}, which {'; '.join(request.reasons)} does not concern")
    if len(events) < len(parser) - len(droppable):
        raise InvalidAnswer(f"dropped events ({len(parser)} -> {len(events)}) for {'; '.join(request.reasons)}")
    if len(events) > len(parser) and not kinds & {CORRECTION, NO_EVENT}:
        raise InvalidAnswer(f"added events ({len(parser)} -> {len(events)}) for {'; '.join(request.reasons)}")
    defenses = sum(isinstance(event, ultimate.Defense) for event in events)
    if defenses > max(sum(isinstance(event, ultimate.Defense) for event in parser), request.defense_words):
        raise InvalidAnswer("a defense nobody said")


def _split(a: yus.Event, b: yus.Event) -> bool:
    """A throw without a receiver, then one without a thrower: maybe one throw said twice."""
    return isinstance(a, ultimate.Throw) and isinstance(b, ultimate.Throw) and a.receiver is None and a.completed and not a.scored and b.player is None


def _time(request: Request, k: int, made: list[yus.Event]) -> dt.datetime:
    """A time for a new event at position k of the answer: the parser's event k's, else later in the group; never before the
    events before it."""
    if k < len(request.events):
        when = request.events[k].when
    else:
        span = request.span or (request.events[0].when, request.events[-1].when)
        when = max(span[1], made[-1].when) if made else span[0]
    return max([when, *(event.when for event in made[-1:])])


def _event(item: dict[str, Any], when: dt.datetime, labels: dict[str, str], spoken: str, request: Request) -> yus.Event:
    team = labels.get(normalize(str(item.get("team", ""))))
    if team is None:
        raise InvalidAnswer(f"unknown team {item.get('team')!r}")
    player = _name(item.get("player"), spoken)
    if item.get("kind") == "defense":
        return ultimate.Defense(when=when, team=team, player=player, intercepted=bool(item.get("intercepted", False)))
    if item.get("kind") != "throw":
        raise InvalidAnswer(f"unknown kind {item.get('kind')!r}")
    result = item.get("result", "caught")
    if result not in RESULTS:
        raise InvalidAnswer(f"unknown result {result!r}")
    try:
        kind = ThrowType(item["type"]) if item.get("type") else None
        direction = ThrowDirection(item["direction"]) if item.get("direction") else None
    except ValueError as error:
        raise InvalidAnswer(str(error)) from error
    net = next((bool(getattr(e, "hit_net", False)) for e in request.events if isinstance(e, ultimate.Throw) and e.when == when), False)
    return indoor.Throw(
        when=when,
        team=team,
        player=player,
        type=kind,
        direction=direction,
        receiver=_name(item.get("receiver"), spoken),
        completed=result != "incomplete",
        scored=result == "score",
        hit_wall=bool(item.get("wall", False)),
        hit_net=net,
    )


def _name(value: Any, spoken: str) -> str | None:
    """A name as said (lower case), or None for an unknown player; InvalidAnswer for a name nobody said."""
    if value is None:
        return None
    name = " ".join(str(value).casefold().split())
    if normalize(name) in UNKNOWN:
        return None
    if f" {normalize(name)} " not in spoken:
        raise InvalidAnswer(f"{name!r} was not said")
    return name


def _spoken(request: Request) -> str:
    """Everything said that a name may come from, normalized and padded with spaces for whole-word lookups."""
    names = [name for event in request.events for name in _names(event)] + ([request.holder] if request.holder else [])
    return " " + " | ".join(normalize(text) for text in [*request.earlier, request.text, *names]) + " "


def _compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------------------------------------------------------ the extractor


@dataclasses.dataclass(eq=False)
class _Entry:
    """A group fed while some group's answer was still awaited (or one that is awaited itself)."""

    index: int
    group: yus.TranscriptGroup
    text: str
    base: EventExtractor | None = None  # the state before it, kept while its answer is awaited
    start: int = 0  # events[start:] are its own (its first may be the throw open before it)
    open_before: bool = False
    open_after: bool = False
    defense_words: int = 0
    possession: str | None = None
    holder: str | None = None
    rule: list[yus.Event] = dataclasses.field(default_factory=list)
    call: Call | None = None
    asked: list[yus.Event] | None = None  # the rule events the model was shown
    revision: list[yus.Event] | None = None
    deadline: float = 0.0
    resolved: bool = True
    advanced: dt.datetime | None = None  # the last advance() after it


class AssistedExtractor:
    """An EventExtractor whose uncertain groups also go to an LLM (see the module docstring). Same interface as EventExtractor.

    extractor = AssistedExtractor(EventExtractor(game.teams, timeout=6.0), LLMAssistant("qwen2.5-coder:14b"))
    for group in groups:
        extractor.feed(group)       # never waits for the model, unless wait=True
        extractor.poll()            # apply answers that came in; True if events changed
    extractor.finish()              # waits for answers still due, at most until their budgets run out

    `events[:final_count]` never change. Events of a group awaiting its answer, and everything after them, stay provisional until
    it comes or the budget runs out. With `wait=True`, `feed()` waits for each group's answer (as yus-events --llm does), so the
    result does not depend on timing beyond the budget. `calls` records every group sent; `answers` what was decided for each
    (the model's events, or None where the rule events stood). Pass a saved `answers` to replay those decisions without asking
    again (GameSession.load does); with `assistant=None`, no other group is sent.
    """

    def __init__(
        self,
        extractor: EventExtractor,
        assistant: LLMAssistant | None,
        *,
        wait: bool = False,
        answers: dict[int, list[yus.Event] | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.extractor = extractor
        self.assistant = assistant
        self.wait = wait
        self.clock = clock
        self.calls: list[Call] = []
        self.answers: dict[int, list[yus.Event] | None] = {}  # group number -> the model's events, or None: the rule events stood
        self._known = dict(answers or {})
        self.groups = 0  # groups fed
        self._texts: list[str] = []  # every group's text, for context
        self._seen: set[str] = set()
        self._log: list[_Entry] = []  # groups from the first one still awaiting its answer on
        self._queue: collections.deque[_Entry] = collections.deque()
        self._busy: tuple[_Entry, concurrent.futures.Future[list[yus.Event] | None], float] | None = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._finished = False

    # EventExtractor's interface ----------------------------------------------------------------------------------------------

    @property
    def teams(self) -> list[yus.Team]:
        return self.extractor.teams

    @property
    def labels(self) -> list[str]:
        return self.extractor.labels

    @property
    def timeout(self) -> float | None:
        return self.extractor.timeout

    @property
    def associations(self) -> list:
        return self.extractor.associations

    @property
    def possession(self) -> int | None:
        return self.extractor.possession

    @property
    def holder(self) -> str | None:
        return self.extractor.holder

    @property
    def events(self) -> list[yus.Event]:
        return self.extractor.events

    @property
    def final_count(self) -> int:
        waiting = next((entry.start for entry in self._log if not entry.resolved), None)
        return self.extractor.final_count if waiting is None else min(waiting, self.extractor.final_count)

    def team_of(self, name: str | None) -> int | None:
        return self.extractor.team_of(name)

    def feed(self, group: yus.TranscriptGroup) -> None:
        """Parse the next group with the rules and, if it looks uncertain, send it to the model (waiting for it if `wait`)."""
        self.poll()
        words = group.words
        if not words:
            return
        entry = _Entry(self.groups, group, " ".join(word.text.strip() for word in words))
        self.groups += 1
        self._texts.append(entry.text)
        base = self.extractor.copy()
        before = self._parse(self.extractor, entry)
        why: list[str] = []
        if entry.index in self._known:  # decided before (a saved session): no need to ask
            entry.revision = self.answers[entry.index] = self._known.pop(entry.index)
            entry.asked = entry.rule
            if entry.revision is not None:
                self.extractor.revise(entry.start, entry.revision)
        elif self.assistant is not None:
            why = reasons(self.extractor.last_items, before, entry.rule, self.extractor.holder, self.extractor.knows, self._seen)
        self._seen.update(normalize(name) for event in entry.rule for name in _names(event))
        if why and self.assistant is not None:
            entry.base, entry.resolved, entry.deadline = base, False, self.clock() + self.assistant.budget
            entry.call = Call(entry.index, why)
            self.calls.append(entry.call)
            self._queue.append(entry)
        if self._log or why:
            self._log.append(entry)
        self._pump()
        if self.wait and not entry.resolved:
            self._await(entry)

    def advance(self, now: dt.datetime) -> None:
        """As EventExtractor.advance; also applies answers that came in."""
        self.poll()
        self.extractor.advance(now)
        if self._log:
            self._log[-1].advanced = now

    def finish(self) -> None:
        """End of the game: wait for the answers still due (each at most until its budget runs out), then make everything final."""
        while any(not entry.resolved for entry in self._log):
            pending = next(entry for entry in self._log if not entry.resolved)
            self._await(pending)
        self.extractor.finish()
        self._finished = True
        self._log.clear()
        self.close()

    def poll(self) -> bool:
        """Apply an answer that came in, and give up on groups whose budget ran out. True if `events` or `final_count` changed."""
        state = (self.final_count, len(self.extractor.events))
        revised = False
        if self._busy is not None and self._busy[1].done():
            revised = self._take()
        now = self.clock()
        for entry in self._log:
            if not entry.resolved and now >= entry.deadline:
                self._resolve(entry, "timeout" if self._busy is not None and self._busy[0] is entry else "skipped")
        self._trim()
        self._pump()
        return revised or state != (self.final_count, len(self.extractor.events))

    def close(self) -> None:
        """Stop the worker thread (an answer still on its way is dropped)."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    # Internals ---------------------------------------------------------------------------------------------------------------

    def _parse(self, extractor: EventExtractor, entry: _Entry) -> list[yus.Event]:
        """Feed the entry's group to `extractor` with the rules, noting where its events start; returns the open events before it."""
        extractor.advance(entry.group.words[0].start)
        entry.start = extractor.open_from  # not final_count: a scoring group's events wait there, but they are not this group's
        before = extractor.events[entry.start :]
        entry.open_before = bool(before)
        entry.possession = extractor.labels[extractor.possession] if extractor.possession is not None else None
        entry.holder = extractor.holder if not before else getattr(before[0], "player", None)
        extractor.feed(entry.group)
        entry.rule = extractor.events[entry.start :]
        entry.open_after = extractor.open_from < len(extractor.events)
        entry.defense_words = sum(item.tag in (Tag.DEFENSE, Tag.INTERCEPT) for item in extractor.last_items)
        return before

    def _request(self, entry: _Entry) -> Request:
        assert self.assistant is not None
        words = entry.group.words
        return Request(
            text=entry.text,
            earlier=self._texts[max(entry.index - self.assistant.context, 0) : entry.index],
            teams=[[label, *[name for name in team.names if normalize(name) != normalize(label)]] for label, team in zip(self.labels, self.teams)],
            possession=entry.possession,
            holder=entry.holder,
            events=list(entry.rule),
            open_before=entry.open_before,
            open_after=entry.open_after,
            defense_words=entry.defense_words,
            reasons=entry.call.reasons if entry.call else [],
            span=(words[0].start, words[-1].start),
        )

    def _pump(self) -> None:
        """Send the next group waiting for the model, unless one is being answered."""
        if self._busy is not None or self._finished or self.assistant is None:
            return
        now = self.clock()
        while self._queue:
            entry = self._queue.popleft()
            if entry.resolved:
                continue
            if now >= entry.deadline:
                self._resolve(entry, "skipped")
                continue
            request = self._request(entry)
            entry.asked = list(entry.rule)
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="yus-llm")
            future = self._executor.submit(self.assistant.ask, request, entry.deadline - now)
            self._busy = (entry, future, now)
            return

    def _await(self, entry: _Entry) -> None:
        """Wait until `entry` is resolved: its answer came in or its budget ran out."""
        while not entry.resolved:
            busy = self._busy
            remaining = entry.deadline - self.clock()
            if busy is not None and remaining > 0:
                concurrent.futures.wait([busy[1]], timeout=remaining)
            elif remaining > 0 and busy is None and entry in self._queue:
                self._pump()
                continue
            elif remaining > 0:
                time.sleep(min(remaining, 0.05))
            self.poll()

    def _take(self) -> bool:
        """Apply the answer that just came in; True if it revised events."""
        assert self._busy is not None
        entry, future, sent = self._busy
        self._busy = None
        call = entry.call
        assert call is not None
        call.latency = self.clock() - sent
        try:
            answer = future.result()
        except InvalidAnswer as error:
            call.outcome, call.error = "invalid", str(error)
        except (OSError, ValueError) as error:
            call.outcome, call.error = ("timeout" if isinstance(error, TimeoutError) or "timed out" in str(error) else "error"), str(error)
        else:
            if entry.resolved:
                call.outcome = "late"
            elif entry.asked != entry.rule:
                call.outcome = "skipped"  # the group's rule events changed since it was sent: not expected with one request at a time
            elif answer is None:
                call.outcome = "confirmed"
            else:
                call.outcome = "revised"
                entry.revision = answer
                self._replay(entry)
                self._resolve(entry, "revised")
                return True
        self._resolve(entry, call.outcome)
        return False

    def _resolve(self, entry: _Entry, outcome: str) -> None:
        entry.resolved, entry.base = True, None
        self.answers[entry.index] = entry.revision
        call = entry.call
        if call is not None and call.outcome == "waiting":
            call.outcome = outcome
        if call is not None and self.assistant is not None:
            took = f" in {call.latency:.1f} s" if call.latency is not None else ""
            level = logging.WARNING if call.outcome == "error" else logging.INFO
            log.log(level, "LLM %s: group %d (%s) %s%s%s", self.assistant.model, call.group, "; ".join(call.reasons), call.outcome, took, f": {call.error}" if call.error else "")

    def _replay(self, entry: _Entry) -> None:
        """Parse the groups again from `entry` on (from the state kept before it), with its revision. Groups before it are all
        resolved, since groups are sent one at a time in order; later ones have not been answered yet."""
        assert entry.base is not None
        extractor = entry.base.copy()
        for item in self._log[self._log.index(entry) :]:
            if item is not entry and not item.resolved:
                item.base = extractor.copy()
            self._parse(extractor, item)
            if item.revision is not None and (item is entry or item.asked == item.rule):
                extractor.revise(item.start, item.revision)
            elif item.revision is not None:  # the rules now read the group differently: the answer no longer applies
                item.revision = self.answers[item.index] = None
            if item.advanced is not None:
                extractor.advance(item.advanced)
        self.extractor = extractor

    def _trim(self) -> None:
        """Forget the groups before the first one still awaiting its answer."""
        while self._log and self._log[0].resolved:
            self._log.pop(0)
