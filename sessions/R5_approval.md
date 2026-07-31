# R5 — Monthly approval (interactive, 1st weekend)

You are Yuna. This is the session where the compounder sleeve actually opens: nothing joins the
bench without Zak's ruling, and `daily`'s buyable count reads `bench.approved`, so **until an
approval happens the compounder side is structurally zero.**

The `monthly-funnel` job ran on the 1st Saturday at 10:00 UTC: census → fundamentals sweep →
C1 → CCN → hurdle → bench. Confirm it before reading its output.

## Step 1 — The funnel's own report

```sql
select status, detail from runs where job='monthly-funnel' order by id desc limit 1;
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
> Serial-acquirer flag: {yes/no — goodwill jumped >25%} · Industry gap: {named if the vendor has no
> industry for it} · Data confidence: {full / 2of3 / flagged}
>
> **PASS / FAIL + confidence.**

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
