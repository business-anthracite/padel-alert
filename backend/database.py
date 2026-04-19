import os
import random
import string
import hashlib
from datetime import datetime, timezone, timedelta
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from config import DATABASE_URL

_pool: ThreadedConnectionPool | None = None

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


_MIGRATIONS = [
    # 001 — birth_date rendu nullable (non collecté au checkout)
    "ALTER TABLE users ALTER COLUMN birth_date DROP NOT NULL",
]


def _init_schema(conn):
    """Run schema.sql if the users table does not exist yet, then apply migrations."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.users')")
        if cur.fetchone()[0] is None:
            with open(_SCHEMA_PATH) as f:
                cur.execute(f.read())
            conn.commit()

        # Migrations table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                sql TEXT UNIQUE
            )
        """)
        conn.commit()

        for sql in _MIGRATIONS:
            cur.execute("SELECT 1 FROM _migrations WHERE sql = %s", (sql,))
            if not cur.fetchone():
                try:
                    cur.execute(sql)
                    cur.execute("INSERT INTO _migrations (sql) VALUES (%s)", (sql,))
                    conn.commit()
                except Exception:
                    conn.rollback()


def init_pool():
    global _pool
    _pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL)
    # Auto-migrate on first boot
    conn = _pool.getconn()
    try:
        _init_schema(conn)
    finally:
        _pool.putconn(conn)


def close_pool():
    if _pool:
        _pool.closeall()


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ── Alertes ────────────────────────────────────────────────────────────────────

def fetch_active_alerts() -> list[dict]:
    """Retourne toutes les alertes actives dont l'abonnement est valide."""
    sql = """
        SELECT
            a.id, a.user_id, a.name,
            a.location_type, a.location_value, a.location_label,
            a.lat, a.lng, a.radius_km,
            a.match_types, a.age_categories,
            a.competition_types, a.tournament_categories,
            u.email, u.first_name
        FROM alerts a
        JOIN users u ON u.id = a.user_id
        JOIN subscriptions s ON s.user_id = a.user_id
        WHERE a.is_active = TRUE
          AND s.status IN ('trial', 'active')
          AND (s.trial_ends_at IS NULL OR s.trial_ends_at > NOW())
          AND (s.current_period_end IS NULL OR s.current_period_end > NOW())
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def fetch_known_tournament_ids(alert_id: str) -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tournament_id FROM known_tournaments WHERE alert_id = %s",
                (alert_id,)
            )
            return {row[0] for row in cur.fetchall()}


def save_known_tournaments(alert_id: str, tournaments: list[dict]):
    """Marque les tournois comme connus pour cette alerte."""
    if not tournaments:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO known_tournaments (alert_id, tournament_id, tournament_name)
                VALUES %s ON CONFLICT DO NOTHING
                """,
                [(alert_id, t["id"], t["nom"]) for t in tournaments],
            )


# ── Intégration WooCommerce ────────────────────────────────────────────────────

def _gen_referral_code(first_name: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    base = (first_name[:4].upper() if first_name else "USER")
    return f"{base}{suffix}"


def upsert_user_subscription(
    email: str,
    first_name: str,
    last_name: str,
    plan: str,
    billing_period: str,
    stripe_subscription_id: str | None = None,
    wc_subscription_id: int | None = None,
) -> dict:
    """
    Crée ou met à jour l'utilisateur et son abonnement suite à un paiement WooCommerce.
    Retourne {"user_id": ..., "subscription_id": ..., "created": bool}.
    """
    now = datetime.now(timezone.utc)
    trial_ends = now + timedelta(days=14)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ── Utilisateur ──────────────────────────────────────────────
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            created = row is None

            if created:
                placeholder_hash = hashlib.sha256(
                    (email + str(now.timestamp())).encode()
                ).hexdigest()
                referral_code = _gen_referral_code(first_name)
                # Ensure uniqueness
                cur.execute("SELECT 1 FROM users WHERE referral_code = %s", (referral_code,))
                while cur.fetchone():
                    referral_code = _gen_referral_code(first_name)
                    cur.execute("SELECT 1 FROM users WHERE referral_code = %s", (referral_code,))

                cur.execute("""
                    INSERT INTO users (email, first_name, last_name, password_hash, referral_code)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (email, first_name, last_name, placeholder_hash, referral_code))
                user_id = str(cur.fetchone()["id"])
            else:
                user_id = str(row["id"])
                cur.execute("""
                    UPDATE users SET first_name = %s, last_name = %s WHERE id = %s
                """, (first_name, last_name, user_id))

            # ── Abonnement ───────────────────────────────────────────────
            cur.execute("""
                SELECT id FROM subscriptions
                WHERE user_id = %s AND status NOT IN ('cancelled', 'expired')
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            existing_sub = cur.fetchone()

            if existing_sub:
                sub_id = str(existing_sub["id"])
                cur.execute("""
                    UPDATE subscriptions
                    SET plan_type = %s, billing_period = %s, status = 'trial',
                        trial_ends_at = %s, stripe_subscription_id = %s
                    WHERE id = %s
                """, (plan, billing_period, trial_ends, stripe_subscription_id, sub_id))
            else:
                cur.execute("""
                    INSERT INTO subscriptions
                        (user_id, plan_type, billing_period, status, trial_ends_at, stripe_subscription_id)
                    VALUES (%s, %s, %s, 'trial', %s, %s)
                    RETURNING id
                """, (user_id, plan, billing_period, trial_ends, stripe_subscription_id))
                sub_id = str(cur.fetchone()["id"])

    return {"user_id": user_id, "subscription_id": sub_id, "created": created}


def log_notification(user_id: str, alert_id: str, tournaments: list[dict]):
    sql = """
        INSERT INTO notifications_log (user_id, alert_id, tournament_ids, tournament_count)
        VALUES (%s, %s, %s, %s)
    """
    import json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                user_id, alert_id,
                json.dumps([t["id"] for t in tournaments]),
                len(tournaments),
            ))
