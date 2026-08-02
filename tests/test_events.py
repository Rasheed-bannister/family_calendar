"""Tests for the SSE event broker.

The broker sits between sync workers and connected displays, so the
properties that matter are the ones that protect each side from the other: a
stalled display must not grow memory or stall a sync, and a disconnected
display must not leak a queue.
"""

import json
import threading
from queue import Queue
from unittest.mock import patch

import pytest

from src import events
from src.events import EventBroker


@pytest.fixture
def brk():
    return EventBroker()


def _drain(queue: Queue) -> list:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


class TestPublishSubscribe:
    def test_subscriber_receives_published_event(self, brk):
        q = brk.subscribe()
        brk.publish(events.CHORES_CHANGED)
        [event] = _drain(q)
        assert event["type"] == events.CHORES_CHANGED
        assert "timestamp" in event

    def test_extra_data_is_carried(self, brk):
        q = brk.subscribe()
        brk.publish(events.CALENDAR_CHANGED, month=8, year=2026)
        [event] = _drain(q)
        assert event["month"] == 8
        assert event["year"] == 2026

    def test_every_subscriber_gets_the_event(self, brk):
        queues = [brk.subscribe() for _ in range(5)]
        assert brk.publish(events.CHORES_CHANGED) == 5
        for q in queues:
            assert len(_drain(q)) == 1

    def test_publish_with_no_subscribers_is_harmless(self, brk):
        assert brk.publish(events.CHORES_CHANGED) == 0

    def test_unsubscribed_client_stops_receiving(self, brk):
        q = brk.subscribe()
        brk.unsubscribe(q)
        brk.publish(events.CHORES_CHANGED)
        assert _drain(q) == []

    def test_unsubscribe_twice_is_safe(self, brk):
        q = brk.subscribe()
        brk.unsubscribe(q)
        brk.unsubscribe(q)  # must not raise

    def test_subscriber_count_tracks_lifecycle(self, brk):
        assert brk.subscriber_count == 0
        q = brk.subscribe()
        assert brk.subscriber_count == 1
        brk.unsubscribe(q)
        assert brk.subscriber_count == 0


class TestBackpressure:
    def test_queue_is_bounded_for_a_stalled_client(self, brk):
        """A display that stops reading must not grow memory without limit."""
        q = brk.subscribe()
        for i in range(events.MAX_QUEUE_SIZE * 3):
            brk.publish(events.CHORES_CHANGED, seq=i)
        assert q.qsize() <= events.MAX_QUEUE_SIZE

    def test_newest_event_survives_when_full(self, brk):
        """The newest event reflects current state; it is the one to keep."""
        q = brk.subscribe()
        for i in range(events.MAX_QUEUE_SIZE + 10):
            brk.publish(events.CHORES_CHANGED, seq=i)
        drained = _drain(q)
        assert drained[-1]["seq"] == events.MAX_QUEUE_SIZE + 9

    def test_a_stalled_client_does_not_block_others(self, brk):
        stalled = brk.subscribe()
        healthy = brk.subscribe()
        for i in range(events.MAX_QUEUE_SIZE + 5):
            brk.publish(events.CHORES_CHANGED, seq=i)
            _drain(healthy)  # healthy client keeps up

        # The publish calls returned normally throughout; the stalled client
        # is merely capped.
        assert stalled.qsize() <= events.MAX_QUEUE_SIZE

    def test_publish_never_raises(self, brk):
        brk.subscribe()
        for _ in range(events.MAX_QUEUE_SIZE * 2):
            brk.publish(events.CHORES_CHANGED)  # must not raise


class TestStream:
    def test_stream_yields_sse_frames(self, brk):
        gen = brk.stream(heartbeat_seconds=5)
        # Give the generator a chance to subscribe before publishing.
        threading.Timer(0.05, lambda: brk.publish(events.CHORES_CHANGED)).start()
        frame = next(gen)
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        payload = json.loads(frame[len("data: ") :].strip())
        assert payload["type"] == events.CHORES_CHANGED
        gen.close()

    def test_stream_emits_heartbeat_when_idle(self, brk):
        gen = brk.stream(heartbeat_seconds=0.05)
        frame = next(gen)
        payload = json.loads(frame[len("data: ") :].strip())
        assert payload["type"] == events.HEARTBEAT
        gen.close()

    def test_closing_the_stream_unsubscribes(self, brk):
        """A disconnected display must not leak its queue."""
        gen = brk.stream(heartbeat_seconds=0.05)
        next(gen)  # force the generator to start and subscribe
        assert brk.subscriber_count == 1
        gen.close()
        assert brk.subscriber_count == 0

    def test_only_filter_suppresses_other_event_types(self, brk):
        gen = brk.stream(only=(events.MOTION_DETECTED,), heartbeat_seconds=0.05)
        next(gen)  # subscribe via the first heartbeat

        brk.publish(events.CHORES_CHANGED)
        brk.publish(events.MOTION_DETECTED)

        payload = json.loads(next(gen)[len("data: ") :].strip())
        assert payload["type"] == events.MOTION_DETECTED, "filtered type leaked"
        gen.close()


class TestThreadSafety:
    def test_concurrent_publish_and_subscribe(self, brk):
        """Subscribing while publishing must not corrupt the subscriber list."""
        stop = threading.Event()

        def publisher():
            while not stop.is_set():
                brk.publish(events.CHORES_CHANGED)

        def subscriber():
            for _ in range(50):
                q = brk.subscribe()
                brk.unsubscribe(q)

        pub = threading.Thread(target=publisher)
        pub.start()
        subs = [threading.Thread(target=subscriber) for _ in range(4)]
        for t in subs:
            t.start()
        for t in subs:
            t.join()
        stop.set()
        pub.join(timeout=5)

        assert brk.subscriber_count == 0


class TestEndpoints:
    """Endpoint smoke tests.

    HEARTBEAT_SECONDS is patched down: the test client consumes the stream,
    so at the production 25s value each of these would block for a full
    heartbeat before the first frame arrives.
    """

    @pytest.fixture(autouse=True)
    def fast_heartbeat(self):
        with patch.object(events, "HEARTBEAT_SECONDS", 0.05):
            yield

    def test_events_endpoint_is_an_sse_stream(self):
        from src.main import create_app

        client = create_app().test_client()
        resp = client.get("/events", buffered=False)
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        assert resp.headers["X-Accel-Buffering"] == "no"
        resp.close()

    def test_pir_events_endpoint_still_works(self):
        """The legacy motion-only stream must keep its contract."""
        from src.main import create_app

        client = create_app().test_client()
        resp = client.get("/pir/events", buffered=False)
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        resp.close()

    def test_both_endpoints_share_one_broker(self):
        """Two client lists would mean two threads held per browser tab."""
        from src.events import broker as global_broker
        from src.pir_sensor import routes as pir_routes

        assert pir_routes.broker is global_broker


class TestWorkersPublish:
    def test_calendar_sync_publishes_only_when_data_changed(self):
        from unittest.mock import patch

        from src.google_integration import routes as gr
        from src.sync_state import registry

        registry.clear()
        with patch.object(gr, "broker") as mock_broker:
            with patch.object(
                gr.calendar_api, "fetch_and_process_google_events", return_value=[]
            ):
                gr.fetch_google_events_background(8, 2026)
        mock_broker.publish.assert_not_called()

    def test_chores_sync_publishes_only_when_data_changed(self):
        from unittest.mock import patch

        from src.google_integration import routes as gr
        from src.sync_state import registry

        registry.clear()
        with patch.object(gr, "broker") as mock_broker:
            with patch.object(gr.tasks_api, "get_chores", return_value=[]):
                gr.fetch_google_tasks_background()
        mock_broker.publish.assert_not_called()
