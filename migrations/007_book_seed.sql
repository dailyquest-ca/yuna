-- 007_book_seed.sql — Phase F cutover, part one: today's book into the database.
-- Quantities and accounts are the broker screenshot of 2026-07-30 (broker truth beats records,
-- the 003 precedent). Cost basis was never captured, so avg_cost becomes nullable and stays
-- null until Zak supplies it; v_book already reports pnl_pct as null when it is missing.
-- Sleeves are 'unassigned' on purpose — §6 Step 2a assigns them by score, not by history.

alter table book alter column avg_cost drop not null;

create unique index if not exists book_open_unique
  on book(ticker, account, lot) where status = 'open';

insert into book (ticker, account, sleeve, lot, qty, avg_cost, currency, status, thesis) values
 ('ANET.US','TFSA','unassigned','core',40.0000, null,'USD','open','seeded at cutover — awaiting §6 Step 2a'),
 ('AVGO.US','TFSA','unassigned','core',30.0964, null,'USD','open','seeded at cutover — awaiting §6 Step 2a'),
 ('ISRG.US','TFSA','unassigned','core',26.0000, null,'USD','open','seeded at cutover — awaiting §6 Step 2a'),
 ('NVDA.US','TFSA','unassigned','core',40.0437, null,'USD','open','seeded at cutover — awaiting §6 Step 2a'),
 ('TSM.US', 'TFSA','unassigned','core',15.1647, null,'USD','open','seeded at cutover — awaiting §6 Step 2a'),
 ('VRT.US', 'TFSA','unassigned','core', 0.0031, null,'USD','open','dust — $0.73 at 2026-07-30'),
 ('CNQ.TO','NONREG','levered',     'core',142.0000,null,'CAD','open','levered layer — judged at §6 Step 5 under §2.5')
on conflict do nothing;
