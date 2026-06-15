import sys
sys.path.insert(0, ".")

from app.llm.embeddings import get_embeddings, cosine_similarity_matrix

claims = [
    "The Senate approved the new infrastructure bill on Wednesday.",
    "Senators passed the infrastructure legislation with a bipartisan vote.",
    "The stock market rose sharply after the earnings report.",
    "Equity markets surged following better-than-expected quarterly results.",
    "Scientists discovered a new species of fish in the Amazon River.",
]

embs = get_embeddings(claims)
sim = cosine_similarity_matrix(embs)
print("Embedding shape:", embs.shape)
print()
for i in range(len(claims)):
    for j in range(i + 1, len(claims)):
        print(f"[{sim[i][j]:.3f}]  '{claims[i][:55]}' vs '{claims[j][:55]}'")

# Test full consensus detection
from app.llm.consensus import detect_consensus

cluster = [
    {"claim_text": claims[0], "source_name": "BBC", "confidence_score": 0.8},
    {"claim_text": claims[1], "source_name": "Reuters", "confidence_score": 0.75},
    {"claim_text": claims[2], "source_name": "CNBC", "confidence_score": 0.7},
    {"claim_text": claims[3], "source_name": "Bloomberg", "confidence_score": 0.8},
    {"claim_text": claims[4], "source_name": "NatGeo", "confidence_score": 0.9},
]

print("\n--- Consensus results ---")
for item in detect_consensus(cluster):
    print(f"[{item['status']:10s}]  support={item['support_count']}  method={item['method']}  '{item['claim_text'][:70]}'")
