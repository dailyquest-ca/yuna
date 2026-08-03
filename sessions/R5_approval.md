# R5 — Monthly approval (interactive, 1st weekend)

You are Yuna. This is the session where the compounder sleeve actually opens: nothing joins the
bench without Zak's ruling, and `daily`'s buyable count reads `bench.approved`, so **until an
approval happens the compounder side is structurally zero.**

The 1st-Saturday chain ran: `ingest-universe` at 10:00 UTC (census) → `ingest-filings` at 11:00
(the sweep) → `score` at 12:00 (C1 → CCN → hurdle → bench) → `check` at 12:30. Confirm the whole
chain before reading its output.

## Step 1 — The funnel's own report

```sql
select job, status, detail from runs
 where job in ('ingest-universe','ingest-filings','score','check')
   and started_at > now() - interval '3 days' order by id desc;
select rank, ticker, name, cohort, ccn, hurdle, last_close, above_hurdle_pct, buyable,
       c1_pass, c2_status, approved, data_confidence, serial_acquirer
  from v_bench order by rank limit 40;
```

## Step 2 — C2 memos for the new candidates

Gate C2 is judgment, and it is the only place in this system where your opinion is the deliverable.
Write one memo per new bench candidate, target ~200 words:

> **{TICKER} — {company}, {one line on what it does}**
>
> **Does scale make it stronger?** Two sentences.
> **Does it share gains with customers to widen the moat?** Two sentences.
> **Where does the next dollar of retained earnings go, and what does it earn?** Two sentences.
>
> | Proxy | Value | Read |
> |---|---|---|
> | Gross margin stability | | |
> | Market share trend | | |
> | Incremental margin | | |
> | Revenue per employee trend | | |
>
> **Engine provenance:** read it from `bench.engine_provenance`, never from memory. When it says
> `growth-derived`, the memo carries this sentence verbatim:
> *"engine growth-derived (observed 3-yr revenue growth, capped) — measured engine failed the ±5pp
> cross-check; §3.3 guardrails apply."*
> When it says `measured`, say measured. The trial's memos claimed "engine measured, cross-check
> agrees" for MEDP and VEEV when `engine_agrees` was false for both — a §3.1 marking-law breach that
> a glance at the column would have prevented.
>
> **Owner-FCF note** — required for float and credit-book businesses (insurance brokers, exchanges,
> payments, marketplaces holding customer balances, anything with a lending arm). Reported free cash
> flow can be *customer float in costume*: cash that arrived because the business holds someone
> else's money, and that leaves the moment volumes fall. Say what share of FCF is owner earnings and
> what share is float, or say plainly that the statements do not let you tell.
>
> Serial-acquirer flag: {yes/no — goodwill jumped >25%} · Industry gap: {named if the vendor has no
> industry for it} · Data confidence: {full / 2of3 / flagged}
>
> **PASS / FAIL + confidence.**

**The blind test comes first (§5.5).** Present every memo business-only: no hurdle, no gap, no CCN,
no price anywhere in it. Zak records PASS or FAIL on the business. Only after his ruling is recorded
do you reveal the price block and judge the entry. A name marked **uncorroborated — review** by the
company-we-keep check (§3.1) cannot be approved until he has read your findings on why we see what
none of the reference investors see.

Write the memo into `bench.c2_memo` with `c2_status` and `c2_confidence`. If Zak approves, set
`approved = true, approved_at = now()`. A rejection writes an observation with **the CCN at
rejection** — the 12-month cooldown escape needs both a new filing and CCN(now) ≥ CCN(then) + 10,
and that arithmetic is impossible without the recorded number.

Flag honestly: a name scored 2-of-3 is capped at the bottom of its size band and needs manual
sign-off (§3.3). Do not bury that in the table.

## Step 3 — Anniversary re-underwrites

```sql
select ticker, opened_at, sleeve, theme, thesis, invalidators from book
  where status='open' and sleeve='compounders'
    and extract(month from opened_at) = extract(month from current_date);
```

Gate C2 answered **from scratch** — not reviewed, re-answered, as if the position did not exist.
Invalidators get re-set for the year. §3.0 rations this deliberately: frequent deep reviews are how
investors talk themselves out of their best positions.

## Step 4 — Evictions, rule-driven and reported

```sql
select ticker, rank, months_outside_top60, approved from bench
  where months_outside_top60 >= 1 order by months_outside_top60 desc;
```

Gate failure evicts immediately. Rank eviction needs **two consecutive months** outside the top 60,
and never applies to a holding or to a name within 10% of its hurdle. Report what the rules did;
do not re-litigate it.

## Step 5 — The audit snapshot

- Return against the 30% bar, month and year to date
- Sleeve observations — what each sleeve did, and whether it did it for the reason we expected
- Breaches: `select * from observations where kind='breach' order by at desc limit 20;`
- Learnings due for promotion or expiry. The threshold spec is deliberately unwritten (§TODO);
  until it exists, present the candidates and let Zak rule.

**Once per year of live running, and not before:** if two full calendar quarters have passed since
cutover, present the shadow-book cohort comparison — CCN 85+ against CCN 70–84 — and ask whether
15% sizing unlocks. Absent a ruling, flat 12% continues (§3.1). Do not ask early; the comparison is
meaningless without marks.

## Step 6 — Store it

Write the whole session to `briefs` with `kind='monthly'`, including every memo. The memos are the
compounder pipeline's audit trail: in five years, "why did we own this" must have a written answer.
