-- Production Trace → Release Decision — Postgres / Supabase schema.
-- Run this in the Supabase SQL editor (or psql) before pointing the app
-- at a real SUPABASE_URL. The app auto-falls back to in-memory storage
-- when SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured.

create extension if not exists pgcrypto; -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- scenarios: one captured (or simulated) production trace per row.
-- ---------------------------------------------------------------------------
create table if not exists scenarios (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  description   text default '',
  source_type   text default 'simulated_production_capture',
  ai_ops_spec   jsonb not null,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create index if not exists scenarios_created_at_idx
  on scenarios (created_at desc);

-- ---------------------------------------------------------------------------
-- trace_events: ordered agent/tool events belonging to a scenario.
-- ---------------------------------------------------------------------------
create table if not exists trace_events (
  id              uuid primary key default gen_random_uuid(),
  scenario_id     uuid not null references scenarios(id) on delete cascade,
  sequence_number int not null,
  agent_name      text not null,
  event_type      text not null,
  input           jsonb,
  output          jsonb,
  metadata        jsonb,
  timestamp       timestamptz
);

create index if not exists trace_events_scenario_seq_idx
  on trace_events (scenario_id, sequence_number);

-- ---------------------------------------------------------------------------
-- evaluation_runs: baseline or simulated_replay evaluations of a scenario.
-- ---------------------------------------------------------------------------
create table if not exists evaluation_runs (
  id                 uuid primary key default gen_random_uuid(),
  scenario_id        uuid references scenarios(id) on delete cascade,
  run_type           text check (run_type in ('baseline', 'simulated_replay')),
  change_type        text,
  change_description text,
  metrics            jsonb,
  issues             jsonb,
  overall_score      numeric,
  readiness_status   text,
  is_simulation      boolean default true,
  simulation_note    text,
  created_at         timestamptz default now()
);

create index if not exists evaluation_runs_scenario_created_idx
  on evaluation_runs (scenario_id, created_at);

-- ---------------------------------------------------------------------------
-- release_decisions: persisted baseline-vs-replay comparison decisions.
-- ---------------------------------------------------------------------------
create table if not exists release_decisions (
  id                uuid primary key default gen_random_uuid(),
  scenario_id       uuid references scenarios(id) on delete cascade,
  baseline_run_id   uuid references evaluation_runs(id) on delete cascade,
  comparison_run_id uuid references evaluation_runs(id) on delete cascade,
  readiness_status  text,
  improvements      jsonb,
  regressions       jsonb,
  remaining_risks   jsonb,
  deltas            jsonb,
  rationale         text,
  recommendation    text,
  recommendation_summary text,
  thresholds        jsonb,
  created_at        timestamptz default now()
);

-- Idempotent backfill for databases where the table already existed without
-- this column (matches _insert_decision()'s `recommendation_summary` key).
alter table release_decisions add column if not exists recommendation_summary text;

create index if not exists release_decisions_scenario_idx
  on release_decisions (scenario_id);

-- ---------------------------------------------------------------------------
-- Row Level Security.
-- The backend authenticates with the service_role key, which BYPASSES RLS.
-- RLS is enabled so anon/authenticated keys get no access by default; the
-- permissive policies below are placeholders documenting service_role usage.
-- ---------------------------------------------------------------------------
alter table scenarios        enable row level security;
alter table trace_events     enable row level security;
alter table evaluation_runs  enable row level security;
alter table release_decisions enable row level security;

-- service_role policies: service_role BYPASSES RLS, so these are documentation
-- only, but must be scoped with `to service_role` — without that clause they
-- would apply to public (anon/authenticated) and neutralize RLS default-deny,
-- granting anyone with the anon key full read/write. Anon/authenticated remain
-- denied because no policies are defined for them.
drop policy if exists "service_role_all_scenarios"  on scenarios;
drop policy if exists "service_role_all_trace_events" on trace_events;
drop policy if exists "service_role_all_runs"       on evaluation_runs;
drop policy if exists "service_role_all_decisions"  on release_decisions;

create policy "service_role_all_scenarios"  on scenarios        to service_role for all using (true) with check (true);
create policy "service_role_all_trace_events" on trace_events   to service_role for all using (true) with check (true);
create policy "service_role_all_runs"       on evaluation_runs  to service_role for all using (true) with check (true);
create policy "service_role_all_decisions"  on release_decisions to service_role for all using (true) with check (true);
