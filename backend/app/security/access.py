from __future__ import annotations


class Missing(Exception):
    pass


class NotOwner(Exception):
    pass


def classify(meeting: dict | None, user_id) -> dict:
    if meeting is None:
        raise Missing()
    owner = meeting.get("created_by")
    if user_id is None or owner is None or str(owner) != str(user_id):
        raise NotOwner()
    return meeting
