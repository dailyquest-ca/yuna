-- Seed: current book (per 2026-07-29 records) + index + FX, and plan-default config
insert into universe (ticker,name,kind,exchange,currency,is_holding,note) values
 ('TSM.US','Taiwan Semiconductor','stock','US','USD',true,'holding'),
 ('NVDA.US','NVIDIA','stock','US','USD',true,'holding'),
 ('AVGO.US','Broadcom','stock','US','USD',true,'holding'),
 ('ANET.US','Arista Networks','stock','US','USD',true,'holding'),
 ('ISRG.US','Intuitive Surgical','stock','US','USD',true,'holding'),
 ('CNQ.TO','Canadian Natural Resources','stock','TO','CAD',true,'holding — levered layer'),
 ('MU.US','Micron','stock','US','USD',true,'dust holding'),
 ('VRT.US','Vertiv','stock','US','USD',true,'dust holding'),
 ('GOOGL.US','Alphabet','stock','US','USD',true,'dust holding (TFSA+RRSP)'),
 ('GSPC.INDX','S&P 500','index','INDX','USD',false,'M1 gate feed'),
 ('USDCAD.FOREX','USD/CAD','fx','FOREX',null,false,'CAD conversion')
on conflict (ticker) do nothing;

insert into config (key,value,note,set_by) values
 ('stop_limit_buffer','0.03','stop-limit: limit = stop - 3%','yuna'),
 ('entry_limit_over_pivot','0.02','entry stop-limit: limit = pivot + 2%','yuna'),
 ('gap_threshold','0.07','+/-7% open vs prior close -> L3','yuna'),
 ('blackout_trading_days','5','earnings blackout window','yuna'),
 ('bars_retention_years','3','rolling bar window','yuna'),
 ('small_large_boundary_usd','10000000000','bench cohort split','yuna'),
 ('queue_cap','20','L2 composition cap','yuna'),
 ('new_entry_tickets_per_brief','2','throttle','yuna'),
 ('api_alarm_fraction','0.70','quota alarm','yuna'),
 ('position_floor_nav','0.04','minimum intended full size','yuna'),
 ('mcn_risk_budget','{"70":0.007,"85":0.009}','momentum risk budgets','yuna'),
 ('mcn_risk_budget_validation','{"70":0.005,"85":0.007}','first-quarter start-low','yuna'),
 ('base_currency','"CAD"','NAV currency','yuna');
