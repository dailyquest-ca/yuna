"""notify — §4.2's fourth verb, second half: deliver what compose wrote.

The channel is a config row (`push_channel`, §4.8), because delivery is a decision, not code:

  cowork   — the ruled default (2026-08-05): the scheduled Routines inside the Yuna chat/cowork
             project ARE the doorbell. They fire on their own crons, read the composed row in one
             select, and put it in front of Zak with a push. This job's duty is then the §4.7
             contract from the pipeline's side: prove the composed words exist and are fresh, and
             go RED when they don't — a Routine that fires onto a missing brief would deliver
             silence, and a missing message is itself the alarm.
  webhook  — POST the composed brief to PUSH_WEBHOOK_URL (a repository secret), for any
             phone-native service that accepts one. Kept so the channel can change with a config
             row and a secret, never a rewrite.

Writes nothing but its own runs row — delivery is not allowed to edit the words it delivers.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, config, Heartbeat

# §4.1's two composed kinds for v1.0: the nightly brief and the Saturday letter. The old engine's
# `stopsheet`, `preopen` and `deepdive` are retired with it — v1.0 has no stops to sheet, and §5.1
# renders one brief per session rather than a pre-open and a post-close.
EXPECTED = {"nightly": ["nightly"], "saturday": ["saturday"]}


def fresh_composed(cur, kinds):
    """The composed brief for the CURRENT session, whatever hour it was written.

    Anchored on `session_date`, not on wall clock, and the change is a bug fix rather than a
    preference. The old window was "written in the last 3 hours", which conflicts with `compose`
    refusing to write a second brief for one session: the first chain run of a session writes the
    brief, and every run after the third hour finds it too old and reports the desk silent. On a
    weekend that is permanent — the newest bar is Friday's and no ingest lands a new session until
    Tuesday, so Saturday, Sunday and Monday all report a missing brief that was composed correctly
    and is sitting right there.

    `briefs.session_date` is already this repo's stated freshness anchor: "the market session an
    output serves, derived from the newest bar, not from `now()::date` in UTC". Delivery uses the
    same anchor as everything else, and a brief goes stale when a NEW SESSION appears — which is
    exactly when it should.
    """
    cur.execute("select max(session_date) from engine_sessions where mode = 'live'")
    row = cur.fetchone()
    session = row[0] if row else None
    if session is None:
        return {}
    cur.execute("""select kind, session_date, at, summary, body from briefs
                   where kind = any(%s) and detail->>'composed' = 'true'
                     and (detail->>'engine') = 'v1'
                     and session_date = %s
                   order by at desc""", (kinds, session))
    rows = {}
    for kind, session_date, at, summary, body in cur.fetchall():
        rows.setdefault(kind, dict(kind=kind, session_date=str(session_date),
                                   at=str(at), summary=summary, body=body))
    return rows


def main():
    # `or`, not a default argument — see compose.main(): a dead upstream job in the chain hands
    # this down as an empty string, and silence is the one outcome §4.7 has no reader for.
    slot = os.environ.get("NOTIFY_SLOT") or "nightly"
    kinds = EXPECTED.get(slot)
    if not kinds:
        raise SystemExit(f"unknown NOTIFY_SLOT {slot!r}")
    with connect() as conn:
        with Heartbeat(conn, "notify",
                       scheduled_utc=os.environ.get("SCHEDULED_UTC")) as hb:
            with conn.cursor() as cur:
                channel = config(cur, "push_channel", "cowork")
                if isinstance(channel, str):
                    channel = channel.strip('"')
                have = fresh_composed(cur, kinds)
                missing = [k for k in kinds if k not in have]
                hb.detail.update(slot=slot, channel=channel,
                                 delivered=sorted(have), missing=missing)
                if missing:
                    # §4.7: the doorbell about to ring on an empty doorstep is a red, tonight,
                    # while there is still time to notice — not tomorrow when Zak does.
                    hb.red(f"composed brief(s) missing for slot {slot}: {', '.join(missing)} — "
                           f"the {channel} delivery would carry silence")
                if channel == "webhook":
                    url = os.environ.get("PUSH_WEBHOOK_URL")
                    if not url:
                        hb.amber("push_channel=webhook but PUSH_WEBHOOK_URL is not set")
                    else:
                        for k, row in have.items():
                            req = urllib.request.Request(url, data=json.dumps(
                                dict(title=f"Yuna · {k}", body=row["body"])).encode(),
                                headers={"content-type": "application/json"})
                            with urllib.request.urlopen(req, timeout=30) as r:
                                hb.detail.setdefault("posted", []).append(
                                    dict(kind=k, status=r.status))
                            hb.calls[0] += 1
                elif channel != "cowork":
                    hb.amber(f"push_channel {channel!r} has no delivery code — "
                             f"cowork Routines remain the doorbell")
            print(f"notify: slot={slot} · channel={channel} · "
                  f"ready: {', '.join(sorted(have)) or 'none'}"
                  + (f" · MISSING: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
