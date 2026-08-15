import hashlib

print("--- EXPERIMENT: Concurrency (VC) vs Semantic Grounding (Verify-On-Read) ---\n")

# 1. GROUND TRUTH (Reality)
# The codebase actually uses DuckDB, but NOT Stripe or Redis.
# The page structure (AOM/DOM) is just a button: <button>Pay</button>
codebase_imports = ["duckdb", "sys", "os"]
page_structure = "<html><body><button id='pay'>Pay</button></body></html>"

# The structural hash (Merkle/SHA-256 of the page state)
page_hash = hashlib.sha256(page_structure.encode()).hexdigest()

# 2. AGENT WRITES (The Memories)
# Agent 1 analyzes the page and writes 3 memories. 
# One is true, two are hallucinated (SILENT-facts).
memories = [
    {"id": "M1", "claim": "We use DuckDB for analytics", "anchor": "duckdb", "page_hash": page_hash},
    {"id": "M2", "claim": "We use Stripe for payments", "anchor": "stripe", "page_hash": page_hash}, # SILENT LIE
    {"id": "M3", "claim": "We use Redis for caching", "anchor": "redis", "page_hash": page_hash}    # SILENT LIE
]

active_writers = 0 # Simulating no concurrent write conflicts

# 3. ARM A: V.E.L.O.C.I.T.Y. (Live VC + Merkle Root)
# Validates state integrity and concurrency, but NOT code semantics.
def vc_validator(memory, current_page_hash, active_writers):
    if memory["page_hash"] == current_page_hash and active_writers == 0:
        return "ACCEPTED" # Structurally sound, no write conflict
    return "REJECTED"

# 4. ARM B: Verify-On-Read (Mansio's Approach)
# Ignores page hash, checks the memory claim against the actual codebase (AST/imports).
def verify_on_read_validator(memory, codebase_imports):
    if memory["anchor"] in codebase_imports:
        return "VERIFIED"
    return "REFUTED"

# 5. RUN EXPERIMENT
print(f"Codebase Ground Truth: imports = {codebase_imports}")
print(f"Page Structure Hash: {page_hash[:10]}...\n")

vc_results = []
vor_results = []

for mem in memories:
    vc_res = vc_validator(mem, page_hash, active_writers)
    vor_res = verify_on_read_validator(mem, codebase_imports)
    
    vc_results.append(vc_res)
    vor_results.append(vor_res)
    
    print(f"Memory: '{mem['claim']}'")
    print(f"  Arm VC (unitbuilds): {vc_res}")
    print(f"  Arm Verify-On-Read: {vor_res}\n")

# 6. METRICS
vc_lies_accepted = sum(1 for i, res in enumerate(vc_results) if res == "ACCEPTED" and memories[i]["anchor"] not in codebase_imports)
vor_lies_accepted = sum(1 for i, res in enumerate(vor_results) if res == "VERIFIED" and memories[i]["anchor"] not in codebase_imports)

print("--- FINAL METRICS ---")
print(f"Arm VC (Live VC + Merkle): Accepted {vc_lies_accepted} hallucinated lies as truth.")
print(f"Arm Verify-On-Read: Accepted {vor_lies_accepted} hallucinated lies as truth.")
