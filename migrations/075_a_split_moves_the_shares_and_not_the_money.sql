-- 075_a_split_moves_the_shares_and_not_the_money.sql — 2026-10-07. The ledger learns a fourth verb,
-- `split`, so a vendor-reported split on a held name moves the position's shares and cost basis
-- and no cash. QC 2026-10-07, findings A1, A2, A21 (its root) and A32.
--
-- Zak's ruling, 2026-10-07. Asked how a split on a held name should reach the book, he chose
-- "Pipeline records splits", the option put to him as: a vendor-reported split on a held name is
-- written to the ledger as a quantity-only confirm (no cash) before score runs, and the brief shows
-- it; ticker changes and takeovers still fail closed until he records them.
--
-- ---- what broke ---------------------------------------------------------------------------------
--
-- Since 059 the book is the ledger's arithmetic, and the ledger had no row that could say "the
-- shares changed and no trade happened". A split on a held name therefore left `book.qty` at the
-- pre-split count for as long as the name was held — the one re-base the system ever had
-- (`arming.rebase_for_splits`, writing `book` directly) retired with arming (§6.3), and a direct
-- write would now be undone by the next ledger recompute anyway. From the split's date:
--
--   A1   every exit sells the pre-split count: half a 2:1 position never exits; after a 1:10 the
--        sheet asks for shares that do not exist and leaves 90% of the line as phantom.
--   A2   derived engine NAV marks the old count at the new raw close — about −10% for a 2:1 on
--        one of five slots, +175% for a 1:10 — and §3.5 sizes every buy off it.
--   A21  the true post-split sale is refused (the ledger cannot go negative), every night.
--   A32  a reverse split stores an inflated `marked_equity` (and engine NAV) on the session, and
--        the running peak in `v_engine_drawdown` keeps it.
--
-- `.claude/rules/investment-tax.md`: "a split changes per-share ACB without a trade occurring, and
-- any position or basis tracking that only reconciles on trades will drift." `market-mechanics`:
-- "share count and per-share cost base change; total cost base does not."
--
-- ---- why a verb of its own, and not a `confirm` row ---------------------------------------------
--
-- The ruling describes the substance — shares move, money does not — and a `confirm` row is the
-- obvious way to write it down. It cannot carry it both ways. `yuna_book_from_ledger` (059, 069)
-- averages cost over every buy and confirm the name has ever had, avg = Σ qty×price / Σ qty, and
-- sells do not enter it:
--
--   forward 2:1 as `confirm +Q @ 0`   the share count is right, and the average is right only if
--       no sell precedes the split in the name's history. Buy 100 @ 50, sell 40, then 2:1: the
--       60 held become 120 at 25.00, and a +60 confirm averages 5,000 / 160 = 31.25. Every name
--       the engine re-enters carries an old exit in its history (WDC: bought, sold out 10-06).
--   reverse 1:10 as `confirm −0.9Q @ 0`   a negative opening balance — 059 defines a confirm as
--       "arithmetically a buy" — and the same flaw inverted: buy 100 @ 50, sell 90, then 1:10, and
--       −9 @ 0 averages 5,000 / 91 = 54.95 against a true 500.00. It would also list every split
--       in `v_unexplained_opening_balances` as an opening balance no export explains.
--
-- So `split` is the fourth verb, and its quantity is the RATIO — new shares per old, 2 for a 2:1,
-- 0.1 for a 1:10 — with price 0. It restates every earlier row of the position: a row dated before
-- the split counts its quantity × the ratio and keeps its quantity × price, which is the doctrine
-- exactly (per-share cost ÷ ratio, total cost unchanged), for a forward and a reverse split alike,
-- with or without sells before it, and for any number of splits in one name. A row dated ON the
-- split's date is already post-split: the vendor's date is the ex-date, the first session that
-- trades on the new basis (APH 160.08 → 82.07 on 2026-09-03, TOP 2.06 → 10.52 on 08-03).
--
-- No cash. `db.cash_by_account` moves cash on `buy` and `sell` only, and names `confirm` and
-- `split` as moving none (src/db.py, same change).
--
-- ---- the sums -----------------------------------------------------------------------------------
--
-- 059: "Adding a fourth verb means editing every sum in this file." The share arithmetic lived in
-- two places — `v_ledger_positions` and `yuna_book_from_ledger` — and both now call ONE function,
-- `yuna_ledger_position`, which reconcile also calls for the position just before a split's date.
-- Every other query over `transactions` was read and left alone, each for a stated reason:
--   v_stale_statements, v_unexplained_opening_balances   select buy/sell and confirm by name; a
--                                                         split is neither, deliberately
--   v_reconciliation_age, 060's confirmed_through         read grade = 'broker'; a split row is
--                                                         `stated` (below)
--   064/069's sleeve lookup                               reads ticketed rows; a split has none
--   reconcile.apply_unapplied and its dry-run count       stamp buy/sell receipts only; a split
--                                                         row is written applied
--   ledger.parse_csv / ledger.record                      an export's split line is skipped as
--                                                         not a trade, and record() matches by
--                                                         side, so no import supersedes a split
--   ledger.rebuild_book's history test                    any live row; a position with only a
--                                                         split row is visited, and the function
--                                                         leaves it alone (rows_seen = 0)
--   arming, check, fills (src/)                           retired from the schedule (§6.3)
--
-- ---- the shape, and once per position per split -----------------------------------------------
--
-- A split row's ratio is positive, finite and not 1, its price is 0, and it carries no fee and no
-- ticket. And there is one per (account, ticker, date) EVER — superseded rows included — so a
-- re-run, a retry chain or a session writing the same split by hand collides instead of
-- squaring the ratio. That is the per-position record `corporate_actions.applied_to_book_at`
-- cannot be: it is one stamp per action, and two accounts holding the name (SPMO sat in the TFSA
-- and the RRSP at once in August) each need their own adjustment, one of which may be refused
-- while the other lands. The column stays, unwritten, with its comment saying so.
--
-- Grade: a split row is `stated`. It is not the bank's record, so it is not `broker`; it is true
-- and provisional in 059's sense — the vendor reported it, the tape agrees (reconcile checks the
-- raw closes before it writes), and the bank's export is still the law that could supersede it.

-- ---- 1. the vocabulary -------------------------------------------------------------------------
alter table transactions drop constraint if exists transactions_side_vocabulary;
alter table transactions add constraint transactions_side_vocabulary
  check (side in ('buy', 'sell', 'confirm', 'split'));

-- `qty < 'Infinity'` because Postgres sorts NaN above every number, so `qty > 0` alone admits both.
alter table transactions drop constraint if exists transactions_split_shape;
alter table transactions add constraint transactions_split_shape
  check (side <> 'split'
         or (qty > 0 and qty < 'Infinity'::double precision and qty <> 1
             and price = 0 and coalesce(fees, 0) = 0 and ticket_id is null));

create unique index if not exists transactions_one_split_per_position
  on transactions (account, ticker, trade_date) where side = 'split';

comment on index transactions_one_split_per_position is
  'One split row per position per date, ever (superseded rows included): a re-run collides rather '
  'than applying a ratio twice. The per-position record of a corporate split (migration 075).';

comment on column transactions.side is
  'buy | sell | confirm | split. `confirm` establishes a position that predates the ledger, '
  'carrying its cost basis — arithmetically a buy. `split` (075) restates the position for a '
  'corporate split: qty is the ratio (new shares per old), price 0; every row dated before it '
  'counts qty x ratio and keeps qty x price, so the shares move and the money does not. The share '
  'arithmetic is yuna_ledger_position and the cash arithmetic db.cash_by_account: a fifth verb '
  'edits both.';

-- ---- 2. one definition of what a split does to a row -------------------------------------------
--
-- The product of every live split ratio dated after `p_after` (and, given `p_before`, before it):
-- what one share of a row dated `p_after` has become. A loop rather than exp(sum(ln(..))): here
-- exp(ln(6.665)) is 6.664999999999999, so 1,000 shares through CTVA's 6.665:1 would come out
-- 6,664.999999999999 — a share short wherever a count is taken with int() — where the product is
-- 6,665. Chronological, so every caller multiplies in the same order and gets the same float.
create or replace function yuna_split_factor(p_account text, p_ticker text, p_after date,
                                             p_before date default null)
returns double precision
language plpgsql stable set search_path = public as $$
declare
  factor double precision := 1;
  ratio double precision;
begin
  for ratio in
    select s.qty from transactions s
     where s.account = p_account and s.ticker = p_ticker and s.side = 'split'
       and s.superseded_by is null
       and s.trade_date > p_after
       and (p_before is null or s.trade_date < p_before)
     order by s.trade_date, s.id
  loop
    factor := factor * ratio;
  end loop;
  return factor;
end $$;

comment on function yuna_split_factor(text, text, date, date) is
  'What one share of a row dated p_after has become: the product of every live split ratio dated '
  'after it (and before p_before when given). Migration 075.';

-- ---- 3. one definition of the position --------------------------------------------------------
--
-- The sums 059 wrote twice, written once. Each position row (buy, confirm, sell) counts its
-- quantity in today's shares; cost is quantity × price, which a split does not touch; the average
-- is cost over the shares bought, in today's shares. `p_before` asks the same question as it stood
-- at the START of that day — the position a split dated `p_before` applies to. `rows_seen` counts
-- position rows only: split rows with nothing to restate are not a history (059: "No history at
-- all: nothing to say about this position"). The `else 'NaN'` keeps 059's rule that a verb the
-- arithmetic does not know comes out visibly broken; the vocabulary above makes it unreachable.
create or replace function yuna_ledger_position(p_account text, p_ticker text,
                                                p_before date default null,
                                                out qty double precision,
                                                out avg_cost double precision,
                                                out opened date,
                                                out rows_seen bigint,
                                                out currency text)
language sql stable set search_path = public as $$
  select sum(case when r.side in ('buy', 'confirm') then r.qty * r.factor
                  when r.side = 'sell'             then -r.qty * r.factor
                  else 'NaN'::double precision end),
         sum(case when r.side in ('buy', 'confirm') then r.qty * r.price else 0 end)
           / nullif(sum(case when r.side in ('buy', 'confirm') then r.qty * r.factor
                             else 0 end), 0),
         min(r.trade_date) filter (where r.side in ('buy', 'confirm')),
         count(*),
         min(r.currency)
    from (select t.side, t.qty, t.price, t.trade_date, t.currency,
                 yuna_split_factor(t.account, t.ticker, t.trade_date, p_before) as factor
            from transactions t
           where t.account = p_account and t.ticker = p_ticker
             and t.superseded_by is null
             and t.side <> 'split'
             and (p_before is null or t.trade_date < p_before)) r
$$;

comment on function yuna_ledger_position(text, text, date) is
  'The position the live ledger implies for one account and ticker, in today''s shares: quantity, '
  'average cost, first purchase, position rows behind it, currency. With p_before, the position '
  'at the start of that day — what a split dated p_before applies to. The one definition of the '
  'share arithmetic: yuna_book_from_ledger, v_ledger_positions and reconcile all read it (075).';

-- ---- 4. the book follows the ledger, splits included -------------------------------------------
--
-- 069's function with its first query replaced by the one definition above. The refusals
-- (negative history, more than one open row), the sleeve rule (064) and the open/close/update
-- branches are 069's; the negative-history hint now names the split route, because a sale larger
-- than everything bought is no longer always the wrong row — after a split the vendor has posted it
-- is the right row, early. With no split rows in a name's history the factor is 1 everywhere and
-- every number comes out as it did.
create or replace function yuna_book_from_ledger(p_account text, p_ticker text)
returns double precision
language plpgsql security definer set search_path = public as $$
declare
  q double precision; c double precision; opened date; ccy text; bid bigint; rows_seen bigint;
  purpose text; open_rows int; which text;
begin
  -- 075: the arithmetic is yuna_ledger_position's, which restates every row for the splits after
  -- it. Position rows only: split rows with no history to restate are no history.
  select p.qty, p.avg_cost, p.opened, p.rows_seen, p.currency
    into q, c, opened, rows_seen, ccy
    from yuna_ledger_position(p_account, p_ticker) p;

  -- No history at all: nothing to say about this position, and saying "zero" would delete a real
  -- holding because one table cannot explain it. Left exactly alone; `v_ledger_vs_book` names it.
  if rows_seen = 0 then
    return null;
  end if;

  -- 075: a verb the arithmetic does not know comes out NaN (learning 51) and must not reach `book`
  -- as a quantity. Unreachable while the vocabulary constraint stands; loud if it ever does not.
  if q = 'NaN'::double precision then
    raise exception 'the ledger for % % holds a verb its arithmetic does not know — refusing to '
                    'move the book', p_account, p_ticker
      using hint = 'transactions.side is buy, sell, confirm or split (migration 075)';
  end if;

  -- A position the ledger drives below zero: the rows for this name are incomplete, or one of
  -- them is wrong. Refusing is the correct outcome; a book holding minus 810 shares is not a fix.
  if q < -1e-6 then
    raise exception 'ledger drives % % to % shares — the history for this name is incomplete',
                    p_account, p_ticker, q
      using hint = 'a holding bought before the ledger needs its opening position recorded as a '
                   '`confirm` row before the sells that follow it. A sell larger than everything '
                   'bought is the post-split count when the vendor has posted a split since the '
                   'purchase (corporate_actions): reconcile records the split before any receipt '
                   '(075), so write the sale on its ticket and it lands after it. Otherwise it is '
                   'a mistyped quantity — check it against the broker before recording anything';
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
  'open row (069): which row is the position is the broker''s fact, and S0.2 makes it Zak''s. '
  'The arithmetic is yuna_ledger_position, splits included (075).';

-- ---- 5. the views say what the function says ----------------------------------------------------
--
-- Same columns, names, types and order as 059's view, so every reader survives; the numbers come
-- from the one definition. `last_activity` and `stated_rows` still count every live row, the split
-- included: it is activity on the position, and it is a provisional row like any `stated` one. A
-- name whose rows net to zero still drops out; NaN still sorts above the threshold and shows.
create or replace view v_ledger_positions as
select k.account, k.ticker,
       p.qty,
       p.avg_cost                                                          as avg_buy_price,
       p.opened                                                            as first_buy,
       k.last_activity,
       k.stated_rows
  from (select account, ticker,
               max(trade_date)                          as last_activity,
               count(*) filter (where grade = 'stated') as stated_rows
          from transactions
         where superseded_by is null
         group by account, ticker) k
 cross join lateral yuna_ledger_position(k.account, k.ticker) p
 where abs(p.qty) > 1e-9;

comment on view v_ledger_positions is
  'The position the live ledger implies, per account and ticker. "They should all match" is this '
  'against `book`; S4.4''s reconciliation gauge is what says so out loud. Splits included: the '
  'numbers are yuna_ledger_position''s (075).';

-- 069's view, one clause changed: "the history exists" is asked the way the function asks it, of
-- position rows. A split row alone restates nothing, so a holding with nothing else behind it
-- still predates the ledger rather than reading as a real break.
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
                            and t.superseded_by is null
                            and t.side <> 'split')
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
  'cases: false is a real break, true is a holding with no live position rows behind it at all '
  '(amber, and self-healing when the export lands). A row left open after the ledger sold the '
  'name out, and a position held in more than one open row (open_rows > 1), are real breaks (069). '
  'A split row alone is no history (075).';

-- ---- 6. the retired stamp says it is retired ---------------------------------------------------
comment on column corporate_actions.applied_to_book_at is
  'Retired with arming.rebase_for_splits (S6.3), which re-based `book` directly, once per action. '
  'Never written by the live path: since migration 075 reconcile records a split in the ledger, '
  'one `split` row per position (unique on account, ticker, date), and that row is the record.';

-- ---- 7. who may call the new functions (066) ---------------------------------------------------
--
-- A function is executable by PUBLIC by default, and PUBLIC includes the Data API's two roles.
-- Neither function can read a row its caller could not (both are SECURITY INVOKER), but 066 made
-- the ledger arithmetic callable only by the roles with a reason to call it, and these are the
-- ledger arithmetic now: the owner, and `yuna_session`, which reads the ledger views that call
-- them.
revoke execute on function yuna_split_factor(text, text, date, date) from public;
revoke execute on function yuna_ledger_position(text, text, date) from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    grant execute on function yuna_split_factor(text, text, date, date) to yuna_session;
    grant execute on function yuna_ledger_position(text, text, date) to yuna_session;
  end if;
end $$;
