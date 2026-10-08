# Design Review — Etapa 1: Titular v7 (Revisão 3)

Reviewer: fresh-eyes design-gate subagent. The design document was read without
the context that produced it, and every load-bearing claim was checked against
the real source tree at `c:\Users\Gustavo\Desktop\RFC\bootcamp-repo\.worktrees\etapa-1-titular-v7`
and the v7 schema at `database/database.sql`.

Verdict: **CHANGES_REQUESTED** (1 HIGH + 2 MEDIUM; also 3 NIT).

The design is unusually thorough and most of its claims verify cleanly against
the code — the generated-column treatment, the error-code range, the fee seeds,
the `no_autoflush` behavior, the KYC mock, and the N-accounts propagation audit
are all correct. The blocking findings are a concrete code path the propagation
audit misclassified as "unchanged" (HIGH), a schema-vs-controller contradiction
in the PATCH flow (MEDIUM), and an under-specified test-harness fan-out that the
design itself flags as "important but open" (MEDIUM).

---

## Findings

### 1. HIGH — `TransferController._pix_manual_fields` reads removed v6 attributes; propagation audit misclassifies it as "não muda"

**Where:** design §1.2 ("Propagação de N contas"), bullet 4, and §1.8; vs.
`src/controllers/transfer_controller.py` `_pix_manual_fields` (around line 143):

```python
holder = destination.customer
holder_document = holder.cnpj if holder.type == Customer.MEI else holder.cpf
if target["document"] != holder_document:
    raise InvalidTargetAccount("document does not match the account holder")
```

The design's §1.2 propagation list, item 4, says:

> `TransferController._pix_manual_fields`/tarifas leem `source.customer`/`destination.customer` (lado N:1, **não muda**)

That sentence is only half true. The *cardinality* (account→customer, N:1) does
not change — but the *body* of `_pix_manual_fields` reads three attributes that
this etapa **removes** from the model: `holder.cnpj`, `holder.cpf`, and
`holder.type == Customer.MEI`. Once §1.2 deletes `cpf`/`type`/`cnpj`/`MEI`/`INDIVIDUAL`
from `Customer`, this code raises `AttributeError` on every manual Pix whose
destination is an on-us account — a 500, in a money path, not covered by any
section of the design.

§1.8 ("Tarifa por `fee_segment`") only rewrites the three `current_fee(...,
source.customer.type)` calls. It does **not** touch the destination-document
comparison in `_pix_manual_fields`. §1.7 (pix_key_controller) rewrites the
analogous `_own_key_data`/`_key_value` document logic, but `_pix_manual_fields`
lives in `transfer_controller.py` and is never addressed. So the single place in
the transfer controller that reads the holder's *document value* (not just the
segment) falls through the cracks.

**Concrete fix:** add an explicit item to §1.8 (or a new §1.8a) rewriting the
destination-document check in `_pix_manual_fields` to the v7 vocabulary, exactly
mirroring §1.7's `_key_value` decision:

```python
holder = destination.customer
if target["document"] != holder.document:
    raise InvalidTargetAccount("document does not match the account holder")
```

`document` is unique per holder in v7, so the `MEI`-vs-`INDIVIDUAL` branch
collapses to a single comparison. Also correct the §1.2 bullet 4 wording: the
cardinality is unchanged but the *vocabulary* reads inside `_pix_manual_fields`
**do** change (drop `.cnpj`/`.cpf`/`.type`/`Customer.MEI`), and add
`transfer_controller._pix_manual_fields` to the explicit list of touch points so
the implementer does not rely on "não muda".

---

### 2. MEDIUM — PATCH flow: controller `update_revenue` still passes `microcredit_eligible`, but §1.5 removes it from the repository signature — the two edits must land together or the PATCH path breaks

**Where:** design §1.5 (`customer_repository.update_revenue` "perde o parâmetro
`microcredit_eligible`" and `customer_controller` "remover ... as duas
computações `annual_revenue <= MICROCREDIT_REVENUE_CAP`"); vs. the real
`src/controllers/customer_controller.py` `update_revenue`:

```python
microcredit_eligible = annual_revenue <= MICROCREDIT_REVENUE_CAP
self.customer_repository.update_revenue(customer, annual_revenue, microcredit_eligible)
self.session.commit()
return CustomerDTO.obj_to_dict(customer)
```

and `src/repositories/customer_repository.py`:

```python
def update_revenue(self, customer, annual_revenue, microcredit_eligible) -> None:
    customer.annual_revenue = annual_revenue
    customer.microcredit_eligible = microcredit_eligible   # writes a GENERATED column -> IntegrityError
    customer.revenue_reference_date = func.current_date()
    customer.updated_at = func.now()
```

The design is internally consistent that `microcredit_eligible` becomes a
generated, read-only column and must be dropped from both the controller and the
repository `update_revenue`. The gap is in *sequencing specificity*: §1.5 states
the controller "adiciona um `flush` + `refresh` após `update_revenue`" and
later gives the create() sequence in full, but for `update_revenue` it only says
"espelha a sequência." It never states, as a hard rule, that the repository
signature change and the controller call-site change are a single atomic edit.
If an implementer applies the repository change (drop the param) but leaves the
controller passing three positional args — or vice-versa, leaves the repository
writing `customer.microcredit_eligible = ...` — the PATCH path either throws
`TypeError` (arity) or writes a GENERATED column (`IntegrityError`/`ProgrammingError`
-> 500). Because the design presents the `create` sequence verbatim but
`update_revenue` only "by analogy," this is the most likely place for a partial
edit to slip through.

**Concrete fix:** in §1.5, write the `update_revenue` controller sequence
verbatim the way `create` is written, and make the coupling explicit:

```
# repository: def update_revenue(self, customer, annual_revenue) -> None:
#   customer.annual_revenue = annual_revenue
#   customer.revenue_reference_date = func.current_date()
#   customer.updated_at = func.now()
#   (NEVER touch microcredit_eligible / fee_segment / exposure_customer_id)

# controller.update_revenue(raw_customer_id, annual_revenue):
1. customer = self._get_customer_or_raise(raw_customer_id)
2. self.customer_repository.update_revenue(customer, annual_revenue)   # NO microcredit_eligible arg
3. self.session.flush()
4. self.session.refresh(customer, ["microcredit_eligible", "fee_segment", "exposure_customer_id"])
5. self.session.commit()
6. return CustomerDTO.obj_to_dict(customer)
```

and add a one-line invariant: "the repository `update_revenue` arity change and
the controller call-site change ship in the same edit; neither compiles against
the old other half." Also confirm `MICROCREDIT_REVENUE_CAP` is deleted (per
finding 6 of the prior cycle) so the controller cannot recompute it.

---

### 3. MEDIUM — Test-harness fan-out (`create_customer_payload` → every caller passing `customer_type=`) is acknowledged but left unspecified; it will break the suite and the design gives no concrete migration

**Where:** design "Testabilidade" / "Harness" paragraph; vs.
`tests/utils/payload_generator.py` (`create_customer_payload(customer_type="INDIVIDUAL", cpf=..., cnpj=..., ...)`)
and `tests/utils/object_generator.py` (`create_active_account(customer_type="INDIVIDUAL", ...)` →
`PayloadGenerator.create_customer_payload(customer_type=customer_type)`).

Verified: `create_customer_payload` emits the v6 payload (`cpf`, `cnpj`, `type`)
and `object_generator.create_active_account` threads `customer_type` straight
into it. Every integration test that opens an account (account, pix, transfer,
card, microcredit flows) goes through this one factory. The design correctly
identifies this as "um ponto de propagação importante e parte do custo da etapa"
and says `object_generator.py` "também precisa de atualização" — but it stops at
"o implementador deve checar e atualizar," with no concrete new signature. Given
the design's own standard (it pins concrete signatures everywhere else — e.g.
`_initial_account_status`), leaving the single most widely-used test factory as
a prose "check and update" is an under-specification that will produce
inconsistent per-implementer choices (e.g. whether `customer_type` stays as a
param name mapping to `person_type`, or becomes `person_type`, and how `MEI`
callers map to `LEGAL + legal_nature=EI + owner_customer_id`).

Note the subtlety the design does not call out: a v6 `MEI` test customer maps to
*two* v7 customers (a NATURAL owner + a LEGAL/EI), because an EI requires an
existing NATURAL `owner_customer_id`. So `create_customer_payload(customer_type="MEI")`
cannot become a single v7 payload — the factory must either create the owner
first or expose a dedicated EI helper. This is exactly the kind of hidden
two-step the migration section (§1.9) spells out for data but the harness
section leaves implicit.

**Concrete fix:** pin the new factory contract in the Testabilidade section. For
example:

```python
# person_type in {"NATURAL","LEGAL"}; legal_nature in {None,"EI","SLU","LTDA"}
@staticmethod
def create_customer_payload(person_type="NATURAL", document=None, legal_nature=None,
                            owner_customer_id=None, birth_date="1990-05-17",
                            annual_revenue=12_000_000, is_pep=None) -> dict: ...
```

and state the migration rule for existing callers: `customer_type="INDIVIDUAL"`
→ `person_type="NATURAL"`; `customer_type="MEI"` → an EI helper
(`create_ei_with_owner(...)`) that first creates a NATURAL owner and returns a
`person_type="LEGAL", legal_nature="EI", owner_customer_id=<owner>` payload.
Name the files to touch (`payload_generator.py`, `object_generator.py`) and the
caller sites (grep `create_active_account(customer_type=`).

---

### 4. NIT — `CustomerDTO.obj_to_dict` currently calls `customer.birth_date.isoformat()` unconditionally; design says make it nullable but the GET-shape section does not restate it in the final contract list

**Where:** `src/dtos/customer_dto.py` `obj_to_dict` has
`"birth_date": customer.birth_date.isoformat()`. §1.5 DTO bullet correctly says
`birth_date` → `customer.birth_date.isoformat() if customer.birth_date else None`.
This is covered, so it is only a NIT: the final "contrato do GET" bullet list in
§1.5 enumerates the new/changed keys but could re-list `birth_date` as nullable
right next to `account_id`/`accounts` so the implementer applying the DTO rewrite
does not miss that one existing line that will `AttributeError` on a LEGAL
customer (`None.isoformat()`).

**Concrete fix:** add `birth_date` (nullable) to the explicit key list in the
GET-shape bullet, not only in the prose above it.

---

### 5. NIT — `GET /customers/{id}` embedded `accounts` list projection: `created_at` is used for ordering but excluded from the item shape; harmless but worth a one-word confirmation

**Where:** §1.5 DTO — the embedded `accounts` item is
`{account_id, branch, account_number, status, status_reason}`, and the relationship
is ordered by `Account.created_at`. The projection deliberately omits `created_at`
(and balances). This is a defensible choice and the design documents the "visão de
titular vs. visão de conta" rationale. NIT only: confirm no existing Fluxo-1 test
asserts `created_at` inside the customer GET body (the dedicated
`GET /customers/{id}/accounts` via `AccountDTO.obj_to_dict` does carry it).

**Concrete fix:** one line stating "no Fluxo-1 test reads `created_at` from the
customer GET body; the field lives only on the accounts endpoint" — or add it to
the thin projection if any does.

---

### 6. NIT — §1.5 says `check_kyc` "passa a receber `document`"; the mock's param is literally named `cpf` and the D-KYC-PJ claim depends on 11-vs-14 digit matching

**Where:** `src/utils/kyc_mock.py` `def check_kyc(cpf: str)` with
`KYC_REJECTED_CPFS = {"52998224725"}`. The design (§1.5 step 4 and D-KYC-PJ)
correctly reasons that passing a 14-digit CNPJ never matches the 11-digit CPF
set, so every LEGAL customer auto-approves. That reasoning is sound and verified.
NIT: the design says the controller "passa a receber `document`" into `check_kyc`
without noting that the mock's parameter is still named `cpf`. No behavior change
is needed, but calling `check_kyc(document)` against a param named `cpf` is a
readability trap. Optional: note that the mock param may be renamed to
`document` for clarity (pure rename, no logic change), or explicitly leave it as
intentional debt.

**Concrete fix:** one sentence either renaming the mock param to `document` (no
logic change) or explicitly flagging the name mismatch as accepted debt for this
etapa.

---

## Verified Assumptions (checked against real source)

1. **Generated columns are read-only and match the v7 expressions exactly.**
   `database/database.sql` `customer` table:
   `exposure_customer_id = COALESCE(owner_customer_id, id)`,
   `fee_segment = CASE WHEN person_type='NATURAL' OR legal_nature='EI' THEN 'INDIVIDUAL' ELSE 'BUSINESS' END`,
   `microcredit_eligible = (annual_revenue <= 36000000)`, all
   `GENERATED ALWAYS AS ... STORED`. The design transcribes all three verbatim and
   correctly treats them as `FetchedValue()` read-only columns never written by the app.

2. **All relevant CHECK/FK constraints exist as the design states:** `ck_document`,
   `ck_fields_by_person_type`, `ck_pep_natural`, `ck_ei_owner`, composite
   `fk_ei_owner (owner_customer_id, owner_person_type) -> customer(id, person_type)`,
   `ux_customer_person_type`, `ux_customer_exposure`, partial `ix_customer_owner`.
   Confirmed in the schema.

3. **`document` UNIQUE is inline and unnamed** (`document VARCHAR(14) NOT NULL UNIQUE`).
   The design's finding-4 remediation (name it `ux_customer_document`) is justified;
   Postgres would otherwise auto-name it `customer_document_key`. Verified the schema
   indeed leaves it anonymous while naming every other constraint.

4. **N accounts per customer in v7:** `account.customer_id` is **not** UNIQUE in the
   schema (only `ix_account_customer` partial index + `ux_account_customer UNIQUE (id, customer_id)`
   as a composite-FK target). The v6 model still declares `customer_id = Column(..., unique=True)`
   and `account = relationship(..., uselist=False)` — both confirmed present and
   needing the change the design describes.

5. **N-accounts propagation audit (`customer.account` singular):** grep confirms the
   only read of the 1:N side (`customer.account`) is in `src/dtos/customer_dto.py`
   (both `obj_to_dict` and `creation_to_dict`). The design's claim that this is the
   single touch point is correct.

6. **`AccountDTO.obj_to_dict` reads `account.customer.microcredit_eligible`** (N:1,
   unchanged) — confirmed; the design correctly says this does not change.

7. **Fee model vs. schema:** `src/models/fee.py` declares `customer_type`; the v7
   schema `fee` table uses `customer_segment`. Rename required, as the design states.

8. **Fee seeds (v7):** `INSERT INTO fee ... VALUES ('TEF','INDIVIDUAL',100),('TEF','BUSINESS',100),('PIX','INDIVIDUAL',0),('PIX','BUSINESS',0),('TED','INDIVIDUAL',1000),('TED','BUSINESS',1000)`.
   Matches the design's §1.8 behavior table exactly (TEF 100, PIX 0, TED 1000 both segments).

9. **Error-code range:** `src/errors/custom_errors.py` ends at `QIT001049`
   (`InvalidScheduleDate`); 001050/51/52 are free. `error_verification()` in
   `src/errors/base_error.py` raises on any duplicate code at boot. `CustomerAlreadyExists`
   (QIT001010, `__init__(field_name, value)`) and `PixKeyNotOwned` (QIT001041) exist
   as the design relies on. No microcredit code (QIT001053+) is introduced. All verified.

10. **`AccountRepository.create_for_customer`** uses `with self.session.no_autoflush:`
    with the exact comment about keeping the customer INSERT inside the controller's
    `try`, and **returns the account** — so the design's plan to thread the fresh
    `account` into `creation_to_dict(customer, account)` is feasible. Confirmed.

11. **`update_revenue` currently has no `flush`** (confirmed in repository) and
    `_violated_document` reads `error.orig.diag.constraint_name` against
    `UNIQUE_DOCUMENT_CONSTRAINTS` (confirmed in controller). Both as the design states.

12. **KYC mock** `check_kyc(cpf)` matches only against an 11-digit CPF set
    (`KYC_REJECTED_CPFS`), so a 14-digit CNPJ never rejects — the D-KYC-PJ
    "PJ always approved" claim is verified.

13. **`is_pep` semantics:** `ck_pep_natural CHECK (NOT is_pep OR person_type='NATURAL')`
    accepts `is_pep=false` for LEGAL and rejects `is_pep=true`. The design's choice to
    forbid `is_pep` entirely in the LEGAL JSON-Schema branch (400 before DB) is a
    stricter-but-safe superset of the DB rule. Verified against the schema.

14. **Account status enum** has exactly `REQUESTED, PENDING, ACTIVE, BLOCKED, REJECTED,
    CLOSED` (seed in schema). The design's NON_TERMINAL = {REQUESTED, PENDING, ACTIVE,
    BLOCKED} and terminal = {REJECTED, CLOSED} for QIT001051 is consistent with the
    schema.

## Unverified / Wrong Assumptions

1. **WRONG (finding 1):** "`_pix_manual_fields` ... lado N:1, **não muda**." The
   cardinality is unchanged, but the body reads `holder.cnpj`/`holder.cpf`/`holder.type ==
   Customer.MEI` — all removed by §1.2. This path needs an explicit rewrite the design
   omits.

2. **UNVERIFIED (acknowledged by the design, finding 3):** the exact content and full
   caller set of the test harness beyond `payload_generator.create_customer_payload` and
   `object_generator.create_active_account`. I confirmed those two emit/thread v6
   vocabulary; I did not enumerate every test module that calls them with
   `customer_type=`. The design leaves the new factory signature and the MEI→(NATURAL+EI)
   two-step unspecified.

3. **UNVERIFIED (out of this review's scope, low risk):** the migration staging tables
   (`migration_source_customer`, `migration_source_account`, `migration_pf_income`,
   `migration_log`) do not yet exist in `database/database.sql` — by design they are
   created by the IF/implementer before running `v6_to_v7_titular.sql`. The migration
   script itself does not exist yet (it is this etapa's deliverable), so its idempotency
   and `SUM(balance)` assertions could only be reviewed as a plan, not as code. The plan
   is internally unambiguous (MEI→PF+CNPJ, balances conserved via reponta-only + zero-balance
   PF account, D5 income as required input with `RAISE EXCEPTION` on absence, D6 CPF key
   ported). No blocking issue found in the specification; D-MIG-PFNAME remains an
   open product confirmation the design correctly flags as low-risk.

---

## Scope check

No scope creep beyond "titular v7 / Fluxo 1" was found. The design explicitly
excludes microcredit/jobs/invoice (Etapa 2/3), introduces no QIT001053+, and the
one DDL change outside the migration (naming `ux_customer_document`) is justified
and semantically inert. The three new routes (additional account, list accounts,
relationship) are all within Fluxo 1 of the RFC.
