"""Tests for LLM-assisted event extraction (yus.processing.event_extraction.llm). The model is never called: tests replace the HTTP
call (`LLMAssistant.post`) or the whole question (`LLMAssistant.ask`)."""

import datetime as dt
import json
import pathlib
import random
import threading
import time
import urllib.error

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_extraction import AssistedExtractor, EventExtractor, LLMAssistant, cli, extract_events, llm
from yus.processing.event_extraction.llm import InvalidAnswer, Request, parse_answer
from yus.session import GameSession
from yus.sports import ultimate
from yus.sports.ultimate import ThrowType, indoor

DATA = pathlib.Path(__file__).parent / "data"
NOW = dt.datetime(2025, 1, 1, 12)
FIRST = "picked up by kaia for white"


@pytest.fixture(scope="module")
def teams() -> list[yus.Team]:
    return build_game().teams


def group(text: str, start: dt.datetime, step: float = 0.4) -> yus.TranscriptGroup:
    result = yus.TranscriptGroup()
    interpretation = result.add_interpretation()
    for k, word in enumerate(text.split()):
        interpretation.add_word(word, start=start + dt.timedelta(seconds=step * k), duration=dt.timedelta(seconds=step))
    return result


def groups(*texts: str) -> list[yus.TranscriptGroup]:
    return [group(text, NOW + dt.timedelta(seconds=5 * k)) for k, text in enumerate(texts)]


def brief(event: yus.Event) -> tuple:
    if isinstance(event, ultimate.Throw):
        flags = "".join(c for c, on in (("C", event.completed), ("S", event.scored)) if on)
        return ("Throw", event.team, event.player, event.receiver, flags)
    if isinstance(event, ultimate.Substitution):
        return ("Sub", event.team, event.player, event.sub_type.value)
    assert isinstance(event, ultimate.Defense)
    return ("Defense", event.team, event.player, event.intercepted)


def replying(*answers: str, seen: list | None = None):
    """A `post` that answers with each content in turn (the last one again once they run out), noting the requests."""
    queue = list(answers)

    def post(url: str, body: dict, timeout: float) -> dict:
        if seen is not None:
            seen.append(body)
        return {"message": {"content": queue.pop(0) if len(queue) > 1 else queue[0]}}

    return post


def run(teams: list[yus.Team], texts: list[str], post, **options) -> AssistedExtractor:
    extractor = AssistedExtractor(EventExtractor(teams), LLMAssistant("test", post=post, **options), wait=True)
    for item in groups(*texts):
        extractor.feed(item)
    extractor.finish()
    return extractor


CONFIRM = '{"correct":true}'


# Which groups are sent ---------------------------------------------------------------------------------------------------


def test_only_uncertain_groups_are_sent(teams: list[yus.Team]):
    texts = [
        FIRST,
        "backhand to joe",  # plain
        "flick to tristan in the end zone nope not in the end zone",  # a correction
        "backhand to red shorts",  # a new name
        "flick wobbles to joe",  # a new name ("wobbles")
        "flick dump to tristan",  # plain
        "backhand dump dump to joe",  # a throw restated
        "kaia's throw is dropped by tristan",  # names no event used
        "huck to red shorts for a score",  # red shorts is no longer new
        "dropped",  # throw words, no event
    ]
    sent: list = []
    extractor = run(teams, texts, replying(CONFIRM, seen=sent))
    assert [(call.group, call.reasons[0].split('"')[0].strip()) for call in extractor.calls] == [
        (2, llm.CORRECTION),
        (3, llm.NEW_NAME),
        (4, llm.NEW_NAME),
        (6, llm.RESTATED),
        (7, llm.UNUSED),
        (9, llm.NO_EVENT),
    ]
    assert all(call.outcome == "confirmed" for call in extractor.calls) and len(sent) == 6
    assert extractor.events == extract_events(yus.Transcript(groups=groups(*texts)), teams).events  # confirmed: the rules' events
    body = sent[0]
    assert body["model"] == "test" and body["stream"] is False and body["options"]["temperature"] == 0 and body["format"]["required"] == ["correct"]
    question = body["messages"][-1]["content"]
    assert 'Utterance: "flick to tristan in the end zone nope not in the end zone"' in question and "Checked because: a correction" in question
    assert '"result":"caught"' in question and "held by kaia" in question  # the rules took the score back; who threw the throw still open


def test_nothing_is_sent_without_reason_and_rosters_count_as_known(teams: list[yus.Team]):
    sent: list = []
    extractor = run(teams, [FIRST, "flick to tristan", "backhand to Kaia Mann", "huck to joe for a score"], replying(CONFIRM, seen=sent))
    assert extractor.calls == [] and sent == []


# Answers -----------------------------------------------------------------------------------------------------------------


def test_a_retracted_score_gives_the_disc_back(teams: list[yus.Team]):
    texts = [FIRST, "flick to tristan in the end zone, wait, he stepped out.", "backhand to george"]
    rules = [brief(e) for e in extract_events(yus.Transcript(groups=groups(*texts)), teams).events]
    assert rules == [("Throw", "white", "kaia", "tristan", "CS"), ("Throw", "dark", None, "george", "C")]  # the rules keep this score
    answer = '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"tristan","type":"flick","result":"caught"}]}'
    extractor = run(teams, texts, replying(answer))
    assert [call.outcome for call in extractor.calls] == ["revised"]
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "C"), ("Throw", "white", "tristan", "george", "C")]
    assert extractor.events[0].type == ThrowType.FLICK and extractor.events[0].when == NOW + dt.timedelta(seconds=5)  # type: ignore[attr-defined]
    assert extractor.answers == {1: extractor.events[:1]}


def test_a_restated_throw_becomes_one(teams: list[yus.Team]):
    answer = '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"joe","type":"backhand","direction":"dump","result":"caught"}]}'
    extractor = run(teams, [FIRST, "backhand dump dump to joe", "flick to tristan"], replying(answer))
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "joe", "C"), ("Throw", "white", "joe", "tristan", "C")]


def test_a_word_taken_for_a_name(teams: list[yus.Team]):
    answer = '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"joe","type":"flick","result":"caught"}]}'
    extractor = run(teams, [FIRST, "flick wobbles to joe", "backhand to tristan"], replying(answer))
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "joe", "C"), ("Throw", "white", "joe", "tristan", "C")]


def test_same_references_keep_events_and_times(teams: list[yus.Team]):
    events = extract_events(yus.Transcript(groups=groups(FIRST, "flick to joe backhand to tristan")), teams).events
    request = Request("flick to joe sorry backhand to tristan", [], [["white"], ["dark"]], "white", "kaia", events, False, True, ["a correction"])
    answer = '{"correct":false,"events":[{"same":1},{"kind":"throw","team":"white","player":"joe","receiver":"tristan","result":"incomplete"}]}'
    revised = parse_answer(answer, request)
    assert revised is not None and revised[0] is events[0] and revised[1].when == events[1].when and not revised[1].completed  # type: ignore[attr-defined]
    assert parse_answer('{"correct":false,"events":[{"same":1},{"same":2}]}', request) is None  # the same events: nothing to revise
    for bad in ('{"correct":false,"events":[{"same":2},{"same":1}]}', '{"correct":false,"events":[{"same":3}]}'):
        with pytest.raises(InvalidAnswer):
            parse_answer(bad, request)


@pytest.mark.parametrize(
    "content, why",
    [
        ("not json", "not JSON"),
        ('{"events":[]}', "no 'correct'"),
        ('{"correct":false}', "no 'events'"),
        ('{"correct":false,"events":[{"kind":"throw","team":"purple","player":"kaia","receiver":"tristan"}]}', "unknown team"),
        ('{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"Tristan Weber"}]}', "was not said"),
        ('{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"tristan","type":"lob"}]}', "lob"),
        ('{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"tristan","result":"maybe"}]}', "unknown result"),
    ],
)
def test_answers_that_do_not_check_out_keep_the_rule_events(teams: list[yus.Team], content: str, why: str):
    texts = [FIRST, "flick to tristan in the end zone nope not in the end zone", "backhand to joe"]
    extractor = run(teams, texts, replying(content))
    assert [call.outcome for call in extractor.calls] == ["invalid"] and why in (extractor.calls[0].error or "")
    assert extractor.events == extract_events(yus.Transcript(groups=groups(*texts)), teams).events
    assert extractor.answers == {1: None}


@pytest.mark.parametrize(
    "texts, content",
    [
        # a new name only allows changing the events that name it: not kaia's throw to joe
        ([FIRST, "flick to joe backhand to red shorts"], '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"tristan"},{"same":2}]}'),
        # ... nor dropping an event it does not throw
        ([FIRST, "flick to joe backhand to red shorts"], '{"correct":false,"events":[{"same":1}]}'),
        # ... nor adding one
        ([FIRST, "backhand to red shorts"], '{"correct":false,"events":[{"same":1},{"kind":"throw","team":"white","player":"red shorts","receiver":null}]}'),
        # ... and a name no event used does not make a throw of its own ("Glasses picks it up the way.")
        ([FIRST, "flick to joe. glasses picks it up the way"], '{"correct":false,"events":[{"same":1},{"kind":"throw","team":"white","player":"glasses","receiver":null}]}'),
        # no defense without a defense word
        ([FIRST, "kaia's throw is dropped by tristan"], '{"correct":false,"events":[{"kind":"defense","team":"dark","player":"tristan"}]}'),
    ],
)
def test_answers_may_only_change_what_was_asked_about(teams: list[yus.Team], texts: list[str], content: str):
    extractor = run(teams, texts, replying(content))
    assert [call.outcome for call in extractor.calls] == ["invalid"]
    assert extractor.events == extract_events(yus.Transcript(groups=groups(*texts)), teams).events


WOBBLES = '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"joe","type":"flick","result":"caught"}]}'


@pytest.mark.parametrize(
    "said, expected",
    [
        ("flick wobbles to joe. tristan off, emily on", [("Throw", "white", "kaia", "joe", "C"), ("Sub", "white", "tristan", "sub_off"), ("Sub", "white", "emily", "sub_on")]),
        ("tristan off. flick wobbles to joe", [("Sub", "white", "tristan", "sub_off"), ("Throw", "white", "kaia", "joe", "C")]),
    ],
)
def test_substitutions_are_not_shown_and_keep_their_place(teams: list[yus.Team], said: str, expected: list[tuple]):
    sent: list = []
    extractor = run(teams, [FIRST, said, "backhand to george"], replying(WOBBLES, seen=sent))
    assert [call.outcome for call in extractor.calls] == ["revised"]
    assert [brief(e) for e in extractor.events] == [*expected, ("Throw", "white", "joe", "george", "C")]
    question = sent[0]["messages"][-1]["content"]
    assert "2. {" in question and "3. {" not in question and '"kind":"throw"' in question  # the two throws, no substitutions
    replayed = AssistedExtractor(EventExtractor(teams), None, answers=extractor.answers)  # as GameSession.load does
    for item in groups(FIRST, said, "backhand to george"):
        replayed.feed(item)
    replayed.finish()
    assert replayed.events == extractor.events


def test_a_nope_that_takes_back_a_substitution_keeps_the_group_s_own_events(teams: list[yus.Team]):
    sent: list = []
    extractor = run(teams, [FIRST, "dylan off.", "nope. flick wobbles to joe", "backhand to george"], replying(WOBBLES, seen=sent))
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "joe", "C"), ("Throw", "white", "joe", "george", "C")]
    assert '1. {"kind":"throw","team":"white","player":"kaia","receiver":"wobbles"' in sent[0]["messages"][-1]["content"]


def test_substitutions_alone_send_nothing(teams: list[yus.Team]):
    sent: list = []
    extractor = run(teams, [FIRST, "sarayan on", "kaia on. sorry, tristan.", "flick to joe"], replying(CONFIRM, seen=sent))
    assert extractor.calls == [] and sent == []
    assert [brief(e)[2:] for e in extractor.events] == [("sarayan", "sub_on"), ("tristan", "sub_on"), ("kaia", "joe", "C")]


def test_errors_keep_the_rule_events(teams: list[yus.Team]):
    def refused(url: str, body: dict, timeout: float) -> dict:
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    texts = [FIRST, "flick to tristan in the end zone nope not in the end zone", "backhand to joe"]
    extractor = run(teams, texts, refused)
    assert [call.outcome for call in extractor.calls] == ["error"] and "refused" in (extractor.calls[0].error or "")
    assert extractor.events == extract_events(yus.Transcript(groups=groups(*texts)), teams).events


def test_a_slow_answer_is_not_waited_for_past_the_budget(teams: list[yus.Team]):
    def slow(url: str, body: dict, timeout: float) -> dict:
        assert timeout <= 0.3
        time.sleep(0.6)
        return {"message": {"content": '{"correct":false,"events":[]}'}}

    texts = [FIRST, "flick to tristan in the end zone nope not in the end zone", "backhand to joe"]
    started = time.monotonic()
    extractor = run(teams, texts, slow, budget=0.3)
    assert time.monotonic() - started < 1.0
    assert extractor.calls[0].outcome == "timeout"
    assert extractor.events == extract_events(yus.Transcript(groups=groups(*texts)), teams).events


# Live: answers arrive later ------------------------------------------------------------------------------------------------


class Gated(LLMAssistant):
    """Answers as `decide` says, once the test opens the gate for that question."""

    def __init__(self, decide, **options):
        super().__init__("test", **options)
        self.decide = decide
        self.gates: list[threading.Event] = []
        self.asked: list[Request] = []

    def ask(self, request: Request, timeout: float) -> list[yus.Event] | None:
        gate = threading.Event()
        self.gates.append(gate)
        self.asked.append(request)
        if not gate.wait(timeout):
            raise TimeoutError("timed out")
        return self.decide(request)


def drop_new_names(request: Request) -> list[yus.Event] | None:
    """A deterministic 'model': every name said for the first time is no name (None), and a retracted score is a catch."""
    new = {name for reason in request.reasons if reason.startswith(llm.NEW_NAME) for name in reason.split('"')[1::2]}
    events = []
    for event in request.events:
        if isinstance(event, ultimate.Throw):
            update = {field: None for field in ("player", "receiver") if getattr(event, field) in new}
            if llm.CORRECTION in request.reasons and event.scored:
                update["scored"] = False
            event = event.model_copy(update=update)
        events.append(event)
    return events if events != request.events else None


def open_gates(assistant: Gated, extractor: AssistedExtractor, final: list[yus.Event]) -> list[yus.Event]:
    """Answer every question, polling until none is left; check that final events never changed."""
    for _ in range(2000):
        for gate in list(assistant.gates):
            gate.set()
        extractor.poll()
        assert extractor.events[: len(final)] == final
        final = extractor.events[: extractor.final_count]
        if extractor._busy is None and not extractor._queue:
            return final
        time.sleep(0.002)
    raise AssertionError("questions left unanswered")


def test_live_answers_revise_events_later_and_final_events_never_change(teams: list[yus.Team]):
    texts = [FIRST, "flick to tristan in the end zone, wait, he stepped out.", "backhand to george", "flick to red shorts", "dump to kaia", "huck to joe"]
    assistant = Gated(drop_new_names, budget=60)
    extractor = AssistedExtractor(EventExtractor(teams), assistant)
    final: list[yus.Event] = []
    items = groups(*texts)
    for item in items[:3]:
        extractor.feed(item)
    assert len(assistant.asked) == 1 and extractor.final_count == 0  # the correction's events wait for the answer
    assert brief(extractor.events[1]) == ("Throw", "dark", None, "george", "C")  # meanwhile the rules' reading shows
    final = open_gates(assistant, extractor, final)
    assert brief(extractor.events[1]) == ("Throw", "white", "tristan", "george", "C")  # replayed after the revision
    for item in items[3:]:
        extractor.feed(item)
        assert extractor.events[: len(final)] == final
        final = extractor.events[: extractor.final_count]
    final = open_gates(assistant, extractor, final)
    extractor.finish()
    assert extractor.events[: len(final)] == final
    batch = AssistedExtractor(EventExtractor(teams), Gated(drop_new_names, budget=60), wait=True)
    batch.assistant.ask = lambda request, timeout: drop_new_names(request)  # type: ignore[method-assign, union-attr]
    for item in items:
        batch.feed(item)
    batch.finish()
    assert extractor.events == batch.events
    assert [call.outcome for call in extractor.calls] == ["revised", "revised"]


@pytest.mark.parametrize("seed", range(6))
def test_live_matches_waiting_for_each_answer_on_the_bundled_transcripts(teams: list[yus.Team], seed: int):
    """Answers released at random moments give the same events as waiting for each, and final events never change; also with
    substitutions, which revisions keep."""
    rng = random.Random(seed)
    name = ["gruindoor_20250114T2030-transcript.json", "gruindoor_20250114T2030-whisper-turbo.json", "subbing_20250128T2050-whisper-turbo.json"][seed % 3]
    transcript = yus.Transcript.model_validate_json((DATA / name).read_text())
    teams = teams if name.startswith("gruindoor") else []
    items = transcript.groups[:120]
    batch = AssistedExtractor(EventExtractor(teams, timeout=6.0), LLMAssistant("x"), wait=True)
    batch.assistant.ask = lambda request, timeout: drop_new_names(request)  # type: ignore[method-assign, union-attr]
    for item in items:
        batch.feed(item)
    batch.finish()
    assistant = Gated(drop_new_names, budget=60)
    extractor = AssistedExtractor(EventExtractor(teams, timeout=6.0), assistant)
    final: list[yus.Event] = []
    for item in items:
        extractor.feed(item)
        if rng.random() < 0.4:
            final = open_gates(assistant, extractor, final)
        assert extractor.events[: len(final)] == final and extractor.final_count >= len(final)
        final = extractor.events[: extractor.final_count]
    final = open_gates(assistant, extractor, final)
    extractor.finish()
    assert extractor.events[: len(final)] == final
    assert extractor.events == batch.events and extractor.answers == batch.answers
    assert any(answer is not None for answer in batch.answers.values())


def test_a_budget_that_runs_out_live_keeps_the_rule_events(teams: list[yus.Team]):
    now = [0.0]
    assistant = Gated(drop_new_names, budget=5)
    extractor = AssistedExtractor(EventExtractor(teams), assistant, clock=lambda: now[0])
    for item in groups(FIRST, "flick to tristan in the end zone nope not in the end zone", "backhand to joe"):
        extractor.feed(item)
    assert extractor.final_count == 0
    now[0] = 5.0
    assert extractor.poll()  # the budget ran out: the rule events become final as the rules see them
    assert extractor.final_count == 1 and extractor.calls[0].outcome == "timeout"
    final = extractor.events[: extractor.final_count]
    assistant.gates[0].set()
    for _ in range(100):
        extractor.poll()
        if extractor._busy is None:
            break
        time.sleep(0.005)
    assert extractor.calls[0].outcome in ("late", "timeout") and extractor.events[: len(final)] == final


# Session, command line, server ------------------------------------------------------------------------------------------


def test_session_saves_answers_and_load_replays_them(teams: list[yus.Team], tmp_path: pathlib.Path):
    game = yus.Game(sport="ultimate/indoor", when=NOW, teams=teams)
    answer = '{"correct":false,"events":[{"kind":"throw","team":"white","player":"kaia","receiver":"tristan","type":"flick","result":"caught"}]}'
    sent: list = []
    session = GameSession(game, directory=tmp_path, llm=LLMAssistant("test", post=replying(answer, seen=sent)))
    session.add_commentator("Gavin")
    session.add_groups("Gavin", groups(FIRST, "flick to tristan in the end zone nope not in the end zone", "backhand to joe"))
    for _ in range(200):  # the answer comes from a worker thread; snapshot() applies it
        snap = session.snapshot()
        if snap.commentators[0].final_count == 1:
            break
        time.sleep(0.005)
    assert [brief(e) for e in snap.raw["Gavin"].events] == [("Throw", "white", "kaia", "tristan", "C"), ("Throw", "white", "tristan", "joe", "C")]
    assert snap.score == {"Dump & Drizzle": 0, "Category 5": 0}
    session.finish()
    session.save()
    saved = json.loads((tmp_path / "session.json").read_text())
    assert list(saved["commentators"][0]["llm_answers"]) == ["1"]
    loaded = GameSession.load(tmp_path)  # no model: the saved answer is replayed
    assert loaded.snapshot().official.events == session.snapshot().official.events and len(sent) == 1


def test_cli_llm(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    sent: list = []
    monkeypatch.setattr(llm, "post_json", replying(CONFIRM, seen=sent))
    transcript = tmp_path / "game.transcript.json"
    transcript.write_text((DATA / "gruindoor_20250114T2030-transcript.json").read_text())
    teams = ["--team", str(DATA / "team_dump_and_drizzle.json"), "--team", str(DATA / "team_category_5.json")]
    assert cli.main([str(transcript), *teams, "--llm", "qwen", "--llm-url", "http://127.0.0.1:9", "--llm-budget", "4"]) == 0
    out = capsys.readouterr().out
    assert "200 events" in out and "LLM qwen: sent 23 of 246 groups (23 confirmed" in out
    assert len(sent) == 23 and sent[0]["model"] == "qwen"


def test_server_flags_make_an_assistant(monkeypatch: pytest.MonkeyPatch):
    from yus.web import server

    warmed = threading.Event()
    monkeypatch.setattr(LLMAssistant, "warm", lambda self, timeout=120.0: warmed.set())
    args = server.build_arg_parser().parse_args(["--llm", "qwen2.5-coder:14b", "--llm-budget", "7"])
    assistant = server.llm_assistant(args)
    assert assistant is not None and (assistant.model, assistant.url, assistant.budget) == ("qwen2.5-coder:14b", llm.DEFAULT_URL, 7.0)
    assert warmed.wait(5)
    assert server.llm_assistant(server.build_arg_parser().parse_args([])) is None


# The extractor's hooks -----------------------------------------------------------------------------------------------------


def test_extractor_copies_are_independent(teams: list[yus.Team]):
    extractor = EventExtractor(teams)
    for item in groups("on dark we have yellow fringe", FIRST, "flick to tristan"):
        extractor.feed(item)
    copy = extractor.copy()
    for item in groups("dropped", "yellow fringe picks it up"):
        copy.feed(item)
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "C")] and extractor.final_count == 0
    assert [brief(e) for e in copy.events] == [("Throw", "white", "kaia", "tristan", "")] and copy.possession == 1
    assert extractor.knows("yellow fringe") and extractor.knows("Kaia Mann") and not extractor.knows("red shorts")


def test_revise_follows_the_new_last_event(teams: list[yus.Team]):
    extractor = EventExtractor(teams)
    for item in groups(FIRST, "flick to tristan for a score"):
        extractor.feed(item)
    assert extractor.possession == 1
    throw = extractor.events[0]
    extractor.revise(0, [throw.model_copy(update={"scored": False})])
    assert extractor.possession == 0 and extractor.holder == "tristan" and extractor.final_count == 1
    for item in groups("x", "backhand to joe")[1:]:
        extractor.feed(item)
    extractor.finish()
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "C"), ("Throw", "white", "tristan", "joe", "C")]
    assert isinstance(extractor.events[1], indoor.Throw)
