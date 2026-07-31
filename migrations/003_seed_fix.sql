-- Correction per Zak's live broker positions (2026-07-30 screenshot):
-- MU and GOOGL dust no longer held. Removed from universe.
delete from prices where ticker in ('MU.US','GOOGL.US');
delete from universe where ticker in ('MU.US','GOOGL.US');
