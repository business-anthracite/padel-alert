-- Padel Alert — Schéma PostgreSQL
-- À exécuter une seule fois sur la DB Railway

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── UTILISATEURS ──────────────────────────────────────────────────────────────
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    email_confirmed     BOOLEAN DEFAULT FALSE,
    email_confirm_token VARCHAR(100),
    password_hash       VARCHAR(255) NOT NULL,
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    birth_date          DATE NOT NULL,
    fft_license         VARCHAR(50),
    referral_code       VARCHAR(20) UNIQUE NOT NULL,
    referred_by_id      UUID REFERENCES users(id),
    utm_source          VARCHAR(100),
    utm_medium          VARCHAR(100),
    utm_campaign        VARCHAR(100),
    newsletter_opt_in   BOOLEAN DEFAULT FALSE,
    reset_token         VARCHAR(100),
    reset_token_expires TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── ABONNEMENTS ───────────────────────────────────────────────────────────────
CREATE TABLE subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_type               VARCHAR(20) NOT NULL CHECK (plan_type IN ('standard', 'premium')),
    billing_period          VARCHAR(10) NOT NULL CHECK (billing_period IN ('monthly', 'annual')),
    status                  VARCHAR(20) NOT NULL CHECK (status IN ('trial', 'active', 'cancelled', 'expired')),
    trial_ends_at           TIMESTAMPTZ,
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    stripe_subscription_id  VARCHAR(255),
    free_months_credit      INTEGER DEFAULT 0,  -- crédits parrainage accumulés
    cancelled_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── PAIEMENTS ─────────────────────────────────────────────────────────────────
CREATE TABLE payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    subscription_id     UUID NOT NULL REFERENCES subscriptions(id),
    amount_cents        INTEGER NOT NULL,
    currency            VARCHAR(3) DEFAULT 'EUR',
    stripe_payment_intent_id  VARCHAR(255) UNIQUE,
    status              VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── ALERTES ───────────────────────────────────────────────────────────────────
-- Chaque alerte correspond à un ensemble de critères de recherche pour un user.
-- Les critères sont stockés en JSONB pour flexibilité (nouveaux types Ten'Up sans migration).
CREATE TABLE alerts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                    VARCHAR(200),
    location_type           VARCHAR(10) NOT NULL CHECK (location_type IN ('ville', 'ligue')),
    -- Valeurs pour construire la requête Ten'Up
    location_value          VARCHAR(200) NOT NULL,   -- ex: "Angers, 49000"
    location_label          VARCHAR(300) NOT NULL,   -- ex: "Angers, 49, Maine-et-Loire, Pays de la Loire"
    lat                     DECIMAL(10, 7),
    lng                     DECIMAL(10, 7),
    radius_km               INTEGER DEFAULT 80,
    -- Critères de filtrage (codes Ten'Up)
    match_types             JSONB DEFAULT '["DM"]',          -- ["DM", "DD", "DX"]
    age_categories          JSONB DEFAULT '["200"]',          -- ["200", "345", ...]
    competition_types       JSONB DEFAULT '["P"]',            -- ["P", "CE", "CEQ"]
    tournament_categories   JSONB DEFAULT '["P50","P100"]',   -- ["P25","P50","P100",...]
    is_active               BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── TOURNOIS CONNUS PAR ALERTE ────────────────────────────────────────────────
-- Évite d'envoyer deux fois la même notification pour la même alerte.
CREATE TABLE known_tournaments (
    alert_id            UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    tournament_id       VARCHAR(50) NOT NULL,
    tournament_name     VARCHAR(300),
    first_detected_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (alert_id, tournament_id)
);

-- ── JOURNAL DES NOTIFICATIONS ENVOYÉES ───────────────────────────────────────
CREATE TABLE notifications_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    alert_id            UUID NOT NULL REFERENCES alerts(id),
    tournament_ids      JSONB NOT NULL,
    tournament_count    INTEGER NOT NULL,
    sent_at             TIMESTAMPTZ DEFAULT NOW()
);

-- ── PARRAINAGE ────────────────────────────────────────────────────────────────
CREATE TABLE referrals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    referrer_id         UUID NOT NULL REFERENCES users(id),
    referred_id         UUID NOT NULL REFERENCES users(id) UNIQUE,
    credit_applied      BOOLEAN DEFAULT FALSE,
    credit_applied_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── INDEX ─────────────────────────────────────────────────────────────────────
CREATE INDEX idx_alerts_user_active ON alerts(user_id, is_active);
CREATE INDEX idx_subscriptions_user ON subscriptions(user_id, status);
CREATE INDEX idx_known_tournaments_alert ON known_tournaments(alert_id);
CREATE INDEX idx_payments_user ON payments(user_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_referral_code ON users(referral_code);

-- ── MISE À JOUR AUTOMATIQUE updated_at ───────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_subscriptions_updated_at
    BEFORE UPDATE ON subscriptions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
