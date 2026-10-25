create table if not exists people (
  id text primary key,
  name text not null,
  first_met date not null default current_date,
  selfie bytea,
  delete_token text not null
);

create table if not exists faces (
  person_id text not null references people(id) on delete cascade,
  print vector(512) not null
);

create table if not exists consents (
  person_id text primary key references people(id) on delete cascade,
  granted_at timestamptz not null default now(),
  expires_at date not null,
  scope text[] not null default '{facePrint,name,voice,notes,facts}'
);

create table if not exists notes (
  id bigserial primary key,
  person_id text not null references people(id) on delete cascade,
  text text not null,
  created_at timestamptz not null default now()
);

-- one row per person per call: Muse Spark's summary when the call ended
create table if not exists encounters (
  id bigserial primary key,
  person_id text not null references people(id) on delete cascade,
  met_at timestamptz not null,
  about text not null,
  last_time text not null
);

-- who they are to the user ("Your team lead"); a role the user typed is never replaced by Muse's suggestion
alter table people add column if not exists role text not null default '';
alter table people add column if not exists role_source text not null default 'muse';

-- what each call was about, whether the person spoke in it, and whether Muse called it "work" or "personal" ("" = unsure)
alter table encounters add column if not exists topic text not null default '';
alter table encounters add column if not exists spoke boolean not null default false;
alter table encounters add column if not exists context text not null default '';

-- one line about the first call together; written once
alter table people add column if not exists how_met text not null default '';

-- plain things Muse noticed a person say about themselves ("Loves F1"); the user's own notes stay in `notes`
create table if not exists facts (
  id bigserial primary key,
  person_id text not null references people(id) on delete cascade,
  text text not null,
  created_at timestamptz not null default now()
);
create unique index if not exists facts_once on facts (person_id, lower(text));

-- what a person agreed to be kept: face print, name, voice, notes and Muse's facts. `connector` (letting the Muse app read them)
-- is added only when the person ticks it; no selfie is kept. Old rows only lose `selfie`: they never saw the newer wording.
alter table consents alter column scope set default '{facePrint,name,voice,notes,facts}';
update consents set scope = array_remove(scope, 'selfie') where 'selfie' = any(scope);

-- places and events from the AI answers that concern a person (Muse decides who), for their file
create table if not exists mentions (
  id bigserial primary key,
  person_id text not null references people(id) on delete cascade,
  text text not null,
  created_at timestamptz not null default now()
);
create unique index if not exists mentions_once on mentions (person_id, lower(text));

-- delete tokens are stored as sha256 hex; this upgrades older plain tokens (22 characters) once and does nothing after
update people set delete_token = encode(sha256(convert_to(delete_token, 'UTF8')), 'hex') where length(delete_token) <> 64;

-- Tiger Data (TimescaleDB): encounters are a time series, so make them a hypertable on met_at. A hypertable's unique keys
-- must include the time column, hence the primary key change. Plain Postgres has no timescaledb: nothing happens.
do $$
declare
  pk record;
begin
  if exists (select 1 from pg_extension where extname = 'timescaledb') then
    if not exists (select 1 from timescaledb_information.hypertables where hypertable_name = 'encounters') then
      for pk in select conname from pg_constraint where conrelid = 'encounters'::regclass and contype = 'p' loop
        execute format('alter table encounters drop constraint %I', pk.conname);  -- whatever the constraint is called
      end loop;
      alter table encounters add primary key (id, met_at);
      perform create_hypertable('encounters', 'met_at', migrate_data => true);
    end if;
  end if;
end $$;
