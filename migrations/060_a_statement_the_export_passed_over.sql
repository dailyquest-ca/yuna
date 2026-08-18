-- 060_a_statement_the_export_passed_over.sql — 2026-08-18. Zak's rule, and a correction to 059.
--
-- Zak, 2026-08-18:
--
--   "The Book is just everything I have... which should be a sum of transactions, some stated and
--    some actually reconciled with the broker. FYI if a stated transaction in an account pre-dates
--    broker transactions... that's a bad sign and likely the stated transaction should be matched
--    to one of the broker transactions or removed... because I had stated data that didn't actually
--    come to pass.
--
--    And then back to Sleeves... they are just subsets of the book. Right now it appears that we
--    have a large Momentum Sleeve... and we have a safe, ETF sleeve in the RRSP... and we have a
--    leveraged Sleeve in VXC... but those can change. The sum of everything is the book though."
--
-- Two things follow, and one of them corrects migration 059.
--
-- ---- 1. a statement the export has already passed over --------------------------------------
--
-- 059 gave a `stated` row one way out: a broker row for the same trade supersedes it. That covers
-- the case where the export CONFIRMS what Zak said. It says nothing about the case where the export
-- arrives, covers the day, and does not mention the trade at all — and that case is not neutral.
-- It means the thing Zak believed had happened did not happen.
--
-- Left alone it is the ghost book in its worst form: a stated SELL that never executed removes a
-- position from the book that is still held, and every later session reasons from a slot that is
-- actually full. The stated row does not decay on its own — it stays live and keeps counting.
--
-- So: a live `stated` buy or sell whose trade date is EARLIER than the newest broker row in the
-- same account is flagged. The broker has reported past that date; if the trade were real it would
-- have come with it.
--
-- **`confirm` rows are excluded, and that is not a loophole.** A `confirm` is an opening balance —
-- a statement that a position EXISTS and what it cost — not a claim that a trade occurred on that
-- date. An export that covers 2026-08-17 and does not mention SPMO does not refute "I hold 810
-- SPMO"; it just does not explain it. That is a different condition, it is amber rather than red,
-- and it gets its own view below.
--
-- Neither view deletes anything (§0.6). They name rows for Zak to match or void, because only he
-- knows which broker line a statement was reaching for.
create or replace view v_stale_statements as
with confirmed_through as (
  select account, max(trade_date) as through
    from transactions
   where grade = 'broker' and superseded_by is null
   group by account)
select t.id, t.account, t.ticker, t.side, t.qty, t.price, t.trade_date, t.source, t.note,
       c.through                        as broker_confirmed_through,
       (c.through - t.trade_date)       as days_the_export_has_passed_it
  from transactions t
  join confirmed_through c on c.account = t.account
 where t.grade = 'stated'
   and t.superseded_by is null
   and t.side in ('buy', 'sell')
   and t.trade_date < c.through
 order by t.account, t.trade_date;

comment on view v_stale_statements is
  'Zak 2026-08-18: a stated trade the broker export has already reported past without confirming '
  'is "stated data that didn''t actually come to pass". It still counts in the book until it is '
  'matched to a broker row or voided — a stated sell that never executed empties a slot that is '
  'still full. Never auto-resolved: only Zak knows which line it was reaching for.';

-- An opening balance no export explains. Not wrong, and not nothing: the position is real and the
-- history behind it is missing, so the cost basis is Zak's estimate rather than the bank's. It
-- resolves when an export carries the purchase — and then the adoption and the purchase BOTH count
-- unless one is retired, which is exactly why this is worth naming rather than leaving implicit.
create or replace view v_unexplained_opening_balances as
select t.id, t.account, t.ticker, t.qty, t.price, t.trade_date, t.source,
       exists (select 1 from transactions b
                where b.account = t.account and b.ticker = t.ticker
                  and b.grade = 'broker' and b.superseded_by is null) as broker_has_this_name
  from transactions t
 where t.grade = 'stated' and t.superseded_by is null and t.side = 'confirm'
 order by t.account, t.ticker;

comment on view v_unexplained_opening_balances is
  'A position carried into the ledger without the trades that created it — cost basis is an '
  'estimate. `broker_has_this_name` true means an export now covers the name, so the opening '
  'balance and the real purchases are probably BOTH counting: retire one.';

-- ---- 2. sleeves are subsets of the book, and 059 mislabelled them ---------------------------
--
-- 059 wrote `sleeve = 'book'` on any position the ledger opened, on the reading that the label had
-- stopped deciding anything. That was wrong. Zak: **"Sleeves… are just subsets of the book. The sum
-- of everything is the book."** The book is the whole; a sleeve is a cut of it; `'book'` is a
-- category error — it labels a part with the name of the whole.
--
-- `unassigned` is what a ledger-opened position gets instead, and it is honest: the ledger records
-- that a trade happened and in which account, and it genuinely does not know which sleeve the
-- position belongs to. That is a judgement about strategy, and §0.3 makes it Zak's. The value
-- already exists — `reconcile` used it for exactly this before 059 — so nothing new is invented.
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
    -- `unassigned`, not 'book' — see the header. A sleeve is a subset of the book and the ledger
    -- does not know which one this belongs to.
    insert into book (ticker, account, sleeve, qty, avg_cost, currency, opened_at, entry_fill,
                      status)
    values (p_ticker, p_account, 'unassigned', q, c, coalesce(ccy, 'USD'), opened, c, 'open');
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
  'the ledger says" — the trigger and reconcile.apply_to_book both call it. Returns the new '
  'quantity, or null when the ledger has no history for the name (left untouched, deliberately). '
  'Opens new positions as `unassigned`: a sleeve is a subset of the book and the ledger does not '
  'know which one (S0.3).';

-- Nothing wrote `sleeve = 'book'` in production — 059 applied at 15:55 and no position has been
-- opened by the ledger since — but a database restored from a dump taken in that window would
-- carry the label, and it would then read as a sleeve named after the whole book.
update book set sleeve = 'unassigned' where sleeve = 'book';
