import csv
import json
import os
import re

def normalize_name(name: str) -> str:
    """
    Normalizes company names by converting to lowercase, stripping whitespace,
    and removing common legal suffixes to improve matching recall.
    """
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r'\b(llc|inc|co|corp|gmbh|ltd|limited|incorporated)\b', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def find_company_record(company_name: str, mock_data: dict) -> tuple[dict | None, str]:
    """
    Implements Three-Tier Matching Logic:
    Tier 1: Exact Match
    Tier 2: Normalized/Suffix-stripped Match
    Tier 3: Substring/Intersection Match (Fallback)
    """
    if company_name in mock_data:
        return mock_data[company_name], "exact"
        
    target_norm = normalize_name(company_name)
    for key in mock_data.keys():
        if normalize_name(key) == target_norm:
            return mock_data[key], "normalized"
            
    for key in mock_data.keys():
        key_norm = normalize_name(key)
        if target_norm in key_norm or key_norm in target_norm:
            return mock_data[key], "substring"
            
    return None, "no_match"

def resolve_persona_and_provenance(record: dict) -> tuple[str | None, str | None, str | None, str | None, list, set]:
    """
    Extracts the best contact identity and communication channels from available blocks.
    Returns: (name, role, email, phone, provenance_list, unique_blocks_set)
    """
    resolved_name = None
    resolved_role = None
    provenance_sources = []
    unique_blocks = set()
    
    registry = record.get("registry", {}) or {}
    listing = record.get("listing", {}) or {}
    enrichment = record.get("enrichment", {}) or {}
    
    # 1. Harvest candidates safely across existing blocks
    candidates = []
    for block_data, block_name in [(registry, "registry"), (listing, "listing"), (enrichment, "enrichment")]:
        name = block_data.get("name") or block_data.get("contact_person") or block_data.get("contact_name")
        role = block_data.get("role") or block_data.get("contact_role")
        
        if name:
            candidates.append({
                "name": name,
                "role": role if role else "Designated Contact",
                "source": block_name,
                "has_explicit_role": bool(role)
            })
            
    if candidates:
        # Identity Resolution Strategy: Prioritize explicit roles, use registry as tie-breaker
        candidates.sort(key=lambda x: (not x["has_explicit_role"], x["source"] != "registry"))
        best_match = candidates[0]
        
        resolved_name = best_match["name"]
        resolved_role = best_match["role"]
        provenance_sources.append(f"{best_match['source']}[name,role]")
        unique_blocks.add(best_match["source"])

    # 2. Extract communication channels directly from source primitives
    email = enrichment.get("email") or registry.get("email") or listing.get("email")
    phone = listing.get("phone") or enrichment.get("phone") or registry.get("phone")
    
    if email:
        src = "enrichment" if enrichment.get("email") else ("registry" if registry.get("email") else "listing")
        provenance_sources.append(f"{src}[email]")
        unique_blocks.add(src)
    if phone:
        src = "listing" if listing.get("phone") else ("enrichment" if enrichment.get("phone") else "registry")
        provenance_sources.append(f"{src}[phone]")
        unique_blocks.add(src)
        
    # Deduplicate provenance while strictly maintaining insertion order for deterministic audits
    ordered_provenance = list(dict.fromkeys(provenance_sources))
        
    return resolved_name, resolved_role, email, phone, ordered_provenance, unique_blocks

def enforce_confidence_and_gating(
    match_tier: str, 
    unique_blocks: set, 
    resolved_name: str | None,
    email: str | None, 
    phone: str | None
) -> tuple[str, int, bool]:
    """
    Computes confidence score matching original PLAN.md heuristics + completeness boosts.
    Enforces absolute hard-blanking policy if score < 70 or on safety overrides.
    """
    has_email = bool(email)
    has_phone = bool(phone)
    
    # Gate 1: Immediate failures (No match or completely missing contact channels)
    # Note: len(unique_blocks) == 0 is conceptually redundant with channel checks, but kept
    # as a defensive invariant in case future schemas introduce blocks with non-contact data.
    if match_tier == "no_match" or not (has_email or has_phone) or len(unique_blocks) == 0:
        return "", 0, True
        
    # Heuristic Base Score based on provider consensus
    score = 75 if len(unique_blocks) > 1 else 40
    
    # Completeness Boosts
    if has_email and has_phone:
        score += 15
    else:
        score += 5
        
    if match_tier == "substring":
        score -= 15
        
    score = max(0, min(score, 100))
    
    # Gate 2: Strict Overrides for High False-Positive Risk categories
    # - Confidence drops below threshold (< 70)
    # - Substring tier (identity accuracy is unverified)
    # - Nameless contacts (insufficient depth for B2B payment outreach workflows)
    if score < 70 or match_tier == "substring" or not resolved_name:
        needs_review = True
        contact_value = ""  # Total suppression to safeguard against data leakage
    else:
        needs_review = False
        # Design Decision: Email is preferred over phone as it provides a less
        # intrusive, highly durable channel for automated accounts receivable logic.
        contact_value = email if email else phone
        
    return contact_value, score, needs_review

def process_contact_finder(input_csv_path, output_csv_path, mock_json_path):
    """
    Core pipeline orchestrator reading input companies, resolving identities,
    scoring results, and writing compliant output.
    """
    if os.path.exists(mock_json_path):
        with open(mock_json_path, 'r', encoding='utf-8') as f:
            mock_data = json.load(f)
    else:
        mock_data = {}

    results = []
    
    with open(input_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_company = row['company_name']
            raw_address = row['mailing_address']
            
            record, match_tier = find_company_record(raw_company, mock_data)
            
            if record:
                res_name, res_role, email, phone, prov, blocks = resolve_persona_and_provenance(record)
                contact_val, conf_score, review_flag = enforce_confidence_and_gating(
                    match_tier, blocks, res_name, email, phone
                )
            else:
                res_name, res_role, contact_val, conf_score, prov, review_flag = None, None, "", 0, [], True
                
            results.append({
                'company_name': raw_company,
                'mailing_address': raw_address,
                'contact_name': res_name if res_name else "",
                'contact_role': res_role if res_role else "",
                'contact_email_or_phone': contact_val if contact_val else "",
                'confidence_score': conf_score,
                'source': ", ".join(prov) if prov else "NONE",
                'needs_human_review': str(review_flag).lower()
            })
            
    fieldnames = [
        'company_name', 'mailing_address', 'contact_name', 'contact_role', 
        'contact_email_or_phone', 'confidence_score', 'source', 'needs_human_review'
    ]
    
    with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        writer.writerows(results)    

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    input_csv = os.path.join(base_dir, 'data', 'companies.csv')
    output_csv = os.path.join(base_dir, 'output_contacts.csv')
    mock_json = os.path.join(base_dir, 'mocks', 'enrichment_responses.json')
    
    print("[*] Launching AgentCollect Pipeline...")
    process_contact_finder(input_csv, output_csv, mock_json)
    print(f"[+] Enrichment Finished. Safe output written to: {output_csv}")