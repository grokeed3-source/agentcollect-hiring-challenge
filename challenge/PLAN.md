# Solution Plan: Contact Finder Challenge

## 1. Proposed Architecture
I will structure the system as a decoupled, sequential data pipeline built for high throughput and strict data integrity. 

[CSV Ingestion] ──> [Data Normalization] ──> [Parallel Mock Querying] ──> [Resolution & Scoring] ──> [Output Generator]


* **Ingestion & Normalization:** Read `companies.csv` and strip common legal suffixes (e.g., LLC, Inc., Co.) from `company_name` to optimize lookup matching while preserving original metadata.
* **Parallel Lookup Engine:** Trigger concurrent asynchronous workers to query the mock providers in parallel using the normalized company identifiers.
* **Entity Resolution Layer:** Deduplicate and aggregate all incoming provider responses per row, evaluating them against our target decision-maker hierarchy.
* **Output Generation:** Emit the final required schema schema mapping directly to the output variables, explicitly marking edge cases.

---

## 2. Sources & Strategy
Since no single source guarantees 100% accuracy, we will combine data from the mock providers:
* **Firmographic Mock Data:** To extract baseline organization maps and identity executive/owner names.
* **Contact Directory Mocks:** To resolve matching names to actual communication channels (`email` or `phone`).
* **Registry Mocks:** To verify physical location alignment against the provided `mailing_address`.

---

## 3. Quality, Confidence & Provenance
* **Deduplication:** Contacts will be deduplicated by hashing normalized emails or phone numbers. If a duplicate exists, the higher-ranking job title is retained.
* **Confidence Scoring (0-100 Logic):** 
  * *Base Score:* A single source match starts at a base score of **40**. Multi-source alignment (e.g., two mock providers agreeing on the same contact) jumps the score to **75**.
  * *Address Anchor:* If the mock registry's address fragment matches our input `mailing_address`, add **+15**.
  * *Completeness:* Having both a verified email AND phone number adds **+10**.
* **Provenance:** Every field in the output will maintain a strict lineage tracker array (e.g., `source: ["mock_provider_a", "mock_provider_b"]`) so every record is completely traceable.
* **"Cannot-Verify" State:** If no contacts are returned, or if the calculated confidence score falls below the required operational threshold, the system will gracefully set all contact fields to `null` and explicitly flag `needs_human_review: true`. We embrace missing data over fake data.

---

## 4. Privacy & Compliance
* **DOs:** Ensure strict data boundaries, validate input safety, and only process data provided by the mock endpoints.
* **DONTs:** We will not perform unauthorized external scraping, store persistent PII unencrypted, or infer or guess personal details without verifiable provenance.

---

## 5. Clarifying Questions

### Question 1: What is the exact operational Confidence Threshold required to safely skip human review, and what is the penalty hierarchy for a False Positive vs. a False Negative?
* **Why it matters:** It defines the mathematical boundary for setting `needs_human_review`.
* **Default Assumption:** I assume a strict threshold of **70/100**, assuming that a False Positive (sending collection messages to the wrong person) is highly damaging to customer retention and brand reputation.
* **Design Impact:** If False Positives are heavily penalized, our scoring engine will default to a highly conservative state, routing more records to manual human review.

### Question 2: If multiple valid decision-makers are recovered for a single company, what is the exact execution priority ranking among roles?
* **Why it matters:** If we discover both an Owner and an AP Manager, the system needs to know who to prioritize in the single output row.
* **Default Assumption:** I assume a target hierarchy of: **Owner/Founder > CFO > AP Manager > Office Manager**.
* **Design Impact:** The entity resolution module will implement a deterministic sort based on this array, filtering out lower-priority roles if a higher-ranking economic decision-maker exists.

### Question 3: How flexible should the address matching logic be when correlating the input `mailing_address` with mock registry data?
* **Why it matters:** Input CSV address formats can be highly inconsistent or missing unit/suite details.
* **Default Assumption:** I assume the mock providers will allow flexible or partial string matching rather than requiring absolute character-by-character parity.
* **Design Impact:** If exact matching is required, I will implement a regex-based address parsing module to split the string into street, city, and zip vectors before querying.