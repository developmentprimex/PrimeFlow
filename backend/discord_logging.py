"""Keep Discord worker stderr writes off the asyncio event loop."""
import logging
from contextlib import contextmanager
from logging.handlers import QueueHandler, QueueListener
from queue import SimpleQueue


@contextmanager
def worker_logging():
    records = SimpleQueue()
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
    queued = QueueHandler(records)
    queued.setFormatter(logging.Formatter('%(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[queued])
    listener = QueueListener(records, stream)
    listener.start()
    try:
        yield
    finally:
        logging.getLogger().removeHandler(queued)
        listener.stop()
