# Fintech Lending Systems (LOS, LMS, LCS): Backend & Database Interview Guide

In fintech system design and backend database interviews, candidates are expected to demonstrate deep domain expertise in data integrity, transactional guarantees, schema normalization, concurrency control, and batch processing. Lending platforms consist of three primary core engines that cover the complete credit lifecycle:

1. **Loan Origination System (LOS)**: Handles customer onboarding, document ingestion, credit scoring integrations, underwriting workflows, and loan approval state transitions.
2. **Loan Management System (LMS)**: Serves as the system of record for active loans, managing amortization schedules, daily interest accruals, payment waterfall allocations, and double-entry general ledgers.
3. **Loan Collection System (LCS)**: Tracks delinquency, calculates Days Past Due (DPD), assigns loan accounts to recovery buckets, manages agent workflows, and processes settlement/write-off operations.

This guide details the architectural expectations, normalized SQL database schemas, real-world database queries, and concurrency strategies for all three lending subsystems.

---

## 1. Architectural Foundations of Lending Systems

When interviewers evaluate backend engineers for fintech roles, they focus heavily on four system design invariants:

* **ACID Compliance & Financial Accuracy**: Financial systems must enforce strong data consistency. Relational databases (e.g., PostgreSQL, MySQL) are the standard choice for core ledgers because foreign keys, unique constraints, and ACID transactions prevent orphan records or corrupted balances.
* **Double-Entry Bookkeeping**: Money is never created or destroyed; it is transferred between accounts. Every transaction must contain at least one debit entry and one credit entry where total debits equal total credits.
* **Idempotency**: API endpoints and background processing workers must handle duplicate network retries gracefully without executing duplicate loan disbursements or double-charging repayments.
* **Auditability & Immutable Logs**: Financial records should never undergo destructive updates (`DELETE` or direct `UPDATE` on historical transactions). Historical changes are preserved via append-only ledger entries or audit trail tables.

---

## 2. Loan Origination System (LOS): Schema & Query Engineering

### Core Responsibilities
The LOS manages the top-of-funnel customer journey. Key backend challenges include state machine management for application statuses, third-party credit bureau integration timeouts, and preventing duplicate application submissions.

### Normalized Database Schema (SQL DDL)

```sql
-- Borrowers Entity
CREATE TABLE borrowers (
    borrower_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    national_id VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Loan Applications Entity
CREATE TABLE loan_applications (
    application_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    borrower_id UUID NOT NULL REFERENCES borrowers(borrower_id),
    requested_amount NUMERIC(15, 2) NOT NULL CHECK (requested_amount > 0),
    tenure_months INT NOT NULL CHECK (tenure_months > 0),
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT' 
        CHECK (status IN ('DRAFT', 'SUBMITTED', 'UNDERWRITING', 'APPROVED', 'REJECTED', 'DISBURSED')),
    idempotency_key VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Underwriting & Credit Bureau Assessment
CREATE TABLE credit_assessments (
    assessment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES loan_applications(application_id),
    credit_score INT NOT NULL CHECK (credit_score BETWEEN 300 AND 850),
    debt_to_income_ratio NUMERIC(5, 2) NOT NULL,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('APPROVE', 'REJECT', 'MANUAL_REVIEW')),
    assessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Key Interview Queries & Backend Scenarios

#### Scenario A: Enforcing Idempotent Loan Application Submissions
To prevent a user from submitting multiple loan applications during a UI lag or network retry, backend systems combine an database unique constraint on `idempotency_key` with transactional locking.

```sql
-- Query: Idempotent Application Creation
INSERT INTO loan_applications (
    borrower_id, 
    requested_amount, 
    tenure_months, 
    status, 
    idempotency_key
)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 
    25000.00, 
    24, 
    'SUBMITTED', 
    'REQ_IDEM_KEY_987654321'
)
ON CONFLICT (idempotency_key) 
DO UPDATE SET updated_at = CURRENT_TIMESTAMP
RETURNING application_id, status, created_at;
```

#### Scenario B: Detecting Active Duplicate Applications
Interviewers frequently ask for queries that flag high-risk applicants attempting to open multiple loans within a 30-day window:

```sql
-- Query: Find applicants submitting > 1 application in 30 days
SELECT 
    b.borrower_id,
    b.national_id,
    COUNT(la.application_id) AS total_recent_applications,
    MAX(la.created_at) AS latest_application_date
FROM borrowers b
JOIN loan_applications la ON b.borrower_id = la.borrower_id
WHERE la.created_at >= NOW() - INTERVAL '30 days'
  AND la.status NOT IN ('REJECTED')
GROUP BY b.borrower_id, b.national_id
HAVING COUNT(la.application_id) > 1;
```

---

## 3. Loan Management System (LMS): Schema & Query Engineering

### Core Responsibilities
The LMS manages active loans post-disbursement. Its primary functions are maintaining amortization payment schedules, calculating daily interest accruals, executing repayment waterfalls, and logging transactions into immutable double-entry accounting ledgers.

### Normalized Database Schema (SQL DDL)

```sql
-- Disbursed Loans Entity
CREATE TABLE loans (
    loan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID UNIQUE NOT NULL REFERENCES loan_applications(application_id),
    principal_amount NUMERIC(15, 2) NOT NULL CHECK (principal_amount > 0),
    annual_interest_rate NUMERIC(5, 2) NOT NULL CHECK (annual_interest_rate >= 0),
    tenure_months INT NOT NULL CHECK (tenure_months > 0),
    outstanding_principal NUMERIC(15, 2) NOT NULL,
    loan_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' 
        CHECK (loan_status IN ('ACTIVE', 'CLOSED', 'DELINQUENT', 'WRITTEN_OFF')),
    disbursed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Amortization Schedule Entity
CREATE TABLE repayment_schedules (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id UUID NOT NULL REFERENCES loans(loan_id),
    installment_number INT NOT NULL,
    due_date DATE NOT NULL,
    principal_component NUMERIC(15, 2) NOT NULL,
    interest_component NUMERIC(15, 2) NOT NULL,
    total_installment NUMERIC(15, 2) NOT NULL,
    paid_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'PARTIAL', 'PAID', 'OVERDUE')),
    UNIQUE (loan_id, installment_number)
);

-- Payment Transactions
CREATE TABLE repayment_transactions (
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id UUID NOT NULL REFERENCES loans(loan_id),
    payment_amount NUMERIC(15, 2) NOT NULL CHECK (payment_amount > 0),
    payment_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    payment_mode VARCHAR(30) NOT NULL,
    transaction_reference VARCHAR(100) UNIQUE NOT NULL
);

-- Immutable Double-Entry Ledger
CREATE TABLE general_ledger (
    ledger_id BIGSERIAL PRIMARY KEY,
    transaction_id UUID REFERENCES repayment_transactions(transaction_id),
    account_name VARCHAR(50) NOT NULL, -- e.g., 'CASH_ACCOUNT', 'INTEREST_INCOME', 'PRINCIPAL_RECEIVABLE'
    entry_type VARCHAR(6) NOT NULL CHECK (entry_type IN ('DEBIT', 'CREDIT')),
    amount NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Key Interview Queries & Backend Scenarios

#### Scenario A: Concurrency Control in Repayment Processing (`SELECT ... FOR UPDATE`)
A classic interview question asks: *"How do you prevent race conditions when an automated recurring auto-debit job and a manual mobile app payment process the same EMI simultaneously?"*

**Solution**: Use database pessimistic locking inside an explicit ACID transaction block.

```sql
BEGIN;

-- 1. Lock the loan row to serialize incoming payment requests
SELECT outstanding_principal, loan_status 
FROM loans 
WHERE loan_id = 'e7b1a2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c' 
FOR UPDATE;

-- 2. Lock the oldest unpaid amortization schedule row
SELECT schedule_id, principal_component, interest_component, paid_amount, total_installment
FROM repayment_schedules
WHERE loan_id = 'e7b1a2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c' 
  AND status IN ('PENDING', 'PARTIAL', 'OVERDUE')
ORDER BY installment_number ASC
LIMIT 1
FOR UPDATE;

-- 3. Execute application logic to record repayment
INSERT INTO repayment_transactions (loan_id, payment_amount, payment_mode, transaction_reference)
VALUES ('e7b1a2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c', 1250.00, 'AUTO_DEBIT', 'TXN_REF_20261006_001');

-- 4. Update the amortization schedule status
UPDATE repayment_schedules
SET paid_amount = paid_amount + 1250.00,
    status = CASE 
        WHEN paid_amount + 1250.00 >= total_installment THEN 'PAID'
        ELSE 'PARTIAL'
    END
WHERE schedule_id = 'f1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c';

-- 5. Reduce the outstanding principal on the master loan
UPDATE loans
SET outstanding_principal = outstanding_principal - 1000.00 -- Principal portion
WHERE loan_id = 'e7b1a2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c';

COMMIT;
```

#### Scenario B: Repayment Waterfall Allocation
When a customer makes a partial or overpayment, payments must strictly follow the contractual waterfall sequence: **Penalties/Fees $\rightarrow$ Accrued Interest $\rightarrow$ Principal**.

```sql
-- Query: Fetch loan repayment breakdown and unpaid balances
SELECT 
    l.loan_id,
    SUM(rs.total_installment - rs.paid_amount) AS total_overdue_amount,
    SUM(rs.interest_component) AS total_unpaid_interest,
    SUM(rs.principal_component) AS total_unpaid_principal
FROM loans l
JOIN repayment_schedules rs ON l.loan_id = rs.loan_id
WHERE l.loan_id = 'e7b1a2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c'
  AND rs.status IN ('PENDING', 'PARTIAL', 'OVERDUE')
GROUP BY l.loan_id;
```

---

## 4. Loan Collection System (LCS): Schema & Query Engineering

### Core Responsibilities
The LCS monitors default risk once an installment passes its due date without payment. Key responsibilities include calculating Days Past Due (DPD), assigning loans into delinquency buckets (Bucket 1 to Bucket 6 / Write-off), distributing delinquent loans to recovery agents, and managing Promise-to-Pay (PTP) commitments.

### Normalized Database Schema (SQL DDL)

```sql
-- Delinquency Tracking Entity
CREATE TABLE delinquency_records (
    delinquency_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id UUID UNIQUE NOT NULL REFERENCES loans(loan_id),
    dpd_count INT NOT NULL DEFAULT 0,
    delinquency_bucket VARCHAR(20) NOT NULL DEFAULT 'CURRENT'
        CHECK (delinquency_bucket IN ('CURRENT', 'BUCKET_1', 'BUCKET_2', 'BUCKET_3', 'NPA', 'WRITE_OFF')),
    overdue_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    last_calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Collection Activity Logs & Agent Allocation
CREATE TABLE collection_cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id UUID NOT NULL REFERENCES loans(loan_id),
    assigned_agent_id UUID,
    case_status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (case_status IN ('OPEN', 'PTP_SET', 'SETTLED', 'CLOSED')),
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Promise to Pay (PTP) Commitments
CREATE TABLE promise_to_pay (
    ptp_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES collection_cases(case_id),
    promised_amount NUMERIC(15, 2) NOT NULL CHECK (promised_amount > 0),
    promised_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'KEPT', 'BROKEN')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Key Interview Queries & Backend Scenarios

#### Scenario A: Automated Daily DPD & Delinquency Bucket Calculation Batch Job
Interviewers often ask candidates to write the SQL script or batch logic executed nightly to update loan delinquency statuses across millions of records.

```sql
-- Query: Nightly DPD Batch Update
WITH loan_dpd_calculation AS (
    SELECT 
        l.loan_id,
        COALESCE(MAX(CURRENT_DATE - rs.due_date), 0) AS calculated_dpd,
        SUM(rs.total_installment - rs.paid_amount) AS total_overdue
    FROM loans l
    JOIN repayment_schedules rs ON l.loan_id = rs.loan_id
    WHERE rs.due_date < CURRENT_DATE
      AND rs.status IN ('PENDING', 'PARTIAL', 'OVERDUE')
      AND l.loan_status = 'ACTIVE'
    GROUP BY l.loan_id
)
INSERT INTO delinquency_records (loan_id, dpd_count, delinquency_bucket, overdue_amount, last_calculated_at)
SELECT 
    ldc.loan_id,
    ldc.calculated_dpd,
    CASE 
        WHEN ldc.calculated_dpd BETWEEN 1 AND 30 THEN 'BUCKET_1'
        WHEN ldc.calculated_dpd BETWEEN 31 AND 60 THEN 'BUCKET_2'
        WHEN ldc.calculated_dpd BETWEEN 61 AND 90 THEN 'BUCKET_3'
        WHEN ldc.calculated_dpd > 90 THEN 'NPA'
        ELSE 'CURRENT'
    END AS delinquency_bucket,
    ldc.total_overdue,
    CURRENT_TIMESTAMP
FROM loan_dpd_calculation ldc
ON CONFLICT (loan_id) 
DO UPDATE SET 
    dpd_count = EXCLUDED.dpd_count,
    delinquency_bucket = EXCLUDED.delinquency_bucket,
    overdue_amount = EXCLUDED.overdue_amount,
    last_calculated_at = CURRENT_TIMESTAMP;
```

#### Scenario B: Non-Performing Asset (NPA) Portfolio Summary Report
Fintech regulators require periodic reporting on loans where DPD $> 90$ days (NPA status).

```sql
-- Query: Risk Aggregation Matrix by Delinquency Bucket
SELECT 
    dr.delinquency_bucket,
    COUNT(dr.loan_id) AS total_delinquent_loans,
    SUM(dr.overdue_amount) AS total_overdue_balance,
    SUM(l.outstanding_principal) AS total_principal_at_risk
FROM delinquency_records dr
JOIN loans l ON dr.loan_id = l.loan_id
WHERE dr.delinquency_bucket != 'CURRENT'
GROUP BY dr.delinquency_bucket
ORDER BY dr.delinquency_bucket ASC;
```

---

## 5. Top 10 High-Frequency Fintech Backend Interview Questions & Model Answers

### Q1: How do you handle distributed transactions across independent microservices (e.g., LOS disbursing funds via a Bank Gateway in LMS)?
**Model Answer**: In distributed microservice architectures, traditional 2-Phase Commit (2PC) blocks resources and limits horizontal scalability. Instead, implement the **Saga Pattern** (Orchestrated or Choreographed) with compensating transactions:
1. LOS emits a `LoanApprovedEvent`.
2. LMS listens and creates a loan in `PENDING_DISBURSEMENT` state.
3. Payment Gateway Service attempts disbursement.
4. If successful, LMS transitions loan to `ACTIVE`. If the payment gateway fails permanently, a compensating event (`CancelLoanDisbursement`) rolls back the LMS record.

### Q2: How do you design an audit log for financial records that guarantees immutability?
**Model Answer**: Implement an append-only ledger pattern. Disallow `UPDATE` and `DELETE` permissions on database level for standard application database roles. Insert a cryptographic hash (e.g., SHA-256 of the previous entry + current transaction payload) into each row to construct a tamper-evident hash chain.

### Q3: When should a fintech company choose SQL vs NoSQL databases?
**Model Answer**:
* **SQL (PostgreSQL/MySQL)**: Used for core transactional systems (LOS, LMS, LCS, Ledgers) where ACID guarantees, strict foreign key constraints, complex JOIN queries, and multi-record consistency are required.
* **NoSQL (MongoDB/Redis/Cassandra)**: Used for high-throughput auxiliary features such as session management, real-time feature flag caching (Redis), storing raw unstructured KYC documents or loan application draft payloads (MongoDB), or high-volume telemetry activity logs (Cassandra).

### Q4: How do you maintain database performance when a `repayment_schedules` table grows to hundreds of millions of rows?
**Model Answer**:
1. **Range Partitioning**: Partition the table by date ranges (e.g., monthly partitions on `due_date`).
2. **Indexing Strategy**: Create composite indexes on `(loan_id, status)` and `(due_date, status)`.
3. **Archiving**: Move closed loans older than 5 years to analytical cold storage (e.g., Snowflake, BigQuery) while keeping hot operational data lean.

### Q5: How do you guarantee zero balance mismatch in double-entry bookkeeping ledgers?
**Model Answer**: Enforce a database check constraint or trigger ensuring that for every `transaction_id`, `SUM(debit_amount) - SUM(credit_amount) = 0`.

```sql
-- Validation Query inside transaction
SELECT transaction_id, 
       SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE -amount END) AS net_balance
FROM general_ledger
WHERE transaction_id = 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f'
GROUP BY transaction_id
HAVING SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE -amount END) != 0;
```
If the query returns any row, abort and rollback the transaction immediately.

### Q6: How do you handle interest calculation precision without floating-point rounding errors?
**Model Answer**: Never use floating-point types (`FLOAT`, `DOUBLE`) for financial balances due to IEEE 754 binary floating-point representation inaccuracies. Always use arbitrary-precision numeric types (`NUMERIC(15, 2)` or `DECIMAL(18, 4)` in SQL) or store balances as integer cents/smallest currency units in backend code (e.g., `$100.50` stored as `10050`).

### Q7: How do you handle third-party gateway timeouts during loan disbursement?
**Model Answer**: Treat timeouts as *Unknown* status rather than *Failure*. Enforce a two-step polling pattern:
1. Store transaction in `PENDING_VERIFICATION` state.
2. Trigger an asynchronous worker job to poll the payment provider's verification endpoint using the original `idempotency_key`.
3. Update local database status only after receiving definitive confirmation.

### Q8: What database isolation level is required for payment processing?
**Model Answer**: Use `READ COMMITTED` combined with explicit pessimistic locking (`SELECT ... FOR UPDATE`), or set the global transaction isolation level to `REPEATABLE READ` or `SERIALIZABLE` to eliminate phantom reads and non-repeatable reads during financial state transitions.

### Q9: How do you scale background batch jobs (like daily interest accrual across 10 million active loans)?
**Model Answer**:
1. **Keyset Pagination / Cursor-based Chunking**: Chunk loan records using sequential integer/UUID ranges (`WHERE loan_id > last_processed_id ORDER BY loan_id ASC LIMIT 1000`). Avoid offset pagination (`OFFSET 1000000`), which degrades performance.
2. **Distributed Queue Routing**: Push chunk identifiers to a message broker (e.g., RabbitMQ, Apache Kafka), allowing multiple worker nodes to process independent chunks concurrently.

### Q10: How do you ensure high availability without risking split-brain state in a multi-region fintech database setup?
**Model Answer**: Follow the CAP theorem for financial databases: prioritize **Consistency and Partition Tolerance (CP)** over Availability. Use single-leader synchronous replication across primary nodes or quorum consensus algorithms (e.g., Raft/Paxos in Spanner or CockroachDB) so that write transactions succeed only when quorum acknowledgement is achieved across data centers.
