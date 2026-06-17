import csv
import json
import os
import re

# 1. Load Mock Data
MOCKS_DIR = os.path.join(os.path.dirname(__file__), 'mocks')

def load_mock_json(filename):
    path = os.path.join(MOCKS_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

companies_registry = load_mock_json('companies_registry.json')
b2b_graph = load_mock_json('b2b_graph.json')
contact_directory = load_mock_json('contact_directory.json')

# Target Persona Hierarchy Priority mapping
PERSONA_PRIORITY = {
    'owner': 4, 'founder': 4,
    'cfo': 3, 'chief financial officer': 3,
    'ap manager': 2, 'accounts payable manager': 2,
    'office manager': 1
}

def normalize_company_name(name):
    """Strips legal suffixes to optimize matching vector"""
    if not name: return ""
    name = name.lower().strip()
    name = re.sub(r'\b(llc|inc|co|corp|gmbh|ltd|limited|incorporated)\b', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def calculate_score(has_address_match, aligned_sources, has_email, has_phone):
    """Deterministic Confidence Scoring Engine (0-100)"""
    score = 40  # Base score for a single match
    if aligned_sources > 1:
        score = 75  # Multi-source alignment boost
    
    if has_address_match:
        score += 15
    if has_email and has_phone:
        score += 10
    elif has_email or has_phone:
        score += 5
        
    return min(score, 100)

def process_contact_finder(input_csv_path, output_csv_path):
    results = []
    
    with open(input_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_company = row['company_name']
            raw_address = row['mailing_address']
            norm_company = normalize_company_name(raw_company)
            
            best_contact = None
            best_priority = -1
            sources_found = []
            address_matched = False
            
            # Step A: Check Registry for Address Anchor
            registry_entry = companies_registry.get(norm_company) or companies_registry.get(raw_company.lower().strip())
            if registry_entry:
                sources_found.append("companies_registry")
                reg_address = registry_entry.get('address', '').lower()
                # Partial match strategy for address parsing resilience
                if any(word in reg_address for word in raw_address.lower().split()[:3]):
                    address_matched = True
            
            # Step B: Fetch Organization Chart from B2B Graph
            graph_entry = b2b_graph.get(norm_company) or b2b_graph.get(raw_company.lower().strip())
            employees = []
            if graph_entry:
                sources_found.append("b2b_graph")
                employees = graph_entry.get('employees', [])
                
            # Step C: Resolve Identity & Hierarchy Matching
            for emp in employees:
                role = emp.get('role', '').lower()
                priority = 0
                for target_role, weight in PERSONA_PRIORITY.items():
                    if target_role in role:
                        priority = weight
                        break
                        
                if priority > best_priority:
                    best_priority = priority
                    best_contact = emp
                    
            # Step D: Enrich with Contact Directory
            contact_details = {}
            if best_contact:
                emp_name = best_contact.get('name', '').lower()
                contact_details = contact_directory.get(emp_name, {})
                if contact_details:
                    sources_found.append("contact_directory")
                    
            # Step E: Compile Meta-Data & Compute Verification Thresholds
            c_name = best_contact.get('name') if best_contact else None
            c_role = best_contact.get('role') if best_contact else None
            c_email = contact_details.get('email')
            c_phone = contact_details.get('phone')
            
            has_email = bool(c_email)
            has_phone = bool(c_phone)
            unique_sources = list(set(sources_found))
            
            # Evaluate final stats
            if c_name and (has_email or has_phone):
                conf_score = calculate_score(address_matched, len(unique_sources), has_email, has_phone)
            else:
                conf_score = 0
                
            # Stage B Gated Requirement: Threshold of 70
            needs_review = True if conf_score < 70 or not c_name else False
            
            results.append({
                'company_name': raw_company,
                'mailing_address': raw_address,
                'contact_name': c_name or "NULL",
                'contact_role': c_role or "NULL",
                'contact_email_or_phone': c_email or c_phone or "NULL",
                'confidence_score': conf_score,
                'source': ", ".join(unique_sources) if unique_sources else "NONE",
                'needs_human_review': str(needs_review).lower()
            })
            
    # Write Final Structured Payload
    fieldnames = ['company_name', 'mailing_address', 'contact_name', 'contact_role', 'contact_email_or_phone', 'confidence_score', 'source', 'needs_human_review']
    with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

if __name__ == "__main__":
    # Point paths dynamically relative to the script execution tree
    base_dir = os.path.dirname(__file__)
    input_csv = os.path.join(base_dir, 'data', 'companies.csv')
    output_csv = os.path.join(base_dir, 'output_contacts.csv')
    
    print("[*] Processing Batch Data Pipeline against Mock Providers...")
    process_contact_finder(input_csv, output_csv)
    print(f"[+] Enrichment Complete. Output saved successfully to: {output_csv}")