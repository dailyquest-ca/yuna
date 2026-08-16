-- 052_the_receipt_closes_the_loop.sql — 2026-08-16. §4.1's `reconcile`.
--
-- §4.3: "Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the
-- receipt." Two columns and one view are all that is missing to make that sentence executable.
--
-- `transactions.broker_ref` is the idempotence key. §4's jobs re-run on failure and the chain
-- re-fires on the retry ingest, so a receipt read twice must fold into the book once. The old fill
-- loop keyed on `tickets.arm_key`, which was the ARMING key of an engine that no longer exists —
-- borrowing it would make the new machine's audit trail depend on the old machine's vocabulary.
--
-- Nothing here places an order (§0.2). A receipt is a record of something Zak already did.

alter table transactions
  add column if not exists broker_ref text,
  add column if not exists source     text;      -- which manifest the row was read from

create unique index if not exists transactions_broker_ref_key
  on transactions(broker_ref) where broker_ref is not null;

comment on column transactions.broker_ref is
  'The broker receipt id. Unique, so a manifest read twice folds into the book once. Partial: the '
  'legacy rows carry no ref and are not constrained.';

-- ---------- v_reconciliation_age -------------------------------------------------------------
-- §4.4 gauges "book-vs-broker reconciliation age". The age is the gauge, not the count: a book
-- that agreed with the broker last Tuesday is a book nobody has checked since, and the number of
-- rows that matched says nothing about that.
--
-- `last_receipt` is the newest broker fill folded in; `last_attested` is the newest run of the job
-- that compared positions. They differ on purpose — a quiet week has no fills and still needs the
-- comparison to have happened.
create or replace view v_reconciliation_age as
select
  (select max(trade_date) from transactions where broker_ref is not null)      as last_receipt,
  (select max(finished_at) from runs
    where job = 'reconcile' and status in ('green','amber'))                   as last_attested,
  (select count(*) from tickets
    where session_date is not null and state = 'approved')                     as awaiting_receipt,
  (select min(session_date) from tickets
    where session_date is not null and state = 'approved')                     as oldest_awaiting;

comment on view v_reconciliation_age is
  'S4.4 book-vs-broker reconciliation age. last_attested is when the comparison last RAN - a quiet '
  'week has no fills and still needs the comparison to have happened.';
