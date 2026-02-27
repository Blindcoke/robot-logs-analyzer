# Error Classification Skill for Log Analyzer

Use this skill when classifying, labeling, or analyzing errors from system logs (e.g. `sample20.log`, `analysis_report.md`). It defines categories, severity levels, and how to map log fields to a consistent taxonomy.

---

## 1. Error categories

Classify each error into exactly one **category** based on `event` and `metadata.component` / `metadata.dependency`:

| Category        | Description                    | Typical `event` / `error_code` examples                    |
|----------------|--------------------------------|------------------------------------------------------------|
| **INFRASTRUCTURE** | DB, cache, or broker failures  | `DB_TIMEOUT`, `CONNECTION_TIMEOUT`, `CACHE_MISS`           |
| **QUEUE**      | Message queue overflow / backpressure | `QUEUE_OVERFLOW`, `QUEUE_FULL`                      |
| **AUTH**       | Authentication / authorization | `AUTH_FAILURE`, `INVALID_TOKEN`                           |
| **PERFORMANCE**| Slow operations, no hard failure | `SLOW_QUERY` (treat as WARN, not ERROR)                   |
| **EXTERNAL**   | Third-party or downstream API  | Timeouts or errors involving `stripe-api`, `user-service`  |
| **APPLICATION**| Business logic or app code     | Other application-level errors not matching above          |

---

## 2. Severity levels

Assign **severity** from log context and business impact:

| Severity | When to use |
|----------|-------------|
| **CRITICAL** | Service down, data loss risk, or security incident. Immediate page. |
| **HIGH**    | Core flow broken (e.g. payment, auth). Fix within hours. |
| **MEDIUM**  | Degraded experience or non-critical path. Fix within days. |
| **LOW**     | Minor or cosmetic. Fix when convenient. |

**Mapping hints:**

- `level == "ERROR"` + payment/auth path → usually **HIGH** (or CRITICAL if widespread).
- `QUEUE_OVERFLOW` / `QUEUE_FULL` in a critical service → **HIGH**.
- `DB_TIMEOUT` / `CONNECTION_TIMEOUT` in payment or auth → **HIGH**.
- `AUTH_FAILURE` / `INVALID_TOKEN` → **HIGH** (or CRITICAL if attack pattern).
- `SLOW_QUERY` only → **LOW** or **MEDIUM** (no hard failure).
- `CACHE_MISS` only → **LOW** unless it causes cascading failures.

---

## 3. Field-to-classification mapping

Use these log fields when classifying:

| Log field                | Use for |
|--------------------------|---------|
| `level`                  | Filter: only `ERROR` (and optionally `WARN`) for actionable errors. |
| `event`                  | Primary signal for category (e.g. `DB_TIMEOUT` → INFRASTRUCTURE). |
| `metadata.error_code`    | Refines category (e.g. `QUEUE_FULL`, `INVALID_TOKEN`). |
| `metadata.component`     | Area of system (database, message-queue, auth-service, etc.). |
| `metadata.dependency`    | Failing dependency (payment-db, rabbitmq, redis, auth-db). |
| `metadata.operation`    | Which operation failed (process_payment, validate_token, enqueue_task). |
| `metadata.duration_ms`   | For severity (e.g. long timeouts → worse impact). |
| `metadata.resource`      | High CPU/memory can elevate severity (e.g. resource exhaustion). |

---

## 4. Quick classification rules

- **QUEUE_OVERFLOW / QUEUE_FULL** → Category: **QUEUE**, Severity: **HIGH** (if critical service).
- **DB_TIMEOUT / CONNECTION_TIMEOUT** → Category: **INFRASTRUCTURE**, Severity: **HIGH** for payment/auth.
- **AUTH_FAILURE / INVALID_TOKEN** → Category: **AUTH**, Severity: **HIGH**.
- **CACHE_MISS** (no downstream failure) → Category: **INFRASTRUCTURE**, Severity: **LOW**.
- **SLOW_QUERY** only → Category: **PERFORMANCE**, Severity: **LOW** or **MEDIUM**.

---

## 5. Output format for classified errors

When producing a classified summary (e.g. for reports or dashboards), use a consistent line per error:

```text
[SEVERITY] CATEGORY | event=EVENT | error_code=CODE | component=COMPONENT | dependency=DEPENDENCY
```

Example:

```text
[HIGH] QUEUE | event=QUEUE_OVERFLOW | error_code=QUEUE_FULL | component=message-queue | dependency=rabbitmq
[HIGH] INFRASTRUCTURE | event=DB_TIMEOUT | error_code=CONNECTION_TIMEOUT | component=database | dependency=payment-db
[HIGH] AUTH | event=AUTH_FAILURE | error_code=INVALID_TOKEN | component=auth-service | dependency=auth-db
```

---

## 6. When to use this skill

- Adding or refining error taxonomy in the log analyzer.
- Generating summaries, dashboards, or alerts from `analysis_report.md` or raw logs.
- Implementing auto-tagging (e.g. scripts or prompts that assign category/severity from `event` and `metadata`).
- Reviewing or explaining why an error was classified as HIGH vs MEDIUM or QUEUE vs INFRASTRUCTURE.

Reference this SKILL when you need a single, project-level definition of error categories and severity for the log-analyzer project.
