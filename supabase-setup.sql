-- À exécuter UNE FOIS dans le SQL Editor du projet Supabase personnel.
begin;
create table if not exists public.startdeck_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null check (jsonb_typeof(data) = 'object'),
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now()
);
alter table public.startdeck_state enable row level security;
revoke all on public.startdeck_state from anon;
grant select, insert, update on public.startdeck_state to authenticated;
drop policy if exists startdeck_owner on public.startdeck_state;
create policy startdeck_owner on public.startdeck_state
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create or replace function public.startdeck_save(expected_revision bigint, new_data jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  who uuid := auth.uid();
  current_revision bigint;
  next_revision bigint;
begin
  if who is null then raise sqlstate 'PT401' using message = 'Connexion requise'; end if;
  if expected_revision is null or expected_revision < 0 or new_data is null
     or jsonb_typeof(new_data) <> 'object'
     or jsonb_typeof(new_data->'tabs') is distinct from 'array'
     or jsonb_typeof(new_data->'settings') is distinct from 'object'
     or octet_length(new_data::text) > 2097152 then
    raise sqlstate 'PT400' using message = 'Données invalides ou supérieures à 2 Mo';
  end if;
  -- Sérialise aussi la toute première écriture lorsque la ligne n'existe pas.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(who::text, 0));
  select revision into current_revision from public.startdeck_state where user_id = who for update;
  current_revision := coalesce(current_revision, 0);
  if current_revision <> expected_revision then
    raise sqlstate 'PT409' using message = 'Une autre version a été enregistrée';
  end if;
  next_revision := current_revision + 1;
  insert into public.startdeck_state(user_id, data, revision, updated_at)
    values (who, new_data, next_revision, now())
    on conflict (user_id) do update set data = excluded.data,
      revision = excluded.revision, updated_at = excluded.updated_at;
  return jsonb_build_object('revision', next_revision);
end;
$$;
revoke all on function public.startdeck_save(bigint,jsonb) from public, anon;
grant execute on function public.startdeck_save(bigint,jsonb) to authenticated;
commit;
