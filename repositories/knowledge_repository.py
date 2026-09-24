"""Knowledge-base repository for scenario, role and tutorial facts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from .base import DatabaseRepository


class KnowledgeRepository(DatabaseRepository):
    @staticmethod
    def ensure_schema() -> None:
        """Create the KB tables on legacy production databases that predate the KB migration."""
        with KnowledgeRepository().SessionLocal() as session:
            session.execute(text("""
                create table if not exists public.mafia_knowledge_categories (
                    id bigserial primary key,
                    slug text unique not null,
                    title text not null,
                    description text,
                    sort_order int not null default 0,
                    created_at timestamptz not null default now()
                )
            """))
            session.execute(text("""
                create table if not exists public.mafia_knowledge_documents (
                    id bigserial primary key,
                    category_id bigint references public.mafia_knowledge_categories(id) on delete set null,
                    title text not null,
                    slug text unique,
                    content text not null default '',
                    scope text not null default 'global',
                    scenario_name text,
                    role_name text,
                    status text not null default 'draft',
                    source_type text not null default 'internal',
                    source_url text,
                    source_title text,
                    confidence text not null default 'unverified',
                    is_active boolean not null default true,
                    metadata jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
            """))
            session.execute(text("""
                create index if not exists idx_mafia_knowledge_scope
                on public.mafia_knowledge_documents(scope, scenario_name, role_name)
            """))
            session.execute(text("""
                create index if not exists idx_mafia_knowledge_status
                on public.mafia_knowledge_documents(status, is_active)
            """))
            session.execute(text("""
                insert into public.mafia_knowledge_categories(slug,title,sort_order)
                values
                  ('scenarios','سناریوها',1),
                  ('roles','نقش‌ها',2),
                  ('tutorials','آموزش‌ها',3),
                  ('faq','پرسش‌های متداول',4),
                  ('sources','منابع',5)
                on conflict(slug) do nothing
            """))
            session.commit()

            # Legacy production may have the KB tables but no seed data. Bundle
            # the canonical 118 documents so the runtime DB gets the same
            # verified/published knowledge that was collected in the main DB.
            count = session.execute(
                text("select count(*) from public.mafia_knowledge_documents")
            ).scalar_one()
            if int(count) == 0:
                seed_path = Path(__file__).resolve().parents[1] / "runtime" / "knowledge_seed.json"
                if seed_path.exists():
                    try:
                        seed_rows = json.loads(seed_path.read_text(encoding="utf-8"))
                    except Exception:
                        seed_rows = []
                    for item in seed_rows:
                        session.execute(text("""
                            insert into public.mafia_knowledge_documents
                            (category_id,title,content,scope,scenario_name,role_name,status,
                             source_type,source_url,source_title,confidence,metadata)
                            values (
                              (select id from public.mafia_knowledge_categories
                               where slug = case
                                 when :scope='scenario' then 'scenarios'
                                 when :scope='role' then 'roles'
                                 when :scope='tutorial' then 'tutorials'
                                 when :scope='faq' then 'faq'
                                 else 'sources' end limit 1),
                              :title,:content,:scope,:scenario_name,:role_name,:status,
                              :source_type,:source_url,:source_title,:confidence,
                              cast(:metadata as jsonb)
                            )
                        """), {
                            "title": item.get("title") or "",
                            "content": item.get("content") or "",
                            "scope": item.get("scope") or "global",
                            "scenario_name": item.get("scenario_name"),
                            "role_name": item.get("role_name"),
                            "status": item.get("status") or "draft",
                            "source_type": item.get("source_type") or "internal",
                            "source_url": item.get("source_url"),
                            "source_title": item.get("source_title"),
                            "confidence": item.get("confidence") or "unverified",
                            "metadata": json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        })
                    session.commit()

    def _ensure_schema(self) -> None:
        self.ensure_schema()

    def search(self, query: str, scenario_name: str | None = None,
               role_name: str | None = None, limit: int = 8):
        query = (query or "").strip()
        if not query:
            return []
        # Normalize the most common Persian/Arabic keyboard variants so a
        # question still matches documents entered with a different keyboard.
        normalized = (
            query.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
                 .replace("ۀ", "ه").replace("ة", "ه")
        )
        tokens = [t for t in normalized.replace("؟", " ").replace("?", " ").split()
                  if len(t.strip()) >= 3]
        tokens = list(dict.fromkeys(tokens[:12]))
        with self.SessionLocal() as session:
            params = {
                "q": f"%{normalized}%",
                "scenario": scenario_name,
                "role": role_name,
                "limit": max(1, min(int(limit), 20)),
            }
            token_clauses = []
            score_terms = []
            for i, token in enumerate(tokens):
                key = f"t{i}"
                params[key] = f"%{token}%"
                token_clauses.append(
                    f"(d.title ilike :{key} or d.content ilike :{key} "
                    f"or coalesce(d.role_name,'') ilike :{key} "
                    f"or coalesce(d.scenario_name,'') ilike :{key})"
                )
                score_terms.append(
                    f"(case when d.title ilike :{key} or d.content ilike :{key} "
                    f"or coalesce(d.role_name,'') ilike :{key} "
                    f"or coalesce(d.scenario_name,'') ilike :{key} then 1 else 0 end)"
                )
            token_filter = " or ".join(token_clauses) or "false"
            score_expr = " + ".join(score_terms) or "0"
            rows = session.execute(text(f"""
                select d.id, d.title, d.content, d.scope, d.scenario_name,
                       d.role_name, d.status, d.source_type, d.source_url,
                       d.confidence, d.metadata
                from public.mafia_knowledge_documents d
                where d.is_active = true
                  and d.status in ('verified','published')
                  and (
                    d.title ilike :q or d.content ilike :q
                    or coalesce(d.role_name,'') ilike :q
                    or coalesce(d.scenario_name,'') ilike :q
                    or {token_filter}
                  )
                  and (:scenario is null or d.scope = 'global'
                       or d.scenario_name = :scenario)
                  and (:role is null or d.scope = 'global'
                       or d.role_name = :role)
                order by
                  ({score_expr}) desc,
                  case
                    when d.source_type like '%internal%' and d.scope='role'
                         and :role is not null and d.role_name=:role then 0
                    when d.source_type like '%internal%' and d.scope='scenario'
                         and :scenario is not null and d.scenario_name=:scenario then 1
                    when d.source_type like '%internal%' and d.scope='global' then 2
                    when d.scope='role' and :role is not null and d.role_name=:role then 3
                    when d.scope='scenario' and :scenario is not null and d.scenario_name=:scenario then 4
                    else 5
                  end,
                  d.updated_at desc
                limit :limit
            """), params).mappings().all()
            return [dict(row) for row in rows]

    def find_explicit_context(self, query: str, limit: int = 12) -> dict[str, list[str]]:
        """Find role/scenario names explicitly mentioned in the user's question.

        This prevents the generic token search from selecting an unrelated
        scenario document merely because a common word appears in its content.
        """
        normalized = (
            (query or "").strip()
            .replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
            .replace("ۀ", "ه").replace("ة", "ه")
        )
        if not normalized:
            return {"roles": [], "scenarios": []}
        with self.SessionLocal() as session:
            rows = session.execute(text("""
                select scope, scenario_name, role_name, title
                from (
                    select distinct scope, scenario_name, role_name, title
                    from public.mafia_knowledge_documents
                    where is_active=true
                      and status in ('verified','published')
                      and (
                        (role_name is not null and :q ilike ('%' || role_name || '%'))
                        or
                        (scenario_name is not null and :q ilike ('%' || scenario_name || '%'))
                      )
                ) matched
                order by
                  case when role_name is not null then length(role_name) else 0 end desc,
                  case when scenario_name is not null then length(scenario_name) else 0 end desc
                limit :limit
            """), {"q": normalized, "limit": max(1, min(int(limit), 30))}).mappings().all()
        roles, scenarios = [], []
        for row in rows:
            role = str(row["role_name"] or "").strip()
            scenario = str(row["scenario_name"] or "").strip()
            if role and role not in roles:
                roles.append(role)
            if scenario and scenario not in scenarios:
                scenarios.append(scenario)
        return {"roles": roles, "scenarios": scenarios}

    def get_context(self, query: str, scenario_name: str | None = None,
                    role_name: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        # Production Vercel workers can start against the legacy database before
        # any KB request has initialized its schema. Ensure the schema/seed exists
        # before the first SELECT instead of letting the first question fail with
        # UndefinedTable.
        self.ensure_schema()
        rows = self.search(query, scenario_name, role_name, limit)
        return rows

    def add_document(self, *, title: str, content: str, scope: str = "global",
                     scenario_name: str | None = None, role_name: str | None = None,
                     status: str = "draft", source_type: str = "internal",
                     source_url: str | None = None, source_title: str | None = None,
                     confidence: str = "unverified", metadata: dict | None = None):
        with self.SessionLocal() as session:
            row = session.execute(text("""
                insert into public.mafia_knowledge_documents
                (category_id,title,slug,content,scope,scenario_name,role_name,status,
                 source_type,source_url,source_title,confidence,metadata)
                values (
                  (select id from public.mafia_knowledge_categories
                   where slug = case when :scope='scenario' then 'scenarios'
                                     when :scope='role' then 'roles'
                                     when :scope='tutorial' then 'tutorials'
                                     when :scope='faq' then 'faq' else 'sources' end
                   limit 1),
                  :title, null, :content, :scope, :scenario_name, :role_name,
                  :status, :source_type, :source_url, :source_title, :confidence,
                  cast(:metadata as jsonb)
                ) returning id
            """), {
                "title": title, "content": content, "scope": scope,
                "scenario_name": scenario_name, "role_name": role_name,
                "status": status, "source_type": source_type,
                "source_url": source_url, "source_title": source_title,
                "confidence": confidence,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            }).scalar_one()
            session.commit()
            return int(row)
