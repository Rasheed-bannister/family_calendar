"""Server-sent event broker.

Lets the server tell connected displays that something changed, instead of the
browser asking every few seconds and reloading the whole page when the answer
is yes.

Why it matters here
-------------------
The frontend polled ``/calendar/check-updates`` on a 10s/5min cycle and
responded to a change with ``window.location.reload()``. On a wall-mounted
display that reload resets the background slideshow, scroll position and any
open UI -- a visible flash every time a chore is ticked off. Pushing a small
notification instead lets the client re-fetch just the fragment that changed.

Design notes
------------
* No imports from the rest of the application, so it cannot join an import
  cycle -- same rule as src/sync_state.py and src/scheduler.py.
* One broker serves every stream. The PIR endpoint and the general event
  endpoint subscribe to the same instance rather than each keeping their own
  client list: Flask's threaded server holds a thread per open SSE
  connection, so a second stream per browser tab would double that for no
  benefit.
* Per-subscriber bounded queues. A display that stops reading (asleep, or a
  wedged tab) must not grow a queue without limit; the oldest event is
  dropped instead. Events are notifications, not a log -- the client re-fetches
  current state when it sees one, so a dropped duplicate costs nothing.
* Subscribers are removed in a ``finally`` when their generator closes, so a
  disconnected client does not leak a queue.
"""

import logging
import threading
import time
from queue import Empty, Full, Queue
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# Bounded so a stalled client cannot consume memory without limit.
MAX_QUEUE_SIZE = 50

# How long a stream waits before emitting a keepalive. Without periodic
# traffic, proxies and browsers quietly drop an idle connection, and the
# server never notices the client is gone.
HEARTBEAT_SECONDS = 25.0

# Event type names. Kept here so the publisher and the endpoint agree.
MOTION_DETECTED = "motion_detected"
CALENDAR_CHANGED = "calendar_changed"
CHORES_CHANGED = "chores_changed"
PHOTOS_CHANGED = "photos_changed"
HEARTBEAT = "heartbeat"


class EventBroker:
    """Fan-out of events to any number of connected SSE clients."""

    def __init__(self):
        self._subscribers: list[Queue] = []
        self._lock = threading.Lock()

    # -- subscription --------------------------------------------------

    def subscribe(self) -> Queue:
        """Register a subscriber and return its queue."""
        q: Queue = Queue(maxsize=MAX_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        """Remove a subscriber. Safe to call more than once."""
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # -- publishing ----------------------------------------------------

    def publish(self, event_type: str, **data: Any) -> int:
        """Broadcast an event. Returns the number of subscribers reached.

        Never raises and never blocks: publishing happens on sync worker
        threads, and a slow display must not be able to stall a sync.
        """
        event = {"type": event_type, "timestamp": time.time(), **data}

        with self._lock:
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(event)
            except Full:
                # Drop the oldest rather than the newest: the newest reflects
                # the most recent state, which is what the client will act on.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (Empty, Full):
                    pass
        return len(subscribers)

    # -- streaming -----------------------------------------------------

    def stream(
        self,
        queue: Optional[Queue] = None,
        only: Optional[tuple] = None,
        heartbeat_seconds: Optional[float] = None,
    ) -> Iterator[str]:
        """Yield SSE-formatted frames for one client until it disconnects.

        ``only`` restricts the stream to the given event types, which lets the
        legacy PIR endpoint keep its narrower contract while sharing the
        broker.
        """
        import json

        # Read the module constant at call time rather than binding it as a
        # default argument, so it stays patchable (tests would otherwise wait
        # a full heartbeat for every stream they open).
        if heartbeat_seconds is None:
            heartbeat_seconds = HEARTBEAT_SECONDS

        own_queue = queue is None
        q = self.subscribe() if own_queue else queue
        try:
            while True:
                try:
                    event = q.get(timeout=heartbeat_seconds)
                    if only is not None and event.get("type") not in only:
                        continue
                except Empty:
                    event = {"type": HEARTBEAT, "timestamp": time.time()}
                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            # Client disconnected; fall through to cleanup.
            raise
        finally:
            if own_queue:
                self.unsubscribe(q)


# Application-wide singleton.
broker = EventBroker()


def sse_headers() -> dict:
    """Headers every SSE response needs.

    ``X-Accel-Buffering`` disables proxy buffering, without which a reverse
    proxy can hold events until its buffer fills and make pushes look broken.
    """
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
