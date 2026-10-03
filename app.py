"""
Wanderly - Travel Package Booking System  (Flask + SQLite, v3)

Run:
    pip install flask
    python app.py          (or: py app.py)
Open http://127.0.0.1:5000

Demo admin login : admin@travel.com / admin123   (change it!)
Coupon codes     : WELCOME10, TRAVEL5, FESTIVE15

Real photos (optional, 3 ways - first one found wins):
  1. Admin > Edit package > "Image URLs" (one URL per line)
  2. Drop files in  static/images/<slug>-1.jpg ... <slug>-4.jpg
     (slug = package name in lowercase with dashes, e.g. goa-beach-escape-1.jpg)
  3. Nothing -> the app draws scenic artwork for every package automatically.
"""

import json
import os
import random
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import quote, urlparse

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template_string, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-me"
DB = "travel_pro.db"          # new file so it never clashes with your old travel.db
BRAND = "Wanderly"
GST = 0.05
CATEGORIES = [("Beach", "🏖️"), ("Backwaters", "🛶"), ("Mountain", "🏔️"),
              ("Heritage", "🏰"), ("Adventure", "🏍️")]


# ================================================================== Database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.isolation_level = None          # autocommit; we use explicit BEGIN/COMMIT
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, phone TEXT,
    password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, destination TEXT NOT NULL,
    category TEXT NOT NULL, price REAL NOT NULL, original_price REAL,
    duration_days INTEGER NOT NULL, description TEXT, emoji TEXT DEFAULT '🏖️',
    highlights TEXT DEFAULT '[]', itinerary TEXT DEFAULT '[]',
    inclusions TEXT DEFAULT '[]', exclusions TEXT DEFAULT '[]',
    hotel TEXT, best_time TEXT, difficulty TEXT, group_size TEXT,
    images TEXT DEFAULT '', gradient TEXT DEFAULT '#ffb347,#ff6a5c,#1b2a49',
    featured INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS inventory(
    package_id INTEGER PRIMARY KEY REFERENCES packages(id) ON DELETE CASCADE,
    slots_available INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bookings(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id), package_id INTEGER REFERENCES packages(id),
    status TEXT NOT NULL, created_at TEXT NOT NULL, travel_date TEXT NOT NULL,
    travelers INTEGER NOT NULL DEFAULT 1, lead_name TEXT, phone TEXT, requests TEXT,
    payment_method TEXT, coupon TEXT, subtotal REAL, discount REAL, tax REAL,
    total REAL, refund REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS wishlist(
    user_id INTEGER REFERENCES users(id), package_id INTEGER REFERENCES packages(id),
    PRIMARY KEY (user_id, package_id));
CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reviewer_name TEXT NOT NULL,
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL, comment TEXT, created_at TEXT NOT NULL,
    UNIQUE(user_id, package_id));
CREATE TABLE IF NOT EXISTS coupons(
    code TEXT PRIMARY KEY, percent INTEGER NOT NULL, note TEXT, active INTEGER NOT NULL DEFAULT 1);
"""

COMMON_INC = ["Accommodation on twin-sharing basis", "Daily breakfast", "Airport / station pick-up and drop",
              "All sightseeing by private AC vehicle", "Driver allowance, tolls, parking and GST on services"]
COMMON_EXC = ["Flights or train tickets to and from the destination", "Lunch and dinner unless mentioned",
              "Personal expenses, tips and shopping", "Entry tickets to optional attractions",
              "Travel insurance", "Anything not listed under Inclusions"]

SEED = [
    dict(name="Goa Beach Escape", dest="Goa", cat="Beach", price=12999, old=15999, days=4, emoji="🏖️",
         grad="#ffb347,#ff6a5c,#1b2a49", feat=1, slots=24, best="November to February", diff="Easy",
         group="2 to 25 travellers",
         hotel="4-star beach resort in Calangute with a pool, five minutes' walk from the sea.",
         desc="Four easy days of golden beaches, Portuguese-era churches, water sports and beach-shack dinners, "
              "with a comfortable resort base close to the sand.",
         hl=["Parasailing, jet-ski and banana-boat rides at Baga", "Sunset cruise on the Mandovi river with live music",
             "Heritage walk through Fontainhas, the Latin Quarter", "Seafood platter dinner at a beach shack",
             "Early-morning dolphin-spotting boat trip"],
         it=[("Arrival and Calangute Beach", "Pick-up from Goa airport, check in at the resort and spend the afternoon on Calangute beach. Dinner at a beach shack."),
             ("North Goa sightseeing", "Fort Aguada, Chapora Fort, Anjuna flea market and Baga beach. Optional water sports in the afternoon, then the nightlife strip."),
             ("Old Goa and South Goa", "Basilica of Bom Jesus, Se Cathedral and the Fontainhas walk, then a quiet afternoon at Palolem or Colva. Sunset cruise in the evening."),
             ("Leisure and departure", "Late breakfast, last-minute shopping at Mapusa market and transfer to the airport.")],
         inc=["3 nights at a 4-star beach resort", "Mandovi sunset cruise with entertainment", "North and South Goa sightseeing"]),
    dict(name="Kerala Backwaters", dest="Kerala", cat="Backwaters", price=15999, old=18999, days=5, emoji="🛶",
         grad="#43cea2,#185a9d,#0b2545", feat=1, slots=18, best="September to March", diff="Easy",
         group="2 to 20 travellers",
         hotel="Hill-view resort in Munnar and a premium air-conditioned houseboat in Alleppey.",
         desc="Tea hills, spice forests and a night afloat on the backwaters. Five slow days across Kochi, Munnar, Thekkady and Alleppey.",
         hl=["Overnight stay on a private houseboat", "Walk through Munnar's tea estates",
             "Boat safari on Periyar Lake", "Kathakali performance in Fort Kochi",
             "60-minute Ayurvedic massage"],
         it=[("Kochi arrival and Fort Kochi", "Meet your driver at Kochi airport, see the Chinese fishing nets, Mattancherry and St Francis Church, then a Kathakali show in the evening."),
             ("Kochi to Munnar", "Drive through waterfalls and spice country to Munnar. Visit Mattupetty Dam, Echo Point and the tea museum."),
             ("Munnar to Thekkady", "Sunrise at the tea gardens, then on to Thekkady for a spice plantation tour and an evening Kalaripayattu show."),
             ("Periyar and Alleppey houseboat", "Morning boat ride on Periyar Lake, then drive to Alleppey and board your houseboat. Lunch, dinner and a village cruise are served on board."),
             ("Ayurveda and departure", "Disembark after breakfast, enjoy a rejuvenating massage and transfer to Kochi for your onward journey.")],
         inc=["1 night on a premium houseboat with all meals", "Periyar Lake boat ride", "60-minute Ayurvedic massage", "Kathakali evening show"]),
    dict(name="Manali Adventure", dest="Manali", cat="Mountain", price=10999, old=12999, days=3, emoji="🏔️",
         grad="#8ec5fc,#5b7fd6,#1d2b53", feat=1, slots=16, best="March to June, December to February", diff="Moderate",
         group="2 to 16 travellers",
         hotel="3-star riverside hotel near Mall Road with room heaters and mountain views.",
         desc="A short, packed escape to the Beas valley: pine forests, snow points, paragliding and cafés in Old Manali.",
         hl=["Paragliding or zorbing at Solang Valley", "Atal Tunnel drive to Sissu",
             "Hadimba Temple in the cedar forest", "Evening at the cafés of Old Manali"],
         it=[("Arrival, Hadimba and Old Manali", "Check in, visit Hadimba Devi Temple, the Manu Temple and Tibetan monastery. Evening stroll on Mall Road."),
             ("Solang Valley and Atal Tunnel", "Full-day adventure at Solang: paragliding, zorbing or snow activities. Continue through the Atal Tunnel to Sissu."),
             ("Naggar and departure", "Visit Naggar Castle and Jogini Falls on the way out. Drop-off at Chandigarh or Bhuntar airport.")],
         inc=["One adventure activity of your choice at Solang Valley", "Room heaters in all rooms", "Atal Tunnel and Sissu sightseeing"]),
    dict(name="Rajasthan Heritage", dest="Jaipur", cat="Heritage", price=18999, old=22999, days=6, emoji="🏰",
         grad="#f6d365,#fda085,#5b2333", feat=1, slots=20, best="October to March", diff="Easy",
         group="2 to 20 travellers",
         hotel="Heritage havelis in Jaipur and Jodhpur, deluxe desert camp in Jaisalmer.",
         desc="Six days through the Pink, Blue and Golden cities: forts, palaces, bazaars and a night under the stars in the Thar desert.",
         hl=["Amber Fort and City Palace in Jaipur", "Mehrangarh Fort, Jodhpur",
             "Jeep and camel safari at Sam Sand Dunes", "Folk music and dance night at the desert camp",
             "Guided bazaar walk in Johari Bazaar"],
         it=[("Arrive in Jaipur", "Check in to your haveli, evening at Hawa Mahal and Johari Bazaar for block-print textiles and jewellery."),
             ("Jaipur sightseeing", "Amber Fort, Jantar Mantar and the City Palace with a local guide. Sunset at Nahargarh Fort."),
             ("Jaipur to Jodhpur via Pushkar", "Drive through Ajmer and Pushkar, pause at the lake and temple, then continue to Jodhpur."),
             ("Jodhpur to Jaisalmer", "Mehrangarh Fort and Jaswant Thada in the morning, then the road to Jaisalmer."),
             ("Jaisalmer and the dunes", "Jaisalmer Fort and Patwon Ki Haveli, then a dune safari at Sam. Dinner and folk performance at camp."),
             ("Departure", "Sunrise over the dunes, breakfast and transfer to Jaisalmer station or airport.")],
         inc=["Jeep and camel safari at Sam Sand Dunes", "Folk music and dance evening with dinner at the camp", "Local guide for Jaipur monuments"]),
    dict(name="Andaman Islands", dest="Port Blair", cat="Beach", price=22999, old=26999, days=5, emoji="🏝️",
         grad="#00c6ff,#0072ff,#001f4d", feat=1, slots=14, best="October to May", diff="Easy",
         group="2 to 14 travellers",
         hotel="Sea-facing resorts in Port Blair and on Havelock Island.",
         desc="Clear water, white sand and coral reefs. Five days between Port Blair and Havelock with snorkelling, a scuba intro and island sunsets.",
         hl=["Sunset at Radhanagar Beach", "Snorkelling at Elephant Beach",
             "Cellular Jail light and sound show", "Introductory scuba dive with a certified instructor"],
         it=[("Arrive in Port Blair", "Airport pick-up and check-in. Evening Cellular Jail light and sound show."),
             ("Ferry to Havelock", "Morning ferry to Havelock Island, afternoon free, sunset at Radhanagar Beach."),
             ("Elephant Beach and scuba", "Boat to Elephant Beach for snorkelling and glass-bottom views, then an optional intro scuba dive."),
             ("Back to Port Blair", "Return ferry, visit Chidiya Tapu or Corbyn's Cove beach and shop for shell crafts."),
             ("Departure", "Breakfast and airport transfer.")],
         inc=["Port Blair to Havelock return ferry tickets", "Snorkelling at Elephant Beach", "Cellular Jail light and sound show ticket"]),
    dict(name="Ladakh Expedition", dest="Leh-Ladakh", cat="Adventure", price=25999, old=29999, days=7, emoji="🏍️",
         grad="#f5af19,#a64d79,#1c1b3a", feat=0, slots=12, best="June to September", diff="Challenging, high altitude",
         group="4 to 12 travellers",
         hotel="Hotels in Leh and deluxe Swiss tents at Nubra and Pangong Lake.",
         desc="High passes, ancient monasteries and electric-blue lakes. A seven-day circuit of Leh, Nubra Valley and Pangong Tso with proper acclimatisation built in.",
         hl=["Drive over Khardung La, one of the highest motorable passes", "Overnight beside Pangong Tso",
             "Double-humped camel ride at Hunder dunes", "Thiksey and Diskit monasteries",
             "Oxygen cylinder carried in every vehicle"],
         it=[("Arrive in Leh and rest", "Check in and rest. Your body needs the first day to adjust to 3,500 m, so we keep it light."),
             ("Leh local sightseeing", "Shanti Stupa, Leh Palace and the Hall of Fame, followed by a stroll through Leh market."),
             ("Sham Valley circuit", "Magnetic Hill, Gurudwara Pathar Sahib and the confluence of the Indus and Zanskar at Sangam."),
             ("Leh to Nubra via Khardung La", "Cross Khardung La and descend to the green Nubra Valley. Evening at leisure by the river."),
             ("Nubra Valley", "Diskit Monastery, the Maitreya Buddha statue and a camel ride on the Hunder dunes."),
             ("Nubra to Pangong Lake", "Scenic drive via the Shyok river road to Pangong Tso. Sunset and stargazing at the lakeshore."),
             ("Pangong sunrise and return", "Watch the lake change colour at dawn, then return to Leh for your departure.")],
         inc=["Inner Line Permits", "Oxygen cylinder in each vehicle", "Camel ride at Hunder", "Swiss tent stay at Nubra and Pangong"]),
]

REVIEWS = [
    ("Ananya R.", 1, 5, "The itinerary was well paced and the resort was five minutes from the beach. The sunset cruise was the best evening of our trip."),
    ("Rohit & Meera", 1, 4, "Smooth pick-up and a helpful driver. Wish we had one more day for South Goa."),
    ("Deepak S.", 2, 5, "The houseboat night was unforgettable. Everything on the itinerary happened exactly as promised."),
    ("Sneha K.", 2, 5, "Munnar in the morning mist is worth the whole trip. Great value for the price."),
    ("Imran A.", 3, 4, "Paragliding at Solang was a highlight. Rooms were warm and clean."),
    ("Kavya N.", 4, 5, "Our guide in Jaipur made the forts come alive. The desert camp night was magical."),
    ("Arjun P.", 4, 5, "Well planned route, comfortable havelis and no stress about transfers."),
    ("Neha & Vikram", 5, 5, "Snorkelling at Elephant Beach was unreal. Ferries and hotels were perfectly coordinated."),
    ("Rahul M.", 6, 5, "Acclimatisation day made all the difference. Pangong at sunrise is something I will never forget."),
]


# Real photos from Wikimedia Commons (free-licensed). Special:FilePath redirects to the actual image file.
def wm(name, width=1400):
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(name.replace(" ", "_")) + f"?width={width}"


PHOTOS = {
    "goa-beach-escape": ["Baga Beach Goa.JPG", "Goa beautiful beach.JPG", "Dolphins at baga.JPG",
                         "People in a beach during sunset (2011).jpg"],
    "kerala-backwaters": ["Kerala backwaters, Houseboat, India.jpg", "Munnar Tea Estate.jpg",
                          "Kerala backwaters, Cruise, India.jpg", "Munnar Tea Plantation.jpg"],
    "manali-adventure": ["Solang Valley, Paragliding, India.jpg", "Solang Valley 5.jpg",
                         "Snow bridge in Solang Valley.jpg", "Solang valley mountain view.jpg"],
    "rajasthan-heritage": ["Amber fort ,Jaipur.jpg", "Jodhpur, India, Old City and Mehrangarh Fort.jpg",
                           "Sam Dunes Jaisalmer 02.jpg", "Camels at Sam sand dunes, Jaisalmer (44753465845).jpg"],
    "andaman-islands": ["Havelock Island, Radhanagar Beach sunset, Andaman Islands.jpg",
                        "Havelock Island, Radhanagar Beach, tropical bliss, Andaman Islands.jpg",
                        "Havelock Island, Sandy lagoon, Andaman Islands.jpg",
                        "Radhanagar Beach, Havelock Island, Andaman, India.jpg"],
    "ladakh-expedition": ["Pangong Tso 2.jpg", "Pangong Tso Lake, Ladakh, India.jpg",
                          "Diskit Gompa Nubra valley India.jpg", "DOUBLE HUMP CAMEL LADAKH.jpg"],
}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0] == 0:
        for s in SEED:
            cur = conn.execute(
                """INSERT INTO packages(slug,name,destination,category,price,original_price,duration_days,description,
                   emoji,highlights,itinerary,inclusions,exclusions,hotel,best_time,difficulty,group_size,gradient,featured)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (slugify(s["name"]), s["name"], s["dest"], s["cat"], s["price"], s["old"], s["days"], s["desc"], s["emoji"],
                 json.dumps(s["hl"]), json.dumps([{"title": t, "desc": d} for t, d in s["it"]]),
                 json.dumps(s["inc"] + COMMON_INC), json.dumps(COMMON_EXC), s["hotel"], s["best"], s["diff"],
                 s["group"], s["grad"], s["feat"]))
            conn.execute("INSERT INTO inventory(package_id, slots_available) VALUES (?,?)", (cur.lastrowid, s["slots"]))
        for name, pid, rating, text in REVIEWS:
            conn.execute("INSERT INTO reviews(user_id,reviewer_name,package_id,rating,comment,created_at) VALUES (NULL,?,?,?,?,?)",
                         (name, pid, rating, text, (datetime.utcnow() - timedelta(days=random.randint(10, 200))).isoformat()))
        conn.executemany("INSERT INTO coupons(code,percent,note) VALUES (?,?,?)",
                         [("WELCOME10", 10, "10% off your first trip"), ("TRAVEL5", 5, "5% off any trip"),
                          ("FESTIVE15", 15, "Festive season offer")])
    for slug, files in PHOTOS.items():
        conn.execute("UPDATE packages SET images=? WHERE slug=? AND (images IS NULL OR images='')",
                     ("\n".join(wm(f) for f in files), slug))
    if not conn.execute("SELECT 1 FROM users WHERE is_admin=1").fetchone():
        conn.execute("INSERT OR IGNORE INTO users(name,email,password_hash,is_admin,created_at) VALUES (?,?,?,1,?)",
                     ("Admin", "admin@travel.com", generate_password_hash("admin123"), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


# ================================================================== Helpers
PKG_SQL = """SELECT p.*, i.slots_available,
  COALESCE((SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.package_id=p.id),0) AS rating,
  (SELECT COUNT(*) FROM reviews r WHERE r.package_id=p.id) AS reviews_count,
  (SELECT COUNT(*) FROM bookings b WHERE b.package_id=p.id AND b.status='CONFIRMED') AS booked
  FROM packages p JOIN inventory i ON i.package_id=p.id"""


def current_user():
    if "_user" not in g:
        uid = session.get("user_id")
        g._user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return g._user


def safe_next(n):
    return n if n and n.startswith("/") and not n.startswith("//") else None


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            flash("Please log in to continue.", "warning")
            if request.method == "POST":
                nxt = urlparse(request.referrer or "").path or url_for("packages")
            else:
                nxt = request.full_path.rstrip("?")
            return redirect(url_for("login", next=nxt))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if not current_user()["is_admin"]:
            abort(403)
        return view(*a, **kw)
    return wrapped


def inr(n):
    n = int(round(n or 0))
    s = str(abs(n))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "₹" + ("-" if n < 0 else "") + s


def fromjson(s):
    try:
        return json.loads(s or "[]")
    except ValueError:
        return []


def pkg_images(p):
    if p["images"]:
        urls = [u.strip() for u in p["images"].splitlines() if u.strip()]
        if urls:
            return urls
    out = []
    for n in range(1, 5):
        fn = f"images/{p['slug']}-{n}.jpg"
        if os.path.exists(os.path.join(app.static_folder, fn)):
            out.append(url_for("static", filename=fn))
        else:
            out.append(url_for("art", pid=p["id"], n=n))
    return out


def price_calc(price, travelers, pct):
    sub = price * travelers
    disc = round(sub * pct / 100)
    tax = round((sub - disc) * GST)
    return sub, disc, tax, sub - disc + tax


def coupon_percent(code):
    if not code:
        return 0
    r = get_db().execute("SELECT percent FROM coupons WHERE code=? AND active=1", (code.strip().upper(),)).fetchone()
    return r["percent"] if r else 0


def refund_percent(travel_date):
    days = (date.fromisoformat(travel_date) - date.today()).days
    return 90 if days >= 15 else 50 if days >= 7 else 0


app.add_template_filter(inr, "inr")
app.add_template_filter(fromjson, "fromjson")


@app.context_processor
def inject():
    return dict(BRAND=BRAND, pkg_images=pkg_images, CATEGORIES=CATEGORIES, user=current_user(),
                today=date.today().isoformat(), GST=GST)


# ================================================================== Generated artwork (works offline)
def _skyline(kind, rnd, base, amp, W=1200, H=800):
    d = f"M0,{H}L0,{base}"
    x = 0
    if kind == "waves":
        while x < W:
            d += f"Q{x + 100},{base - amp * rnd.uniform(.4, 1.4):.0f} {x + 200},{base}"
            x += 200
    elif kind == "peaks":
        while x < W:
            w = rnd.randint(140, 260)
            d += f"L{x + w // 2},{base - rnd.randint(amp // 2, amp)}L{x + w},{base}"
            x += w
    else:  # castle skyline
        while x < W:
            w, h = rnd.randint(70, 140), base - rnd.randint(0, amp)
            d += f"L{x},{h}L{x + w},{h}L{x + w},{base}"
            x += w
    return d + f"L{x},{H}Z"


@app.route("/art/<int:pid>/<int:n>.svg")
def art(pid, n):
    p = get_db().execute("SELECT category,gradient,emoji FROM packages WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    cols = (p["gradient"] or "#ffb347,#ff6a5c,#1b2a49").split(",")
    while len(cols) < 3:
        cols.append("#1b2a49")
    k = n % 3
    cols = cols[k:] + cols[:k]
    rnd = random.Random(pid * 100 + n)
    kind = {"Beach": "waves", "Backwaters": "waves", "Mountain": "peaks", "Adventure": "peaks"}.get(p["category"], "castle")
    layers = ""
    for i, (fill, op) in enumerate([("#ffffff", .22), ("#ffffff", .38), ("#0b1626", .55)]):
        layers += f'<path d="{_skyline(kind, rnd, 440 + i * 120, 150 - i * 25)}" fill="{fill}" fill-opacity="{op}"/>'
    sx, sy = rnd.randint(250, 950), rnd.randint(150, 300)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{cols[0]}"/>
<stop offset=".55" stop-color="{cols[1]}"/><stop offset="1" stop-color="{cols[2]}"/></linearGradient>
<radialGradient id="s"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>
<rect width="1200" height="800" fill="url(#g)"/><circle cx="{sx}" cy="{sy}" r="190" fill="url(#s)"/>
<circle cx="{sx}" cy="{sy}" r="58" fill="#fff" fill-opacity=".9"/>{layers}
<text x="70" y="170" font-size="110" opacity=".9">{p['emoji']}</text></svg>"""
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


# ================================================================== Shared UI
MACROS = """
{% macro stars(r) %}<span class="stars">{% for i in range(1,6) %}<i class="bi {{ 'bi-star-fill' if r >= i else ('bi-star-half' if r >= i-0.5 else 'bi-star') }}"></i>{% endfor %}</span>{% endmacro %}

{% macro card(p, wished=[]) %}
<div class="col-md-6 col-lg-4">
 <article class="pkg h-100">
  <div class="pkg-img">
    <a href="{{ url_for('package_detail', pkg_id=p['id']) }}"><img loading="lazy" src="{{ pkg_images(p)[0] }}" alt="{{ p['name'] }}"></a>
    <span class="tag tag-cat">{{ p['emoji'] }} {{ p['category'] }}</span>
    {% if p['original_price'] and p['original_price'] > p['price'] %}
      <span class="tag tag-off">{{ ((1 - p['price']/p['original_price'])*100)|round|int }}% off</span>{% endif %}
    <form method="post" action="{{ url_for('toggle_wishlist', pkg_id=p['id']) }}">
      <button class="heart {{ 'on' if p['id'] in wished }}" aria-label="Save to wishlist"><i class="bi bi-heart{{ '-fill' if p['id'] in wished }}"></i></button>
    </form>
  </div>
  <div class="pkg-body">
    <div class="d-flex justify-content-between small text-muted mb-1">
      <span><i class="bi bi-geo-alt"></i> {{ p['destination'] }}</span>
      <span><i class="bi bi-clock"></i> {{ p['duration_days'] }}D / {{ p['duration_days']-1 }}N</span>
    </div>
    <h5 class="pkg-title"><a href="{{ url_for('package_detail', pkg_id=p['id']) }}">{{ p['name'] }}</a></h5>
    {% if p['reviews_count'] %}<div class="small mb-2">{{ stars(p['rating']) }} <strong>{{ p['rating'] }}</strong> <span class="text-muted">({{ p['reviews_count'] }} reviews)</span></div>{% endif %}
    <p class="small text-muted flex-grow-1">{{ p['description'][:92] }}{{ '...' if p['description']|length > 92 }}</p>
    <div class="d-flex justify-content-between align-items-end">
      <div>{% if p['original_price'] and p['original_price'] > p['price'] %}<del class="small text-muted">{{ p['original_price']|inr }}</del>{% endif %}
        <div class="pkg-price">{{ p['price']|inr }} <small>per person</small></div></div>
      {% if p['slots_available'] == 0 %}<span class="badge text-bg-secondary">Sold out</span>
      {% elif p['slots_available'] <= 5 %}<span class="badge text-bg-warning">Only {{ p['slots_available'] }} left</span>{% endif %}
    </div>
    <a class="btn btn-brand w-100 mt-3" href="{{ url_for('package_detail', pkg_id=p['id']) }}">View details</a>
  </div>
 </article>
</div>
{% endmacro %}
"""

BASE = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title or BRAND ~ ' - Travel packages across India' }}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{ --ink:#10202f; --brand:#c62e3d; --brand-dark:#9e1f2d; --sea:#0f6b73; --bg:#f3f5f7; --line:#e3e8ed; --muted:#5f6f7e; }
  body{ font-family:'Plus Jakarta Sans',sans-serif; background:var(--bg); color:var(--ink); }
  h1,h2,h3,.display{ font-family:'Fraunces',serif; font-weight:600; letter-spacing:-.01em; }
  a{ color:var(--brand); } a:hover{ color:var(--brand-dark); }
  :focus-visible{ outline:3px solid #f2a33a; outline-offset:2px; }
  .nav-glass{ background:rgba(255,255,255,.92); backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }
  .navbar-brand{ font-family:'Fraunces',serif; font-weight:700; font-size:1.45rem; color:var(--ink); }
  .navbar-brand .logo{ display:inline-grid; place-items:center; width:34px; height:34px; background:var(--brand); color:#fff; border-radius:10px; font-size:1rem; margin-right:.4rem; transform:rotate(-8deg); }
  .nav-link{ color:var(--ink); font-weight:500; } .nav-link.active,.nav-link:hover{ color:var(--brand); }
  .btn-brand{ background:var(--brand); color:#fff; border:0; font-weight:600; border-radius:10px; padding:.6rem 1.1rem; }
  .btn-brand:hover,.btn-brand:focus{ background:var(--brand-dark); color:#fff; }
  .btn-ghost{ border:1px solid var(--line); background:#fff; border-radius:10px; font-weight:600; }
  .form-control,.form-select{ border-radius:10px; border-color:#d5dce3; padding:.65rem .85rem; }
  .form-control:focus,.form-select:focus{ border-color:var(--brand); box-shadow:0 0 0 .2rem rgba(198,46,61,.15); }
  .panel{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:1.5rem; }
  /* hero */
  .hero{ background-size:cover; background-position:center; color:#fff; padding:6.5rem 0 7rem; }
  .hero h1{ font-size:clamp(2.2rem,5vw,3.7rem); max-width:16ch; line-height:1.08; }
  .hero p{ font-size:1.15rem; max-width:52ch; opacity:.92; }
  .search-bar{ background:#fff; border-radius:16px; padding:.7rem; display:grid; grid-template-columns:2fr 1.3fr 1.3fr auto; gap:.5rem; margin-top:2rem; box-shadow:0 20px 50px rgba(0,0,0,.3); max-width:900px; }
  .search-bar .form-control,.search-bar .form-select{ border:0; background:#f3f5f7; }
  @media(max-width:767px){ .search-bar{ grid-template-columns:1fr; } }
  .stat-strip{ margin-top:-2.6rem; position:relative; z-index:2; }
  .stat-strip .panel{ display:grid; grid-template-columns:repeat(3,1fr); text-align:center; padding:1.2rem; }
  .stat-strip b{ font-family:'Fraunces',serif; font-size:1.9rem; display:block; }
  /* package cards */
  .pkg{ background:#fff; border:1px solid var(--line); border-radius:16px; overflow:hidden; display:flex; flex-direction:column; transition:box-shadow .2s; }
  .pkg:hover{ box-shadow:0 14px 34px rgba(16,32,47,.12); }
  .pkg-img{ position:relative; aspect-ratio:16/11; overflow:hidden; background:#dde3e8; }
  .pkg-img img{ width:100%; height:100%; object-fit:cover; transition:transform .5s; } .pkg:hover .pkg-img img{ transform:scale(1.05); }
  .tag{ position:absolute; font-size:.75rem; font-weight:600; padding:.3rem .65rem; border-radius:20px; }
  .tag-cat{ top:.8rem; left:.8rem; background:rgba(255,255,255,.95); color:var(--ink); }
  .tag-off{ bottom:.8rem; left:.8rem; background:var(--brand); color:#fff; }
  .heart{ position:absolute; top:.7rem; right:.7rem; width:38px; height:38px; border-radius:50%; border:0; background:rgba(255,255,255,.95); color:var(--ink); }
  .heart.on,.heart:hover{ color:var(--brand); }
  .pkg-body{ padding:1rem 1.1rem 1.2rem; display:flex; flex-direction:column; flex:1; }
  .pkg-title{ font-family:'Fraunces',serif; font-weight:600; font-size:1.25rem; } .pkg-title a{ color:var(--ink); text-decoration:none; }
  .pkg-price{ font-weight:700; font-size:1.3rem; } .pkg-price small{ font-weight:400; font-size:.75rem; color:var(--muted); }
  .stars{ color:#f2a33a; letter-spacing:1px; }
  .theme{ display:flex; align-items:center; gap:.7rem; background:#fff; border:1px solid var(--line); border-radius:14px; padding:1rem 1.2rem; text-decoration:none; color:var(--ink); font-weight:600; }
  .theme:hover{ border-color:var(--brand); color:var(--brand); } .theme span{ font-size:1.8rem; }
  .section{ padding:3.5rem 0; } .section-title{ font-size:clamp(1.6rem,3vw,2.2rem); margin-bottom:.4rem; }
  /* detail page */
  .gallery{ display:grid; grid-template-columns:1fr; gap:.6rem; }
  .gallery .main{ aspect-ratio:16/9; border-radius:18px; overflow:hidden; background:#dde3e8; } .gallery .main img{ width:100%; height:100%; object-fit:cover; }
  .thumbs{ display:grid; grid-template-columns:repeat(4,1fr); gap:.6rem; }
  .thumbs button{ border:2px solid transparent; padding:0; border-radius:12px; overflow:hidden; aspect-ratio:16/10; background:#dde3e8; }
  .thumbs button.on{ border-color:var(--brand); } .thumbs img{ width:100%; height:100%; object-fit:cover; }
  .facts{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.8rem; }
  .fact{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:.8rem 1rem; } .fact i{ color:var(--brand); font-size:1.2rem; }
  .fact small{ display:block; color:var(--muted); } .fact b{ font-size:.92rem; }
  .nav-pills .nav-link{ border-radius:10px; } .nav-pills .nav-link.active{ background:var(--ink); color:#fff; }
  .timeline{ position:relative; padding-left:3.2rem; }
  .timeline:before{ content:''; position:absolute; left:19px; top:6px; bottom:6px; width:2px; background:var(--line); }
  .t-item{ position:relative; margin-bottom:1.4rem; }
  .t-day{ position:absolute; left:-3.2rem; top:0; width:40px; height:40px; border-radius:50%; background:var(--brand); color:#fff; display:grid; place-items:center; font-weight:700; font-size:.78rem; text-align:center; line-height:1; }
  .t-card{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:1rem 1.2rem; }
  .check li,.cross li{ list-style:none; padding:.35rem 0 .35rem 1.8rem; position:relative; }
  .check li:before{ content:'\\F26E'; font-family:bootstrap-icons; color:#188a4a; position:absolute; left:0; }
  .cross li:before{ content:'\\F62A'; font-family:bootstrap-icons; color:var(--brand); position:absolute; left:0; }
  .check,.cross{ padding:0; margin:0; }
  .book-card{ position:sticky; top:88px; }
  .old-price{ text-decoration:line-through; color:var(--muted); }
  .stepper{ display:flex; align-items:center; border:1px solid #d5dce3; border-radius:10px; overflow:hidden; background:#fff; }
  .stepper button{ border:0; background:#f3f5f7; width:42px; height:42px; font-size:1.2rem; } .stepper input{ border:0; text-align:center; width:100%; font-weight:600; }
  .bar{ height:8px; border-radius:6px; background:#e9edf1; overflow:hidden; } .bar i{ display:block; height:100%; background:#f2a33a; }
  .confirm-tick{ width:76px; height:76px; border-radius:50%; background:#188a4a; color:#fff; display:grid; place-items:center; font-size:2.4rem; margin:0 auto 1rem; animation:pop .5s cubic-bezier(.2,1.4,.4,1) both; }
  @keyframes pop{ from{ transform:scale(.3); opacity:0; } to{ transform:scale(1); opacity:1; } }
  .booking-row{ background:#fff; border:1px solid var(--line); border-radius:16px; overflow:hidden; display:grid; grid-template-columns:200px 1fr auto; }
  .booking-row img{ width:100%; height:100%; object-fit:cover; min-height:130px; }
  @media(max-width:767px){ .booking-row{ grid-template-columns:1fr; } .booking-row img{ height:150px; } }
  .avatar{ width:72px; height:72px; border-radius:50%; background:var(--ink); color:#fff; display:grid; place-items:center; font-family:'Fraunces',serif; font-size:2rem; }
  footer{ background:var(--ink); color:#c9d3dc; } footer a{ color:#c9d3dc; text-decoration:none; } footer a:hover{ color:#fff; }
  .quote{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:1.4rem; height:100%; }
  @media print{ body{ background:#fff; } .panel{ border:0; } }
  @media(prefers-reduced-motion:reduce){ *{ animation:none !important; transition:none !important; } }
</style></head><body>
<nav class="navbar navbar-expand-lg sticky-top nav-glass d-print-none">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}"><span class="logo">&#9992;</span>{{ BRAND }}</a>
    <button class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#nav" aria-label="Menu"><span class="navbar-toggler-icon"></span></button>
    <div class="collapse navbar-collapse" id="nav">
      <ul class="navbar-nav me-auto ms-lg-4">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">Home</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('packages') }}">Packages</a></li>
        {% if user %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('my_bookings') }}">My bookings</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('wishlist') }}">Wishlist</a></li>
        {% endif %}
      </ul>
      {% if user %}
      <div class="dropdown">
        <a class="btn btn-ghost dropdown-toggle" data-bs-toggle="dropdown" href="#"><i class="bi bi-person-circle"></i> {{ user['name'].split()[0] }}</a>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><a class="dropdown-item" href="{{ url_for('profile') }}">Profile</a></li>
          {% if user['is_admin'] %}<li><a class="dropdown-item" href="{{ url_for('admin_home') }}">Admin panel</a></li>{% endif %}
          <li><hr class="dropdown-divider"></li>
          <li><a class="dropdown-item" href="{{ url_for('logout') }}">Log out</a></li>
        </ul>
      </div>
      {% else %}
      <a class="btn btn-ghost me-2" href="{{ url_for('login') }}">Log in</a>
      <a class="btn btn-brand" href="{{ url_for('register') }}">Create account</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container mt-3 d-print-none">
  {% for cat, m in get_flashed_messages(with_categories=true) %}
    <div class="alert alert-{{ 'info' if cat=='message' else cat }} alert-dismissible fade show" role="alert">{{ m }}<button class="btn-close" data-bs-dismiss="alert"></button></div>
  {% endfor %}
</div>
{{ body|safe }}
<footer class="mt-5 py-5 d-print-none"><div class="container"><div class="row g-4">
  <div class="col-md-5"><div class="navbar-brand text-white mb-2">{{ BRAND }}</div>
    <p class="small">Complete travel packages across India. Stays, transfers, sightseeing and local guides, sorted before you leave home.</p></div>
  <div class="col-6 col-md-3"><b class="text-white">Explore</b><ul class="list-unstyled small mt-2">
    {% for c, e in CATEGORIES %}<li class="mb-1"><a href="{{ url_for('packages', category=c) }}">{{ c }}</a></li>{% endfor %}</ul></div>
  <div class="col-6 col-md-4"><b class="text-white">Help</b><ul class="list-unstyled small mt-2">
    <li class="mb-1">support@wanderly.example</li><li class="mb-1">+91 98765 43210</li><li>Mon to Sat, 9am to 7pm IST</li></ul></div>
</div><hr><p class="small mb-0">&copy; {{ today[:4] }} {{ BRAND }}. Payments in this demo are simulated. Photos: Wikimedia Commons contributors.</p></div></footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""


def page(body, title=None, **ctx):
    inner = render_template_string(MACROS + body, **ctx)
    return render_template_string(BASE, body=inner, title=title)


# ================================================================== Home
@app.route("/")
def index():
    db = get_db()
    featured = db.execute(PKG_SQL + " WHERE p.featured=1 ORDER BY booked DESC LIMIT 6").fetchall()
    hero = featured[0] if featured else db.execute(PKG_SQL + " LIMIT 1").fetchone()
    stats = db.execute("""SELECT (SELECT COUNT(*) FROM packages) pk,
        (SELECT COALESCE(SUM(travelers),0) FROM bookings WHERE status='CONFIRMED') tr,
        (SELECT COALESCE(ROUND(AVG(rating),1),0) FROM reviews) rt""").fetchone()
    quotes = db.execute("""SELECT r.*, p.name pname FROM reviews r JOIN packages p ON p.id=r.package_id
                           WHERE r.rating=5 ORDER BY r.created_at DESC LIMIT 3""").fetchall()
    wished = set()
    if current_user():
        wished = {r[0] for r in db.execute("SELECT package_id FROM wishlist WHERE user_id=?", (current_user()["id"],))}
    body = """
    {% if hero %}<section class="hero" style="background-image:linear-gradient(180deg,rgba(16,32,47,.45),rgba(16,32,47,.85)),url('{{ pkg_images(hero)[0] }}')">
      <div class="container">
        <h1>Your next trip, planned from the first transfer to the last sunset</h1>
        <p class="mt-3">Hand-built packages across India. Stays, transfers, sightseeing and local guides are already sorted. Pick a date and go.</p>
        <form class="search-bar" action="{{ url_for('packages') }}">
          <input class="form-control" name="q" placeholder="Where to? Goa, Kerala, Ladakh">
          <select class="form-select" name="category"><option value="">Any theme</option>
            {% for c,e in CATEGORIES %}<option>{{ c }}</option>{% endfor %}</select>
          <select class="form-select" name="max_price"><option value="">Any budget</option>
            <option value="15000">Under ₹15,000</option><option value="25000">Under ₹25,000</option><option value="50000">Under ₹50,000</option></select>
          <button class="btn btn-brand px-4"><i class="bi bi-search"></i> Search</button>
        </form>
      </div></section>{% endif %}
    <div class="container stat-strip"><div class="panel">
      <div><b>{{ stats['pk'] }}</b><span class="text-muted small">curated packages</span></div>
      <div><b>{{ stats['tr'] }}+</b><span class="text-muted small">travellers booked</span></div>
      <div><b>{{ stats['rt'] }} / 5</b><span class="text-muted small">average rating</span></div></div></div>

    <section class="section"><div class="container">
      <h2 class="section-title">Pick a kind of trip</h2><p class="text-muted mb-4">Start with the mood and we will show you the routes.</p>
      <div class="row g-3">{% for c,e in CATEGORIES %}
        <div class="col-6 col-md"><a class="theme" href="{{ url_for('packages', category=c) }}"><span>{{ e }}</span>{{ c }}</a></div>{% endfor %}</div>
    </div></section>

    <section class="pb-4"><div class="container">
      <div class="d-flex justify-content-between align-items-end mb-3">
        <div><h2 class="section-title mb-0">Popular right now</h2><p class="text-muted mb-0">Most booked by travellers this season.</p></div>
        <a href="{{ url_for('packages') }}" class="fw-semibold">See all packages</a></div>
      <div class="row g-4">{% for p in featured %}{{ card(p, wished) }}{% endfor %}</div>
    </div></section>

    <section class="section"><div class="container">
      <h2 class="section-title">How booking works</h2>
      <div class="row g-4 mt-1">
        <div class="col-md-4"><div class="panel h-100"><h5>1. Choose a package</h5><p class="text-muted mb-0">Compare day-by-day itineraries, hotels, inclusions and real traveller reviews.</p></div></div>
        <div class="col-md-4"><div class="panel h-100"><h5>2. Pick date and group size</h5><p class="text-muted mb-0">See the full price including taxes before you pay, and apply a coupon if you have one.</p></div></div>
        <div class="col-md-4"><div class="panel h-100"><h5>3. Get your confirmation</h5><p class="text-muted mb-0">Your booking reference and printable invoice are ready immediately in My bookings.</p></div></div>
      </div></div></section>

    <section class="pb-4"><div class="container">
      <h2 class="section-title">What travellers say</h2>
      <div class="row g-4 mt-1">{% for q in quotes %}
        <div class="col-md-4"><div class="quote">{{ stars(q['rating']) }}
          <p class="mt-2">{{ q['comment'] }}</p><small class="text-muted"><b>{{ q['reviewer_name'] }}</b> on {{ q['pname'] }}</small></div></div>{% endfor %}</div>
    </div></section>
    """
    return page(body, hero=hero, featured=featured, stats=stats, quotes=quotes, wished=wished)


# ================================================================== Auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email = request.form["name"].strip(), request.form["email"].strip().lower()
        phone, pw = request.form.get("phone", "").strip(), request.form["password"]
        if len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif pw != request.form.get("confirm"):
            flash("Passwords do not match.", "danger")
        else:
            try:
                get_db().execute("INSERT INTO users(name,email,phone,password_hash,created_at) VALUES (?,?,?,?,?)",
                                 (name, email, phone, generate_password_hash(pw), datetime.utcnow().isoformat()))
                flash("Account created. Log in to start booking.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email is already registered. Try logging in.", "danger")
    body = """
    <div class="container py-4"><div class="row justify-content-center"><div class="col-md-6 col-lg-5">
      <div class="panel p-4"><h2 class="mb-1">Create your account</h2><p class="text-muted">Save trips, book packages and track every booking.</p>
      <form method="post">
        <label class="form-label small fw-semibold">Full name</label><input class="form-control mb-3" name="name" required>
        <label class="form-label small fw-semibold">Email</label><input class="form-control mb-3" name="email" type="email" required>
        <label class="form-label small fw-semibold">Mobile number</label><input class="form-control mb-3" name="phone" pattern="[0-9]{10}" placeholder="10 digits" title="10-digit mobile number">
        <div class="row"><div class="col"><label class="form-label small fw-semibold">Password</label><input class="form-control mb-3" name="password" type="password" minlength="6" required></div>
        <div class="col"><label class="form-label small fw-semibold">Confirm</label><input class="form-control mb-3" name="confirm" type="password" required></div></div>
        <button class="btn btn-brand w-100">Create account</button></form>
      <p class="text-center mt-3 mb-0 small">Already registered? <a href="{{ url_for('login') }}">Log in</a></p></div></div></div></div>"""
    return page(body, title="Create account")


@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.values.get("next"))
    if request.method == "POST":
        email, pw = request.form["email"].strip().lower(), request.form["password"]
        u = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and check_password_hash(u["password_hash"], pw):
            session["user_id"] = u["id"]
            flash(f"Welcome back, {u['name'].split()[0]}.", "success")
            return redirect(nxt or url_for("dashboard"))
        flash("Email or password is incorrect.", "danger")
    body = """
    <div class="container py-4"><div class="row justify-content-center"><div class="col-md-6 col-lg-5">
      <div class="panel p-4"><h2 class="mb-1">Log in</h2><p class="text-muted">Pick up where you left off.</p>
      <form method="post"><input type="hidden" name="next" value="{{ nxt or '' }}">
        <label class="form-label small fw-semibold">Email</label><input class="form-control mb-3" name="email" type="email" required>
        <label class="form-label small fw-semibold">Password</label><input class="form-control mb-3" name="password" type="password" required>
        <button class="btn btn-brand w-100">Log in</button></form>
      <p class="text-center mt-3 mb-0 small">New here? <a href="{{ url_for('register') }}">Create an account</a></p></div></div></div></div>"""
    return page(body, title="Log in", nxt=nxt)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ================================================================== Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    db, u = get_db(), current_user()
    upcoming = db.execute("""SELECT b.*, p.name pname, p.destination, p.id pid, p.slug, p.images, p.emoji
        FROM bookings b JOIN packages p ON p.id=b.package_id
        WHERE b.user_id=? AND b.status='CONFIRMED' AND b.travel_date>=? ORDER BY b.travel_date LIMIT 1""",
                          (u["id"], date.today().isoformat())).fetchone()
    s = db.execute("""SELECT (SELECT COUNT(*) FROM bookings WHERE user_id=? AND status='CONFIRMED') bk,
        (SELECT COALESCE(SUM(total),0) FROM bookings WHERE user_id=? AND status='CONFIRMED') spent,
        (SELECT COUNT(*) FROM wishlist WHERE user_id=?) wl""", (u["id"],) * 3).fetchone()
    wished = {r[0] for r in db.execute("SELECT package_id FROM wishlist WHERE user_id=?", (u["id"],))}
    recs = db.execute(PKG_SQL + " WHERE i.slots_available>0 ORDER BY rating DESC, booked DESC LIMIT 3").fetchall()
    days_left = (date.fromisoformat(upcoming["travel_date"]) - date.today()).days if upcoming else None
    body = """
    <div class="container py-4">
      <h2 class="mb-1">Hello, {{ user['name'].split()[0] }}</h2><p class="text-muted mb-4">Here is where your trips stand.</p>
      <div class="row g-3 mb-4">
        <div class="col-md-4"><div class="panel"><small class="text-muted">Active bookings</small><h2 class="mb-0">{{ s['bk'] }}</h2></div></div>
        <div class="col-md-4"><div class="panel"><small class="text-muted">Total spent</small><h2 class="mb-0">{{ s['spent']|inr }}</h2></div></div>
        <div class="col-md-4"><div class="panel"><small class="text-muted">Saved to wishlist</small><h2 class="mb-0">{{ s['wl'] }}</h2></div></div>
      </div>
      {% if upcoming %}
      <div class="booking-row mb-4">
        <img src="{{ pkg_images(upcoming)[0] }}" alt="">
        <div class="p-3"><span class="badge text-bg-success mb-2">Next trip in {{ days_left }} day{{ 's' if days_left != 1 }}</span>
          <h4 class="mb-1">{{ upcoming['pname'] }}</h4>
          <div class="text-muted small">{{ upcoming['destination'] }}, departing {{ upcoming['travel_date'] }} for {{ upcoming['travelers'] }} traveller{{ 's' if upcoming['travelers']>1 }}</div>
          <div class="small mt-1">Reference <b>{{ upcoming['ref'] }}</b></div></div>
        <div class="p-3 d-flex align-items-center"><a class="btn btn-brand" href="{{ url_for('booking_detail', ref=upcoming['ref']) }}">View booking</a></div>
      </div>
      {% else %}
      <div class="panel mb-4 d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div><h5 class="mb-1">No trip planned yet</h5><span class="text-muted">Browse the packages and lock in your dates.</span></div>
        <a class="btn btn-brand" href="{{ url_for('packages') }}">Find a package</a></div>
      {% endif %}
      <h4 class="mb-3">Recommended for you</h4>
      <div class="row g-4">{% for p in recs %}{{ card(p, wished) }}{% endfor %}</div>
    </div>"""
    return page(body, title="Dashboard", s=s, upcoming=upcoming, recs=recs, wished=wished, days_left=days_left)


# ================================================================== Browse
@app.route("/packages")
def packages():
    db = get_db()
    q, cat = request.args.get("q", "").strip(), request.args.get("category", "").strip()
    max_price, max_days = request.args.get("max_price", "").strip(), request.args.get("max_days", "").strip()
    sort = request.args.get("sort", "popular")
    sql, params = PKG_SQL + " WHERE 1=1", []
    if q:
        sql += " AND (p.name LIKE ? OR p.destination LIKE ? OR p.description LIKE ?)"
        params += [f"%{q}%"] * 3
    if cat:
        sql += " AND p.category=?"; params.append(cat)
    if max_price.isdigit():
        sql += " AND p.price<=?"; params.append(int(max_price))
    if max_days.isdigit():
        sql += " AND p.duration_days<=?"; params.append(int(max_days))
    order = {"popular": "booked DESC", "price_asc": "p.price ASC", "price_desc": "p.price DESC",
             "rating": "rating DESC", "duration": "p.duration_days ASC"}.get(sort, "booked DESC")
    pkgs = db.execute(sql + " ORDER BY " + order, params).fetchall()
    wished = set()
    if current_user():
        wished = {r[0] for r in db.execute("SELECT package_id FROM wishlist WHERE user_id=?", (current_user()["id"],))}
    body = """
    <div class="container py-4">
      <h2 class="mb-1">Travel packages</h2><p class="text-muted">{{ pkgs|length }} package{{ 's' if pkgs|length != 1 }} found</p>
      <form class="panel mb-4"><div class="row g-2 align-items-end">
        <div class="col-md-3"><label class="form-label small fw-semibold">Search</label><input class="form-control" name="q" value="{{ request.args.get('q','') }}" placeholder="Destination or keyword"></div>
        <div class="col-md-2"><label class="form-label small fw-semibold">Theme</label><select class="form-select" name="category"><option value="">All</option>
          {% for c,e in CATEGORIES %}<option {{ 'selected' if request.args.get('category')==c }}>{{ c }}</option>{% endfor %}</select></div>
        <div class="col-md-2"><label class="form-label small fw-semibold">Max price</label><select class="form-select" name="max_price"><option value="">Any</option>
          {% for v in [12000,15000,20000,25000,50000] %}<option value="{{ v }}" {{ 'selected' if request.args.get('max_price')==v|string }}>{{ v|inr }}</option>{% endfor %}</select></div>
        <div class="col-md-2"><label class="form-label small fw-semibold">Max days</label><select class="form-select" name="max_days"><option value="">Any</option>
          {% for v in [3,4,5,6,7] %}<option value="{{ v }}" {{ 'selected' if request.args.get('max_days')==v|string }}>{{ v }} days</option>{% endfor %}</select></div>
        <div class="col-md-2"><label class="form-label small fw-semibold">Sort by</label><select class="form-select" name="sort">
          {% for k,l in [('popular','Most booked'),('rating','Top rated'),('price_asc','Price: low to high'),('price_desc','Price: high to low'),('duration','Shortest first')] %}
          <option value="{{ k }}" {{ 'selected' if sort==k }}>{{ l }}</option>{% endfor %}</select></div>
        <div class="col-md-1 d-grid"><button class="btn btn-brand">Go</button></div>
      </div></form>
      {% if not pkgs %}<div class="panel text-center py-5"><h4>No packages match those filters</h4>
        <p class="text-muted">Try a higher budget or clear the theme.</p><a class="btn btn-brand" href="{{ url_for('packages') }}">Clear filters</a></div>{% endif %}
      <div class="row g-4">{% for p in pkgs %}{{ card(p, wished) }}{% endfor %}</div>
    </div>"""
    return page(body, title="Packages", pkgs=pkgs, wished=wished, sort=sort)


@app.route("/package/<int:pkg_id>")
def package_detail(pkg_id):
    db = get_db()
    p = db.execute(PKG_SQL + " WHERE p.id=?", (pkg_id,)).fetchone()
    if not p:
        abort(404)
    u = current_user()
    reviews = db.execute("SELECT * FROM reviews WHERE package_id=? ORDER BY created_at DESC", (pkg_id,)).fetchall()
    dist = {k: 0 for k in range(1, 6)}
    for r in reviews:
        dist[r["rating"]] += 1
    wished, can_review = False, False
    if u:
        wished = bool(db.execute("SELECT 1 FROM wishlist WHERE user_id=? AND package_id=?", (u["id"], pkg_id)).fetchone())
        has_trip = db.execute("SELECT 1 FROM bookings WHERE user_id=? AND package_id=? AND status='CONFIRMED'", (u["id"], pkg_id)).fetchone()
        done = db.execute("SELECT 1 FROM reviews WHERE user_id=? AND package_id=?", (u["id"], pkg_id)).fetchone()
        can_review = bool(has_trip and not done)
    similar = db.execute(PKG_SQL + " WHERE p.id!=? ORDER BY (p.category=?) DESC, booked DESC LIMIT 3", (pkg_id, p["category"])).fetchall()
    sim_wished = {r[0] for r in db.execute("SELECT package_id FROM wishlist WHERE user_id=?", (u["id"],))} if u else set()
    body = """
    <div class="container py-4">
      <nav class="small mb-2"><a href="{{ url_for('packages') }}">Packages</a> / <a href="{{ url_for('packages', category=p['category']) }}">{{ p['category'] }}</a> / {{ p['name'] }}</nav>
      <div class="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
        <div><h1 class="mb-1">{{ p['name'] }}</h1>
          <div class="text-muted"><i class="bi bi-geo-alt"></i> {{ p['destination'] }}
            {% if p['reviews_count'] %}&nbsp;&nbsp;{{ stars(p['rating']) }} <b class="text-dark">{{ p['rating'] }}</b> ({{ p['reviews_count'] }} reviews){% endif %}</div></div>
        <form method="post" action="{{ url_for('toggle_wishlist', pkg_id=p['id']) }}">
          <button class="btn btn-ghost"><i class="bi bi-heart{{ '-fill text-danger' if wished }}"></i> {{ 'Saved' if wished else 'Save' }}</button></form>
      </div>
      <div class="row g-4">
        <div class="col-lg-8">
          <div class="gallery">
            <div class="main"><img id="mainImg" src="{{ imgs[0] }}" alt="{{ p['name'] }}"></div>
            <div class="thumbs">{% for im in imgs[:4] %}<button class="{{ 'on' if loop.first }}" type="button" data-src="{{ im }}" aria-label="Photo {{ loop.index }}"><img src="{{ im }}" alt=""></button>{% endfor %}</div>
          </div>
          <div class="facts my-4">
            <div class="fact"><i class="bi bi-clock"></i><small>Duration</small><b>{{ p['duration_days'] }} days, {{ p['duration_days']-1 }} nights</b></div>
            <div class="fact"><i class="bi bi-people"></i><small>Group size</small><b>{{ p['group_size'] }}</b></div>
            <div class="fact"><i class="bi bi-sun"></i><small>Best time</small><b>{{ p['best_time'] }}</b></div>
            <div class="fact"><i class="bi bi-activity"></i><small>Difficulty</small><b>{{ p['difficulty'] }}</b></div>
          </div>
          <ul class="nav nav-pills mb-3 flex-nowrap overflow-auto" role="tablist">
            {% for id,l in [('ov','Overview'),('it','Itinerary'),('inc','Inclusions'),('rv','Reviews'),('pol','Policies and FAQ')] %}
            <li class="nav-item"><button class="nav-link {{ 'active' if loop.first }} text-nowrap" data-bs-toggle="pill" data-bs-target="#{{ id }}" type="button">{{ l }}</button></li>{% endfor %}
          </ul>
          <div class="tab-content panel">
            <div class="tab-pane fade show active" id="ov">
              <h4>About this trip</h4><p>{{ p['description'] }}</p>
              <h5 class="mt-4">Trip highlights</h5><ul class="check">{% for h in p['highlights']|fromjson %}<li>{{ h }}</li>{% endfor %}</ul>
              <h5 class="mt-4">Where you will stay</h5><p class="mb-0"><i class="bi bi-building text-danger"></i> {{ p['hotel'] }}</p>
            </div>
            <div class="tab-pane fade" id="it">
              <h4 class="mb-4">Day-by-day plan</h4>
              <div class="timeline">{% for d in p['itinerary']|fromjson %}
                <div class="t-item"><div class="t-day">Day<br>{{ loop.index }}</div>
                  <div class="t-card"><h6 class="mb-1">{{ d['title'] }}</h6><p class="mb-0 text-muted small">{{ d['desc'] }}</p></div></div>{% endfor %}</div>
            </div>
            <div class="tab-pane fade" id="inc"><div class="row g-4">
              <div class="col-md-6"><h5>What is included</h5><ul class="check">{% for i in p['inclusions']|fromjson %}<li>{{ i }}</li>{% endfor %}</ul></div>
              <div class="col-md-6"><h5>What is not included</h5><ul class="cross">{% for i in p['exclusions']|fromjson %}<li>{{ i }}</li>{% endfor %}</ul></div></div></div>
            <div class="tab-pane fade" id="rv">
              <div class="row g-4 mb-3"><div class="col-md-4 text-center"><div class="display" style="font-size:3rem">{{ p['rating'] or '-' }}</div>
                {{ stars(p['rating']) }}<div class="small text-muted">{{ p['reviews_count'] }} reviews</div></div>
                <div class="col-md-8">{% for k in [5,4,3,2,1] %}<div class="d-flex align-items-center gap-2 small mb-1"><span style="width:14px">{{ k }}</span>
                  <div class="bar flex-grow-1"><i style="width:{{ (dist[k]/p['reviews_count']*100)|int if p['reviews_count'] else 0 }}%"></i></div><span class="text-muted" style="width:24px">{{ dist[k] }}</span></div>{% endfor %}</div></div>
              {% if can_review %}<form method="post" action="{{ url_for('add_review', pkg_id=p['id']) }}" class="border rounded-3 p-3 mb-3">
                <b>Share your experience</b><div class="row g-2 mt-1"><div class="col-md-3"><select class="form-select" name="rating">{% for k in [5,4,3,2,1] %}<option value="{{ k }}">{{ k }} stars</option>{% endfor %}</select></div>
                <div class="col-md-7"><input class="form-control" name="comment" placeholder="What stood out?" required maxlength="400"></div>
                <div class="col-md-2 d-grid"><button class="btn btn-brand">Post</button></div></div></form>{% endif %}
              {% for r in reviews %}<div class="border-top py-3"><div class="d-flex justify-content-between"><b>{{ r['reviewer_name'] }}</b><small class="text-muted">{{ r['created_at'][:10] }}</small></div>
                {{ stars(r['rating']) }}<p class="mb-0 mt-1">{{ r['comment'] }}</p></div>{% endfor %}
              {% if not reviews %}<p class="text-muted mb-0">No reviews yet. Book this trip and be the first.</p>{% endif %}
            </div>
            <div class="tab-pane fade" id="pol">
              <h5>Cancellation and refund</h5>
              <table class="table table-sm"><thead><tr><th>Cancel before departure</th><th>Refund</th></tr></thead>
                <tbody><tr><td>15 days or more</td><td>90% of amount paid</td></tr><tr><td>7 to 14 days</td><td>50% of amount paid</td></tr><tr><td>Less than 7 days</td><td>No refund</td></tr></tbody></table>
              <h5 class="mt-4">Frequently asked questions</h5>
              <div class="accordion" id="faq">{% for q,a in [
                ('Are flights included?','No. Packages start at arrival and end at departure, so you can book flights or trains that suit your budget.'),
                ('Can I customise the itinerary?','Yes. Add a note in Special requests at checkout and our team will contact you within 24 hours.'),
                ('Is GST included in the price?','The price shown is per person before tax. A ' ~ (GST*100)|int ~ '% GST is added and shown in the total before you pay.'),
                ('Do I need to carry any ID?','Carry a government photo ID for every traveller. Some destinations also need permits, which we help arrange.')] %}
                <div class="accordion-item"><h2 class="accordion-header"><button class="accordion-button collapsed fw-semibold" data-bs-toggle="collapse" data-bs-target="#f{{ loop.index }}">{{ q }}</button></h2>
                <div id="f{{ loop.index }}" class="accordion-collapse collapse" data-bs-parent="#faq"><div class="accordion-body">{{ a }}</div></div></div>{% endfor %}</div>
            </div>
          </div>
        </div>

        <div class="col-lg-4"><div class="panel book-card">
          {% if p['original_price'] and p['original_price'] > p['price'] %}<span class="old-price">{{ p['original_price']|inr }}</span>
            <span class="badge text-bg-danger ms-1">{{ ((1 - p['price']/p['original_price'])*100)|round|int }}% off</span>{% endif %}
          <div class="display" style="font-size:2rem">{{ p['price']|inr }} <small class="fs-6 text-muted fw-normal">per person</small></div>
          <form action="{{ url_for('checkout', pkg_id=p['id']) }}" method="get" class="mt-3">
            <label class="form-label small fw-semibold">Travel date</label>
            <input class="form-control mb-3" type="date" name="date" min="{{ min_date }}" max="{{ max_date }}" required>
            <label class="form-label small fw-semibold">Travellers</label>
            <div class="stepper mb-3"><button type="button" id="minus">&minus;</button><input id="trav" name="travelers" value="1" readonly><button type="button" id="plus">+</button></div>
            <div class="d-flex justify-content-between small text-muted"><span>Estimated total with tax</span><b class="text-dark fs-5" id="tot"></b></div>
            {% if p['slots_available'] > 0 %}
              <div class="bar my-3"><i style="width:{{ 100 - (p['slots_available']/ 30 * 100)|int if p['slots_available'] < 30 else 5 }}%"></i></div>
              <div class="small {{ 'text-danger' if p['slots_available'] <= 5 else 'text-muted' }} mb-3">{{ p['slots_available'] }} seat{{ 's' if p['slots_available']>1 }} left for this package</div>
              <button class="btn btn-brand w-100 py-2">Continue to booking</button>
            {% else %}<button class="btn btn-secondary w-100 mt-3" disabled>Sold out</button>{% endif %}
          </form>
          <ul class="list-unstyled small text-muted mt-3 mb-0">
            <li class="mb-1"><i class="bi bi-shield-check text-success"></i> Free cancellation up to 15 days before (90% refund)</li>
            <li class="mb-1"><i class="bi bi-receipt text-success"></i> Instant confirmation and invoice</li>
            <li><i class="bi bi-headset text-success"></i> Trip support during travel</li></ul>
        </div></div>
      </div>
      <h3 class="mt-5 mb-3">You might also like</h3>
      <div class="row g-4">{% for s in similar %}{{ card(s, sim_wished) }}{% endfor %}</div>
    </div>
    <script>
      const PRICE={{ p['price'] }}, MAX=Math.min({{ p['slots_available'] }},10), GST={{ GST }};
      const trav=document.getElementById('trav'), tot=document.getElementById('tot');
      const fmt=n=>'₹'+Math.round(n).toLocaleString('en-IN');
      const upd=()=>tot.textContent=fmt(PRICE*trav.value*(1+GST));
      document.getElementById('plus').onclick=()=>{ if(+trav.value<MAX){trav.value++;upd();} };
      document.getElementById('minus').onclick=()=>{ if(+trav.value>1){trav.value--;upd();} };
      document.querySelectorAll('.thumbs button').forEach(b=>b.onclick=()=>{
        document.getElementById('mainImg').src=b.dataset.src;
        document.querySelectorAll('.thumbs button').forEach(x=>x.classList.remove('on')); b.classList.add('on'); });
      upd();
    </script>"""
    return page(body, title=p["name"], p=p, imgs=pkg_images(p), reviews=reviews, dist=dist, wished=wished,
                can_review=can_review, similar=similar, sim_wished=sim_wished,
                min_date=(date.today() + timedelta(days=2)).isoformat(),
                max_date=(date.today() + timedelta(days=365)).isoformat())


@app.route("/review/<int:pkg_id>", methods=["POST"])
@login_required
def add_review(pkg_id):
    db, u = get_db(), current_user()
    if db.execute("SELECT 1 FROM bookings WHERE user_id=? AND package_id=? AND status='CONFIRMED'", (u["id"], pkg_id)).fetchone():
        try:
            rating = min(5, max(1, int(request.form.get("rating", 5))))
            db.execute("INSERT INTO reviews(user_id,reviewer_name,package_id,rating,comment,created_at) VALUES (?,?,?,?,?,?)",
                       (u["id"], u["name"], pkg_id, rating, request.form.get("comment", "")[:400], datetime.utcnow().isoformat()))
            flash("Thanks for your review.", "success")
        except (sqlite3.IntegrityError, ValueError):
            flash("You have already reviewed this package.", "warning")
    return redirect(url_for("package_detail", pkg_id=pkg_id) + "#rv")


# ================================================================== Checkout and booking
@app.route("/api/coupon")
def api_coupon():
    code = request.args.get("code", "").strip().upper()
    pct = coupon_percent(code)
    return jsonify(ok=bool(pct), percent=pct, message=f"{code} applied: {pct}% off" if pct else "That coupon code is not valid.")


def _parse_trip(form):
    try:
        travelers = int(form.get("travelers", 1))
        tdate = date.fromisoformat(form.get("travel_date") or form.get("date", ""))
    except ValueError:
        return None, None, "Please choose a valid travel date."
    if not 1 <= travelers <= 10:
        return None, None, "You can book 1 to 10 travellers at a time."
    if tdate < date.today() + timedelta(days=2) or tdate > date.today() + timedelta(days=365):
        return None, None, "Choose a date between 2 days and 12 months from today."
    return travelers, tdate, None


@app.route("/checkout/<int:pkg_id>")
@login_required
def checkout(pkg_id):
    p = get_db().execute(PKG_SQL + " WHERE p.id=?", (pkg_id,)).fetchone()
    if not p:
        abort(404)
    travelers, tdate, err = _parse_trip(request.args)
    if err:
        flash(err, "danger")
        return redirect(url_for("package_detail", pkg_id=pkg_id))
    if travelers > p["slots_available"]:
        flash(f"Only {p['slots_available']} seat(s) left for this package.", "warning")
        return redirect(url_for("package_detail", pkg_id=pkg_id))
    body = """
    <div class="container py-4"><h2 class="mb-4">Review and pay</h2>
    <form method="post" action="{{ url_for('book_package', pkg_id=p['id']) }}"><div class="row g-4">
      <div class="col-lg-7">
        <div class="panel mb-3"><h5>Trip details</h5><div class="row g-3">
          <div class="col-md-6"><label class="form-label small fw-semibold">Travel date</label><input class="form-control" type="date" name="travel_date" value="{{ tdate }}" min="{{ min_date }}" required></div>
          <div class="col-md-6"><label class="form-label small fw-semibold">Travellers</label>
            <select class="form-select" name="travelers" id="trav">{% for n in range(1, [p['slots_available'],10]|min + 1) %}<option {{ 'selected' if n==travelers }}>{{ n }}</option>{% endfor %}</select></div></div></div>
        <div class="panel mb-3"><h5>Lead traveller</h5><div class="row g-3">
          <div class="col-md-6"><label class="form-label small fw-semibold">Full name</label><input class="form-control" name="lead_name" value="{{ user['name'] }}" required></div>
          <div class="col-md-6"><label class="form-label small fw-semibold">Mobile number</label><input class="form-control" name="phone" value="{{ user['phone'] or '' }}" pattern="[0-9]{10}" title="10-digit mobile number" required></div>
          <div class="col-12"><label class="form-label small fw-semibold">Special requests (optional)</label><textarea class="form-control" name="requests" rows="2" maxlength="300" placeholder="Dietary needs, celebrations, pick-up time"></textarea></div></div></div>
        <div class="panel"><h5>Payment method</h5><p class="small text-muted">Demo mode: no money is charged.</p>
          {% for m in ['UPI','Credit / debit card','Net banking','Pay at agency office'] %}
          <div class="form-check mb-1"><input class="form-check-input" type="radio" name="payment_method" id="pm{{ loop.index }}" value="{{ m }}" {{ 'checked' if loop.first }}><label class="form-check-label" for="pm{{ loop.index }}">{{ m }}</label></div>{% endfor %}
          <div class="form-check mt-3"><input class="form-check-input" type="checkbox" id="terms" required><label class="form-check-label small" for="terms">I accept the cancellation policy and terms of travel.</label></div></div>
      </div>
      <div class="col-lg-5"><div class="panel book-card">
        <div class="d-flex gap-3 mb-3"><img src="{{ pkg_images(p)[0] }}" alt="" style="width:96px;height:72px;object-fit:cover;border-radius:10px">
          <div><b>{{ p['name'] }}</b><div class="small text-muted">{{ p['destination'] }}, {{ p['duration_days'] }} days</div></div></div>
        <div class="input-group mb-1"><input class="form-control" id="code" placeholder="Coupon code"><button class="btn btn-ghost" type="button" id="apply">Apply</button></div>
        <div class="small mb-3" id="cmsg"><span class="text-muted">Try WELCOME10 or FESTIVE15</span></div>
        <input type="hidden" name="coupon" id="coupon">
        <table class="table table-sm mb-2"><tbody>
          <tr><td id="lbl"></td><td class="text-end" id="sub"></td></tr>
          <tr class="text-success"><td>Coupon discount</td><td class="text-end" id="disc"></td></tr>
          <tr><td>GST ({{ (GST*100)|int }}%)</td><td class="text-end" id="tax"></td></tr>
          <tr class="fw-bold fs-5"><td>Total</td><td class="text-end" id="tot"></td></tr></tbody></table>
        <button class="btn btn-brand w-100 py-2">Confirm and pay</button></div></div>
    </div></form></div>
    <script>
      const PRICE={{ p['price'] }}, GST={{ GST }}; let pct=0;
      const fmt=n=>'₹'+Math.round(n).toLocaleString('en-IN'), $=id=>document.getElementById(id);
      function calc(){ const t=+$('trav').value, sub=PRICE*t, d=Math.round(sub*pct/100), tax=Math.round((sub-d)*GST);
        $('lbl').textContent=fmt(PRICE)+' x '+t+' traveller'+(t>1?'s':''); $('sub').textContent=fmt(sub);
        $('disc').textContent=d?'-'+fmt(d):'-'; $('tax').textContent=fmt(tax); $('tot').textContent=fmt(sub-d+tax); }
      $('trav').onchange=calc;
      $('apply').onclick=async()=>{ const c=$('code').value.trim(); if(!c) return;
        const r=await (await fetch('/api/coupon?code='+encodeURIComponent(c))).json();
        pct=r.ok?r.percent:0; $('coupon').value=r.ok?c.toUpperCase():'';
        $('cmsg').innerHTML='<span class="'+(r.ok?'text-success':'text-danger')+'">'+r.message+'</span>'; calc(); };
      calc();
    </script>"""
    return page(body, title="Checkout", p=p, tdate=tdate.isoformat(), travelers=travelers,
                min_date=(date.today() + timedelta(days=2)).isoformat())


@app.route("/book/<int:pkg_id>", methods=["POST"])
@login_required
def book_package(pkg_id):
    db, u = get_db(), current_user()
    travelers, tdate, err = _parse_trip(request.form)
    phone = request.form.get("phone", "").strip()
    if not err and not re.fullmatch(r"\d{10}", phone):
        err = "Enter a valid 10-digit mobile number."
    if err:
        flash(err, "danger")
        return redirect(url_for("package_detail", pkg_id=pkg_id))
    pkg = db.execute("SELECT * FROM packages WHERE id=?", (pkg_id,)).fetchone()
    if not pkg:
        abort(404)
    code = request.form.get("coupon", "").strip().upper()
    pct = coupon_percent(code)
    sub, disc, tax, total = price_calc(pkg["price"], travelers, pct)
    ref = "WDR" + secrets.token_hex(3).upper()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT slots_available FROM inventory WHERE package_id=?", (pkg_id,)).fetchone()
        if row is None or row["slots_available"] < travelers:
            db.execute("ROLLBACK")
            flash("Sorry, there are not enough seats left for that group size.", "danger")
            return redirect(url_for("package_detail", pkg_id=pkg_id))
        db.execute("UPDATE inventory SET slots_available=slots_available-?, version=version+1 WHERE package_id=?", (travelers, pkg_id))
        db.execute("""INSERT INTO bookings(ref,user_id,package_id,status,created_at,travel_date,travelers,lead_name,phone,
                      requests,payment_method,coupon,subtotal,discount,tax,total) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (ref, u["id"], pkg_id, "CONFIRMED", datetime.utcnow().isoformat(), tdate.isoformat(), travelers,
                    request.form.get("lead_name", u["name"]).strip(), phone, request.form.get("requests", "")[:300],
                    request.form.get("payment_method", "UPI"), code if pct else None, sub, disc, tax, total))
        db.execute("COMMIT")
    except Exception as e:  # noqa
        try:
            db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        flash(f"Booking failed, please try again. ({e})", "danger")
        return redirect(url_for("package_detail", pkg_id=pkg_id))
    return redirect(url_for("booking_detail", ref=ref, new=1))


def _get_booking(ref):
    b = get_db().execute("""SELECT b.*, p.name pname, p.destination, p.slug, p.images, p.id pid, p.itinerary, p.hotel,
                            p.duration_days, p.emoji FROM bookings b JOIN packages p ON p.id=b.package_id WHERE b.ref=?""", (ref,)).fetchone()
    if not b or (b["user_id"] != current_user()["id"] and not current_user()["is_admin"]):
        abort(404)
    return b


@app.route("/booking/<ref>")
@login_required
def booking_detail(ref):
    b = _get_booking(ref)
    end = date.fromisoformat(b["travel_date"]) + timedelta(days=b["duration_days"] - 1)
    can_cancel = b["status"] == "CONFIRMED" and b["travel_date"] >= date.today().isoformat()
    body = """
    <div class="container py-4" style="max-width:900px">
      {% if request.args.get('new') %}<div class="text-center mb-4"><div class="confirm-tick"><i class="bi bi-check-lg"></i></div>
        <h2>Your trip is booked</h2><p class="text-muted">Reference <b>{{ b['ref'] }}</b>. Keep it handy for check-in.</p></div>{% endif %}
      <div class="panel mb-3">
        <div class="d-flex justify-content-between flex-wrap gap-2"><div><h3 class="mb-0">{{ b['pname'] }}</h3><span class="text-muted">{{ b['destination'] }}</span></div>
          <div><span class="badge fs-6 text-bg-{{ 'success' if b['status']=='CONFIRMED' else 'secondary' }}">{{ b['status'].title() }}</span></div></div><hr>
        <div class="row g-3">
          <div class="col-6 col-md-3"><small class="text-muted d-block">Reference</small><b>{{ b['ref'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Departure</small><b>{{ b['travel_date'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Return</small><b>{{ end }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Travellers</small><b>{{ b['travelers'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Lead traveller</small><b>{{ b['lead_name'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Mobile</small><b>{{ b['phone'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Payment</small><b>{{ b['payment_method'] }}</b></div>
          <div class="col-6 col-md-3"><small class="text-muted d-block">Booked on</small><b>{{ b['created_at'][:10] }}</b></div></div>
        {% if b['requests'] %}<p class="mt-3 mb-0 small"><b>Your note:</b> {{ b['requests'] }}</p>{% endif %}</div>
      <div class="row g-3">
        <div class="col-md-6"><div class="panel h-100"><h5>Payment summary</h5><table class="table table-sm mb-0"><tbody>
          <tr><td>Package ({{ b['travelers'] }} x)</td><td class="text-end">{{ b['subtotal']|inr }}</td></tr>
          {% if b['discount'] %}<tr class="text-success"><td>Coupon {{ b['coupon'] }}</td><td class="text-end">-{{ b['discount']|inr }}</td></tr>{% endif %}
          <tr><td>GST</td><td class="text-end">{{ b['tax']|inr }}</td></tr>
          <tr class="fw-bold"><td>Total paid</td><td class="text-end">{{ b['total']|inr }}</td></tr>
          {% if b['status']=='CANCELLED' %}<tr><td>Refund</td><td class="text-end">{{ b['refund']|inr }}</td></tr>{% endif %}</tbody></table></div></div>
        <div class="col-md-6"><div class="panel h-100"><h5>Your plan</h5>
          <ol class="ps-3 small mb-2">{% for d in b['itinerary']|fromjson %}<li>{{ d['title'] }}</li>{% endfor %}</ol>
          <div class="small text-muted"><i class="bi bi-building"></i> {{ b['hotel'] }}</div></div></div></div>
      <div class="d-flex flex-wrap gap-2 mt-4 d-print-none">
        <a class="btn btn-brand" href="{{ url_for('invoice', ref=b['ref']) }}"><i class="bi bi-printer"></i> Invoice</a>
        <a class="btn btn-ghost" href="{{ url_for('my_bookings') }}">All bookings</a>
        <a class="btn btn-ghost" href="{{ url_for('package_detail', pkg_id=b['pid']) }}">View package</a>
        {% if can_cancel %}<a class="btn btn-outline-danger ms-auto" href="{{ url_for('cancel_booking', ref=b['ref']) }}">Cancel booking</a>{% endif %}</div>
    </div>"""
    return page(body, title=f"Booking {ref}", b=b, end=end, can_cancel=can_cancel)


@app.route("/booking/<ref>/invoice")
@login_required
def invoice(ref):
    b = _get_booking(ref)
    body = """
    <div class="container py-4" style="max-width:780px"><div class="panel p-4 p-md-5">
      <div class="d-flex justify-content-between"><div><div class="navbar-brand">{{ BRAND }}</div><div class="small text-muted">support@wanderly.example</div></div>
        <div class="text-end"><h4 class="mb-0">Tax invoice</h4><small class="text-muted">{{ b['ref'] }} · {{ b['created_at'][:10] }}</small></div></div><hr>
      <div class="row mb-4"><div class="col-6"><small class="text-muted">Billed to</small><div><b>{{ b['lead_name'] }}</b></div><div class="small">{{ b['phone'] }}</div></div>
        <div class="col-6 text-end"><small class="text-muted">Trip</small><div><b>{{ b['pname'] }}</b></div><div class="small">Departing {{ b['travel_date'] }}</div></div></div>
      <table class="table"><thead><tr><th>Description</th><th class="text-end">Qty</th><th class="text-end">Amount</th></tr></thead><tbody>
        <tr><td>{{ b['pname'] }}, {{ b['duration_days'] }} days</td><td class="text-end">{{ b['travelers'] }}</td><td class="text-end">{{ b['subtotal']|inr }}</td></tr>
        {% if b['discount'] %}<tr><td>Discount ({{ b['coupon'] }})</td><td></td><td class="text-end">-{{ b['discount']|inr }}</td></tr>{% endif %}
        <tr><td>GST</td><td></td><td class="text-end">{{ b['tax']|inr }}</td></tr>
        <tr class="fw-bold"><td>Total</td><td></td><td class="text-end">{{ b['total']|inr }}</td></tr></tbody></table>
      <p class="small text-muted mb-0">Payment method: {{ b['payment_method'] }}. Status: {{ b['status'].title() }}. This is a demo invoice.</p></div>
      <div class="text-center mt-3 d-print-none"><button class="btn btn-brand" onclick="window.print()"><i class="bi bi-printer"></i> Print or save as PDF</button></div></div>"""
    return page(body, title=f"Invoice {ref}", b=b)


@app.route("/cancel/<ref>", methods=["GET", "POST"])
@login_required
def cancel_booking(ref):
    b = _get_booking(ref)
    if b["status"] != "CONFIRMED" or b["travel_date"] < date.today().isoformat():
        flash("This booking can no longer be cancelled.", "warning")
        return redirect(url_for("my_bookings"))
    pct = refund_percent(b["travel_date"])
    refund = round(b["total"] * pct / 100)
    if request.method == "POST":
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE bookings SET status='CANCELLED', refund=? WHERE id=?", (refund, b["id"]))
        db.execute("UPDATE inventory SET slots_available=slots_available+? WHERE package_id=?", (b["travelers"], b["package_id"]))
        db.execute("COMMIT")
        flash(f"Booking cancelled. Refund of {inr(refund)} will reach you in 5 to 7 working days.", "success")
        return redirect(url_for("my_bookings"))
    body = """
    <div class="container py-4" style="max-width:560px"><div class="panel p-4">
      <h3>Cancel this booking?</h3><p class="text-muted">{{ b['pname'] }}, departing {{ b['travel_date'] }} ({{ b['ref'] }})</p>
      <table class="table table-sm"><tr><td>Amount paid</td><td class="text-end">{{ b['total']|inr }}</td></tr>
        <tr><td>Refund ({{ pct }}%)</td><td class="text-end fw-bold">{{ refund|inr }}</td></tr></table>
      <form method="post" class="d-flex gap-2"><button class="btn btn-danger">Yes, cancel booking</button>
        <a class="btn btn-ghost" href="{{ url_for('booking_detail', ref=b['ref']) }}">Keep my trip</a></form></div></div>"""
    return page(body, title="Cancel booking", b=b, pct=pct, refund=refund)


@app.route("/my-bookings")
@login_required
def my_bookings():
    rows = get_db().execute("""SELECT b.*, p.name pname, p.destination, p.slug, p.images, p.id pid FROM bookings b
        JOIN packages p ON p.id=b.package_id WHERE b.user_id=? ORDER BY b.travel_date DESC""", (current_user()["id"],)).fetchall()
    t = date.today().isoformat()
    groups = [("Upcoming", [r for r in rows if r["status"] == "CONFIRMED" and r["travel_date"] >= t]),
              ("Completed", [r for r in rows if r["status"] == "CONFIRMED" and r["travel_date"] < t]),
              ("Cancelled", [r for r in rows if r["status"] == "CANCELLED"])]
    body = """
    <div class="container py-4"><h2 class="mb-3">My bookings</h2>
      {% if not rows %}<div class="panel text-center py-5"><h4>No bookings yet</h4><p class="text-muted">Your confirmed trips will show up here.</p>
        <a class="btn btn-brand" href="{{ url_for('packages') }}">Browse packages</a></div>{% endif %}
      {% for label, items in groups if items %}<h5 class="mt-4 mb-3">{{ label }} ({{ items|length }})</h5>
        {% for b in items %}<div class="booking-row mb-3">
          <img src="{{ pkg_images(b)[0] }}" alt="">
          <div class="p-3"><h5 class="mb-1">{{ b['pname'] }}</h5><div class="small text-muted">{{ b['destination'] }}, departing {{ b['travel_date'] }}, {{ b['travelers'] }} traveller{{ 's' if b['travelers']>1 }}</div>
            <div class="small mt-1">Ref <b>{{ b['ref'] }}</b> &nbsp; Total <b>{{ b['total']|inr }}</b>
              <span class="badge text-bg-{{ 'success' if b['status']=='CONFIRMED' else 'secondary' }} ms-2">{{ b['status'].title() }}</span></div></div>
          <div class="p-3 d-flex flex-column gap-2 justify-content-center">
            <a class="btn btn-brand btn-sm" href="{{ url_for('booking_detail', ref=b['ref']) }}">View</a>
            <a class="btn btn-ghost btn-sm" href="{{ url_for('invoice', ref=b['ref']) }}">Invoice</a>
            {% if label=='Upcoming' %}<a class="btn btn-outline-danger btn-sm" href="{{ url_for('cancel_booking', ref=b['ref']) }}">Cancel</a>{% endif %}
            {% if label=='Completed' %}<a class="btn btn-ghost btn-sm" href="{{ url_for('package_detail', pkg_id=b['pid']) }}#rv">Write review</a>{% endif %}</div>
        </div>{% endfor %}{% endfor %}</div>"""
    return page(body, title="My bookings", rows=rows, groups=groups)


# ================================================================== Wishlist
@app.route("/wishlist")
@login_required
def wishlist():
    db = get_db()
    rows = db.execute(PKG_SQL + " JOIN wishlist w ON w.package_id=p.id WHERE w.user_id=?", (current_user()["id"],)).fetchall()
    body = """
    <div class="container py-4"><h2 class="mb-3">Your wishlist</h2>
      {% if not rows %}<div class="panel text-center py-5"><h4>Nothing saved yet</h4><p class="text-muted">Tap the heart on any package to keep it here.</p>
        <a class="btn btn-brand" href="{{ url_for('packages') }}">Browse packages</a></div>{% endif %}
      <div class="row g-4">{% for p in rows %}{{ card(p, wished) }}{% endfor %}</div></div>"""
    return page(body, title="Wishlist", rows=rows, wished={r["id"] for r in rows})


@app.route("/wishlist/toggle/<int:pkg_id>", methods=["POST"])
@login_required
def toggle_wishlist(pkg_id):
    db, u = get_db(), current_user()
    if db.execute("SELECT 1 FROM wishlist WHERE user_id=? AND package_id=?", (u["id"], pkg_id)).fetchone():
        db.execute("DELETE FROM wishlist WHERE user_id=? AND package_id=?", (u["id"], pkg_id))
        flash("Removed from your wishlist.", "info")
    else:
        db.execute("INSERT INTO wishlist(user_id,package_id) VALUES (?,?)", (u["id"], pkg_id))
        flash("Saved to your wishlist.", "success")
    return redirect(request.referrer or url_for("packages"))


# ================================================================== Profile
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db, u = get_db(), current_user()
    if request.method == "POST":
        if request.form.get("action") == "password":
            if not check_password_hash(u["password_hash"], request.form["old"]):
                flash("Current password is incorrect.", "danger")
            elif len(request.form["new"]) < 6:
                flash("New password must be at least 6 characters.", "danger")
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(request.form["new"]), u["id"]))
                flash("Password updated.", "success")
        else:
            db.execute("UPDATE users SET name=?, phone=? WHERE id=?", (request.form["name"].strip(), request.form.get("phone", "").strip(), u["id"]))
            flash("Profile saved.", "success")
        return redirect(url_for("profile"))
    s = db.execute("""SELECT COUNT(*) c, COALESCE(SUM(total),0) s FROM bookings WHERE user_id=? AND status='CONFIRMED'""", (u["id"],)).fetchone()
    body = """
    <div class="container py-4" style="max-width:900px"><div class="d-flex align-items-center gap-3 mb-4">
      <div class="avatar">{{ user['name'][0]|upper }}</div><div><h2 class="mb-0">{{ user['name'] }}</h2>
      <span class="text-muted">{{ user['email'] }}, member since {{ user['created_at'][:10] }}</span></div></div>
      <div class="row g-3 mb-3"><div class="col-6"><div class="panel"><small class="text-muted">Active bookings</small><h3 class="mb-0">{{ s['c'] }}</h3></div></div>
        <div class="col-6"><div class="panel"><small class="text-muted">Total spent</small><h3 class="mb-0">{{ s['s']|inr }}</h3></div></div></div>
      <div class="row g-3">
        <div class="col-md-6"><form method="post" class="panel"><h5>Personal details</h5>
          <label class="form-label small fw-semibold">Full name</label><input class="form-control mb-2" name="name" value="{{ user['name'] }}" required>
          <label class="form-label small fw-semibold">Mobile number</label><input class="form-control mb-3" name="phone" value="{{ user['phone'] or '' }}" pattern="[0-9]{10}">
          <button class="btn btn-brand">Save changes</button></form></div>
        <div class="col-md-6"><form method="post" class="panel"><h5>Change password</h5><input type="hidden" name="action" value="password">
          <input class="form-control mb-2" type="password" name="old" placeholder="Current password" required>
          <input class="form-control mb-3" type="password" name="new" placeholder="New password (6+ characters)" required>
          <button class="btn btn-brand">Update password</button></form></div></div></div>"""
    return page(body, title="Profile", s=s)


# ================================================================== Admin
@app.route("/admin")
@admin_required
def admin_home():
    db = get_db()
    s = db.execute("""SELECT (SELECT COALESCE(SUM(total-COALESCE(refund,0)),0) FROM bookings) rev,
        (SELECT COUNT(*) FROM bookings WHERE status='CONFIRMED') bk, (SELECT COUNT(*) FROM users WHERE is_admin=0) us,
        (SELECT COUNT(*) FROM packages) pk""").fetchone()
    recent = db.execute("""SELECT b.*, p.name pname, u.email FROM bookings b JOIN packages p ON p.id=b.package_id
        JOIN users u ON u.id=b.user_id ORDER BY b.created_at DESC LIMIT 8""").fetchall()
    top = db.execute(PKG_SQL + " ORDER BY booked DESC LIMIT 5").fetchall()
    body = """
    <div class="container py-4"><div class="d-flex justify-content-between align-items-center mb-3"><h2 class="mb-0">Admin panel</h2>
      <div class="d-flex gap-2"><a class="btn btn-ghost" href="{{ url_for('admin_bookings') }}">All bookings</a><a class="btn btn-ghost" href="{{ url_for('admin_packages') }}">Manage packages</a>
      <a class="btn btn-brand" href="{{ url_for('admin_package_form') }}">Add package</a></div></div>
      <div class="row g-3 mb-4">{% for l,v in [('Net revenue', s['rev']|inr),('Confirmed bookings', s['bk']),('Customers', s['us']),('Packages', s['pk'])] %}
        <div class="col-6 col-md-3"><div class="panel"><small class="text-muted">{{ l }}</small><h3 class="mb-0">{{ v }}</h3></div></div>{% endfor %}</div>
      <div class="row g-3"><div class="col-lg-8"><div class="panel"><h5>Recent bookings</h5><div class="table-responsive"><table class="table table-sm align-middle mb-0">
        <thead><tr><th>Ref</th><th>Package</th><th>Customer</th><th>Trip date</th><th class="text-end">Total</th><th>Status</th></tr></thead><tbody>
        {% for b in recent %}<tr><td><a href="{{ url_for('booking_detail', ref=b['ref']) }}">{{ b['ref'] }}</a></td><td>{{ b['pname'] }}</td><td>{{ b['email'] }}</td><td>{{ b['travel_date'] }}</td>
          <td class="text-end">{{ b['total']|inr }}</td><td><span class="badge text-bg-{{ 'success' if b['status']=='CONFIRMED' else 'secondary' }}">{{ b['status'].title() }}</span></td></tr>{% endfor %}</tbody></table></div></div></div>
        <div class="col-lg-4"><div class="panel"><h5>Top packages</h5>{% for p in top %}<div class="d-flex justify-content-between border-bottom py-2"><span>{{ p['name'] }}</span><b>{{ p['booked'] }}</b></div>{% endfor %}</div></div></div></div>"""
    return page(body, title="Admin", s=s, recent=recent, top=top)


@app.route("/admin/bookings")
@admin_required
def admin_bookings():
    rows = get_db().execute("""SELECT b.*, p.name pname, u.email FROM bookings b JOIN packages p ON p.id=b.package_id
        JOIN users u ON u.id=b.user_id ORDER BY b.created_at DESC""").fetchall()
    body = """
    <div class="container py-4"><h2 class="mb-3">All bookings</h2><div class="panel table-responsive"><table class="table table-sm align-middle mb-0">
      <thead><tr><th>Ref</th><th>Package</th><th>Customer</th><th>Phone</th><th>Trip date</th><th>Pax</th><th class="text-end">Total</th><th>Status</th></tr></thead><tbody>
      {% for b in rows %}<tr><td><a href="{{ url_for('booking_detail', ref=b['ref']) }}">{{ b['ref'] }}</a></td><td>{{ b['pname'] }}</td><td>{{ b['email'] }}</td><td>{{ b['phone'] }}</td>
        <td>{{ b['travel_date'] }}</td><td>{{ b['travelers'] }}</td><td class="text-end">{{ b['total']|inr }}</td>
        <td><span class="badge text-bg-{{ 'success' if b['status']=='CONFIRMED' else 'secondary' }}">{{ b['status'].title() }}</span></td></tr>{% endfor %}</tbody></table></div></div>"""
    return page(body, title="Bookings", rows=rows)


@app.route("/admin/packages")
@admin_required
def admin_packages():
    rows = get_db().execute(PKG_SQL + " ORDER BY p.id").fetchall()
    body = """
    <div class="container py-4"><div class="d-flex justify-content-between mb-3"><h2 class="mb-0">Packages</h2>
      <a class="btn btn-brand" href="{{ url_for('admin_package_form') }}">Add package</a></div>
      <div class="panel table-responsive"><table class="table align-middle mb-0"><thead><tr><th>Name</th><th>Theme</th><th>Price</th><th>Seats left</th><th>Bookings</th><th></th></tr></thead><tbody>
      {% for p in rows %}<tr><td><b>{{ p['name'] }}</b><div class="small text-muted">{{ p['destination'] }}, {{ p['duration_days'] }} days</div></td><td>{{ p['category'] }}</td><td>{{ p['price']|inr }}</td>
        <td>{{ p['slots_available'] }}</td><td>{{ p['booked'] }}</td><td class="text-end">
        <a class="btn btn-ghost btn-sm" href="{{ url_for('admin_package_form', pkg_id=p['id']) }}">Edit</a>
        <form class="d-inline" method="post" action="{{ url_for('admin_package_delete', pkg_id=p['id']) }}" onsubmit="return confirm('Delete this package?')"><button class="btn btn-outline-danger btn-sm">Delete</button></form></td></tr>{% endfor %}</tbody></table></div></div>"""
    return page(body, title="Packages", rows=rows)


@app.route("/admin/package", methods=["GET", "POST"])
@app.route("/admin/package/<int:pkg_id>", methods=["GET", "POST"])
@admin_required
def admin_package_form(pkg_id=None):
    db = get_db()
    p = db.execute(PKG_SQL + " WHERE p.id=?", (pkg_id,)).fetchone() if pkg_id else None
    if request.method == "POST":
        f = request.form
        lines = lambda k: [l.strip() for l in f.get(k, "").splitlines() if l.strip()]
        itin = []
        for l in lines("itinerary"):
            t, _, d = l.partition("|")
            itin.append({"title": t.strip(), "desc": d.strip()})
        vals = (f["name"].strip(), f["destination"].strip(), f["category"], float(f["price"]),
                float(f["original_price"] or 0) or None, int(f["duration_days"]), f["description"].strip(),
                f.get("emoji") or "🏖️", json.dumps(lines("highlights")), json.dumps(itin), json.dumps(lines("inclusions")),
                json.dumps(lines("exclusions")), f["hotel"].strip(), f["best_time"].strip(), f["difficulty"].strip(),
                f["group_size"].strip(), f.get("images", "").strip(), f.get("gradient") or "#ffb347,#ff6a5c,#1b2a49",
                1 if f.get("featured") else 0)
        cols = """name=?,destination=?,category=?,price=?,original_price=?,duration_days=?,description=?,emoji=?,highlights=?,
                  itinerary=?,inclusions=?,exclusions=?,hotel=?,best_time=?,difficulty=?,group_size=?,images=?,gradient=?,featured=?"""
        slots = max(0, int(f.get("slots", 20)))
        if p:
            db.execute(f"UPDATE packages SET {cols} WHERE id=?", vals + (p["id"],))
            db.execute("UPDATE inventory SET slots_available=? WHERE package_id=?", (slots, p["id"]))
        else:
            slug = slugify(vals[0])
            if db.execute("SELECT 1 FROM packages WHERE slug=?", (slug,)).fetchone():
                slug += "-" + secrets.token_hex(2)
            cur = db.execute(f"INSERT INTO packages(slug,{cols.replace('=?', '')}) VALUES (?,{','.join('?' * 19)})", (slug,) + vals)
            db.execute("INSERT INTO inventory(package_id,slots_available) VALUES (?,?)", (cur.lastrowid, slots))
        flash("Package saved.", "success")
        return redirect(url_for("admin_packages"))
    v = {}
    if p:
        v = dict(p)
        v["highlights"] = "\n".join(fromjson(p["highlights"]))
        v["inclusions"] = "\n".join(fromjson(p["inclusions"]))
        v["exclusions"] = "\n".join(fromjson(p["exclusions"]))
        v["itinerary"] = "\n".join(f"{d['title']} | {d['desc']}" for d in fromjson(p["itinerary"]))
        v["slots"] = p["slots_available"]
    body = """
    <div class="container py-4" style="max-width:900px"><h2 class="mb-3">{{ 'Edit' if v else 'Add' }} package</h2>
    <form method="post" class="panel"><div class="row g-3">
      <div class="col-md-6"><label class="form-label small fw-semibold">Name</label><input class="form-control" name="name" value="{{ v.get('name','') }}" required></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Destination</label><input class="form-control" name="destination" value="{{ v.get('destination','') }}" required></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Theme</label><select class="form-select" name="category">{% for c,e in CATEGORIES %}<option {{ 'selected' if v.get('category')==c }}>{{ c }}</option>{% endfor %}</select></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Price per person</label><input class="form-control" type="number" name="price" value="{{ v.get('price','') }}" required></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Original price</label><input class="form-control" type="number" name="original_price" value="{{ v.get('original_price') or '' }}"></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Days</label><input class="form-control" type="number" min="1" name="duration_days" value="{{ v.get('duration_days','') }}" required></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Emoji</label><input class="form-control" name="emoji" value="{{ v.get('emoji','🏖️') }}"></div>
      <div class="col-md-3"><label class="form-label small fw-semibold">Seats available</label><input class="form-control" type="number" name="slots" value="{{ v.get('slots',20) }}"></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Artwork colours (3 hex, comma separated)</label><input class="form-control" name="gradient" value="{{ v.get('gradient','#ffb347,#ff6a5c,#1b2a49') }}"></div>
      <div class="col-12"><label class="form-label small fw-semibold">Description</label><textarea class="form-control" name="description" rows="2" required>{{ v.get('description','') }}</textarea></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Highlights (one per line)</label><textarea class="form-control" name="highlights" rows="4">{{ v.get('highlights','') }}</textarea></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Itinerary (one day per line: Title | description)</label><textarea class="form-control" name="itinerary" rows="4">{{ v.get('itinerary','') }}</textarea></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Inclusions (one per line)</label><textarea class="form-control" name="inclusions" rows="4">{{ v.get('inclusions','') }}</textarea></div>
      <div class="col-md-6"><label class="form-label small fw-semibold">Exclusions (one per line)</label><textarea class="form-control" name="exclusions" rows="4">{{ v.get('exclusions','') }}</textarea></div>
      <div class="col-12"><label class="form-label small fw-semibold">Hotel / stay</label><input class="form-control" name="hotel" value="{{ v.get('hotel','') }}"></div>
      <div class="col-md-4"><label class="form-label small fw-semibold">Best time</label><input class="form-control" name="best_time" value="{{ v.get('best_time','') }}"></div>
      <div class="col-md-4"><label class="form-label small fw-semibold">Difficulty</label><input class="form-control" name="difficulty" value="{{ v.get('difficulty','Easy') }}"></div>
      <div class="col-md-4"><label class="form-label small fw-semibold">Group size</label><input class="form-control" name="group_size" value="{{ v.get('group_size','2 to 20 travellers') }}"></div>
      <div class="col-12"><label class="form-label small fw-semibold">Image URLs (optional, one per line, first is the cover photo)</label><textarea class="form-control" name="images" rows="3">{{ v.get('images','') }}</textarea></div>
      <div class="col-12"><div class="form-check"><input class="form-check-input" type="checkbox" name="featured" id="ft" {{ 'checked' if v.get('featured') }}><label class="form-check-label" for="ft">Show on the home page</label></div></div>
      <div class="col-12 d-flex gap-2"><button class="btn btn-brand">Save package</button><a class="btn btn-ghost" href="{{ url_for('admin_packages') }}">Cancel</a></div>
    </div></form></div>"""
    return page(body, title="Package", v=v)


@app.route("/admin/package/<int:pkg_id>/delete", methods=["POST"])
@admin_required
def admin_package_delete(pkg_id):
    db = get_db()
    if db.execute("SELECT 1 FROM bookings WHERE package_id=?", (pkg_id,)).fetchone():
        flash("This package has bookings, so it cannot be deleted. Set its seats to 0 instead.", "warning")
    else:
        db.execute("DELETE FROM wishlist WHERE package_id=?", (pkg_id,))
        db.execute("DELETE FROM packages WHERE id=?", (pkg_id,))
        flash("Package deleted.", "success")
    return redirect(url_for("admin_packages"))


@app.errorhandler(404)
def not_found(e):
    return page('<div class="container py-5 text-center"><h1>Page not found</h1><p class="text-muted">That page does not exist or has moved.</p>'
                '<a class="btn btn-brand" href="{{ url_for(\'index\') }}">Back to home</a></div>', title="Not found"), 404


@app.errorhandler(403)
def forbidden(e):
    return page('<div class="container py-5 text-center"><h1>Admins only</h1><p class="text-muted">Your account cannot open this page.</p>'
                '<a class="btn btn-brand" href="{{ url_for(\'index\') }}">Back to home</a></div>', title="Forbidden"), 403


# ================================================================== Main
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
