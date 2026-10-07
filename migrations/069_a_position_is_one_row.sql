-- 069_a_position_is_one_row.sql — 2026-10-07. A position is one open book row: the ledger never
-- picks between two, the one split production carries is closed on Zak's word, and an index makes
-- the next one impossible. QC 2026-10-07, findings A11, A13 (the production instance) and A26.
--
-- ---- what broke ---------------------------------------------------------------------------------
--
-- 059 made the book the ledger's arithmetic: `yuna_book_from_ledger` SETs a position to the sum of
-- the rows that count. It found the position with
--
--     select id into bid from book where account = .. and ticker = .. and status = 'open' limit 1
--
-- — one row, no ORDER BY — and nothing ever promised there would be only one. `book_open_unique`
-- (007) is keyed on (ticker, account, lot), and `lot` is the retired plan's core/tactical split
-- (005). Every reader that sums a position — `desk.held_book`, the sheet gauge's top-up, `v_book`,
-- the brief — then counts any second open row ON TOP of the row the function had already set to
-- the whole ledger. After a full ledger exit the function closes the row it picked and leaves the
-- other open: a phantom that holds one of §3.5's five slots and is marked into engine NAV.
--
-- It is live. On 2026-09-28 at 12:06:31 the trigger set NONREG VXC.TO lot `tranche1` (book 22) to
-- the full ledger, 279 = 140 + 139 — correctly. Six seconds later a chat session inserted lot
-- `tranche2` (book 28, 139 shares) straight into `book`, against routines-contract §5 ("Never
-- write `book` directly"). `guard_book` let it through because `yuna_jobs_only` admits `postgres`,
-- the role the chat connector logs in as (059's header: "That is not a design"). Every brief since
-- has listed 418 shares against a ledger of 279. The engine is untouched — it reads only the TFSA
-- — but the same insert on an engine name inflates the gate-off sell, engine NAV and every NAV/5
-- buy (the QC reproduced all three).
--
-- ---- 1. the function counts the rows; it never picks one ---------------------------------------
--
-- Two ways to stop picking a row at random: refuse to move a position the book holds in more than
-- one open row, or fold the rows into one. The function refuses, because which row IS the
-- position is a fact about the broker, not about the ledger: the ledger knows the total, and it
-- cannot know whether a second row is a stray (VXC's) or the trace of a purchase the ledger is
-- missing. §0.2: "Ambiguity escalates to Zak; it is never resolved by improvisation." That is
-- exactly how the one real split is resolved below — by Zak's confirmation of the broker's
-- quantity — and a fold would have resolved it without him, at the next VXC write.
--
-- Section 2's index makes a split impossible from here on, so the refusal is the second line: it
-- holds wherever the index is not — a dump restored before its indexes, a database rebuilt by
-- hand — and it names the position, the rows and the ledger total rather than moving one row.
-- A name with no ledger history at all is still left exactly alone (059).
--
-- The negative-history hint also stops naming a `confirm` row as the only repair. A sell larger
-- than everything bought is the A21 case — most often the post-split share count, or a mistyped
-- quantity — and a `confirm` row there would invent shares and move the cost basis.
create or replace function yuna_book_from_ledger(p_account text, p_ticker text)
returns double precision
language plpgsql security definer set search_path = public as $$
declare
  q double precision; c double precision; opened date; ccy text; bid bigint; rows_seen int;
  purpose text; open_rows int; which text;
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

  -- A position the ledger drives below zero: the rows for this name are incomplete, or one of
  -- them is wrong. Refusing is the correct outcome; a book holding minus 810 shares is not a fix.
  if q < -1e-6 then
    raise exception 'ledger drives % % to % shares — the history for this name is incomplete',
                    p_account, p_ticker, q
      using hint = 'a holding bought before the ledger needs its opening position recorded as a '
                   '`confirm` row before the sells that follow it; a sell larger than everything '
                   'bought (a split since the purchase, a mistyped quantity) is itself the wrong '
                   'row — check it against the broker before recording anything';
  end if;

  -- 064: the sleeve the engine's own ticket names, if any. The newest ticketed row wins, so a
  -- position opened by an engine buy and topped up by a ticket-less broker row reads as the
  -- engine's, and a later engine exit ticket cannot relabel a position Zak labelled by hand.
  select k.sleeve into purpose
    from transactions t
    join tickets k on k.id = t.ticket_id
   where t.account = p_account and t.ticker = p_ticker and t.superseded_by is null
     and k.sleeve is not null
   order by t.trade_date desc, t.id desc
   limit 1;

  -- 069: the position is ONE open row. Counted, never picked: `min(id)` is the row only when it is
  -- the only one, and more than one is refused below rather than resolved.
  select count(*), min(id),
         string_agg(format('book %s lot %s: %s', id, lot, qty), ', ' order by id)
    into open_rows, bid, which
    from book
   where account = p_account and ticker = p_ticker and status = 'open';

  if open_rows > 1 then
    raise exception 'book holds % % in % open rows (%) against a ledger of % shares — refusing to '
                    'choose which row the ledger moves', p_account, p_ticker, open_rows, which, q
      using hint = 'a position is one book row and only the ledger moves it, so a second row was '
                   'written to `book` directly (routines-contract §5). Once Zak confirms what the '
                   'broker holds, close the row that is not the position; the ledger then moves '
                   'the one that is';
  end if;

  if bid is null then
    if q <= 1e-9 then
      return 0;                       -- opened and closed inside the ledger; nothing to carry
    end if;
    -- `book.ticker` references `universe`; say the foreign-key failure plainly (060).
    if not exists (select 1 from universe where ticker = p_ticker) then
      raise exception '% is not in `universe` — the ledger row stands, but no position can open '
                      'for a symbol this system does not know', p_ticker
        using hint = 'check the symbol (EODHD form, e.g. NUE.US or CNQ.TO); if it is right, the '
                     'universe ingest has not seen it yet';
    end if;
    insert into book (ticker, account, sleeve, qty, avg_cost, currency, opened_at, entry_fill,
                      status)
    values (p_ticker, p_account, coalesce(purpose, 'unassigned'), q, c, coalesce(ccy, 'USD'),
            opened, c, 'open');
  elsif q <= 1e-9 then
    update book set qty = 0, status = 'closed', closed_at = coalesce(closed_at, current_date),
                    updated_at = now()
     where id = bid;
  else
    update book set qty = q, avg_cost = c, updated_at = now(),
                    sleeve = case when sleeve = 'unassigned' then coalesce(purpose, sleeve)
                                  else sleeve end
     where id = bid;
  end if;
  return q;
end $$;

comment on function yuna_book_from_ledger(text, text) is
  'Recompute one book position from the live ledger. The single definition of "the book is what '
  'the ledger says" — the trigger and reconcile.apply_to_book both call it. Returns the new '
  'quantity, or null when the ledger has no history for the name (left untouched, deliberately). '
  'Opens a position under the sleeve its newest ticketed transaction names (064), and as '
  '`unassigned` when no ticket is behind it. Refuses a position the book holds in more than one '
  'open row (069): which row is the position is the broker''s fact, and S0.2 makes it Zak''s.';

-- ---- 2. the one split production carries, closed on Zak's word ----------------------------------
--
-- Zak, 2026-10-07: the NONREG account holds 279 VXC.TO, not 418. So book 28 is not a position: it
-- restates ledger txn 39 (139 @ 86.30, the 2026-09-22 tranche), which the trigger had already
-- folded into book 22. It is CLOSED, never deleted (§0.6), the way the function closes a position
-- — status, `closed_at`, quantity to zero — with a note saying what it held, who confirmed what,
-- and when. `guard_book` admits this write because a migration runs as the owner; that is the
-- path the guard leaves for a correction, and the note is what makes it one rather than a poke.
--
-- Matched on everything Zak's confirmation describes, not on the id alone: book 28, NONREG, VXC.TO,
-- lot `tranche2`, still open, still 139 shares, and still beside another open row. A database
-- where any of that is not true is not touched here — a restore with other ids, or a book whose
-- row 28 has moved since (tranche 3 is planned ~2026-10-15, and before this file lands the old
-- function moves whichever VXC row it picks). Such a database keeps its split, and the check below
-- then stops the whole migration by name, so a confirmation of one state is never applied to
-- another.
update book b
   set status = 'closed', qty = 0, closed_at = current_date, updated_at = now(),
       note = coalesce(b.note || ' | ', '')
              || 'Closed by migration 069 on Zak''s confirmation of 2026-10-07 that NONREG holds '
              || '279 VXC.TO, not 418: this row (139 @ 86.30) restated ledger txn 39, which '
              || 'book 22 already carried. It was written straight into `book` on 2026-09-28, '
              || 'beside the row the ledger had moved (QC 2026-10-07 A13).'
 where b.id = 28 and b.account = 'NONREG' and b.ticker = 'VXC.TO' and b.lot = 'tranche2'
   and b.status = 'open' and b.qty = 139
   and exists (select 1 from book k
                where k.account = b.account and k.ticker = b.ticker and k.status = 'open'
                  and k.id <> b.id);

-- Verify before the index, and stop rather than half-apply: `migrate.py` runs this file as one
-- transaction, so a refusal here leaves the database exactly as it was — the closure above
-- included. The message names every split position and its rows, which is what Zak needs to rule
-- on; the index cannot be built over a split, and must not be built over a guess.
do $$
declare
  split text;
begin
  select string_agg(format('%s %s (%s)', account, ticker, rows_held), '; ' order by account, ticker)
    into split
    from (select account, ticker,
                 string_agg(format('book %s lot %s: %s', id, lot, qty), ', ' order by id)
                   as rows_held
            from book
           where status = 'open'
           group by account, ticker
          having count(*) > 1) s;
  if split is not null then
    raise exception 'migration 069 stops: a position is held in more than one open book row — %',
                    split
      using hint = 'which row is the position is the broker''s fact. Close the row that is not, on '
                   'Zak''s confirmation and with a note saying so, then apply 069 again';
  end if;
end $$;

-- The row the ledger moves now carries the ledger's total, whatever landed between this file being
-- written and applied. Today that is book 22 at 279 already, and the call changes nothing else; it
-- is a recompute, not an increment, and a position with no ledger history is left alone (null).
select yuna_book_from_ledger('NONREG', 'VXC.TO');

-- And the rule becomes the schema. The guard keyed on `current_user` cannot tell a chat session
-- from a job — both arrive as `postgres` — so this refuses a second open row for a position from
-- every role, the owner included, and its name says why. `book_open_unique` (ticker, account, lot)
-- stays: it is implied by this one, and a migration that drops an index nothing needs dropped is
-- a second change riding on the first.
create unique index if not exists book_one_open_row_per_position
  on book (account, ticker) where status = 'open';

comment on index book_one_open_row_per_position is
  'A position is one open book row; only the ledger moves it (yuna_book_from_ledger). A second '
  'purchase is a second ledger row, never a second book row (migration 069, QC 2026-10-07 A11).';

-- ---- 3. the view names the break it was calling self-healing -----------------------------------
--
-- `v_ledger_vs_book` read `predates_the_ledger` as `l.qty is null`. But `v_ledger_positions` drops
-- a name whose live rows net to zero, so a name the ledger has SOLD OUT read exactly like a name
-- it has never heard of — and a row left open after a full exit (A11's phantom) was reported as
-- "held since before the ledger — the export has not landed yet": amber, and self-healing, for a
-- position no export will ever heal (A26). The question the column asks is whether the history
-- EXISTS, which is the question `yuna_book_from_ledger` asks before it touches anything
-- (`rows_seen = 0`), so it is now asked the same way: no live transaction for the account and
-- ticker.
--
-- And a position split across open rows is a break whatever the sums say — the ledger refuses to
-- move it and every summed reader counts both rows — so it is listed even where the rows add up to
-- the ledger, it is never `predates_the_ledger`, and the new last column, `open_rows`, says how
-- many rows carry it. Section 2's index makes that row unreachable here; the view is also read
-- wherever the index is not. Every existing column keeps its name, type and place.
create or replace view v_ledger_vs_book as
select coalesce(l.account, b.account) as account,
       coalesce(l.ticker, b.ticker)   as ticker,
       l.qty                          as ledger_qty,
       b.qty                          as book_qty,
       coalesce(l.qty, 0) - coalesce(b.qty, 0) as difference,
       l.stated_rows,
       coalesce(b.open_rows, 0) <= 1
         and not exists (select 1 from transactions t
                          where t.account = coalesce(l.account, b.account)
                            and t.ticker  = coalesce(l.ticker, b.ticker)
                            and t.superseded_by is null)
                                      as predates_the_ledger,
       coalesce(b.open_rows, 0)       as open_rows
  from v_ledger_positions l
  full outer join (select account, ticker, sum(qty) as qty, count(*) as open_rows from book
                    where status = 'open' group by account, ticker) b
    on b.account = l.account and b.ticker = l.ticker
 where abs(coalesce(l.qty, 0) - coalesce(b.qty, 0)) > 1e-6
    or coalesce(b.open_rows, 0) > 1;

comment on view v_ledger_vs_book is
  'Every disagreement between the ledger and the book. predates_the_ledger separates the two '
  'cases: false is a real break, true is a holding with no live ledger rows behind it at all '
  '(amber, and self-healing when the export lands). A row left open after the ledger sold the '
  'name out, and a position held in more than one open row (open_rows > 1), are real breaks (069).';
