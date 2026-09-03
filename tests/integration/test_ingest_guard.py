"""The retry's red is for a night with NO tape (2026-09-02, the 22:23 schedule).

The two firings drift independently (learning 58), so the retry can arrive hours after the first
firing — or a hand dispatch — has already landed today's session. Then the vendor's newest tape
equals the store's date because the store HAS it, and a red there would be a false alarm on the
first night of the new slot. The tell is a run that landed rows for exactly that tape date inside
the night; the previous night's landing must not count, because that is the late-vendor case.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import ingest  # noqa: E402


def _run(cur, *, started, as_of, rows=44_401, dry_run=False, job="ingest-daily"):
    cur.execute(f"""insert into runs (job, status, started_at, finished_at, dry_run, rows_written,
                                      detail)
                    values (%s, 'green', now() - interval '{started}', now() - interval '{started}',
                            %s, %s, %s::jsonb) returning id""",
                (job, dry_run, rows, '{"tape": {"as_of": "%s", "rows": 11000}}' % as_of))
    return cur.fetchone()[0]


def test_a_tape_landed_this_night_is_recognised_and_last_nights_is_not(db):
    with db.cursor() as cur:
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "an empty night has no tape"
        old = _run(cur, started="20 hours", as_of="2026-09-01")
        assert ingest.tape_already_landed(cur, "2026-09-01") is None, (
            "the previous night's landing is the late-vendor case and must stay red")
        assert ingest.tape_already_landed(cur, "2026-09-02") is None
        this = _run(cur, started="5 hours", as_of="2026-09-02")
        assert ingest.tape_already_landed(cur, "2026-09-02") == this
        assert ingest.tape_already_landed(cur, "2026-09-01") is None, "the date must match exactly"
        db.commit()
        assert old != this


def test_rows_that_landed_nothing_do_not_count(db):
    with db.cursor() as cur:
        _run(cur, started="2 hours", as_of="2026-09-02", rows=0)
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "a green skip landed no tape"
        _run(cur, started="2 hours", as_of="2026-09-02", dry_run=True)
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "a dry run wrote nothing"
        _run(cur, started="2 hours", as_of="2026-09-02", job="ingest-universe")
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "another job is not this tape"
        db.commit()
