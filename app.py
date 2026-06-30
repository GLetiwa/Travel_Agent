"""
Flight Research & Recommendation Agent — web server.
Search logic lives in flights.py; this file handles HTTP only.
"""

import os

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from flights import SliceInfo, find_best_flights

app = Flask(__name__)
# Signs the session cookie — set a strong random string as SECRET_KEY in production
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")


# ---------------------------------------------------------------------------
# Access gate
# ---------------------------------------------------------------------------

@app.before_request
def require_login():
    """Redirect unauthenticated requests to /login, except the login page itself."""
    if request.endpoint in ("login", "static"):
        return
    if not session.get("authenticated"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.environ.get("APP_PASSWORD", "")
        # Require APP_PASSWORD to be set; reject if it's empty (misconfigured env)
        if password and expected and password == expected:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Incorrect password — try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Main routes
# ---------------------------------------------------------------------------

def _slice_to_dict(sl: SliceInfo) -> dict:
    return {
        "origin": sl.origin,
        "destination": sl.destination,
        "departs_at": sl.departs_at.isoformat(),
        "arrives_at": sl.arrives_at.isoformat(),
        "duration_minutes": sl.duration_minutes,
        "stops": sl.stops,
        "airlines": sl.airlines,
        "layovers": [
            {"airport": lv.airport, "duration_minutes": lv.duration_minutes}
            for lv in sl.layovers
        ],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON."}), 400

    origin = body.get("origin", "").strip().upper()
    destination = body.get("destination", "").strip().upper()
    depart_date = body.get("depart_date", "").strip()
    return_date_raw = body.get("return_date")
    return_date = return_date_raw.strip() if return_date_raw else None

    if not origin or not destination or not depart_date:
        return jsonify({"error": "origin, destination, and depart_date are required."}), 400

    try:
        result = find_best_flights(origin, destination, depart_date, return_date)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    offers = [
        {
            "rank": i + 1,
            "price": s.offer.price,
            "currency": s.offer.currency,
            "total_duration_minutes": s.offer.total_duration_minutes,
            "checked_bags": s.offer.checked_bags,
            "carry_on_bags": s.offer.carry_on_bags,
            "reason": s.reason,
            "flags": s.flags,
            "slices": [_slice_to_dict(sl) for sl in s.offer.slices],
        }
        for i, s in enumerate(result.scored_offers)
    ]

    return jsonify({
        "offers": offers,
        "sandbox_filtered": result.sandbox_filtered,
        "codeshares_removed": result.codeshares_removed,
    })


if __name__ == "__main__":
    # Port 5002: macOS AirPlay Receiver occupies 5000 by default
    # debug=True gives auto-reload on file save; local only, never production
    app.run(debug=True, port=5002)
