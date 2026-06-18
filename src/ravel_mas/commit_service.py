"""Deterministic CommitService — the SOLE write path (Contract §4.5).

NOT an LLM. It is the only component that may execute real write tools, and it
does so only after deterministic validation against the ledger's actual read-set.
It checks BOTH the worker's declared referenced_evidence_ids AND the
middleware-recorded actual latest versions — it never trusts the model's claims
alone.

A real write executes iff verify() returns an AllowedCommitToken. Any attempt to
write without a valid token raises WriteIsolationError (env unchanged).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import sys
from pathlib import Path
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ravel_core.evidence import EvidenceLedger


class WriteIsolationError(RuntimeError):
    """Raised when a real write is attempted without a valid commit token."""


@dataclass(frozen=True)
class AllowedCommitToken:
    token: str
    action: str
    object_versions: dict[str, int]


@dataclass
class CommitDecision:
    verdict: str                       # commit | reconcile | replan | ask_user | abstain
    reasons: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    conflict: tuple[str, ...] = ()
    untraceable: tuple[str, ...] = ()
    token: Optional[AllowedCommitToken] = None

    @property
    def allowed(self) -> bool:
        return self.verdict == "commit" and self.token is not None


@dataclass(frozen=True)
class CandidateWriteMsg:
    action: str
    arguments: dict[str, Any]
    target_objects: tuple[str, ...]
    referenced_evidence_ids: tuple[str, ...] = ()
    claimed_preconditions: tuple[dict[str, Any], ...] = ()
    expected_versions: dict[str, int] = field(default_factory=dict)


class CommitService:
    """Deterministic transactional commit gate over the ledger."""

    def __init__(
        self,
        ledger: EvidenceLedger,
        *,
        write_tools: set[str],
        action_required_fields: Optional[dict[str, list[str]]] = None,
        real_write_executor: Optional[Callable[[str, dict], Any]] = None,
        enforce_version_check: bool = True,
        enforce_conflict_check: bool = True,
    ) -> None:
        self.ledger = ledger
        self.write_tools = set(write_tools)
        # action -> required field names (read-set schema)
        self.action_required_fields = action_required_fields or {}
        # callable that actually performs the env write; only CommitService holds it
        self._executor = real_write_executor
        # Production guards — mutation tests toggle these to prove they matter.
        self.enforce_version_check = enforce_version_check
        self.enforce_conflict_check = enforce_conflict_check
        self._issued_tokens: set[str] = set()
        self.decisions: list[CommitDecision] = []

    # -- the only tool set the service may run --
    @property
    def tools(self) -> set[str]:
        return set(self.write_tools)

    def verify(self, cw: CandidateWriteMsg) -> CommitDecision:
        """Deterministic validation. Returns a CommitDecision; on 'commit'
        attaches an AllowedCommitToken."""
        reasons: list[str] = []
        missing: list[str] = []
        stale: list[str] = []
        conflict: list[str] = []
        untraceable: list[str] = []

        if cw.action not in self.write_tools:
            dec = CommitDecision(verdict="abstain", reasons=("unknown_write_action",))
            self.decisions.append(dec)
            return dec

        required = self.action_required_fields.get(cw.action)
        committed_versions: dict[str, int] = {}

        for obj in cw.target_objects:
            latest_v = self.ledger.object_version(obj)
            if latest_v == 0:
                missing.append(f"{obj}:<no-evidence>")
                continue
            committed_versions[obj] = latest_v

            # expected version (worker's claim) must match current latest (no stale write)
            expected = cw.expected_versions.get(obj)
            if self.enforce_version_check and expected is not None and expected != latest_v:
                stale.append(f"{obj}:expected_v{expected}!=latest_v{latest_v}")

            # required-field presence + conflict check against latest record
            rec = self.ledger.latest(obj)
            if self.enforce_conflict_check and rec is not None and getattr(rec, "conflict_flag", False):
                conflict.append(f"{obj}:conflict_flag")
            if required:
                fields = dict(rec.field_values) if rec else {}
                for fld in required:
                    if fld not in fields:
                        missing.append(f"{obj}.{fld}")

        # VALUE-LEVEL conflict: each claimed precondition is checked against the
        # LATEST ledger value. If the world changed under the worker (worker relied
        # on status=confirmed but latest=cancelled) this is a real cross-agent
        # conflict, not merely a version-number mismatch.
        if self.enforce_conflict_check:
            for pre in cw.claimed_preconditions:
                oid = pre.get("object_id")
                fld = pre.get("field")
                op = pre.get("operator", "equals")
                claimed = pre.get("value")
                latest = self.ledger.latest_field(oid, fld) if oid and fld else None
                if latest is None:
                    missing.append(f"{oid}.{fld}:<no-evidence>")
                    continue
                _v, latest_val, _eid = latest
                holds = (latest_val == claimed) if op == "equals" else (latest_val != claimed)
                if not holds:
                    conflict.append(f"{oid}.{fld}:claimed={claimed}!=latest={latest_val}")

        # traceability: declared evidence must exist in the ledger (don't trust blindly)
        for ev in cw.referenced_evidence_ids:
            if self.ledger.get(ev) is None:
                untraceable.append(ev)

        if missing:
            reasons.append("missing_required_evidence")
        if stale:
            reasons.append("stale_read_set")
        if conflict:
            reasons.append("unresolved_conflict")
        if untraceable:
            reasons.append("untraceable_evidence")

        if stale or conflict:
            verdict = "reconcile"
        elif missing:
            verdict = "reconcile"
        elif untraceable:
            verdict = "replan"
        else:
            verdict = "commit"
            reasons.append("evidence_valid")

        token = None
        if verdict == "commit":
            tok = f"commit-{uuid.uuid4().hex[:12]}"
            self._issued_tokens.add(tok)
            token = AllowedCommitToken(token=tok, action=cw.action,
                                       object_versions=committed_versions)

        dec = CommitDecision(
            verdict=verdict, reasons=tuple(reasons),
            missing=tuple(missing), stale=tuple(stale),
            conflict=tuple(conflict), untraceable=tuple(untraceable),
            token=token,
        )
        self.decisions.append(dec)
        return dec

    def execute_write(self, cw: CandidateWriteMsg, token: Optional[AllowedCommitToken]) -> Any:
        """Execute the real write ONLY with a valid token issued by this service."""
        if token is None or token.token not in self._issued_tokens:
            raise WriteIsolationError(
                f"refused real write '{cw.action}': no valid commit token")
        if token.action != cw.action:
            raise WriteIsolationError("commit token action mismatch")
        # consume token (single use)
        self._issued_tokens.discard(token.token)
        if self._executor is not None:
            return self._executor(cw.action, dict(cw.arguments))
        return {"executed": cw.action, "arguments": dict(cw.arguments)}

    def submit(self, cw: CandidateWriteMsg) -> tuple[CommitDecision, Any]:
        """verify → if commit, execute; otherwise return decision without writing."""
        dec = self.verify(cw)
        if dec.allowed:
            result = self.execute_write(cw, dec.token)
            return dec, result
        return dec, None
