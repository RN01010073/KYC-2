CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(100),
    dob DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- DOCUMENTS TABLE
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    doc_type VARCHAR(20), -- PAN, AADHAAR, PASSPORT
    doc_number VARCHAR(50) UNIQUE,
    extracted_name VARCHAR(100),
    extracted_dob DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- KYC RECORDS TABLE
CREATE TABLE kyc_records (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    source VARCHAR(20), -- ekyc / offline
    status VARCHAR(20), -- Approved / Review / Rejected
    risk_score INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- VALIDATION LOGS
CREATE TABLE validation_logs (
    id SERIAL PRIMARY KEY,
    user_id INT,
    validation_status VARCHAR(20), -- Passed / Failed
    errors TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- DEDUPLICATION LOGS
CREATE TABLE dedup_logs (
    id SERIAL PRIMARY KEY,
    user_id INT,
    matched_user_id INT,
    match_type VARCHAR(50), -- PAN / NAME_DOB
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT * FROM users;
SELECT * FROM documents;
SELECT * FROM kyc_records;

-- ============================================================
-- eKYC FORM - DATABASE MIGRATION
-- Run this on your existing Postgres DB
-- Safe to run: all use ADD COLUMN IF NOT EXISTS
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- 1. USERS TABLE
--    Add all personal, contact, address, and financial fields
-- ────────────────────────────────────────────────────────────

-- Personal Details
ALTER TABLE users ADD COLUMN IF NOT EXISTS nationality     VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS gender          VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS marital_status  VARCHAR(20);

-- Contact Info
ALTER TABLE users ADD COLUMN IF NOT EXISTS mobile          VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email           VARCHAR(150);
ALTER TABLE users ADD COLUMN IF NOT EXISTS alternate_contact VARCHAR(20);

-- Permanent Address
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_address_line1 VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_address_line2 VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_city          VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_state         VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_pin           VARCHAR(10);
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_country       VARCHAR(100);

-- Current Address
ALTER TABLE users ADD COLUMN IF NOT EXISTS same_address       BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_address_line1 VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_address_line2 VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_city          VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_state         VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_pin           VARCHAR(10);
ALTER TABLE users ADD COLUMN IF NOT EXISTS curr_country       VARCHAR(100);

-- Financial & Additional Details
ALTER TABLE users ADD COLUMN IF NOT EXISTS occupation      VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS annual_income   VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS source_of_funds VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS pep_status      VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_purpose TEXT;


-- ────────────────────────────────────────────────────────────
-- 2. DOCUMENTS TABLE
--    Track which ID type was submitted and file paths
-- ────────────────────────────────────────────────────────────

ALTER TABLE documents ADD COLUMN IF NOT EXISTS id_proof_front_path  TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS id_proof_back_path   TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS address_proof_path   TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS income_proof_path    TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS selfie_path          TEXT;


-- ────────────────────────────────────────────────────────────
-- 3. KYC_RECORDS TABLE
--    No new columns needed — status/risk_score already exist
--    Adding ocr_processed flag for when OCR is plugged in later
-- ────────────────────────────────────────────────────────────

ALTER TABLE kyc_records ADD COLUMN IF NOT EXISTS ocr_processed BOOLEAN DEFAULT FALSE;


-- ────────────────────────────────────────────────────────────
-- VERIFY — quick sanity check after running migration
-- ────────────────────────────────────────────────────────────

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'documents'
ORDER BY ordinal_position;


ALTER TABLE documents ADD COLUMN extracted_aadhaar TEXT;
ALTER TABLE documents ADD COLUMN extracted_pan TEXT;
ALTER TABLE documents ADD COLUMN extracted_address TEXT;

SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'documents';
