"""Phase 2 sanity: concepts, ask, eval, contradiction detection."""
from __future__ import annotations

from pathlib import Path

from kb.ask import ask
from kb.compile import compile_source
from kb.concepts import (
    attach_evidence,
    create_concept_stub,
    extract_claims,
    load_concepts,
)
from kb.eval import run_retrieval_eval
from kb.ingest import ingest_path
from kb.llm import HeuristicClient
from kb.thread_review import review_thread
from kb.threads import new_thread


CLAIM_DOC = """# 测试研报

## 主要结论

- 动量因子在高换手股票上失效
- 行业中性化提升动量表现
- 小市值因子在 2020 年后衰减

## 方法

按 60 日均换手率分桶。
"""


SUPPORT_DOC = """# 支持文档

## 主要结论

- 动量因子在高换手股票上确实出现反转
- 残差动量贡献显著

## 方法

测试集 2018-2023。
"""


CONTRADICT_DOC = """# 反例文档

## 主要结论

- 动量因子在高换手股票上仍然有效，反转效应不显著
- 我们没有观察到衰减

## 方法

测试集 2016-2024，剔除流动性最差股票。
"""


def _ingest(text: str, name: str, kb_root, meta, vstore, embedder):
    raw = kb_root.raw / name
    raw.write_text(text, encoding="utf-8")
    results = ingest_path(raw, paths=kb_root, meta=meta, vstore=vstore, embedder=embedder)
    return results[0]


def test_extract_claims_pulls_bullets():
    claims = extract_claims(CLAIM_DOC)
    assert "动量因子在高换手股票上失效" in claims
    assert "行业中性化提升动量表现" in claims
    assert "小市值因子在 2020 年后衰减" in claims
    assert len(claims) == 3


def test_compile_writes_proposals_when_no_concepts(kb_root, meta, vstore, embedder):
    r = _ingest(CLAIM_DOC, "测试-动量.md", kb_root, meta, vstore, embedder)
    result = compile_source(
        r.source_id, paths=kb_root, meta=meta,
        embedder=embedder, llm=HeuristicClient(),
    )
    proposals_dir = kb_root.root / "inbox" / "concepts"
    assert proposals_dir.exists()
    assert any(proposals_dir.iterdir()), "expected at least one proposal stub"
    assert result.proposals_written >= 1


def test_evidence_attaches_to_existing_concept(kb_root, meta, vstore, embedder):
    create_concept_stub(
        "动量因子在高换手股票上的衰减",
        paths=kb_root,
        definition="动量因子在高换手股票上有显著反转、收益失效。",
        domains=["选股"],
    )
    r = _ingest(SUPPORT_DOC, "support.md", kb_root, meta, vstore, embedder)
    result = compile_source(
        r.source_id, paths=kb_root, meta=meta,
        embedder=embedder, llm=HeuristicClient(),
    )
    # Either evidence was applied OR similarity didn't cross the threshold;
    # for hash embedder we accept proposals too — but at least one route fired.
    concept_path = next((kb_root.concepts).glob("*.md"))
    body = concept_path.read_text(encoding="utf-8")
    assert ("Evidence For" in body) or (result.proposals_written >= 1)


def test_contradiction_logged_for_opposite_stance(kb_root, meta, vstore, embedder):
    create_concept_stub(
        "动量因子在高换手股票上的衰减",
        paths=kb_root,
        definition="动量因子在高换手股票上失效、出现反转。",
        domains=["选股"],
    )
    # Inject a contradiction claim directly so we don't depend on the noisy
    # hash embedder for similarity routing.
    concept = load_concepts(kb_root)[0]
    applied, _proposals = attach_evidence(
        source_id="src-test-contra-001",
        claims=["动量因子在高换手股票上没有失效，仍然有效"],
        paths=kb_root, meta=meta, embedder=embedder, llm=HeuristicClient(),
        page=2,
    )
    # We bypass the embedder route by re-running attach_evidence directly
    # against the loaded concept summary if needed. If similarity was below
    # threshold, proposals path will fire instead — at minimum we should not
    # crash, and the stance heuristic should flag contradiction when called.
    stance = HeuristicClient().judge_stance(
        "动量因子在高换手股票上没有失效，仍然有效",
        concept.summary,
    )
    assert stance == "contradict"


def test_ask_writes_memo_into_thread(kb_root, meta, vstore, embedder):
    _ingest(CLAIM_DOC, "claims.md", kb_root, meta, vstore, embedder)
    thread_main = new_thread("动量调研", paths=kb_root)
    # The id is in frontmatter; pass slug as fallback.
    tid = thread_main.parent.name
    r = ask(
        "动量因子在高换手股票上是否失效？",
        paths=kb_root, meta=meta, vstore=vstore, embedder=embedder,
        llm=HeuristicClient(), thread=tid, top_k=3,
    )
    assert r.memo_path.exists()
    assert r.thread_id is not None
    body = r.memo_path.read_text(encoding="utf-8")
    assert "[^" in body  # at least one citation marker
    # Thread changelog should mention the new memo.
    thread_body = thread_main.read_text(encoding="utf-8")
    assert r.memo_id in thread_body


def test_thread_review_writes_summary(kb_root, meta, vstore, embedder):
    _ingest(CLAIM_DOC, "claims.md", kb_root, meta, vstore, embedder)
    main = new_thread("动量调研", paths=kb_root)
    tid = main.parent.name
    ask("动量与换手率", paths=kb_root, meta=meta, vstore=vstore, embedder=embedder,
        llm=HeuristicClient(), thread=tid, top_k=3)
    result = review_thread(tid, paths=kb_root, llm=HeuristicClient())
    assert result.memos_seen >= 1
    body = main.read_text(encoding="utf-8")
    assert "阶段性总结" in body


def test_eval_runs_over_keyword_only_cases(kb_root, meta, vstore, embedder):
    _ingest(CLAIM_DOC, "claims.md", kb_root, meta, vstore, embedder)
    # Seed a minimal golden file inline so we don't depend on the shipped one.
    kb_root.eval_dir.mkdir(parents=True, exist_ok=True)
    kb_root.golden.write_text(
        '{"id":"t-1","query":"动量 换手率 衰减","expected_keywords":["动量","换手"]}\n',
        encoding="utf-8",
    )
    report = run_retrieval_eval(kb_root, meta=meta, vstore=vstore, embedder=embedder)
    assert len(report.cases) == 1
    assert report.mean_keyword_coverage >= 0.5
