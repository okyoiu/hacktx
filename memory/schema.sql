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
  scope text[] not null default '{facePrint,selfie,notes}'
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

-- delete tokens are stored as sha256 hex; this upgrades older plain tokens (22 characters) once and does nothing after
update people set delete_token = encode(sha256(convert_to(delete_token, 'UTF8')), 'hex') where length(delete_token) <> 64;
