-- 055_the_shadow_attests.sql — 2026-08-16. §6.4's record.
--
-- "**6.4 Shadow — 10 sessions.** The pipeline runs live producing order sheets nobody trades. Each
--  night: live output vs the sim's decision on the same-vintage bars, **attested in writing**.
--  Pass = 10/10 matches, or every divergence named and ruled."
--
-- "Attested in writing" is the operative phrase and it is why this is a table rather than a log
-- line. A shadow whose evidence is a green workflow run proves that a job exited zero; §6.5 gates
-- the seed on this record, so the record has to say WHAT was compared, on WHICH bars, and where
-- the two answers differed.
--
-- One row per session per comparison. `matched` is the verdict; `detail` carries the names.

create table if not exists shadow_attestations (
  id bigint generated always as identity primary key,
  session_date date not null,
  compared text not null,                  -- rank | gate
  matched boolean not null,
  live jsonb,
  sim jsonb,
  detail jsonb,
  ruling text,                             -- §6.4: a divergence passes only once it is NAMED AND RULED
  ruled_at timestamptz,
  created_at timestamptz not null default now()
);
create unique index if not exists shadow_attestations_key
  on shadow_attestations(session_date, compared);
create index if not exists shadow_attestations_session_idx
  on shadow_attestations(session_date desc);

comment on table shadow_attestations is
  'S6.4: live output vs the sim''s decision on the same bars, attested in writing. S6.5 gates the '
  'seed on this record, so a divergence is not "resolved" by a later matching session - it stays '
  'until it carries a ruling.';

comment on column shadow_attestations.ruling is
  'S6.4 passes on "10/10 matches, OR every divergence named and ruled". A divergence with no '
  'ruling is an open question, not a tolerated difference.';

-- §6.4's pass condition, computed rather than asserted. Ten sessions, and either every comparison
-- matched or every divergence carries a ruling.
create or replace view v_shadow_progress as
select count(distinct session_date)                                        as sessions,
       count(*) filter (where not matched)                                 as divergences,
       count(*) filter (where not matched and ruling is null)              as unruled,
       min(session_date)                                                   as first_session,
       max(session_date)                                                   as last_session,
       (count(distinct session_date) >= 10
        and count(*) filter (where not matched and ruling is null) = 0)    as passes
  from shadow_attestations;

comment on view v_shadow_progress is
  'S6.4: "Pass = 10/10 matches, or every divergence named and ruled." S6.5 adds the other three '
  'conditions - pipeline green, gate ON, and Zak''s seed ruling in chat.';
