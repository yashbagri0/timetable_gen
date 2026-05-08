"""
Room data + lookups (project/config/rooms.json).

Replaces the old hardcoded ``Config.ROOMS`` dict and
``Config.DEPARTMENT_LABS`` mapping. Centralizes a single rule that the
constraint builder enforces by *construction* (not as a soft penalty):

    Commerce subjects ↔ commerce rooms.
    Non-commerce subjects ↔ non-commerce rooms.

The check is bidirectional: a subject's allowed-room list never crosses
the commerce boundary, so it's impossible for the solver to assign a
B.Com class to a non-commerce room (or vice versa).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

# Locate config/rooms.json relative to this file.
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "rooms.json"

# Department-tag value reserved for commerce-only rooms in rooms.json.
COMMERCE_DEPT = "commerce"


class RoomManager:
    """Loads rooms.json and answers every "which rooms are available?" query."""

    def __init__(self, rooms_path: Optional[Path] = None):
        path = Path(rooms_path) if rooms_path else _DEFAULT_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"rooms.json not found at {path}. "
                f"Create it (see project/config/rooms.json template)."
            )
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        rooms = data.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            raise ValueError(f"rooms.json at {path} must contain a non-empty 'rooms' list.")

        self._rooms: Dict[str, dict] = {}
        for r in rooms:
            rid = r.get("id")
            if not rid:
                raise ValueError(f"Room entry missing 'id': {r!r}")
            if rid in self._rooms:
                raise ValueError(f"Duplicate room id '{rid}' in rooms.json")
            # Normalize: department always stored as either lowercase string or None.
            dept = r.get("department")
            r["department"] = dept.strip().lower() if isinstance(dept, str) else None
            self._rooms[rid] = r

    # ------------------------------------------------------------
    # Core lookups
    # ------------------------------------------------------------
    def get_all_rooms(self) -> Dict[str, dict]:
        """Returns a *copy* of the room map. id → info dict."""
        return dict(self._rooms)

    def get_room(self, room_id: str) -> dict:
        return self._rooms[room_id]

    def has_room(self, room_id: str) -> bool:
        return room_id in self._rooms

    def get_rooms_by_type(self, room_type: str) -> List[str]:
        return [rid for rid, r in self._rooms.items() if r.get("type") == room_type]

    def get_rooms_for_department(self, department: Optional[str]) -> List[str]:
        """All rooms allowed for this department.

        Rules (mirror _subject_matches_room):
          • Commerce departments see commerce-tagged rooms only.
          • Non-commerce dept X sees: rooms tagged X + rooms with no tag (general).
          • Commerce-tagged rooms are never visible to non-commerce departments.
        """
        if self.is_commerce_dept_name(department):
            return [rid for rid, r in self._rooms.items()
                    if r.get("department") == COMMERCE_DEPT]
        norm = (department or "").strip().lower() if department else None
        return [
            rid for rid, r in self._rooms.items()
            if r.get("department") != COMMERCE_DEPT
            and (r.get("department") in (None, "") or r.get("department") == norm)
        ]

    def get_selected_rooms(self, selected_ids: Optional[List[str]] = None) -> List[str]:
        """If ``selected_ids`` is provided, returns those that exist.
        Otherwise returns every room id."""
        if selected_ids is None:
            return list(self._rooms.keys())
        return [rid for rid in selected_ids if rid in self._rooms]

    # ------------------------------------------------------------
    # Commerce exclusivity
    # ------------------------------------------------------------
    @staticmethod
    def is_commerce_dept_name(department: Optional[str]) -> bool:
        if not department:
            return False
        return department.strip().lower() == COMMERCE_DEPT

    @staticmethod
    def is_commerce_subject(subj: Dict) -> bool:
        """A subject is commerce-only if its Course contains 'B.Com'/'BCom'
        or its Department equals 'Commerce' (case-insensitive)."""
        course = (subj.get("Course") or "").strip().lower()
        dept   = (subj.get("Department") or "").strip().lower()
        if "b.com" in course or "bcom" in course:
            return True
        if dept == COMMERCE_DEPT:
            return True
        return False

    def is_commerce_room(self, room_id: str) -> bool:
        info = self._rooms.get(room_id, {})
        return info.get("department") == COMMERCE_DEPT

    # ------------------------------------------------------------
    # Subject-aware filters
    # ------------------------------------------------------------
    def _subject_matches_room(self, subj: Dict, room_info: Dict) -> bool:
        """Single source of truth for subject↔room access.

        Rules (in order):
          1. Commerce subjects ↔ commerce-tagged rooms ONLY (bidirectional hard
             exclusion; never crosses).
          2. Non-commerce subject + room with no department tag → allowed
             (general classroom / lab).
          3. Non-commerce subject + room tagged with a specific department →
             allowed only when subject's Department matches that tag (so
             Physics labs are Physics-only, CS labs are CS-only, etc.).
        """
        room_dept = room_info.get("department")

        # Rule 1 — commerce side, bidirectional
        if self.is_commerce_subject(subj):
            return room_dept == COMMERCE_DEPT
        if room_dept == COMMERCE_DEPT:
            return False  # non-commerce subject can never use a commerce room

        # Rule 2 — general (untagged) room: any non-commerce subject may use it
        if room_dept in (None, ""):
            return True

        # Rule 3 — department-specific tag must match the subject's department
        subj_dept = (subj.get("Department") or "").strip().lower()
        return room_dept == subj_dept

    def get_classrooms_for_subject(self, subj: Dict) -> List[str]:
        return [rid for rid, r in self._rooms.items()
                if r.get("type") == "classroom" and self._subject_matches_room(subj, r)]

    def get_labs_for_subject(self, subj: Dict) -> List[str]:
        return [rid for rid, r in self._rooms.items()
                if r.get("type") == "lab" and self._subject_matches_room(subj, r)]

    def get_all_rooms_for_subject(self, subj: Dict) -> List[str]:
        return [rid for rid, r in self._rooms.items()
                if self._subject_matches_room(subj, r)]


# ---------------------------------------------------------------------------
# Module-level singleton + thin wrappers — most consumers only need these.
# ---------------------------------------------------------------------------
_default_manager: Optional[RoomManager] = None


def _default() -> RoomManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = RoomManager()
    return _default_manager


def reload_rooms(path: Optional[Path] = None) -> RoomManager:
    """Force a fresh load (handy in tests)."""
    global _default_manager
    _default_manager = RoomManager(path)
    return _default_manager


def get_all_rooms()                      : return _default().get_all_rooms()
def get_room(room_id)                    : return _default().get_room(room_id)
def has_room(room_id)                    : return _default().has_room(room_id)
def get_rooms_by_type(room_type)         : return _default().get_rooms_by_type(room_type)
def get_rooms_for_department(department) : return _default().get_rooms_for_department(department)
def get_selected_rooms(selected_ids=None): return _default().get_selected_rooms(selected_ids)
def is_commerce_subject(subj)            : return RoomManager.is_commerce_subject(subj)
def is_commerce_room(room_id)            : return _default().is_commerce_room(room_id)
def get_classrooms_for_subject(subj)     : return _default().get_classrooms_for_subject(subj)
def get_labs_for_subject(subj)           : return _default().get_labs_for_subject(subj)
def get_all_rooms_for_subject(subj)      : return _default().get_all_rooms_for_subject(subj)
