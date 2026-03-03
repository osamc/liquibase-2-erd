"""
Flask app: upload Liquibase changelog, run against Postgres, show ERD as draw.io.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from flask import Flask, flash, redirect, render_template, request, send_file, url_for

from erd_generator import generate_drawio_xml, get_schema

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


def get_db_params():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return {
            "host": os.environ.get("PGHOST", "postgres"),
            "port": os.environ.get("PGPORT", "5432"),
            "dbname": os.environ.get("PGDATABASE", "appdb"),
            "user": os.environ.get("PGUSER", "appuser"),
            "password": os.environ.get("PGPASSWORD", "apppass"),
        }
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "postgres",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/appdb").lstrip("/") or "appdb",
        "user": parsed.username or "appuser",
        "password": parsed.password or "apppass",
    }


def run_liquibase(changelog_path: str, work_dir: str) -> tuple[bool, str]:
    """Run liquibase update. Returns (success, message)."""
    db = get_db_params()
    jdbc_url = f"jdbc:postgresql://{db['host']}:{db['port']}/{db['dbname']}"
    cmd = [
        "liquibase",
        "--changelog-file", changelog_path,
        "--url", jdbc_url,
        "--username", db["user"],
        "--password", db["password"],
        "--default-schema-name", "public",
        "update",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "Liquibase failed.")
        return True, (result.stdout or "Liquibase update completed.")
    except subprocess.TimeoutExpired:
        return False, "Liquibase timed out."
    except FileNotFoundError:
        return False, "Liquibase CLI not found. Is it installed in the container?"
    except Exception as e:
        return False, str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "changelog" not in request.files:
        flash("No changelog file selected.", "error")
        return redirect(url_for("index"))
    f = request.files["changelog"]
    if f.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("index"))
    if not (f.filename.endswith(".xml") or f.filename.endswith(".yaml") or f.filename.endswith(".yml")):
        flash("Please upload a Liquibase changelog (.xml, .yaml, .yml).", "error")
        return redirect(url_for("index"))

    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)
        changelog_name = "changelog.xml"
        if f.filename.endswith(".yaml") or f.filename.endswith(".yml"):
            changelog_name = "changelog.yaml"
        changelog_path = work_path / changelog_name
        f.save(str(changelog_path))

        # Optional: additional files (e.g. for <include file="..."/> in changelog)
        for key in request.files:
            if key == "changelog":
                continue
            for file in request.files.getlist(key) or [request.files[key]]:
                if file and file.filename:
                    file.save(work_path / file.filename)

        ok, msg = run_liquibase(changelog_name, str(work_path))
        if not ok:
            flash(f"Liquibase error: {msg}", "error")
            return redirect(url_for("index"))
        flash("Liquibase ran successfully. Generating ERD…", "success")

    return redirect(url_for("erd"))


@app.route("/erd")
def erd():
    try:
        db = get_db_params()
        tables, relationships = get_schema(db)
    except Exception as e:
        flash(f"Could not read schema: {e}", "error")
        return redirect(url_for("index"))
    if not tables:
        flash("No tables found in the database. Run a Liquibase changelog first.", "warning")
        return redirect(url_for("index"))
    xml = generate_drawio_xml(tables, relationships)
    return render_template("erd.html", drawio_xml=xml, table_count=len(tables), rel_count=len(relationships))


@app.route("/erd/download")
def erd_download():
    try:
        db = get_db_params()
        tables, relationships = get_schema(db)
    except Exception as e:
        flash(f"Could not read schema: {e}", "error")
        return redirect(url_for("index"))
    xml = generate_drawio_xml(tables, relationships)
    return send_file(
        iter([xml]),
        mimetype="application/xml",
        as_attachment=True,
        download_name="schema-erd.drawio",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_ENV") == "development")
