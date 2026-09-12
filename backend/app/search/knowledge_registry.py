"""Owner-scoped immutable research revisions with atomic compare-and-swap heads."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from typing import Any, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract, Evidence
from app.preprocessing.storage import canonical, digest
from .knowledge_contracts import ScientificKnowledge


class KnowledgeEdit(Contract):
    kind: Literal['source', 'rule']
    id: str = Field(min_length=1)
    status: Literal['active', 'suspended', 'withdrawn']
    reason: str = Field(min_length=1)
    evidence: Evidence
    observed_at: datetime
    replacement: dict[str, Any] | None = None

    @model_validator(mode='after')
    def dated_review(self):
        if self.observed_at.tzinfo is None:
            raise ValueError('knowledge review time requires an explicit timezone')
        return self


class KnowledgeUpdate(Contract):
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    changes: list[KnowledgeEdit] = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def unique_targets(self):
        if len({(c.kind,c.id) for c in self.changes}) != len(self.changes):
            raise ValueError('a revision may change each source/rule only once')
        return self


class KnowledgeRebase(Contract):
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    catalog: ScientificKnowledge
    reason: str = Field(min_length=1)
    evidence: Evidence
    observed_at: datetime


def inactive(book):
    sources = {s['id'] for s in book['sources'] if unavailable(s)}
    rules = {r['id'] for r in book['rules'] if unavailable(r) or sources.intersection(r['source_ids'])}
    return sources, rules


def unavailable(row):
    return row.get('status','active') != 'active' or row.get('binding_review_required',False)


def mark_binding_changes(book, baseline):
    """Edited prose cannot silently certify the compiled bindings derived from it."""
    metadata={'status','status_reason','status_observed_at','status_evidence','binding_review_required','binding_original_url'}
    for kind in ('sources','rules'):
        original={r['id']:{k:v for k,v in r.items() if k not in metadata} for r in baseline[kind]}
        for row in book[kind]:
            row['binding_review_required']={k:v for k,v in row.items() if k not in metadata} != original.get(row['id'])
            if kind=='sources':
                old_url=original.get(row['id'],{}).get('url')
                row['binding_original_url']=old_url if old_url!=row['url'] else None
    return book


def normalized_url(url):
    from urllib.parse import urlsplit, urlunsplit
    parts=urlsplit(url)
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/'),parts.query,''))


def method_issues(method, book):
    blocked_sources={normalized_url(url):s for s in book['sources'] if unavailable(s)
                     for url in (s['url'],s.get('binding_original_url')) if url}
    issues=[]
    for evidence in method.evidence:
        source=blocked_sources.get(normalized_url(evidence.source_url))
        if source:
            issues.append(dict(severity='blocking',code='SOURCE_KNOWLEDGE_INACTIVE',
                message=f"来源 {source['id']} 当前停用或变更后尚待重新核对执行绑定：{source.get('status_reason') or 'binding review required'}"))
    _, inactive_rules=inactive(book)
    for row in method.lineage.get('rule_audit',{}).get('decisions',[]):
        affected=inactive_rules.intersection(row.get('knowledge_rule_ids',[]))
        if affected and row.get('status') not in ('revoked','not_applicable','exception_applies') and row.get('origin') not in ('implementation','mathematical'):
            issues.append(dict(severity='blocking',code='RULE_KNOWLEDGE_INACTIVE',
                message='方法所用研究规则当前失效：'+', '.join(sorted(affected))))
    return issues


def verify_snapshot(snapshot):
    if snapshot.get('sha256') != digest({k:v for k,v in snapshot.items() if k!='sha256'}):
        raise ValueError('frozen knowledge revision checksum mismatch')
    ScientificKnowledge.model_validate(snapshot['catalog'])
    return deepcopy(snapshot)


def apply_to_space(value, book):
    sources, rules=inactive(book)
    blocked=[]
    for op in value['operators']:
        evidence=set(op.get('evidence_ids',[]))
        evidence.update(e for domain in op.get('domains',{}).values() for e in domain.get('evidence_ids',[]))
        if evidence & sources:
            op.update(status='blocked',status_reason='当前来源状态禁止使用这一研究派生算子/参数域：'+', '.join(sorted(evidence & sources)))
            blocked.append(op['id'])
    retired, retained=[] ,[]
    for prior in value['priors']:
        affected=(set(prior.get('evidence_ids',[])) & sources) or (set(prior.get('knowledge_rule_ids',[])) & rules)
        if not affected:
            continue
        if prior['origin'] in ('implementation','mathematical'):
            prior['change_reason']='关联研究状态失效；此原生实现/数学约束有独立依据，继续保留。'
            retained.append(prior['id'])
        else:
            prior.update(status='revoked' if prior['strength']=='soft' else 'suspended',
                change_reason='依赖的来源/研究规则当前失效：'+', '.join(sorted(affected)))
            retired.append(prior['id'])
    removed=[m['id'] for m in value['methods'] if set(m.get('evidence_ids',[])) & sources
             or any(n['operator'] in blocked for n in m['recipe']['nodes'])]
    value['methods']=[m for m in value['methods'] if m['id'] not in removed]
    value['knowledge_effects']=dict(inactive_source_ids=sorted(sources),inactive_rule_ids=sorted(rules),
        blocked_operator_ids=blocked,removed_seed_ids=removed,disabled_prior_ids=retired,
        independent_contracts_retained=retained)
    return value


def impact(before, after):
    a_sources, a_rules = inactive(before)
    b_sources, b_rules = inactive(after)
    old_sources = {s['id']:s for s in before['sources']}
    old_rules = {r['id']:r for r in before['rules']}
    changed_sources = {s['id'] for s in after['sources'] if s != old_sources.get(s['id'])}
    changed_rules = {r['id'] for r in after['rules'] if r != old_rules.get(r['id'])}
    affected = changed_rules | {r['id'] for r in after['rules'] if changed_sources.intersection(r['source_ids'])}
    return dict(changed_source_ids=sorted(changed_sources), changed_rule_ids=sorted(changed_rules),
        removed_source_ids=sorted(old_sources.keys()-{s['id'] for s in after['sources']}),
        removed_rule_ids=sorted(old_rules.keys()-{r['id'] for r in after['rules']}),
        affected_rule_ids=sorted(affected), newly_inactive_source_ids=sorted(b_sources-a_sources),
        newly_inactive_rule_ids=sorted(b_rules-a_rules), reactivated_rule_ids=sorted(a_rules-b_rules),
        affected_parameter_ids=[p['id'] for p in after['parameters'] if changed_sources.intersection(p['source_ids'])],
        affected_operator_pairs=[[p['a'],p['b']] for p in after['pair_coverage'] if affected.intersection(p['rule_ids'])],
        policy='new runs use this revision; existing frozen artifacts remain unchanged')


class KnowledgeRegistry:
    def __init__(self, root, catalog):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root/'knowledge.db'
        self.catalog = ScientificKnowledge.model_validate(catalog).model_dump(mode='json')
        self.base_hash = digest(self.catalog)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS snapshots(
                owner TEXT NOT NULL, sha256 TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(owner,sha256));
                CREATE TABLE IF NOT EXISTS heads(owner TEXT PRIMARY KEY, sha256 TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _base(self):
        return dict(schema_version='knowledge-revision-1', revision=0, parent_sha256=None,
            base_catalog_sha256=self.base_hash, catalog=self.catalog, changes=[], impact=None, created_at=None)

    def _get(self, db, owner, reference=None):
        if reference is None:
            head = db.execute('SELECT sha256 FROM heads WHERE owner=?',(owner,)).fetchone()
            if head is None:
                value = self._base()
                return {**value,'sha256':digest(value)}
            reference = head['sha256']
        row = db.execute('SELECT body FROM snapshots WHERE owner=? AND sha256=?',(owner,reference)).fetchone()
        if row is None:
            value = self._base()
            if digest(value) == reference:
                return {**value,'sha256':reference}
            raise KeyError('knowledge revision not found')
        value = json.loads(row['body'])
        if digest(value) != reference:
            raise ValueError('knowledge revision checksum mismatch')
        ScientificKnowledge.model_validate(value['catalog'])
        return {**value,'sha256':reference}

    def rebase(self, owner, request):
        request = KnowledgeRebase.model_validate(request)
        if request.observed_at.tzinfo is None:
            raise ValueError('knowledge review time requires an explicit timezone')
        book = request.catalog.model_dump(mode='json')
        for key in book.keys()-{'sources','rules'}:
            if book[key] != self.catalog[key]:
                raise ValueError('rebase must retain the current bundled operator/parameter/coverage contract')
        for key in ('sources','rules'):
            if {r['id'] for r in book[key]} != {r['id'] for r in self.catalog[key]}:
                raise ValueError('rebase requires the current bundled source/rule identities')
        book=mark_binding_changes(book,self.catalog)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._get(db,owner)
            if previous['sha256'] != request.expected_sha256:
                raise ValueError('knowledge head changed; review the current revision before rebasing')
            value = dict(schema_version='knowledge-revision-1',revision=previous['revision']+1,
                parent_sha256=previous['sha256'],base_catalog_sha256=self.base_hash,catalog=book,
                changes=[dict(kind='explicit_catalog_rebase',reason=request.reason,
                    evidence=request.evidence.model_dump(mode='json'),observed_at=request.observed_at.isoformat())],
                impact=impact(previous['catalog'],book),created_at=datetime.now(timezone.utc).isoformat())
            reference=digest(value)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',
                (owner,previous['sha256'],canonical({k:v for k,v in previous.items() if k!='sha256'})))
            db.execute('INSERT INTO snapshots VALUES(?,?,?)',(owner,reference,canonical(value)))
            db.execute('INSERT INTO heads VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET sha256=excluded.sha256',(owner,reference))
        return {**value,'sha256':reference}

    def get(self, owner, reference=None, *, require_current=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            value = self._get(db,owner,reference)
            if reference is None:
                db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',
                    (owner,value['sha256'],canonical({k:v for k,v in value.items() if k!='sha256'})))
                db.execute('INSERT OR IGNORE INTO heads VALUES(?,?)',(owner,value['sha256']))
        if require_current and value['base_catalog_sha256'] != self.base_hash:
            raise ValueError('bundled knowledge catalog changed; explicit revision rebase is required')
        return deepcopy(value)

    def update(self, owner, request):
        request = KnowledgeUpdate.model_validate(request)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._get(db,owner)
            if previous['sha256'] != request.expected_sha256:
                raise ValueError('knowledge head changed; review the current revision before applying this update')
            if previous['base_catalog_sha256'] != self.base_hash:
                raise ValueError('bundled knowledge catalog changed; explicit revision rebase is required')
            book = deepcopy(previous['catalog'])
            for change in request.changes:
                rows = book['sources' if change.kind=='source' else 'rules']
                original = next((r for r in rows if r['id']==change.id),None)
                if original is None:
                    raise ValueError('knowledge update references an unknown source/rule')
                revised = deepcopy(change.replacement) if change.replacement is not None else deepcopy(original)
                if revised.get('id') != change.id:
                    raise ValueError('replacement cannot change the source/rule identity')
                revised.update(status=change.status,status_reason=change.reason,
                    status_observed_at=change.observed_at.isoformat(),status_evidence=change.evidence.model_dump(mode='json'))
                rows[rows.index(original)] = revised
            book = ScientificKnowledge.model_validate(mark_binding_changes(book,self.catalog)).model_dump(mode='json')
            value = dict(schema_version='knowledge-revision-1', revision=previous['revision']+1,
                parent_sha256=previous['sha256'],base_catalog_sha256=self.base_hash,catalog=book,
                changes=[c.model_dump(mode='json') for c in request.changes],impact=impact(previous['catalog'],book),
                created_at=datetime.now(timezone.utc).isoformat())
            reference = digest(value)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',
                (owner,previous['sha256'],canonical({k:v for k,v in previous.items() if k!='sha256'})))
            db.execute('INSERT INTO snapshots VALUES(?,?,?)',(owner,reference,canonical(value)))
            db.execute('INSERT INTO heads VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET sha256=excluded.sha256',(owner,reference))
        return {**value,'sha256':reference}
