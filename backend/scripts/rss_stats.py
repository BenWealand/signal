from __future__ import annotations
import sys
sys.path.insert(0, ".")
from app.db.connection import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:

        # Actual columns in articles table
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='articles' ORDER BY ordinal_position"
        )
        cols = [r["column_name"] for r in cur.fetchall()]
        print("Articles table columns:", cols)
        has_rss_url = "rss_url" in cols

        cur.execute("SELECT COUNT(*) AS n FROM articles")
        print("\nTotal articles:", cur.fetchone()["n"])

        cur.execute("SELECT status, COUNT(*) AS n FROM articles GROUP BY status ORDER BY n DESC")
        print("\nBy status:")
        for r in cur.fetchall():
            print(f"  {r['status']}: {r['n']}")

        if has_rss_url:
            cur.execute(
                "SELECT CASE WHEN rss_url IS NOT NULL AND rss_url != '' "
                "THEN 'rss' ELSE 'gdelt/other' END AS origin, COUNT(*) AS n "
                "FROM articles GROUP BY origin"
            )
            print("\nRSS vs GDELT/other:")
            for r in cur.fetchall():
                print(f"  {r['origin']}: {r['n']}")
        else:
            print("\nrss_url column missing from live DB — column needs to be added via migration")

        cur.execute(
            "SELECT source_name, COUNT(*) AS n FROM articles "
            "GROUP BY source_name ORDER BY n DESC LIMIT 25"
        )
        print("\nBy source (top 25):")
        for r in cur.fetchall():
            print(f"  {r['source_name']}: {r['n']}")

        cur.execute(
            "SELECT COUNT(*) AS n FROM articles "
            "WHERE created_at > NOW() - INTERVAL '1 hour'"
        )
        print("\nIngested in last hour:", cur.fetchone()["n"])

        cur.execute(
            "SELECT COUNT(*) AS n FROM articles "
            "WHERE created_at > NOW() - INTERVAL '10 minutes'"
        )
        print("Ingested in last 10 min:", cur.fetchone()["n"])

        cur.execute("SELECT COUNT(*) AS n FROM generated_articles")
        print("\nGenerated articles:", cur.fetchone()["n"])

        cur.execute("SELECT COUNT(*) AS n FROM entities")
        print("Entities extracted:", cur.fetchone()["n"])

        cur.execute("SELECT COUNT(*) AS n FROM claims")
        print("Claims extracted:", cur.fetchone()["n"])

        cur.execute(
            "SELECT source_name, title, created_at FROM articles "
            "ORDER BY created_at DESC LIMIT 15"
        )
        rows = cur.fetchall()
        print(f"\nMost recent 15 articles:")
        for r in rows:
            print(f"  [{r['source_name']}] {str(r['title'])[:70]}  ({str(r['created_at'])[:16]})")
