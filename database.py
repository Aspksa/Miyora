"""Compatibility import for existing integrations."""
from app.core.database import (connect, initialize, health, list_notes, create_note, delete_note,
                               restore_note, update_note, stats, backup)
