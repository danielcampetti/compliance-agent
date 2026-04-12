# LGPD Governance System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LGPD-compliant PII masking, audit trail, data retention, privacy consent UI, and governance dashboard to ComplianceAgent so that agent logs never store plain-text CPFs, names, or financial data.

**Architecture:** PII detection runs at the Coordinator layer after each agent returns — user-facing responses are never masked, only the audit log entries. A new `audit_log` table replaces the existing `agent_log` for all new interactions (legacy `agent_log` is preserved). Three `/governance/*` endpoints expose the masked audit trail, dashboard metrics, and retention status.

**Tech Stack:** Python 3.11, FastAPI, SQLite (sqlite3 + WAL mode), pytest-asyncio, vanilla JS (existing frontend)

**Design spec:** `docs/superpowers/specs/2026-04-12-lgpd-governance-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/governance/__init__.py` | Package marker |
| Create | `src/governance/pii_detector.py` | All PII detection + masking logic |
| Create | `src/governance/audit.py` | Session IDs, classification, `log_interaction()` |
| Create | `src/governance/retention.py` | `purge_expired_pii()`, `get_retention_report()` |
| Create | `src/api/governance.py` | `/governance/dashboard`, `/audit-log`, `/retention-report` |
| Modify | `src/database/setup.py` | Add `audit_log` + `governance_daily_stats` tables |
| Modify | `src/agents/coordinator.py` | session_id, `audit.log_interaction()`, new response fields |
| Modify | `src/api/main.py` | Register governance router |
| Modify | `src/api/templates/index.html` | Privacy modal, PII notice, classification badge |
| Modify | `src/agents/coordinator.py` | Remove `_log()`, add `pii_detected`/`data_classification`/`session_id` to response |
| Create | `tests/test_pii_detector.py` | Unit tests for all PII types |
| Create | `tests/test_audit.py` | Unit tests with in-memory DB |
| Create | `tests/test_governance_api.py` | Integration tests via TestClient |
| Modify | `tests/test_coordinator.py` | Update patches after `_log()` removal |
| Modify | `CLAUDE.md` | Document governance system |

---

## Task 1: Bootstrap governance package + write failing PII tests

**Files:**
- Create: `src/governance/__init__.py`
- Create: `tests/test_pii_detector.py`

- [ ] **Step 1: Create the package marker**

```python
# src/governance/__init__.py
```
(empty file)

- [ ] **Step 2: Write the full failing test file**

```python
# tests/test_pii_detector.py
"""Tests for the PII detector module."""
import pytest
from src.governance.pii_detector import (
    PIIType, MaskLevel, PIIMatch,
    detect_pii, mask_text, has_pii, count_pii,
)


class TestCPFDetection:
    def test_formatted_cpf_detected(self):
        matches = detect_pii("CPF do cliente: 123.456.789-09")
        cpf_matches = [m for m in matches if m.type == PIIType.CPF]
        assert len(cpf_matches) == 1
        assert cpf_matches[0].original == "123.456.789-09"

    def test_unformatted_cpf_detected(self):
        matches = detect_pii("CPF: 12345678909")
        assert any(m.type == PIIType.CPF for m in matches)

    def test_cpf_full_mask(self):
        masked, _ = mask_text("CPF: 123.456.789-09", MaskLevel.FULL)
        assert "[CPF_MASCARADO]" in masked
        assert "123.456.789-09" not in masked

    def test_cpf_partial_mask(self):
        masked, _ = mask_text("CPF: 123.456.789-09", MaskLevel.PARTIAL)
        assert "123.456.789-09" not in masked
        assert "[CPF_MASCARADO]" not in masked
        assert "123." in masked  # first group preserved

    def test_cpf_inside_longer_number_not_matched(self):
        # 14-digit number should NOT match as CPF
        matches = detect_pii("Número: 12345678901234")
        cpf_matches = [m for m in matches if m.type == PIIType.CPF]
        assert len(cpf_matches) == 0


class TestNameDetection:
    def test_multi_word_name_detected(self):
        matches = detect_pii("Cliente Roberto Alves Costa realizou depósito")
        name_matches = [m for m in matches if m.type == PIIType.NAME]
        assert len(name_matches) == 1
        assert name_matches[0].original == "Roberto Alves Costa"

    def test_single_brazilian_first_name_detected(self):
        matches = detect_pii("Transação de João registrada ontem")
        assert any(m.type == PIIType.NAME for m in matches)

    def test_coaf_not_detected_as_name(self):
        matches = detect_pii("Reportado ao COAF conforme regulamentação")
        assert not any(m.type == PIIType.NAME for m in matches)

    def test_bcb_not_detected_as_name(self):
        matches = detect_pii("Circular do BCB publicada em 2023")
        assert not any(m.type == PIIType.NAME for m in matches)

    def test_resolucao_cmn_not_detected_as_name(self):
        matches = detect_pii("Resolução CMN 5.274/2025 estabelece prazos")
        assert not any(m.type == PIIType.NAME for m in matches)

    def test_name_full_mask(self):
        masked, _ = mask_text("Cliente Roberto Alves Costa", MaskLevel.FULL)
        assert "[NOME_MASCARADO]" in masked
        assert "Roberto Alves Costa" not in masked

    def test_name_partial_mask(self):
        masked, _ = mask_text("Cliente Roberto Alves Costa", MaskLevel.PARTIAL)
        assert "Roberto Alves Costa" not in masked
        assert "R." in masked  # first initial preserved


class TestMoneyDetection:
    def test_above_threshold_detected(self):
        matches = detect_pii("Depósito de R$ 50.000,00 registrado")
        assert any(m.type == PIIType.MONEY for m in matches)

    def test_below_threshold_not_detected(self):
        matches = detect_pii("Taxa de R$ 500,00 cobrada")
        assert not any(m.type == PIIType.MONEY for m in matches)

    def test_exactly_at_threshold_detected(self):
        matches = detect_pii("Valor de R$ 10.000,00")
        assert any(m.type == PIIType.MONEY for m in matches)

    def test_money_full_mask(self):
        masked, _ = mask_text("Valor R$ 50.000,00", MaskLevel.FULL)
        assert "[VALOR_MASCARADO]" in masked

    def test_money_partial_mask(self):
        masked, _ = mask_text("Valor R$ 50.000,00", MaskLevel.PARTIAL)
        assert "R$ *.**" in masked


class TestPhoneDetection:
    def test_formatted_phone_detected(self):
        matches = detect_pii("Telefone: (11) 99999-1234")
        assert any(m.type == PIIType.PHONE for m in matches)

    def test_phone_full_mask(self):
        masked, _ = mask_text("Tel: (11) 99999-1234", MaskLevel.FULL)
        assert "[TELEFONE_MASCARADO]" in masked

    def test_phone_partial_mask(self):
        masked, _ = mask_text("Tel: (11) 99999-1234", MaskLevel.PARTIAL)
        assert "(11) ****-1234" in masked


class TestEmailDetection:
    def test_email_detected(self):
        matches = detect_pii("Contato: joao@email.com")
        assert any(m.type == PIIType.EMAIL for m in matches)

    def test_email_full_mask(self):
        masked, _ = mask_text("Email: joao@email.com", MaskLevel.FULL)
        assert "[EMAIL_MASCARADO]" in masked

    def test_email_partial_mask(self):
        masked, _ = mask_text("Email: joao@email.com", MaskLevel.PARTIAL)
        assert "j***@email.com" in masked


class TestHelpers:
    def test_has_pii_true(self):
        assert has_pii("CPF: 123.456.789-09") is True

    def test_has_pii_false(self):
        assert has_pii("Resolução CMN 4.893 publicada em 2021") is False

    def test_count_pii_multiple_types(self):
        text = "CPF 123.456.789-09 de Roberto Alves, valor R$ 50.000,00"
        counts = count_pii(text)
        assert counts.get("cpf", 0) == 1
        assert counts.get("name", 0) >= 1
        assert counts.get("money", 0) == 1

    def test_mask_right_to_left_preserves_offsets(self):
        # Two CPFs in the same string — both must be masked
        text = "CPF1: 123.456.789-09 e CPF2: 987.654.321-00"
        masked, matches = mask_text(text, MaskLevel.FULL)
        assert masked.count("[CPF_MASCARADO]") == 2
```

- [ ] **Step 3: Run tests to confirm they fail (import error expected)**

```
pytest tests/test_pii_detector.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'src.governance'`

- [ ] **Step 4: Commit the failing tests**

```bash
git add src/governance/__init__.py tests/test_pii_detector.py
git commit -m "test: add failing PII detector tests (governance bootstrap)"
```

---

## Task 2: Implement `src/governance/pii_detector.py`

**Files:**
- Create: `src/governance/pii_detector.py`

- [ ] **Step 1: Write the full implementation**

```python
# src/governance/pii_detector.py
"""PII (Personally Identifiable Information) detection and masking for LGPD compliance.

Detects and masks:
- CPF numbers (XXX.XXX.XXX-XX or 11 unformatted digits)
- Names (multi-word Title-Case sequences + 100 most common Brazilian first names)
- Monetary values >= R$10,000
- Brazilian phone numbers
- Email addresses
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MONEY_THRESHOLD = 10_000.0


class PIIType(Enum):
    CPF = "cpf"
    NAME = "name"
    MONEY = "money"
    PHONE = "phone"
    EMAIL = "email"


class MaskLevel(Enum):
    PARTIAL = "partial"
    FULL = "full"


@dataclass
class PIIMatch:
    type: PIIType
    original: str
    start: int
    end: int
    masked_partial: str
    masked_full: str


_NAME_EXCLUSIONS: frozenset[str] = frozenset({
    "Art", "Resolução", "Circular", "COAF", "Banco", "Central", "LGPD",
    "CLT", "PIX", "STR", "RSFN", "BCB", "CMN", "CVM", "CEO", "CFO",
    "Decreto", "Lei", "Instrução", "Normativo", "Portaria",
    "Superintendência", "Diretoria", "Departamento", "Gerência",
    "Sistema", "Brasil", "Federal", "Nacional",
    "Ministério", "Conselho", "Monetário",
})

_BRAZILIAN_NAMES: frozenset[str] = frozenset({
    "João", "Maria", "José", "Ana", "Carlos", "Paulo", "Pedro", "Lucas",
    "Luiz", "Marcos", "Luis", "Gabriel", "Rafael", "Francisco", "Daniel",
    "Marcelo", "Bruno", "Eduardo", "Felipe", "Raimundo", "Rodrigo", "Manoel",
    "Nelson", "Roberto", "Diego", "Antônio", "Gustavo", "Mateus", "Matheus",
    "Leonardo", "Adriano", "Alessandro", "Alex", "André", "Bernardo",
    "Caio", "Cláudio", "Cristiano", "Danilo", "Douglas", "Edson", "Emerson",
    "Fábio", "Fernando", "Flávio", "Gilberto", "Guilherme", "Henrique",
    "Igor", "Ivan", "Jorge", "Júlio", "Leandro", "Márcio", "Maurício",
    "Miguel", "Murilo", "Nicolas", "Patrick", "Renato", "Ricardo", "Sérgio",
    "Tiago", "Thiago", "Victor", "Vítor", "Wagner", "Wellington", "William",
    "Alessandra", "Aline", "Amanda", "Beatriz", "Bruna", "Camila", "Carolina",
    "Claudia", "Cristina", "Daniela", "Débora", "Elaine", "Fernanda",
    "Gabriela", "Isabela", "Isabel", "Jéssica", "Juliana", "Larissa",
    "Laura", "Letícia", "Lúcia", "Mariana", "Michele", "Mônica", "Natália",
    "Patrícia", "Paula", "Priscila", "Raquel", "Regina", "Renata", "Sandra",
    "Sara", "Simone", "Tatiana", "Vanessa", "Viviane",
})

_CPF_RE = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_PHONE_RE = re.compile(r'\(?\d{2}\)?\s*\d{4,5}-?\d{4}')
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
_MONEY_RE = re.compile(r'R\$\s*[\d.,]+')
_NAME_MULTI_RE = re.compile(
    r'\b[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇÜ][a-záéíóúâêîôûãõàçü]+'
    r'(?:\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇÜ][a-záéíóúâêîôûãõàçü]+)+\b'
)


def _parse_money_value(text: str) -> float:
    """Parse a Brazilian monetary string like 'R$ 50.000,00' to float."""
    digits = text.replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return 0.0


def _mask_cpf_partial(cpf: str) -> str:
    digits = re.sub(r'\D', '', cpf)
    if len(digits) == 11:
        return f"{digits[:3]}.***.**{digits[8]}-{digits[9:]}"
    return "[CPF_MASCARADO]"


def _mask_name_partial(name: str) -> str:
    parts = name.split()
    if len(parts) == 1:
        return parts[0][0] + "."
    return parts[0][0] + ". " + " ".join(p[0] + "." for p in parts[1:])


def _mask_phone_partial(phone: str) -> str:
    digits = re.sub(r'\D', '', phone)
    if len(digits) >= 10:
        return f"({digits[:2]}) ****-{digits[-4:]}"
    return phone


def _mask_email_partial(email: str) -> str:
    local, domain = email.split("@", 1)
    return local[0] + "***@" + domain


def detect_pii(text: str) -> list[PIIMatch]:
    """Detect all PII occurrences in text. Returns non-overlapping matches sorted by position."""
    matches: list[PIIMatch] = []

    for m in _CPF_RE.finditer(text):
        matches.append(PIIMatch(
            type=PIIType.CPF, original=m.group(),
            start=m.start(), end=m.end(),
            masked_partial=_mask_cpf_partial(m.group()),
            masked_full="[CPF_MASCARADO]",
        ))

    for m in _PHONE_RE.finditer(text):
        matches.append(PIIMatch(
            type=PIIType.PHONE, original=m.group(),
            start=m.start(), end=m.end(),
            masked_partial=_mask_phone_partial(m.group()),
            masked_full="[TELEFONE_MASCARADO]",
        ))

    for m in _EMAIL_RE.finditer(text):
        matches.append(PIIMatch(
            type=PIIType.EMAIL, original=m.group(),
            start=m.start(), end=m.end(),
            masked_partial=_mask_email_partial(m.group()),
            masked_full="[EMAIL_MASCARADO]",
        ))

    for m in _MONEY_RE.finditer(text):
        if _parse_money_value(m.group()) >= MONEY_THRESHOLD:
            matches.append(PIIMatch(
                type=PIIType.MONEY, original=m.group(),
                start=m.start(), end=m.end(),
                masked_partial="R$ *.**",
                masked_full="[VALOR_MASCARADO]",
            ))

    for m in _NAME_MULTI_RE.finditer(text):
        words = m.group().split()
        if any(w in _NAME_EXCLUSIONS for w in words):
            continue
        matches.append(PIIMatch(
            type=PIIType.NAME, original=m.group(),
            start=m.start(), end=m.end(),
            masked_partial=_mask_name_partial(m.group()),
            masked_full="[NOME_MASCARADO]",
        ))

    covered = {(m.start, m.end) for m in matches if m.type == PIIType.NAME}
    for name in _BRAZILIAN_NAMES:
        pattern = re.compile(r'\b' + re.escape(name) + r'\b')
        for m in pattern.finditer(text):
            if not any(m.start() >= s and m.end() <= e for s, e in covered):
                matches.append(PIIMatch(
                    type=PIIType.NAME, original=m.group(),
                    start=m.start(), end=m.end(),
                    masked_partial=_mask_name_partial(m.group()),
                    masked_full="[NOME_MASCARADO]",
                ))

    return _remove_overlaps(sorted(matches, key=lambda x: x.start))


def _remove_overlaps(matches: list[PIIMatch]) -> list[PIIMatch]:
    """Keep the longer match when two ranges overlap."""
    result: list[PIIMatch] = []
    for m in matches:
        if not result or m.start >= result[-1].end:
            result.append(m)
        elif (m.end - m.start) > (result[-1].end - result[-1].start):
            result[-1] = m
    return result


def mask_text(text: str, level: MaskLevel = MaskLevel.FULL) -> tuple[str, list[PIIMatch]]:
    """Mask all PII in text. Returns (masked_text, list_of_detections)."""
    pii_matches = detect_pii(text)
    result = text
    for m in reversed(pii_matches):
        replacement = m.masked_full if level == MaskLevel.FULL else m.masked_partial
        result = result[:m.start] + replacement + result[m.end:]
    return result, pii_matches


def has_pii(text: str) -> bool:
    """Quick check if text contains any PII."""
    return bool(detect_pii(text))


def count_pii(text: str) -> dict[str, int]:
    """Count PII occurrences by type. Returns e.g. {'cpf': 1, 'name': 2}."""
    counts: dict[str, int] = {}
    for m in detect_pii(text):
        counts[m.type.value] = counts.get(m.type.value, 0) + 1
    return counts
```

- [ ] **Step 2: Run the tests**

```
pytest tests/test_pii_detector.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/governance/pii_detector.py
git commit -m "feat: add PII detection and masking module (LGPD compliance)"
```

---

## Task 3: Add `audit_log` + `governance_daily_stats` tables to `setup.py`

**Files:**
- Modify: `src/database/setup.py`

- [ ] **Step 1: Append the two new table definitions to `_DDL`**

Open `src/database/setup.py`. The `_DDL` string ends just before `"""`. Add the two new tables inside `_DDL` (after the `agent_log` block):

```python
_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    ...existing...
);

CREATE TABLE IF NOT EXISTS alerts (
    ...existing...
);

CREATE TABLE IF NOT EXISTS agent_log (
    ...existing...
);

CREATE TABLE IF NOT EXISTS audit_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            TEXT    NOT NULL,
    timestamp             TEXT    NOT NULL,
    agent_name            TEXT    NOT NULL,
    action                TEXT    NOT NULL,
    input_original        TEXT,
    input_masked          TEXT    NOT NULL,
    output_original       TEXT,
    output_masked         TEXT    NOT NULL,
    input_has_pii         BOOLEAN DEFAULT FALSE,
    output_has_pii        BOOLEAN DEFAULT FALSE,
    pii_types_detected    TEXT,
    data_classification   TEXT    DEFAULT 'public',
    provider              TEXT,
    model                 TEXT,
    tokens_used           INTEGER,
    chunks_ids            TEXT,
    chunks_count          INTEGER DEFAULT 0,
    retention_expires_at  TEXT,
    pii_purged            BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS governance_daily_stats (
    date                        TEXT PRIMARY KEY,
    total_queries               INTEGER DEFAULT 0,
    queries_with_pii            INTEGER DEFAULT 0,
    classification_public       INTEGER DEFAULT 0,
    classification_internal     INTEGER DEFAULT 0,
    classification_confidential INTEGER DEFAULT 0,
    classification_restricted   INTEGER DEFAULT 0,
    pii_cpf_count               INTEGER DEFAULT 0,
    pii_name_count              INTEGER DEFAULT 0,
    pii_money_count             INTEGER DEFAULT 0
);
"""
```

The full updated `_DDL` (replace the entire `_DDL = """..."""` block):

```python
_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name        TEXT    NOT NULL,
    client_cpf         TEXT    NOT NULL,
    transaction_type   TEXT    NOT NULL,
    amount             REAL    NOT NULL,
    date               TEXT    NOT NULL,
    branch             TEXT,
    channel            TEXT,
    reported_to_coaf   BOOLEAN DEFAULT FALSE,
    pep_flag           BOOLEAN DEFAULT FALSE,
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   INTEGER,
    alert_type       TEXT NOT NULL,
    severity         TEXT NOT NULL,
    description      TEXT NOT NULL,
    status           TEXT DEFAULT 'open',
    created_at       TEXT NOT NULL,
    resolved_at      TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);

CREATE TABLE IF NOT EXISTS agent_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    action          TEXT NOT NULL,
    input_summary   TEXT,
    output_summary  TEXT,
    tokens_used     INTEGER
);

CREATE TABLE IF NOT EXISTS audit_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            TEXT    NOT NULL,
    timestamp             TEXT    NOT NULL,
    agent_name            TEXT    NOT NULL,
    action                TEXT    NOT NULL,
    input_original        TEXT,
    input_masked          TEXT    NOT NULL,
    output_original       TEXT,
    output_masked         TEXT    NOT NULL,
    input_has_pii         BOOLEAN DEFAULT FALSE,
    output_has_pii        BOOLEAN DEFAULT FALSE,
    pii_types_detected    TEXT,
    data_classification   TEXT    DEFAULT 'public',
    provider              TEXT,
    model                 TEXT,
    tokens_used           INTEGER,
    chunks_ids            TEXT,
    chunks_count          INTEGER DEFAULT 0,
    retention_expires_at  TEXT,
    pii_purged            BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS governance_daily_stats (
    date                        TEXT PRIMARY KEY,
    total_queries               INTEGER DEFAULT 0,
    queries_with_pii            INTEGER DEFAULT 0,
    classification_public       INTEGER DEFAULT 0,
    classification_internal     INTEGER DEFAULT 0,
    classification_confidential INTEGER DEFAULT 0,
    classification_restricted   INTEGER DEFAULT 0,
    pii_cpf_count               INTEGER DEFAULT 0,
    pii_name_count              INTEGER DEFAULT 0,
    pii_money_count             INTEGER DEFAULT 0
);
"""
```

- [ ] **Step 2: Verify the tables are created (run the module directly)**

```
python -m src.database.setup
```
Expected output: `Tables created.`

- [ ] **Step 3: Confirm new tables exist in the DB**

```
python -c "
from src.database.connection import get_db
with get_db() as c:
    rows = c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
    print([r[0] for r in rows])
"
```
Expected: list includes `audit_log` and `governance_daily_stats`.

- [ ] **Step 4: Run existing DB tests to ensure nothing broke**

```
pytest tests/test_database.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/database/setup.py
git commit -m "feat: add audit_log and governance_daily_stats tables"
```

---

## Task 4: Implement `src/governance/audit.py` (TDD)

**Files:**
- Create: `tests/test_audit.py`
- Create: `src/governance/audit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit.py
"""Tests for the audit trail module."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.database.setup import _DDL


@pytest.fixture
def audit_db():
    """In-memory SQLite with all tables for isolated audit testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()

    @contextmanager
    def fake_get_db():
        yield conn

    with patch("src.governance.audit.get_db", fake_get_db):
        yield conn

    conn.close()


class TestGenerateSessionId:
    def test_returns_8_char_string(self):
        from src.governance.audit import generate_session_id
        sid = generate_session_id()
        assert isinstance(sid, str)
        assert len(sid) == 8

    def test_unique_ids(self):
        from src.governance.audit import generate_session_id
        ids = {generate_session_id() for _ in range(100)}
        assert len(ids) == 100  # all unique


class TestClassifyQuery:
    def test_data_with_pii_is_restricted(self):
        from src.governance.audit import classify_query
        assert classify_query("data", True, "qualquer") == "restricted"

    def test_data_without_pii_is_confidential(self):
        from src.governance.audit import classify_query
        assert classify_query("data", False, "qualquer") == "confidential"

    def test_action_is_confidential(self):
        from src.governance.audit import classify_query
        assert classify_query("action", False, "qualquer") == "confidential"

    def test_knowledge_is_public(self):
        from src.governance.audit import classify_query
        assert classify_query("knowledge", False, "qualquer") == "public"

    def test_coordinator_is_public(self):
        from src.governance.audit import classify_query
        assert classify_query("coordinator", False, "qualquer") == "public"


class TestGetRetentionExpiry:
    def test_restricted_expires_in_1_year(self):
        from src.governance.audit import get_retention_expiry
        expiry = get_retention_expiry("restricted")
        expected = (datetime.utcnow() + timedelta(days=365)).year
        assert str(expected) in expiry

    def test_confidential_expires_in_2_years(self):
        from src.governance.audit import get_retention_expiry
        expiry = get_retention_expiry("confidential")
        expected = (datetime.utcnow() + timedelta(days=730)).year
        assert str(expected) in expiry

    def test_public_expires_in_5_years(self):
        from src.governance.audit import get_retention_expiry
        expiry = get_retention_expiry("public")
        expected = (datetime.utcnow() + timedelta(days=1825)).year
        assert str(expected) in expiry


class TestLogInteraction:
    @pytest.mark.asyncio
    async def test_inserts_row_and_returns_id(self, audit_db):
        from src.governance.audit import log_interaction
        log_id = await log_interaction(
            session_id="abc12345",
            agent_name="knowledge",
            action="route:KNOWLEDGE",
            input_text="O que é compliance?",
            output_text="Compliance é conformidade regulatória.",
        )
        assert isinstance(log_id, int)
        assert log_id > 0
        row = audit_db.execute("SELECT * FROM audit_log WHERE id=?", (log_id,)).fetchone()
        assert row["agent_name"] == "knowledge"
        assert row["session_id"] == "abc12345"

    @pytest.mark.asyncio
    async def test_pii_is_masked_and_original_is_null(self, audit_db):
        from src.governance.audit import log_interaction
        await log_interaction(
            session_id="test1111",
            agent_name="data",
            action="route:DATA",
            input_text="Consulta do cliente Roberto Alves Costa",
            output_text="O cliente Roberto Alves Costa tem CPF 123.456.789-09",
        )
        row = audit_db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert "[NOME_MASCARADO]" in row["output_masked"]
        assert "[CPF_MASCARADO]" in row["output_masked"]
        assert "Roberto Alves Costa" not in row["output_masked"]
        assert row["output_original"] is None
        assert row["output_has_pii"] == 1

    @pytest.mark.asyncio
    async def test_no_pii_stores_original_text(self, audit_db):
        from src.governance.audit import log_interaction
        await log_interaction(
            session_id="test2222",
            agent_name="knowledge",
            action="route:KNOWLEDGE",
            input_text="Qual é a Resolução CMN 4.893?",
            output_text="A resolução trata de cibersegurança.",
        )
        row = audit_db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["input_original"] == "Qual é a Resolução CMN 4.893?"
        assert row["output_original"] == "A resolução trata de cibersegurança."
        assert row["input_has_pii"] == 0
        assert row["output_has_pii"] == 0

    @pytest.mark.asyncio
    async def test_data_with_pii_classified_restricted(self, audit_db):
        from src.governance.audit import log_interaction
        await log_interaction(
            session_id="test3333",
            agent_name="data",
            action="route:DATA",
            input_text="Transações de Roberto Alves Costa",
            output_text="Encontradas 3 transações para Roberto Alves Costa.",
        )
        row = audit_db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["data_classification"] == "restricted"

    @pytest.mark.asyncio
    async def test_upserts_daily_stats(self, audit_db):
        from src.governance.audit import log_interaction
        today = datetime.utcnow().date().isoformat()
        await log_interaction(
            session_id="test4444",
            agent_name="data",
            action="route:DATA",
            input_text="Transações de Roberto Alves Costa",
            output_text="Resultado.",
        )
        stats = audit_db.execute(
            "SELECT * FROM governance_daily_stats WHERE date=?", (today,)
        ).fetchone()
        assert stats is not None
        assert stats["total_queries"] == 1
        assert stats["queries_with_pii"] == 1

    @pytest.mark.asyncio
    async def test_daily_stats_accumulate(self, audit_db):
        from src.governance.audit import log_interaction
        today = datetime.utcnow().date().isoformat()
        for _ in range(3):
            await log_interaction(
                session_id="s1", agent_name="knowledge",
                action="route:KNOWLEDGE",
                input_text="O que é compliance?",
                output_text="Resposta sem PII.",
            )
        stats = audit_db.execute(
            "SELECT * FROM governance_daily_stats WHERE date=?", (today,)
        ).fetchone()
        assert stats["total_queries"] == 3
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_audit.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` or `ImportError` for `src.governance.audit`

- [ ] **Step 3: Write the implementation**

```python
# src/governance/audit.py
"""Audit trail manager — logs all agent interactions with PII masking."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from src.database.connection import get_db
from src.governance.pii_detector import MaskLevel, mask_text


def generate_session_id() -> str:
    """Generate a unique 8-character session ID."""
    return str(uuid.uuid4())[:8]


def classify_query(agent_name: str, has_pii: bool, query: str) -> str:
    """Classify query sensitivity.

    Rules:
    - data + PII present  → restricted
    - data (no PII)       → confidential (financial data regardless)
    - action              → confidential (modifies DB)
    - knowledge/coordinator → public
    """
    name = agent_name.lower()
    if name == "data" and has_pii:
        return "restricted"
    if name == "data":
        return "confidential"
    if name == "action":
        return "confidential"
    return "public"


def get_retention_expiry(classification: str) -> str:
    """Return ISO date when PII fields must be purged.

    restricted   → 1 year
    confidential → 2 years
    public/internal → 5 years (Art. 23, Resolution 4.893)
    """
    today = datetime.utcnow().date()
    if classification == "restricted":
        return (today + timedelta(days=365)).isoformat()
    if classification == "confidential":
        return (today + timedelta(days=730)).isoformat()
    return (today + timedelta(days=1825)).isoformat()


async def log_interaction(
    session_id: str,
    agent_name: str,
    action: str,
    input_text: str,
    output_text: str,
    provider: str = "ollama",
    model: str = "",
    tokens_used: int = 0,
    chunks_count: int = 0,
) -> int:
    """Log an agent interaction with automatic PII detection and masking.

    Stores masked text in audit_log. Original text is stored only when no PII
    is detected. Updates governance_daily_stats via upsert.

    Returns the audit_log row ID.
    """
    input_masked, input_matches = mask_text(input_text, MaskLevel.FULL)
    output_masked, output_matches = mask_text(output_text, MaskLevel.FULL)

    input_has_pii = bool(input_matches)
    output_has_pii = bool(output_matches)
    any_pii = input_has_pii or output_has_pii

    input_original = None if input_has_pii else input_text
    output_original = None if output_has_pii else output_text

    all_counts: dict[str, int] = {}
    for m in input_matches + output_matches:
        all_counts[m.type.value] = all_counts.get(m.type.value, 0) + 1
    pii_types_json = json.dumps(all_counts) if all_counts else None

    classification = classify_query(agent_name, any_pii, input_text)
    retention_expires = get_retention_expiry(classification)
    timestamp = datetime.utcnow().isoformat()
    today = datetime.utcnow().date().isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                session_id, timestamp, agent_name, action,
                input_original, input_masked, output_original, output_masked,
                input_has_pii, output_has_pii, pii_types_detected,
                data_classification, provider, model, tokens_used,
                chunks_count, retention_expires_at, pii_purged
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,FALSE)
            """,
            (
                session_id, timestamp, agent_name, action,
                input_original, input_masked, output_original, output_masked,
                input_has_pii, output_has_pii, pii_types_json,
                classification, provider, model, tokens_used,
                chunks_count, retention_expires,
            ),
        )
        log_id: int = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            """
            INSERT INTO governance_daily_stats (
                date, total_queries, queries_with_pii,
                classification_public, classification_internal,
                classification_confidential, classification_restricted,
                pii_cpf_count, pii_name_count, pii_money_count
            ) VALUES (?,1,?,?,0,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                total_queries               = total_queries + 1,
                queries_with_pii            = queries_with_pii + excluded.queries_with_pii,
                classification_public       = classification_public + excluded.classification_public,
                classification_confidential = classification_confidential + excluded.classification_confidential,
                classification_restricted   = classification_restricted + excluded.classification_restricted,
                pii_cpf_count               = pii_cpf_count + excluded.pii_cpf_count,
                pii_name_count              = pii_name_count + excluded.pii_name_count,
                pii_money_count             = pii_money_count + excluded.pii_money_count
            """,
            (
                today,
                1 if any_pii else 0,
                1 if classification == "public" else 0,
                1 if classification == "confidential" else 0,
                1 if classification == "restricted" else 0,
                all_counts.get("cpf", 0),
                all_counts.get("name", 0),
                all_counts.get("money", 0),
            ),
        )

    return log_id
```

- [ ] **Step 4: Run audit tests**

```
pytest tests/test_audit.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/governance/audit.py tests/test_audit.py
git commit -m "feat: add audit trail module with PII masking and daily stats"
```

---

## Task 5: Implement `src/governance/retention.py` (TDD)

**Files:**
- Create: `src/governance/retention.py`
- (tests inline below — add to a new `tests/test_retention.py`)

- [ ] **Step 1: Write failing retention tests**

```python
# tests/test_retention.py
"""Tests for the data retention manager."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.database.setup import _DDL


@pytest.fixture
def retention_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()

    @contextmanager
    def fake_get_db():
        yield conn

    with patch("src.governance.retention.get_db", fake_get_db):
        yield conn

    conn.close()


def _insert_row(conn, *, input_has_pii=True, pii_purged=False, expires_at=None):
    """Insert a test audit_log row."""
    if expires_at is None:
        expires_at = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    conn.execute(
        """INSERT INTO audit_log (
            session_id, timestamp, agent_name, action,
            input_masked, output_masked,
            input_has_pii, output_has_pii, data_classification,
            retention_expires_at, pii_purged
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("sid", datetime.utcnow().isoformat(), "data", "route:DATA",
         "[NOME_MASCARADO]", "[CPF_MASCARADO]",
         1 if input_has_pii else 0, 0, "restricted",
         expires_at, 1 if pii_purged else 0),
    )
    conn.commit()


class TestPurgeExpiredPii:
    @pytest.mark.asyncio
    async def test_purges_expired_row(self, retention_db):
        from src.governance.retention import purge_expired_pii
        _insert_row(retention_db)
        result = await purge_expired_pii()
        assert result["rows_purged"] == 1
        row = retention_db.execute("SELECT * FROM audit_log").fetchone()
        assert row["pii_purged"] == 1
        assert row["input_masked"] == "[DADO_EXPIRADO]"
        assert row["output_masked"] == "[DADO_EXPIRADO]"

    @pytest.mark.asyncio
    async def test_does_not_purge_future_expiry(self, retention_db):
        from src.governance.retention import purge_expired_pii
        future = (datetime.utcnow() + timedelta(days=365)).date().isoformat()
        _insert_row(retention_db, expires_at=future)
        result = await purge_expired_pii()
        assert result["rows_purged"] == 0

    @pytest.mark.asyncio
    async def test_does_not_purge_already_purged(self, retention_db):
        from src.governance.retention import purge_expired_pii
        _insert_row(retention_db, pii_purged=True)
        result = await purge_expired_pii()
        assert result["rows_purged"] == 0

    @pytest.mark.asyncio
    async def test_does_not_purge_no_pii_rows(self, retention_db):
        from src.governance.retention import purge_expired_pii
        _insert_row(retention_db, input_has_pii=False)
        result = await purge_expired_pii()
        assert result["rows_purged"] == 0


class TestGetRetentionReport:
    @pytest.mark.asyncio
    async def test_report_keys_present(self, retention_db):
        from src.governance.retention import get_retention_report
        report = await get_retention_report()
        assert "total_records" in report
        assert "records_with_pii" in report
        assert "records_pii_purged" in report
        assert "records_expiring_30_days" in report
        assert "oldest_record" in report
        assert "storage_by_classification" in report

    @pytest.mark.asyncio
    async def test_counts_are_correct(self, retention_db):
        from src.governance.retention import get_retention_report
        future = (datetime.utcnow() + timedelta(days=365)).date().isoformat()
        _insert_row(retention_db, expires_at=future, input_has_pii=True)
        _insert_row(retention_db, expires_at=future, input_has_pii=False)
        report = await get_retention_report()
        assert report["total_records"] == 2
        assert report["records_with_pii"] == 1
        assert report["records_pii_purged"] == 0
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/test_retention.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` for `src.governance.retention`

- [ ] **Step 3: Write the implementation**

```python
# src/governance/retention.py
"""Data retention manager — enforces LGPD data minimization principles.

Purges PII from audit logs after the retention period expires.
Preserves non-PII metadata for the 5-year regulatory audit trail
required by Art. 23 of Resolution CMN 4.893.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.database.connection import get_db


async def purge_expired_pii() -> dict:
    """Overwrite PII fields in expired audit log rows with '[DADO_EXPIRADO]'.

    Does NOT delete rows — preserves metadata for regulatory compliance.
    Only processes rows where pii_purged=FALSE and at least one PII flag is set.

    Returns:
        {'rows_purged': int, 'oldest_purged': str|None, 'newest_purged': str|None}
    """
    today = datetime.utcnow().date().isoformat()

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   MIN(timestamp) AS oldest,
                   MAX(timestamp) AS newest
            FROM audit_log
            WHERE retention_expires_at <= ?
              AND pii_purged = FALSE
              AND (input_has_pii = TRUE OR output_has_pii = TRUE)
            """,
            (today,),
        ).fetchone()

        count = row["count"] if row else 0
        oldest = row["oldest"] if row else None
        newest = row["newest"] if row else None

        if count > 0:
            conn.execute(
                """
                UPDATE audit_log
                SET input_original  = '[DADO_EXPIRADO]',
                    output_original = '[DADO_EXPIRADO]',
                    input_masked    = '[DADO_EXPIRADO]',
                    output_masked   = '[DADO_EXPIRADO]',
                    pii_purged      = TRUE
                WHERE retention_expires_at <= ?
                  AND pii_purged = FALSE
                  AND (input_has_pii = TRUE OR output_has_pii = TRUE)
                """,
                (today,),
            )

    return {"rows_purged": count, "oldest_purged": oldest, "newest_purged": newest}


async def get_retention_report() -> dict:
    """Generate a retention status report for the governance dashboard.

    Returns:
        Dict with total records, PII counts, purge status, and storage by classification.
    """
    today = datetime.utcnow().date().isoformat()
    future_30 = (datetime.utcnow() + timedelta(days=30)).date().isoformat()

    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        with_pii = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE input_has_pii = TRUE OR output_has_pii = TRUE"
        ).fetchone()[0]
        purged = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE pii_purged = TRUE"
        ).fetchone()[0]
        expiring = conn.execute(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE retention_expires_at <= ?
              AND retention_expires_at > ?
              AND pii_purged = FALSE
              AND (input_has_pii = TRUE OR output_has_pii = TRUE)
            """,
            (future_30, today),
        ).fetchone()[0]
        oldest = conn.execute("SELECT MIN(timestamp) FROM audit_log").fetchone()[0]
        by_class_rows = conn.execute(
            "SELECT data_classification, COUNT(*) AS cnt "
            "FROM audit_log GROUP BY data_classification"
        ).fetchall()

    return {
        "total_records": total,
        "records_with_pii": with_pii,
        "records_pii_purged": purged,
        "records_expiring_30_days": expiring,
        "oldest_record": oldest,
        "storage_by_classification": {r["data_classification"]: r["cnt"] for r in by_class_rows},
    }
```

- [ ] **Step 4: Run all governance tests**

```
pytest tests/test_audit.py tests/test_retention.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/governance/retention.py tests/test_retention.py
git commit -m "feat: add data retention manager with LGPD purge logic"
```

---

## Task 6: Update `src/agents/coordinator.py` + fix its tests

**Files:**
- Modify: `src/agents/coordinator.py`
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Replace the full `coordinator.py`**

Key changes: add `pii_detected`, `data_classification`, `session_id` to `CoordinatorResponse`; rewrite `process()` to use `audit.log_interaction()`; remove `_log()`.

```python
# src/agents/coordinator.py
"""Coordinator agent — classifies intent and routes to specialized agents."""
from __future__ import annotations

from pydantic import BaseModel

from src.agents.action_agent import ActionAgent
from src.agents.base import AgentResponse
from src.agents.data_agent import DataAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.database.seed import init_db
from src.governance import audit, pii_detector
from src.llm import llm_router

_LGPD_FOOTER = (
    "\n\n---\n\U0001f512 Esta resposta contém dados pessoais protegidos pela LGPD. "
    "Uso restrito a fins de compliance."
)

_ROUTING_PROMPT = """\
Você é um roteador de agentes de compliance financeiro. Classifique a intenção da pergunta.

Agentes disponíveis:
- KNOWLEDGE: Perguntas sobre regulamentações, normas, resoluções, circulares, artigos, prazos legais.
  Exemplos: "O que diz o Art. 49 da Circular 3.978?", "Quais são os requisitos de cibersegurança?"
- DATA: Perguntas sobre dados de transações, clientes, operações, alertas no banco de dados.
  Exemplos: "Quantas operações acima de R$50.000 temos?", "Quais clientes são PEP?"
- ACTION: Solicitações de ações concretas no sistema.
  Exemplos: "Crie um alerta", "Gere um relatório de alertas abertos", "Resolver alerta #3"
- KNOWLEDGE+DATA: Perguntas que cruzam regulamentação com dados reais.
  Exemplos: "Verifique se estamos em conformidade com o Art. 49 sobre operações em espécie"

Responda APENAS com uma das opções: KNOWLEDGE, DATA, ACTION, KNOWLEDGE+DATA

Pergunta: {question}
Classificação:"""


class CoordinatorResponse(BaseModel):
    """Full response from the coordinator including routing metadata."""

    pergunta: str
    roteamento: str
    agentes_utilizados: list[str]
    resposta_final: str
    detalhes_agentes: list[dict]
    log_id: int
    provider_utilizado: str
    pii_detected: bool = False
    data_classification: str = "public"
    session_id: str = ""


class CoordinatorAgent:
    """Routes questions to the appropriate specialized agent(s)."""

    def __init__(self) -> None:
        self.knowledge_agent = KnowledgeAgent()
        self.data_agent = DataAgent()
        self.action_agent = ActionAgent()

    async def process(self, question: str, provider: str = "ollama") -> CoordinatorResponse:
        """Classify and route a question to the appropriate agent(s).

        Generates a session_id, routes the question, detects PII in the response,
        logs the interaction to audit_log with masked PII, and returns the full
        response including LGPD metadata.

        Args:
            question: Natural language question in Portuguese.
            provider: LLM backend — "ollama" (default) or "claude".
        """
        init_db()
        session_id = audit.generate_session_id()
        routing = await self._classify(question, provider=provider)
        details: list[dict] = []
        agents_used: list[str] = []
        pii_found = False
        classification = "public"
        log_id = 0

        if routing == "KNOWLEDGE":
            response = await self.knowledge_agent.answer(question, provider=provider)
            details.append(_to_detail(response))
            agents_used.append("knowledge")
            final = response.answer
            pii_found = pii_detector.has_pii(final)
            classification = audit.classify_query("knowledge", pii_found, question)
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="knowledge",
                action=f"route:{routing}", input_text=question, output_text=final,
                provider=provider,
            )

        elif routing == "DATA":
            response = await self.data_agent.answer(question, provider=provider)
            details.append(_to_detail(response))
            agents_used.append("data")
            pii_found = pii_detector.has_pii(response.answer)
            classification = audit.classify_query("data", pii_found, question)
            final = response.answer
            if pii_found:
                final += _LGPD_FOOTER
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="data",
                action=f"route:{routing}", input_text=question,
                output_text=response.answer,  # log without footer
                provider=provider,
            )

        elif routing == "ACTION":
            response = await self.action_agent.answer(question)
            details.append(_to_detail(response))
            agents_used.append("action")
            final = response.answer
            pii_found = pii_detector.has_pii(final)
            classification = audit.classify_query("action", pii_found, question)
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="action",
                action=f"route:{routing}", input_text=question, output_text=final,
                provider=provider,
            )

        else:  # KNOWLEDGE+DATA
            k_resp = await self.knowledge_agent.answer(question, provider=provider)
            await audit.log_interaction(
                session_id=session_id, agent_name="knowledge",
                action="route:KNOWLEDGE+DATA:knowledge",
                input_text=question, output_text=k_resp.answer, provider=provider,
            )
            d_resp = await self.data_agent.answer(
                question, extra_context=k_resp.answer, provider=provider
            )
            details.extend([_to_detail(k_resp), _to_detail(d_resp)])
            agents_used.extend(["knowledge", "data"])
            pii_found = pii_detector.has_pii(d_resp.answer)
            classification = "confidential"
            final = (
                f"**Análise Regulatória:**\n{k_resp.answer}\n\n"
                f"**Análise de Dados:**\n{d_resp.answer}"
            )
            if pii_found:
                final += _LGPD_FOOTER
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="data",
                action="route:KNOWLEDGE+DATA:data",
                input_text=question, output_text=d_resp.answer, provider=provider,
            )

        return CoordinatorResponse(
            pergunta=question,
            roteamento=routing,
            agentes_utilizados=agents_used,
            resposta_final=final,
            detalhes_agentes=details,
            log_id=log_id,
            provider_utilizado=provider,
            pii_detected=pii_found,
            data_classification=classification,
            session_id=session_id,
        )

    async def _classify(self, question: str, provider: str = "ollama") -> str:
        try:
            prompt = _ROUTING_PROMPT.format(question=question)
            raw = await llm_router.generate(prompt, provider=provider)
            classification = raw.strip().upper().split()[0]
            valid = {"KNOWLEDGE", "DATA", "ACTION", "KNOWLEDGE+DATA"}
            if "KNOWLEDGE" in classification and "DATA" in raw.upper():
                return "KNOWLEDGE+DATA"
            if classification in valid:
                return classification
        except Exception:
            pass
        return _heuristic_route(question)


def _heuristic_route(question: str) -> str:
    q = question.lower()
    action_kws = ("criar alerta", "crie", "relatório", "atualizar", "resolver", "investigar", "reportar coaf")
    data_kws = ("transação", "operação", "cliente", "valor", "quantas", "total", "espécie", "coaf reportado")
    reg_kws = ("resolução", "circular", "artigo", "normativo", "regulamentação", "bcb", "cmn")

    is_action = any(kw in q for kw in action_kws)
    is_data = any(kw in q for kw in data_kws)
    is_reg = any(kw in q for kw in reg_kws)

    if is_action:
        return "ACTION"
    if is_reg and is_data:
        return "KNOWLEDGE+DATA"
    if is_data:
        return "DATA"
    return "KNOWLEDGE"


def _to_detail(r: AgentResponse) -> dict:
    return {
        "agente": r.agent_name,
        "resposta": r.answer,
        "fontes": r.sources,
        "dados": r.data,
        "acoes": r.actions_taken,
    }
```

- [ ] **Step 2: Update `tests/test_coordinator.py` to patch `audit.log_interaction` instead of `_log`**

The existing tests use `patch.object(coord, "_log", return_value=1)`. Replace those patches:

```python
# In tests/test_coordinator.py — update each test that patches _log

# OLD:
with patch("src.agents.coordinator.llm_router.generate",
           new_callable=AsyncMock, return_value="KNOWLEDGE"), \
     patch("src.agents.coordinator.init_db"), \
     patch.object(coord, "_log", return_value=1):
    result = await coord.process("Qual o prazo da Resolução 5.274?")

# NEW:
with patch("src.agents.coordinator.llm_router.generate",
           new_callable=AsyncMock, return_value="KNOWLEDGE"), \
     patch("src.agents.coordinator.init_db"), \
     patch("src.agents.coordinator.audit.log_interaction",
           new_callable=AsyncMock, return_value=1):
    result = await coord.process("Qual o prazo da Resolução 5.274?")
```

Apply the same change to all other tests in `test_coordinator.py` that use `patch.object(coord, "_log", ...)`. Also add assertions for the new fields:

```python
assert result.pii_detected is False        # no PII in mock response
assert result.data_classification == "public"
assert len(result.session_id) == 8
```

- [ ] **Step 3: Run coordinator tests**

```
pytest tests/test_coordinator.py -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/agents/coordinator.py tests/test_coordinator.py
git commit -m "feat: integrate PII detection and audit logging into coordinator"
```

---

## Task 7: Create `src/api/governance.py` + register in `main.py`

**Files:**
- Create: `src/api/governance.py`
- Modify: `src/api/main.py`

- [ ] **Step 1: Write `governance.py`**

```python
# src/api/governance.py
"""Governance API — /governance/dashboard, /governance/audit-log, /governance/retention-report."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from src.database.connection import get_db
from src.database.seed import init_db
from src.governance.retention import get_retention_report

router = APIRouter(prefix="/governance", tags=["Governance"])


@router.get("/dashboard")
async def governance_dashboard() -> dict:
    """Governance metrics for the last 30 days + retention status."""
    init_db()
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    today = datetime.utcnow().date().isoformat()
    future_30 = (datetime.utcnow() + timedelta(days=30)).date().isoformat()

    with get_db() as conn:
        stats = conn.execute(
            """
            SELECT
                COALESCE(SUM(total_queries), 0)               AS total,
                COALESCE(SUM(queries_with_pii), 0)            AS with_pii,
                COALESCE(SUM(classification_public), 0)       AS pub,
                COALESCE(SUM(classification_internal), 0)     AS internal,
                COALESCE(SUM(classification_confidential), 0) AS conf,
                COALESCE(SUM(classification_restricted), 0)   AS restr,
                COALESCE(SUM(pii_cpf_count), 0)               AS cpf,
                COALESCE(SUM(pii_name_count), 0)              AS name_cnt,
                COALESCE(SUM(pii_money_count), 0)             AS money
            FROM governance_daily_stats
            WHERE date >= ?
            """,
            (thirty_days_ago,),
        ).fetchone()

        agent_rows = conn.execute(
            "SELECT agent_name, COUNT(*) AS cnt FROM audit_log "
            "WHERE timestamp >= ? GROUP BY agent_name",
            (thirty_days_ago + "T00:00:00",),
        ).fetchall()

        phone_email = conn.execute(
            """
            SELECT
                COALESCE(SUM(CAST(json_extract(pii_types_detected, '$.phone') AS INTEGER)), 0) AS phone_cnt,
                COALESCE(SUM(CAST(json_extract(pii_types_detected, '$.email') AS INTEGER)), 0) AS email_cnt
            FROM audit_log
            WHERE timestamp >= ? AND pii_types_detected IS NOT NULL
            """,
            (thirty_days_ago + "T00:00:00",),
        ).fetchone()

        retention_total = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE input_has_pii=TRUE OR output_has_pii=TRUE"
        ).fetchone()[0]
        retention_purged = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE pii_purged=TRUE"
        ).fetchone()[0]
        expiring = conn.execute(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE retention_expires_at <= ? AND retention_expires_at > ?
              AND pii_purged = FALSE
              AND (input_has_pii = TRUE OR output_has_pii = TRUE)
            """,
            (future_30, today),
        ).fetchone()[0]
        oldest = conn.execute("SELECT MIN(timestamp) FROM audit_log").fetchone()[0]

    total = stats["total"]
    with_pii = stats["with_pii"]
    pct_pii = round(with_pii / total * 100, 1) if total > 0 else 0.0
    por_agente = {r["agent_name"]: r["cnt"] for r in agent_rows}

    alertas: list[str] = []
    if expiring > 0:
        alertas.append(
            f"{expiring} registro(s) com PII expiram nos próximos 30 dias — "
            "execute purge_expired_pii() para remover dados pessoais."
        )
    if not alertas:
        alertas.append("Nenhum alerta de governança ativo")

    return {
        "periodo": "últimos 30 dias",
        "metricas": {
            "total_consultas": total,
            "consultas_com_pii": with_pii,
            "percentual_pii": pct_pii,
            "por_classificacao": {
                "public": stats["pub"], "internal": stats["internal"],
                "confidential": stats["conf"], "restricted": stats["restr"],
            },
            "por_agente": por_agente,
            "pii_por_tipo": {
                "cpf":   stats["cpf"],
                "name":  stats["name_cnt"],
                "money": stats["money"],
                "phone": phone_email["phone_cnt"] if phone_email else 0,
                "email": phone_email["email_cnt"] if phone_email else 0,
            },
        },
        "retencao": {
            "registros_com_pii":           retention_total,
            "registros_pii_purgados":      retention_purged,
            "registros_expirando_30_dias": expiring,
            "registro_mais_antigo":        oldest,
        },
        "alertas": alertas,
    }


@router.get("/audit-log")
async def audit_log_endpoint(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    classification: Optional[str] = None,
    agent: Optional[str] = None,
    has_pii: Optional[bool] = None,
) -> dict:
    """Paginated audit log. Never returns _original fields."""
    init_db()
    conditions: list[str] = []
    params: list = []

    if classification:
        conditions.append("data_classification = ?")
        params.append(classification)
    if agent:
        conditions.append("agent_name = ?")
        params.append(agent)
    if has_pii is not None:
        if has_pii:
            conditions.append("(input_has_pii = TRUE OR output_has_pii = TRUE)")
        else:
            conditions.append("(input_has_pii = FALSE AND output_has_pii = FALSE)")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * limit

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, session_id, timestamp, agent_name, action,
                   input_masked, output_masked,
                   input_has_pii, output_has_pii, pii_types_detected,
                   data_classification, provider, model, tokens_used,
                   chunks_count, retention_expires_at, pii_purged
            FROM audit_log {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
        "registros": [dict(r) for r in rows],
    }


@router.get("/retention-report")
async def retention_report() -> dict:
    """Data retention status report."""
    init_db()
    return await get_retention_report()
```

- [ ] **Step 2: Register the router in `main.py`**

Add the import and `include_router` call. In `src/api/main.py`, after the existing router registrations:

```python
from src.api.governance import router as governance_router

# ... existing include_router calls ...
app.include_router(governance_router)
```

The import block (top of `main.py`) gets:
```python
from src.api.governance import router as governance_router
```

And after the existing `app.include_router(evaluate_router)` line:
```python
app.include_router(governance_router)
```

- [ ] **Step 3: Quick smoke test (start the server and curl)**

```bash
uvicorn src.api.main:app --reload &
sleep 2
curl -s http://localhost:8000/governance/dashboard | python -m json.tool | head -20
curl -s "http://localhost:8000/governance/audit-log?limit=5" | python -m json.tool
curl -s http://localhost:8000/governance/retention-report | python -m json.tool
```
Expected: valid JSON with the correct keys from the spec.

Kill the server: `pkill -f uvicorn`

- [ ] **Step 4: Commit**

```bash
git add src/api/governance.py src/api/main.py
git commit -m "feat: add /governance/dashboard, /audit-log, /retention-report endpoints"
```

---

## Task 8: Update `src/api/templates/index.html` (privacy modal + PII notice + badge)

**Files:**
- Modify: `src/api/templates/index.html`

- [ ] **Step 1: Add CSS for privacy modal, PII notice, and classification badge**

Insert the following block inside `<style>` just before the closing `</style>` tag (after the `@media` block):

```css
        /* ── Privacy modal ───────────────────────────────── */
        .privacy-modal {
            position: fixed;
            inset: 0;
            background: rgba(12,11,10,0.92);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            backdrop-filter: blur(4px);
        }

        .privacy-content {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 32px 36px;
            max-width: 520px;
            width: 90%;
        }

        .privacy-content h2 {
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 1.2rem;
            color: var(--text);
            margin-bottom: 14px;
        }

        .privacy-content p {
            font-size: 0.81rem;
            color: var(--text-2);
            line-height: 1.75;
            margin-bottom: 10px;
        }

        .privacy-content ul {
            margin: 10px 0 14px 18px;
            font-size: 0.79rem;
            color: var(--text-2);
            line-height: 1.85;
        }

        .privacy-btn {
            background: var(--gold);
            color: #0c0b0a;
            border: none;
            border-radius: 8px;
            padding: 10px 26px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.68rem;
            letter-spacing: 0.08em;
            cursor: pointer;
            transition: background .18s;
        }

        .privacy-btn:hover { background: #d4b55c; }

        /* ── PII notice ──────────────────────────────────── */
        .pii-notice {
            margin-top: 10px;
            padding: 7px 12px;
            background: rgba(229,62,62,0.06);
            border: 1px solid rgba(229,62,62,0.22);
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.62rem;
            color: #e07070;
            letter-spacing: 0.02em;
        }

        /* ── Classification badge ────────────────────────── */
        .class-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.52rem;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            padding: 2px 7px;
            border-radius: 3px;
        }

        .class-badge.public       { background:rgba(150,150,150,.10); border:1px solid rgba(150,150,150,.25); color:#888; }
        .class-badge.internal     { background:rgba(91,155,213,.10);  border:1px solid rgba(91,155,213,.25);  color:#7ab3d8; }
        .class-badge.confidential { background:rgba(240,180,41,.10);  border:1px solid rgba(240,180,41,.30);  color:#f0b429; }
        .class-badge.restricted   { background:rgba(229,62,62,.10);   border:1px solid rgba(229,62,62,.28);   color:#e53e3e; }
```

- [ ] **Step 2: Add the privacy modal HTML**

Insert the following block inside `<body>` right after `<div id="app">` opens (before `<header>`):

```html
    <div id="privacy-modal" class="privacy-modal" style="display:none;">
        <div class="privacy-content">
            <h2>Aviso de Privacidade — ComplianceAgent</h2>
            <p>Este sistema registra as interações para fins de auditoria e compliance regulatório.</p>
            <ul>
                <li>Suas perguntas e as respostas geradas são armazenadas em log de auditoria</li>
                <li>Dados pessoais (CPF, nomes, valores) são automaticamente mascarados nos logs</li>
                <li>Dados pessoais são retidos por no máximo 1 ano, conforme política de retenção</li>
                <li>Metadados de auditoria são retidos por 5 anos (Art. 23, Resolução CMN 4.893)</li>
                <li>Os dados não são compartilhados com terceiros</li>
            </ul>
            <p>Ao continuar, você concorda com o processamento de dados conforme descrito acima.</p>
            <button class="privacy-btn" onclick="acceptPrivacy()">Aceitar e Continuar</button>
        </div>
    </div>
```

- [ ] **Step 3: Update the JavaScript**

Replace the entire `<script>` block with the updated version. The changes are:
1. Add `acceptPrivacy()` function and localStorage check at the top
2. Add `CLASS_LABEL` map
3. Add `buildClassBadge()` function
4. Update `buildRouteMeta()` to accept and render classification
5. Update `appendAgentResponse()` to read `pii_detected`/`data_classification` and render the PII notice

```javascript
<script>
    const msgs   = document.getElementById('messages');
    const input  = document.getElementById('question');
    const btn    = document.getElementById('send');
    let loading  = false;
    let currentProvider = 'ollama';

    // ── Privacy consent ──────────────────────────────────
    function acceptPrivacy() {
        localStorage.setItem('privacy_accepted', '1');
        document.getElementById('privacy-modal').style.display = 'none';
    }

    if (!localStorage.getItem('privacy_accepted')) {
        document.getElementById('privacy-modal').style.display = 'flex';
    }

    // ── Provider toggle ──────────────────────────────────
    function setProvider(p) {
        currentProvider = p;
        document.getElementById('btn-ollama').className = 'provider-btn' + (p === 'ollama' ? ' active' : '');
        document.getElementById('btn-claude').className = 'provider-btn' + (p === 'claude' ? ' active claude-active' : '');
    }

    // Load doc count on start
    fetch('/documents').then(r => r.json()).then(d => {
        const el = document.getElementById('doc-count');
        if (d.total > 0) el.textContent = d.total + ' DOC' + (d.total > 1 ? 'S' : '') + ' INDEXADOS';
    }).catch(() => {});

    // Auto-resize textarea
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 130) + 'px';
    });

    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    function useChip(el) {
        input.value = el.textContent.trim();
        input.dispatchEvent(new Event('input'));
        send();
    }

    function scrollDown() { msgs.scrollTop = msgs.scrollHeight; }

    function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    }

    function removeWelcome() {
        const w = document.getElementById('welcome');
        if (w) w.remove();
    }

    function appendUser(text) {
        removeWelcome();
        const d = document.createElement('div');
        d.className = 'msg user';
        d.innerHTML = `<div class="avatar">EU</div><div class="msg-body"><div class="bubble">${esc(text)}</div></div>`;
        msgs.appendChild(d);
        scrollDown();
    }

    function showTyping() {
        removeWelcome();
        const d = document.createElement('div');
        d.id = 'typing-msg';
        d.innerHTML = `
            <div class="avatar">⚖</div>
            <div class="msg-body">
                <div class="typing-bubble">
                    <div class="dot"></div><div class="dot"></div><div class="dot"></div>
                </div>
            </div>`;
        msgs.appendChild(d);
        scrollDown();
    }

    function hideTyping() { const t = document.getElementById('typing-msg'); if (t) t.remove(); }

    const ROUTE_META = {
        'KNOWLEDGE':       { cls: 'knowledge',      label: 'Regulatório'  },
        'DATA':            { cls: 'data',            label: 'Dados'        },
        'ACTION':          { cls: 'action',          label: 'Ação'         },
        'KNOWLEDGE+DATA':  { cls: 'knowledge-data',  label: 'Multi-Agente' },
    };

    const AGENT_LABEL = {
        'knowledge': 'knowledge',
        'data':      'data',
        'action':    'action',
    };

    const CLASS_LABEL = {
        'public':       'Público',
        'internal':     'Interno',
        'confidential': 'Confidencial',
        'restricted':   'Restrito',
    };

    function buildClassBadge(classification) {
        const cls   = classification || 'public';
        const label = CLASS_LABEL[cls] || cls;
        return `<span class="class-badge ${cls}">${esc(label)}</span>`;
    }

    function buildRouteMeta(routing, agents, classification) {
        const rm = ROUTE_META[routing] || { cls: 'knowledge', label: routing };
        const agentPills = (agents || []).map(a =>
            `<span class="agent-pill">${esc(AGENT_LABEL[a] || a)}</span>`
        ).join('');
        const classBadge = classification ? buildClassBadge(classification) : '';
        return `<div class="route-meta">
            <span class="route-badge ${rm.cls}">${esc(rm.label)}</span>
            ${agentPills}
            ${classBadge}
        </div>`;
    }

    function buildSources(fontes) {
        if (!fontes || fontes.length === 0) return '';
        const tags = fontes.map(f => {
            const clean = String(f).replace(/.*[\\/]/, '').replace(/\.pdf,/i, ',');
            return `<span class="src-tag">${esc(clean)}</span>`;
        }).join('');
        return `<div class="sources">${tags}</div>`;
    }

    function buildSqlBlock(dados) {
        if (!dados || !dados.sql) return '';
        const id = 'sql-' + Math.random().toString(36).slice(2);
        const rowLabel = dados.total != null ? `${dados.total} linha${dados.total !== 1 ? 's' : ''}` : '';
        return `<div class="sql-block" id="${id}">
            <div class="sql-header" onclick="document.getElementById('${id}').classList.toggle('open')">
                <span class="sql-label">SQL gerado</span>
                <span class="sql-rows-badge">${esc(rowLabel)}</span>
            </div>
            <pre class="sql-code">${esc(dados.sql)}</pre>
        </div>`;
    }

    function buildActions(acoes) {
        if (!acoes || acoes.length === 0) return '';
        const items = acoes.map(a => `<div class="action-item">${esc(a)}</div>`).join('');
        return `<div class="actions-list">${items}</div>`;
    }

    function appendAgentResponse(data) {
        const routing        = data.roteamento || 'KNOWLEDGE';
        const agents         = data.agentes_utilizados || [];
        const text           = data.resposta_final || '';
        const details        = data.detalhes_agentes || [];
        const piiDetected    = data.pii_detected || false;
        const classification = data.data_classification || 'public';

        let allFontes = [];
        let sqlBlock  = '';
        let actionsHtml = '';

        details.forEach(det => {
            if (det.fontes && det.fontes.length) allFontes = allFontes.concat(det.fontes);
            if (det.dados)  sqlBlock    = buildSqlBlock(det.dados);
            if (det.acoes && det.acoes.length) actionsHtml = buildActions(det.acoes);
        });

        allFontes = [...new Set(allFontes)];

        const piiNotice = piiDetected
            ? `<div class="pii-notice">🔒 Esta resposta contém dados pessoais protegidos pela LGPD. Uso restrito a fins de compliance.</div>`
            : '';

        const d = document.createElement('div');
        d.className = 'msg assistant';
        d.innerHTML = `
            <div class="avatar">⚖</div>
            <div class="msg-body">
                ${buildRouteMeta(routing, agents, classification)}
                <div class="bubble">${esc(text)}</div>
                ${sqlBlock}
                ${actionsHtml}
                ${piiNotice}
                ${buildSources(allFontes)}
            </div>`;
        msgs.appendChild(d);
        scrollDown();
    }

    function appendError(msg) {
        hideTyping();
        const d = document.createElement('div');
        d.className = 'msg assistant';
        d.innerHTML = `<div class="avatar">⚖</div><div class="msg-body"><div class="error-bubble">⚠ ${esc(msg)}</div></div>`;
        msgs.appendChild(d);
        scrollDown();
    }

    async function send() {
        const q = input.value.trim();
        if (!q || loading) return;

        loading = true;
        btn.disabled = true;
        input.value = '';
        input.style.height = 'auto';

        appendUser(q);
        showTyping();

        try {
            const res = await fetch('/agent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pergunta: q, provider: currentProvider })
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            hideTyping();
            appendAgentResponse(data);
        } catch (err) {
            appendError(
                currentProvider === 'claude'
                    ? 'Erro ao obter resposta do Claude. Verifique se ANTHROPIC_API_KEY está configurado.'
                    : 'Não foi possível obter resposta. Verifique se o Ollama está em execução (ollama serve).'
            );
        } finally {
            loading = false;
            btn.disabled = false;
            input.focus();
        }
    }
</script>
```

- [ ] **Step 4: Verify in browser**

Start the server and open `http://localhost:8000` in a browser.

```
uvicorn src.api.main:app --reload
```

Check:
1. Privacy modal appears on first visit — click "Aceitar e Continuar" → modal dismisses
2. Refresh the page — modal does NOT appear again (localStorage key set)
3. Ask a knowledge question (e.g. "O que é compliance?") — grey `Público` badge visible
4. Ask a data question with a client name (e.g. "Transações do Roberto Alves Costa?") — red `Restrito` badge + 🔒 notice visible

- [ ] **Step 5: Commit**

```bash
git add src/api/templates/index.html
git commit -m "feat: add privacy modal, PII notice, and classification badge to UI"
```

---

## Task 9: Write integration tests `tests/test_governance_api.py`

**Files:**
- Create: `tests/test_governance_api.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_governance_api.py
"""Integration tests for the /governance/* endpoints via FastAPI TestClient."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.setup import _DDL


@pytest.fixture
def gov_client():
    """TestClient backed by an in-memory SQLite DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()

    @contextmanager
    def fake_get_db():
        yield conn

    patches = [
        patch("src.governance.audit.get_db",      fake_get_db),
        patch("src.governance.retention.get_db",  fake_get_db),
        patch("src.api.governance.get_db",        fake_get_db),
        patch("src.database.seed.init_db",        lambda: None),
        patch("src.database.setup.get_db",        fake_get_db),
    ]
    for p in patches:
        p.start()

    yield TestClient(app), conn

    for p in patches:
        p.stop()
    conn.close()


def _insert_audit_row(conn, *, agent="knowledge", classification="public",
                      input_has_pii=False, output_has_pii=False,
                      input_masked="pergunta", output_masked="resposta",
                      input_original="pergunta", output_original="resposta",
                      retention_expires_at="2031-01-01"):
    conn.execute(
        """INSERT INTO audit_log (
            session_id, timestamp, agent_name, action,
            input_original, input_masked, output_original, output_masked,
            input_has_pii, output_has_pii, data_classification,
            retention_expires_at, pii_purged
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,FALSE)""",
        ("sid1", datetime.utcnow().isoformat(), agent, f"route:{agent.upper()}",
         input_original, input_masked, output_original, output_masked,
         1 if input_has_pii else 0, 1 if output_has_pii else 0,
         classification, retention_expires_at),
    )
    conn.commit()


class TestDashboard:
    def test_returns_200(self, gov_client):
        client, _ = gov_client
        assert client.get("/governance/dashboard").status_code == 200

    def test_required_top_level_keys(self, gov_client):
        client, _ = gov_client
        data = client.get("/governance/dashboard").json()
        assert "periodo" in data
        assert "metricas" in data
        assert "retencao" in data
        assert "alertas" in data

    def test_metricas_keys(self, gov_client):
        client, _ = gov_client
        m = client.get("/governance/dashboard").json()["metricas"]
        for key in ("total_consultas", "consultas_com_pii", "percentual_pii",
                    "por_classificacao", "por_agente", "pii_por_tipo"):
            assert key in m, f"Missing key: {key}"

    def test_alertas_no_alert_when_empty(self, gov_client):
        client, _ = gov_client
        alertas = client.get("/governance/dashboard").json()["alertas"]
        assert alertas == ["Nenhum alerta de governança ativo"]


class TestAuditLog:
    def test_empty_returns_zero_total(self, gov_client):
        client, _ = gov_client
        data = client.get("/governance/audit-log").json()
        assert data["total"] == 0
        assert data["registros"] == []

    def test_pagination_works(self, gov_client):
        client, conn = gov_client
        for i in range(5):
            _insert_audit_row(conn, agent="knowledge")
        data = client.get("/governance/audit-log?page=1&limit=2").json()
        assert len(data["registros"]) == 2
        assert data["total"] == 5
        assert data["pages"] == 3

    def test_filter_by_classification(self, gov_client):
        client, conn = gov_client
        _insert_audit_row(conn, classification="restricted")
        _insert_audit_row(conn, classification="public")
        data = client.get("/governance/audit-log?classification=restricted").json()
        assert data["total"] == 1
        assert data["registros"][0]["data_classification"] == "restricted"

    def test_filter_by_agent(self, gov_client):
        client, conn = gov_client
        _insert_audit_row(conn, agent="data")
        _insert_audit_row(conn, agent="knowledge")
        data = client.get("/governance/audit-log?agent=data").json()
        assert data["total"] == 1

    def test_original_fields_never_returned(self, gov_client):
        """The _original fields must never appear in the audit-log response."""
        client, conn = gov_client
        _insert_audit_row(conn, input_has_pii=True,
                          input_original="Roberto Alves Costa",
                          input_masked="[NOME_MASCARADO]")
        data = client.get("/governance/audit-log").json()
        record = data["registros"][0]
        assert "input_original" not in record
        assert "output_original" not in record
        assert record["input_masked"] == "[NOME_MASCARADO]"

    def test_has_pii_filter_true(self, gov_client):
        client, conn = gov_client
        _insert_audit_row(conn, input_has_pii=True)
        _insert_audit_row(conn, input_has_pii=False)
        data = client.get("/governance/audit-log?has_pii=true").json()
        assert data["total"] == 1


class TestRetentionReport:
    def test_returns_200(self, gov_client):
        client, _ = gov_client
        assert client.get("/governance/retention-report").status_code == 200

    def test_correct_structure(self, gov_client):
        client, _ = gov_client
        data = client.get("/governance/retention-report").json()
        for key in ("total_records", "records_with_pii", "records_pii_purged",
                    "records_expiring_30_days", "storage_by_classification"):
            assert key in data, f"Missing key: {key}"

    def test_counts_with_pii(self, gov_client):
        client, conn = gov_client
        _insert_audit_row(conn, input_has_pii=True)
        _insert_audit_row(conn, input_has_pii=False)
        data = client.get("/governance/retention-report").json()
        assert data["total_records"] == 2
        assert data["records_with_pii"] == 1
```

- [ ] **Step 2: Run the integration tests**

```
pytest tests/test_governance_api.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Run the full test suite to check for regressions**

```
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all tests pass (or only pre-existing failures).

- [ ] **Step 4: Commit**

```bash
git add tests/test_governance_api.py
git commit -m "test: add integration tests for governance API endpoints"
```

---

## Task 10: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the governance system section**

Find the `## Module Status Tracker` table and add the new entries:

```markdown
| src/governance/pii_detector.py | ✅ Done |
| src/governance/audit.py | ✅ Done |
| src/governance/retention.py | ✅ Done |
| src/api/governance.py | ✅ Done |
```

Find the `### Phase 4 — Governance & Observability [FUTURE]` section and update its status to `[CURRENT]`. Add a description of what was built:

```markdown
### Phase 4 — Governance & Observability [CURRENT]

LGPD compliance layer for the multi-agent pipeline.

Components:
- `src/governance/pii_detector.py` — Regex-based detection + masking for CPF, names, monetary values ≥ R$10k, phones, emails. Two mask levels: PARTIAL (user-facing) and FULL (audit logs).
- `src/governance/audit.py` — Session ID generation, sensitivity classification (public/internal/confidential/restricted), retention expiry calculation, `log_interaction()` writes to `audit_log` and updates `governance_daily_stats`.
- `src/governance/retention.py` — `purge_expired_pii()` overwrites PII fields with `[DADO_EXPIRADO]` (rows preserved for 5-year regulatory audit trail). `get_retention_report()` for dashboard.
- `src/api/governance.py` — `GET /governance/dashboard` (30-day metrics), `GET /governance/audit-log` (paginated, masked), `GET /governance/retention-report`.
- `src/api/templates/index.html` — Privacy modal (localStorage), 🔒 PII notice footer, data classification badge.

Key invariant: user-facing responses are NEVER masked. Only `audit_log` stores masked text.

New API endpoints:
- `GET /governance/dashboard` — aggregate metrics, PII type breakdown, retention status
- `GET /governance/audit-log?page=&limit=&classification=&agent=&has_pii=` — masked log entries
- `GET /governance/retention-report` — purge candidates and classification breakdown
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Phase 4 governance system documentation"
```

---

## Final Verification

After all tasks complete, run the full test flow from the spec:

```bash
# Start the server (with Ollama running)
uvicorn src.api.main:app --reload &

# 1. Data query with PII → expect pii_detected=true, classification=restricted
curl -s -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Quais transações do Roberto Alves Costa não foram reportadas ao COAF?"}' \
  | python -m json.tool | grep -E "pii_detected|data_classification|session_id"

# 2. Check audit log — PII should be masked
curl -s "http://localhost:8000/governance/audit-log?limit=1" \
  | python -m json.tool | grep -E "MASCARADO|Roberto"

# 3. Governance dashboard
curl -s http://localhost:8000/governance/dashboard | python -m json.tool

# 4. Knowledge query → expect pii_detected=false, classification=public
curl -s -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Qual o prazo da Resolução 5.274?"}' \
  | python -m json.tool | grep -E "pii_detected|data_classification"

# 5. Retention report
curl -s http://localhost:8000/governance/retention-report | python -m json.tool
```
