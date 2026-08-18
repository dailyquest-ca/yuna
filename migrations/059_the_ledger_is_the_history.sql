-- 059_the_ledger_is_the_history.sql — 2026-08-18. Zak's model, made law in the schema.
--
-- Zak, 2026-08-18:
--
--   "There are a list of transactions... And those will always come in with a transaction ledger
--    csv from Wealthsimple or another bank... Those are law... You keep them in the transaction
--    ledger and they should all match. That's our actual history. I will upload those to the chat
--    so the chat should be able to write them... And know how...
--
--    And then additionally sometimes those transactions are lagged... By days... So I will just
--    tell the chat other sales so it can process the books correctly... Those are true to me... But
--    they might change or be tweaked by the transactions later. Maybe the pennies are different....
--    But the engine should run assuming both.
--
--    As for tagging as pre-seed or momentum etc... I'm not so certain why we would do either.
--    That's just the book."
--
-- That is a cleaner design than the one the code had, and it replaces a tangle. Four things follow
-- from it, and this migration is those four things.
--
-- ---- 1. every row says where its authority comes from -------------------------------------------
--
--   `broker`  a row from the bank's own export. **Law.** Never contradicted, only superseded by a
--             later export of the same trade.
--   `stated`  Zak's word in chat, before the export catches up. **True, and provisional** — the
--             engine runs on it, and the broker row corrects it when it lands.
--
-- Both move the book, because a book that ignores what Zak knows is wrong for however many days
-- the export lags — that is the ghost-book failure, and it proposed a sell he had already made.
--
-- The correction is supersession, not deletion (§0.6: run records are never deleted). When a broker
-- row lands for a trade a stated row already described, the stated row is stamped `superseded_by`
-- and stops counting. The history then shows both what Zak believed on the day and what the bank
-- confirmed afterwards — which is the honest record of a lagged ledger, and is exactly the
-- difference the pennies live in.
--
-- The distinction is not new; it was being kept by hand. Every one of today's five book rows
-- carries a note saying so — *"avg_cost 155.5 is Zak's cash-delta estimate; exact fills pending
-- next WS export — reconcile trues it."* This makes that a column instead of a sentence.
--
-- ---- 2. the chat can write the ledger ----------------------------------------------------------
--
-- It could not. `transactions` was locked three ways: the INSERT grant revoked, RLS on with no
-- policy, and a jobs-only trigger. All three came from migration 033, on the authority of the
-- 2026-08-04 plan's §4.3 write list — **and v1.0 carries no such list.** Its §4.3 says only "Yuna
-- writes rows; Zak's execution is the event; reconcile closes the loop with the receipt." So the
-- lock outlived the law that set it, and Zak's instruction above is the law that replaces it.
--
-- (The current chat connector happens to log in as `postgres`, which walks through all three. That
-- is not a design — it is the reason the failure looked intermittent, and why a session could write
-- the seven opening rows on 08-03 while `yuna_session` could not have written any of them.)
--
-- ---- 3. the book follows the ledger, by construction --------------------------------------------
--
-- "They should all match" is not a thing to hope for or to check after the fact. `yuna_book_from_
-- ledger` recomputes one position from the rows that count, a trigger calls it on every write, and
-- `reconcile.apply_to_book` calls the same function. One definition, three callers, nothing to
-- drift. A fill that reaches the ledger cannot fail to reach the book, which is the entire class of
-- defect Zak reported.
--
-- ---- 4. the label decides nothing --------------------------------------------------------------
--
-- §2.1 makes the account the allocation — "there are no percentage targets" — so `book.sleeve` has
-- nothing left to decide in v1.0. It is NOT NULL and the retired jobs still read it, so it stays;
-- positions the ledger opens are labelled `book` and no code in the live path branches on it. The
-- existing labels are left alone: `preseed` on AXTI and MU is now inert, and rewriting history to
-- tidy a column nobody reads would be a data change with no purpose (§0.6).

-- ---- the vocabulary ----------------------------------------------------------------------------
--
-- Three verbs, and the third one is load-bearing. `confirm` is how a position that predates the
-- ledger enters it: seven rows written by hand on 2026-08-03 record the §6.1 book as it stood, with
-- its cost basis, so that the 08-17 liquidation had something to net against. It is
-- position-ESTABLISHING — arithmetically a buy — and the first draft of the view below counted it
-- as a sell, which valued the whole pre-Phase-0 book at exactly minus itself.
--
-- The constraint is what stops a fourth verb arriving unnoticed. It is VALIDATED: all 25 live rows
-- conform, and a vocabulary that admits anything is not a vocabulary.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'transactions_side_vocabulary') then
    alter table transactions add constraint transactions_side_vocabulary
      check (side in ('buy', 'sell', 'confirm'));
  end if;
end $$;

comment on column transactions.side is
  'buy | sell | confirm. `confirm` establishes a position that predates the ledger, carrying its '
  'cost basis — arithmetically a buy. Adding a fourth verb means editing every sum in this file.';

alter table transactions
  add column if not exists grade text not null default 'broker',
  add column if not exists superseded_by bigint references transactions(id),
  add column if not exists external_ref text;

comment on column transactions.grade is
  'broker = from the bank''s export, law. stated = Zak''s word before the export lands, true and '
  'provisional. Both move the book; a broker row supersedes the stated row for the same trade.';
comment on column transactions.superseded_by is
  'The broker row that replaced this stated one. Superseded rows stay (S0.6) and stop counting.';
comment on column transactions.external_ref is
  'The bank''s own identifier for the row, when the export carries one. Distinct from broker_ref, '
  'which is this system''s idempotence key for a manifest fill.';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'transactions_grade_vocabulary') then
    alter table transactions add constraint transactions_grade_vocabulary
      check (grade in ('broker', 'stated'));
  end if;
end $$;

create index if not exists transactions_live_idx
  on transactions(account, ticker, trade_date)
  where superseded_by is null;

-- ---- the book, as the ledger says it -----------------------------------------------------------
--
-- The position every live row implies, so "the ledger and the book should match" is a query rather
-- than a hope. `book` stays the table jobs write — it carries `entry_fill`, `opened_at` and the
-- rest — and this is what it is CHECKED against.
--
-- The `else 'NaN'` is deliberate and is not reachable while the constraint above holds. If it ever
-- becomes reachable — the constraint dropped, a restore from an older dump — the quantity comes out
-- visibly broken instead of quietly wrong, and NaN sorts above the HAVING threshold in Postgres so
-- the row appears rather than vanishing. A silently dropped verb is the failure this guards.
create or replace view v_ledger_positions as
select account, ticker,
       sum(case when side in ('buy', 'confirm') then qty
                when side = 'sell'             then -qty
                else 'NaN'::double precision end)                          as qty,
       sum(case when side in ('buy', 'confirm') then qty * price else 0 end)
         / nullif(sum(case when side in ('buy', 'confirm') then qty else 0 end), 0)
                                                                           as avg_buy_price,
       min(trade_date) filter (where side in ('buy', 'confirm'))           as first_buy,
       max(trade_date)                                                     as last_activity,
       count(*) filter (where grade = 'stated')                            as stated_rows
  from transactions
 where superseded_by is null
 group by account, ticker
having abs(sum(case when side in ('buy', 'confirm') then qty
                    when side = 'sell'             then -qty
                    else 'NaN'::double precision end)) > 1e-9;

comment on view v_ledger_positions is
  'The position the live ledger implies, per account and ticker. "They should all match" is this '
  'against `book`; S4.4''s reconciliation gauge is what says so out loud.';

-- Where the two disagree. A row here is one of two different things and they are not equally bad:
--
--   ledger_qty and book_qty both present and different  — a real break. Something wrote one side.
--   ledger_qty null, book_qty present                   — a position that PREDATES the ledger.
--
-- The second is the honest state of SPMO today: 810 shares in the TFSA and 107 in the RRSP, bought
-- with the §6.1 liquidation proceeds, with no rows behind them because the Wealthsimple export has
-- not landed yet. Nothing is wrong; the history is incomplete, and it completes itself when the
-- export arrives. `ledger.py check` reports that as amber and the first case as red.
create or replace view v_ledger_vs_book as
select coalesce(l.account, b.account) as account,
       coalesce(l.ticker, b.ticker)   as ticker,
       l.qty                          as ledger_qty,
       b.qty                          as book_qty,
       coalesce(l.qty, 0) - coalesce(b.qty, 0) as difference,
       l.stated_rows,
       l.qty is null                  as predates_the_ledger
  from v_ledger_positions l
  full outer join (select account, ticker, sum(qty) as qty from book
                    where status = 'open' group by account, ticker) b
    on b.account = l.account and b.ticker = l.ticker
 where abs(coalesce(l.qty, 0) - coalesce(b.qty, 0)) > 1e-6;

comment on view v_ledger_vs_book is
  'Every disagreement between the ledger and the book. predates_the_ledger separates the two cases: '
  'false is a real break, true is a holding older than its history (amber, and self-healing when '
  'the export lands).';

-- ---- the book follows the ledger ---------------------------------------------------------------
--
-- One position, recomputed from the rows that count. SET, not nudged: the book is not poked
-- incrementally and then trusted, it is made equal to the sum, so a superseded stated row, a
-- corrected penny and a late export all land the same way. The answer is right by construction
-- rather than by every previous write having been right.
--
-- SECURITY DEFINER because the caller is often a chat session rather than a job, and `guard_book`
-- admits only the jobs. Inside a definer function `current_user` is the owner, so the guard sees a
-- job and the session never needs a grant on `book` — the ledger stays the only surface it writes.
create or replace function yuna_book_from_ledger(p_account text, p_ticker text)
returns double precision
language plpgsql security definer set search_path = public as $$
declare
  q double precision; c double precision; opened date; ccy text; bid bigint; rows_seen int;
begin
  select count(*),
         sum(case when side in ('buy','confirm') then qty
                  when side = 'sell'            then -qty end),
         sum(case when side in ('buy','confirm') then qty * price else 0 end)
           / nullif(sum(case when side in ('buy','confirm') then qty else 0 end), 0),
         min(trade_date) filter (where side in ('buy','confirm')),
         min(currency)
    into rows_seen, q, c, opened, ccy
    from transactions
   where account = p_account and ticker = p_ticker and superseded_by is null;

  -- No history at all: nothing to say about this position, and saying "zero" would delete a real
  -- holding because one table cannot explain it. Left exactly alone; `v_ledger_vs_book` names it.
  if rows_seen = 0 then
    return null;
  end if;

  -- A position the ledger drives below zero. This is not a rounding question — it means the rows
  -- for this name are incomplete, almost always a sell recorded against a holding whose purchase
  -- predates the ledger. Refusing is the correct outcome: the fix is to record the opening
  -- position with a `confirm` row, and a book quietly holding minus 810 shares is not a fix.
  if q < -1e-6 then
    raise exception 'ledger drives % % to % shares — the history for this name is incomplete',
                    p_account, p_ticker, q
      using hint = 'record the opening position as a `confirm` row before the sells that follow it';
  end if;

  select id into bid from book
   where account = p_account and ticker = p_ticker and status = 'open' limit 1;

  if bid is null then
    if q <= 1e-9 then
      return 0;                       -- opened and closed inside the ledger; nothing to carry
    end if;
    -- `book.ticker` references `universe`, so an unknown symbol fails here as a foreign key
    -- violation naming a constraint. The person reading that message is a chat session that has
    -- just been handed a CSV, and "book_ticker_fkey" tells them nothing about what to do. Say it
    -- plainly instead: the ledger row is fine, the symbol is not one this system knows.
    if not exists (select 1 from universe where ticker = p_ticker) then
      raise exception '% is not in `universe` — the ledger row stands, but no position can open '
                      'for a symbol this system does not know', p_ticker
        using hint = 'check the symbol (EODHD form, e.g. NUE.US or CNQ.TO); if it is right, the '
                     'universe ingest has not seen it yet';
    end if;
    -- §2.1 makes the account the allocation, so the label decides nothing (see the header). It is
    -- NOT NULL, so it gets a value, and the value says what it is.
    insert into book (ticker, account, sleeve, qty, avg_cost, currency, opened_at, entry_fill,
                      status)
    values (p_ticker, p_account, 'book', q, c, coalesce(ccy, 'USD'), opened, c, 'open');
  elsif q <= 1e-9 then
    update book set qty = 0, status = 'closed', closed_at = coalesce(closed_at, current_date),
                    updated_at = now()
     where id = bid;
  else
    update book set qty = q, avg_cost = c, updated_at = now() where id = bid;
  end if;
  return q;
end $$;

comment on function yuna_book_from_ledger(text, text) is
  'Recompute one book position from the live ledger. The single definition of "the book is what '
  'the ledger says" — the trigger below and reconcile.apply_to_book both call it. Returns the new '
  'quantity, or null when the ledger has no history for the name (left untouched, deliberately).';

-- Every write to the ledger moves the book. This is what makes a chat session writing plain SQL
-- sufficient: it inserts one row and the position follows, with no job to wait for and no fold to
-- forget. Both OLD and NEW are resynced so that re-pointing a row at another account or ticker
-- leaves neither side stale.
create or replace function yuna_ledger_moves_the_book() returns trigger
language plpgsql as $$
begin
  if TG_OP in ('UPDATE', 'DELETE') then
    perform yuna_book_from_ledger(OLD.account, OLD.ticker);
  end if;
  if TG_OP in ('INSERT', 'UPDATE') then
    perform yuna_book_from_ledger(NEW.account, NEW.ticker);
  end if;
  return null;
end $$;

-- **DEFERRED, and that is the difference between working and not.** Supersession takes two
-- statements: the broker row goes in, and then the stated row it replaces is stamped. An immediate
-- trigger fires between them, at the one instant when the ledger holds BOTH — a 32-share sale and
-- the 31.5-share sale that corrects it — and computes a position 31.5 shares short of reality. It
-- then refuses the write for being negative, which is the guard working perfectly on a state that
-- exists for microseconds and means nothing.
--
-- The book is what the ledger says at the END of a transaction, not part-way through one. Deferring
-- to commit says exactly that, and it makes a 200-row CSV import recompute each position once
-- instead of once per row.
drop trigger if exists ledger_moves_the_book on transactions;
create constraint trigger ledger_moves_the_book
  after insert or update or delete on transactions
  deferrable initially deferred
  for each row execute function yuna_ledger_moves_the_book();

-- ---- the book joins the ledger -----------------------------------------------------------------
--
-- Every open position needs history behind it, or the first sell drives it negative and the guard
-- above refuses the write. Today two do not: SPMO.US, 810 shares in the TFSA and 107 in the RRSP,
-- bought with the §6.1 liquidation proceeds while the Wealthsimple export was still days away. At
-- seed, §6.5 sells the TFSA line to fill the five slots — and that sell would be REFUSED, on the
-- one night of the deployment that cannot afford a refusal.
--
-- So the existing book is adopted into the ledger as opening balances. Nothing here is invented:
-- every number is transcribed from the `book` row it describes — its own quantity, its own average
-- cost, its own `opened_at`. Grade `stated`, because that is what those rows are and the book says
-- so itself: *"avg_cost 155.5 is Zak's cash-delta estimate; exact fills pending next WS export."*
--
-- Idempotent by construction: after this runs the position HAS history, so a second pass finds
-- nothing to adopt.
--
-- What it does NOT do is resolve the overlap with the export when it lands. If Zak's CSV carries
-- the actual SPMO purchases, they ADD to this opening balance rather than replacing it, and the
-- position doubles. That is a judgement — the file might hold the original purchase, or a later
-- top-up, and only Zak can say which — so `ledger.py import` reports it and stops short of
-- deciding, and `reconcile.compare_positions` catches it against the broker's own position
-- statement if nobody acts. §0.3.
insert into transactions (ticker, account, side, qty, price, currency, trade_date, confirmed,
                          confirmed_at, grade, source, note)
select b.ticker, b.account, 'confirm', b.qty, coalesce(b.avg_cost, 0), b.currency,
       coalesce(b.opened_at, current_date), true, now(), 'stated',
       'book adoption (migration 059)',
       'Opening balance transcribed from the book row, which predates this ledger. Superseded by '
       'the bank export when it lands — see migration 059.'
  from book b
 where b.status = 'open' and b.qty > 0
   and coalesce(b.avg_cost, 0) > 0
   and not exists (select 1 from transactions t
                    where t.account = b.account and t.ticker = b.ticker
                      and t.superseded_by is null);

-- ---- the chat may write the ledger -------------------------------------------------------------
--
-- The jobs-only trigger goes. It said `transactions` is job-written, which was the 2026-08-04
-- plan's rule; under Zak's 2026-08-18 instruction the ledger is precisely the surface the chat
-- writes. `book` stays guarded — the session writes history and the history moves the book, so it
-- never needs to touch a position directly.
drop trigger if exists guard_transactions on transactions;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    -- `id` is an identity column, so INSERT on the table is the whole grant: identity draws from
    -- its sequence as the table's owner and needs no separate USAGE.
    grant insert, update, select on transactions to yuna_session;
    drop policy if exists yuna_session_rw on transactions;
    create policy yuna_session_rw on transactions to yuna_session using (true) with check (true);
  end if;
exception when insufficient_privilege then
  raise notice 'yuna_session grants on transactions not applied here (%): mirror them in the '
               'dashboard', sqlerrm;
end $$;

-- The guard's error message enumerates the session write list; `transactions` rejoins it.
create or replace function yuna_jobs_only() returns trigger
language plpgsql as $$
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception '% is job-written only — sessions may write transactions, briefs, tickets, observations, rulings, learnings, config', TG_TABLE_NAME
      using hint = 'jobs compute · database remembers · Yuna judges · Zak acts (plan §4.0)';
  end if;
  return coalesce(NEW, OLD);
end $$;
