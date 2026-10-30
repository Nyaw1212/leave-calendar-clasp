from __future__ import annotations


def preview_queue_slots(entries, index, limit=3):
    """Return consecutive queue entries starting with the current position."""
    if not entries:
        return []
    start = max(0, min(index, len(entries) - 1))
    return [(position, entries[position]) for position in range(start, min(start + limit, len(entries)))]
