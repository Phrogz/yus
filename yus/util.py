import datetime
import pathlib
import pickle

from google.cloud import speech_v1 as speech  # type: ignore
from google.protobuf.duration_pb2 import Duration

import yus


def load_response(path: pathlib.Path) -> speech.LongRunningRecognizeResponse:
    return pickle.load(path.open("rb"))


def google_response_to_transcript(response: speech.LongRunningRecognizeResponse, transcript_start: datetime.datetime) -> yus.Transcript:
    """
    Convert a Google Cloud Speech-to-Text response to a YUS Transcript.

    Args:
        response (speech.LongRunningRecognizeResponse): The response object from Google Cloud Speech-to-Text API, v1.
        transcript_start (datetime.datetime): The exact start time of the recording the transcript is based on.

    Returns:
        yus.Transcript
    """

    def duration_to_delta(dur: Duration) -> datetime.timedelta:
        return datetime.timedelta(seconds=dur.seconds + dur.nanos / 1e9)

    transcript = yus.Transcript()
    for result in response.results:
        group = transcript.add_group()
        for alternative in result.alternatives:
            interp = group.add_interpretation(confidence=alternative.confidence)
            for w in alternative.words:
                interp.add_word(
                    w.word,
                    start=transcript_start + duration_to_delta(w.start_time),
                    duration=duration_to_delta(w.end_time) - duration_to_delta(w.start_time),
                    confidence=float(w.confidence),
                )
    return transcript
