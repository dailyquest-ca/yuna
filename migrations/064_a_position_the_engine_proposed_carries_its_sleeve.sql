-- 064_a_position_the_engine_proposed_carries_its_sleeve.sql — 2026-09-02. Zak's question, and
-- the half of migration 060's reading that it corrects.
--
-- Zak, 2026-09-02, reading the brief's sleeve-divergence line on SNDK, WDC and RVMD:
--
--   "Why are they unassigned?? ... They were recommended to me... What's broken there?"
--
-- ---- what broke, and when ---------------------------------------------------------------------
--
-- Before 059 the book got its sleeve from the ticket: `arming.sync_fills_from_tickets` wrote
-- `sleeve or 'momentum'` onto the position it opened (`arming.py`, retired from the schedule by
-- §6.3). 059 moved the book's movement into `yuna_book_from_ledger`, which opens a position under
-- a fixed label — 'book' in 059, corrected to 'unassigned' by 060 on the reading that "the ledger
-- knows a trade happened and in which account, and genuinely does not know which sleeve the
-- position belongs to. That is a judgement about strategy, and §0.3 makes it Zak's."
--
-- That reading is right for a row with no ticket behind it and wrong for a row with one. The
-- engine's ticket names the sleeve — `sheet.SLEEVE = 'momentum'`, "a placement ruling, quoted"
-- (§2.1) — Zak approved and executed it, and the transaction derived from it carries `ticket_id`.
-- Nothing here invents a purpose: the purpose was written on the ticket by the plan, and the label
-- simply stopped crossing over when the fill loop retired. Three positions opened 2026-08-28
-- behind reconciled momentum tickets 156, 157 and 158 (SNDK.US, WDC.US, RVMD.US, all TFSA) have
-- carried `unassigned` since, and `desk.sleeve_divergence` has named them every night. A gauge
-- that fires on the same three rows for five days is reporting a defect, not weather — the same
-- shape as learning 58's drift number.
--
-- The engine was never wrong about them. `desk.held_book` reads the ACCOUNT (§2.1's proxy, ruled
-- 2026-08-18), so all three were ranked, marked and sized correctly. What was wrong was the
-- record: the payload's book, the divergence line, and any future move of `held_book` back to the
-- sleeve, which `desk.py` says "needs the labels corrected first".
--
-- ---- the rule ----------------------------------------------------------------------------------
--
-- When the ledger opens a position, or recomputes one that is still `unassigned`, it takes the
-- sleeve of the newest surviving transaction for that (account, ticker) that carries a ticket with
-- a sleeve. A history with no ticketed row stays `unassigned` — §0.3 holds exactly as 060 stated
-- it. A sleeve that is already set is never touched: a label Zak set by hand outranks a ticket.
--
-- Not a plan change. §2.1 places the engine's tickets; this transcribes them onto the book.
create or replace function yuna_book_from_ledger(p_account text, p_ticker text)
returns double precision
language plpgsql security definer set search_path = public as $$
declare
  q double precision; c double precision; opened date; ccy text; bid bigint; rows_seen int;
  purpose text;
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

  -- A position the ledger drives below zero: the rows for this name are incomplete, almost always
  -- a sell recorded against a holding whose purchase predates the ledger. Refusing is the correct
  -- outcome; the fix is a `confirm` row, and a book quietly holding minus 810 shares is not a fix.
  if q < -1e-6 then
    raise exception 'ledger drives % % to % shares — the history for this name is incomplete',
                    p_account, p_ticker, q
      using hint = 'record the opening position as a `confirm` row before the sells that follow it';
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

  select id into bid from book
   where account = p_account and ticker = p_ticker and status = 'open' limit 1;

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
  '`unassigned` when no ticket is behind it — the ledger does not know, and S0.3 makes that Zak''s.';

-- ---- the standing book, once, under the same rule ----------------------------------------------
--
-- Written as the rule rather than as three names, so a database restored from any dump between
-- 060 and now lands identically. Today it relabels SNDK.US, WDC.US and RVMD.US (TFSA, opened
-- 2026-08-28) to `momentum` and touches nothing else: AXTI and MU already carry it, the RRSP's
-- SPMO carries `reserve` from ticket 89, and VXC has no ticket and is not `unassigned`.
update book b
   set sleeve = s.sleeve, updated_at = now()
  from (select distinct on (t.account, t.ticker) t.account, t.ticker, k.sleeve
          from transactions t
          join tickets k on k.id = t.ticket_id
         where t.superseded_by is null and k.sleeve is not null
         order by t.account, t.ticker, t.trade_date desc, t.id desc) s
 where b.status = 'open' and b.sleeve = 'unassigned'
   and b.account = s.account and b.ticker = s.ticker;
