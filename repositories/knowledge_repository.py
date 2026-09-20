"""Knowledge-base repository for scenario, role and tutorial facts."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from .base import DatabaseRepository


class KnowledgeRepository(DatabaseRepository):
    def search(self, query: str, scenario_name: str | None = None,
               role_name: str | None = None, limit: int = 8):
        query = (query or "").strip()
        if not query:
            return []
        with self.SessionLocal() as session:
            rows = session.execute(text("""
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
                  )
                  and (:scenario is null or d.scope = 'global'
                       or d.scenario_name = :scenario)
                  and (:role is null or d.scope = 'global'
                       or d.role_name = :role)
                order by
                  case when d.scope='role' and :role is not null and d.role_name=:role then 0
                       when d.scope='scenario' and :scenario is not null and d.scenario_name=:scenario then 1
                       when d.scope='global' then 2 else 3 end,
                  d.updated_at desc
                limit :limit
            """), {
                "q": f"%{query}%", "scenario": scenario_name,
                "role": role_name, "limit": max(1, min(int(limit), 20)),
            }).mappings().all()
            return [dict(row) for row in rows]

    def get_context(self, query: str, scenario_name: str | None = None,
                    role_name: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
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
