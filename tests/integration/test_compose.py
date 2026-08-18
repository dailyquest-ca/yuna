"""compose — §4.2's fourth verb, first half, and the two ways a chained run can go wrong.

`compose` writes the words down mechanically and keyless. Off a cron it ran once a night, so
"already composed for this date" was a sound guard. Off the `needs:` chain it runs after every
ingest, and that guard froze the brief: the first version of the day became the final one, however
many fresh scores landed behind it.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import compose                                                            # noqa: E402


class Beat:
    def __init__(self):
        self.detail, self.rows = {}, 0

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


def composed(conn, kind="stopsheet"):
    with conn.cursor() as cur:
        # `at, id` and not `at` alone. `briefs.at` defaults to `now()`, which is TRANSACTION time in
        # Postgres, so two briefs written in one transaction carry a byte-identical timestamp and
        # "order by at" is a coin toss decided by the heap. This helper reads "the newest row",
        # which under a tie it could not deliver — and the same ambiguity was live in `notify`,
        # where the loser of the toss is the message Zak reads.
        cur.execute("""select body, detail->>'sha', detail->>'recomposed', at from briefs
                       where kind=%s and detail->>'composed'='true'
                       order by at, id""", (kind,))
        return cur.fetchall()


def test_the_same_words_twice_write_one_row(db):
    """A second chain the same night with nothing new to say must not duplicate the sheet."""
    hb = Beat()
    with db.cursor() as cur:
        assert compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh", "✓ stops all placed")
        assert not compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh",
                                   "✓ stops all placed")
    db.commit()
    assert len(composed(db)) == 1
    assert "unchanged" in str(hb.detail["skipped"])


def test_an_unchanged_sheet_too_old_to_deliver_is_written_again(db):
    """§5.2: the stop sheet's line IS the pipeline's nightly receipt, and its body is often
    byte-identical night to night — "✓ stops all placed correctly". Dedupe on content alone left
    the 2026-08-05 receipt eight hours old and outside R2's three-hour window, so `notify` went red
    on words that existed and could not be delivered. The receipt is owed to the run, not the prose.
    """
    hb = Beat()
    with db.cursor() as cur:
        compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh", "✓ stops all placed")
        cur.execute("""update briefs set at = now() - interval '9 hours'
                        where kind='stopsheet'""")
        assert compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh", "✓ stops all placed")
    db.commit()
    rows = composed(db)
    assert len(rows) == 2 and rows[0][1] == rows[1][1], "same words, new receipt"


def test_new_numbers_replace_the_frozen_brief(db):
    """The live failure: a stop sheet composed at 14:18 described a book without that day's fills,
    a fresh score recomputed everything at 22:52, and the desk kept the 14:18 words."""
    hb = Beat()
    with db.cursor() as cur:
        compose.publish(cur, hb, "stopsheet", dt.date.today(), "stale", "✓ stops all placed")
        assert compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh",
                               "NUE.US · stop 249.23 / limit 241.75")
    db.commit()
    rows = composed(db)
    assert len(rows) == 2, "briefs is an append ledger — the correction is a new row"
    assert rows[-1][0].startswith("NUE.US"), "and the newest row is the current one"
    assert rows[-1][2] == "true", "marked as a recomposition, so the ledger says what happened"


def test_a_dry_run_composes_nothing_and_says_what_it_would_have(db, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    hb = Beat()
    with db.cursor() as cur:
        assert not compose.publish(cur, hb, "stopsheet", dt.date.today(), "fresh", "words")
    db.commit()
    assert composed(db) == []
    assert hb.detail["dry_run_would_write"] == ["stopsheet"]


def test_a_red_check_ships_the_banner_and_nothing_else(db):
    """§4.2: a red check ships nothing but the stale banner and the protective lines."""
    assert compose.stale({"status": "red", "blocks_dispatch": ["hurdle_reproduces_floor"]})
    assert compose.stale({}) == "no check row — the night never proved itself"
    assert compose.stale({"status": "amber", "blocks_dispatch": []}) is None
