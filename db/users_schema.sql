CREATE TABLE IF NOT EXISTS api_users (
    id           BIGSERIAL PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer',  -- 'viewer' | 'admin'
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
