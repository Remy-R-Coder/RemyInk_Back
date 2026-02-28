# user_module/utils.py
from threading import Lock

class GuestIDCounter:
    _counter = 0
    _lock = Lock()

    @classmethod
    def get_next_guest_id(cls):
        with cls._lock:
            cls._counter += 1
            return cls._counter
