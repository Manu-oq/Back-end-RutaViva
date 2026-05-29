CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- HNSW indexes for pgvector semantic search (cosine distance)
-- Without these, queries fall back to sequential scan O(n) which does NOT scale.
-- HNSW provides ~O(log n) search with high recall.

-- POI description embeddings (CRITICAL — used in every POI search)
CREATE INDEX IF NOT EXISTS idx_pois_description_embedding_hnsw
    ON pois USING hnsw (description_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Conversation memory fact embeddings (used in semantic fact retrieval)
CREATE INDEX IF NOT EXISTS idx_conversation_memory_embedding_hnsw
    ON conversation_memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Tourist profile interests embeddings (used for personalized ranking)
CREATE INDEX IF NOT EXISTS idx_tourist_profiles_interests_embedding_hnsw
    ON tourist_profiles USING hnsw (interests_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Review text embeddings (used for semantic review search)
CREATE INDEX IF NOT EXISTS idx_reviews_text_embedding_hnsw
    ON reviews USING hnsw (text_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
