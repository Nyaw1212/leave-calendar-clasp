"""Confirmed card checklist, separated by balance period."""
import sqlite3

from .settings import app_data_dir


def _connect():
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'print_tracker.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS card_status (scope TEXT NOT NULL, employee_key TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (scope, employee_key))')
    return db


def load_statuses(scope):
    if not scope:
        return {}
    with _connect() as db:
        return dict(db.execute('SELECT employee_key, status FROM card_status WHERE scope = ?', (scope,)))


def save_status(scope, key, status):
    if not scope:
        return
    with _connect() as db:
        db.execute('INSERT OR REPLACE INTO card_status(scope, employee_key, status) VALUES (?, ?, ?)', (scope, str(key), status))
