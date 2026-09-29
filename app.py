from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.secret_key = "restaurant-demo-secret-change-me"
DB = Path(__file__).with_name("restaurant.db")


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        email TEXT,
        password TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS staff(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS menu_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL CHECK(price >= 0),
        available INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT NOT NULL UNIQUE,
        customer_id INTEGER,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        order_type TEXT NOT NULL,
        table_no TEXT,
        address TEXT,
        total REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Received',
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        menu_item_id INTEGER,
        item_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY(menu_item_id) REFERENCES menu_items(id)
    );
    CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        booking_date TEXT NOT NULL,
        booking_time TEXT NOT NULL,
        guests INTEGER NOT NULL,
        table_no TEXT,
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0] == 0:
        conn.execute("INSERT INTO staff(username,password) VALUES(?,?)",
                     ("admin", "admin123"))
    if conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        sample = [
            ("Chicken Burger", "Main", "Grilled chicken, lettuce and house sauce", 12000),
            ("Beef Pizza", "Main", "Beef, mozzarella and vegetables", 28000),
            ("Chicken & Chips", "Main", "Crispy chicken with seasoned chips", 18000),
            ("Vegetable Rice", "Main", "Rice with fresh mixed vegetables", 10000),
            ("Fresh Juice", "Drinks", "Fresh seasonal fruit juice", 6000),
            ("Soda", "Drinks", "Cold soft drink", 3000),
            ("Chocolate Cake", "Dessert", "Chocolate cake slice", 8000),
        ]
        conn.executemany(
            "INSERT INTO menu_items(name,category,description,price) VALUES(?,?,?,?)",
            sample)
    conn.commit()
    conn.close()


def cart_items():
    cart = session.get("cart", {})
    if not cart:
        return [], 0
    ids = [int(i) for i in cart]
    placeholders = ",".join("?" * len(ids))
    conn = db()
    rows = conn.execute(
        f"SELECT * FROM menu_items WHERE id IN ({placeholders}) AND available=1", ids
    ).fetchall()
    conn.close()
    result, total = [], 0
    for row in rows:
        qty = max(1, int(cart.get(str(row["id"]), 1)))
        subtotal = row["price"] * qty
        result.append({"item": row, "qty": qty, "subtotal": subtotal})
        total += subtotal
    return result, total


@app.context_processor
def inject():
    return {"cart_count": sum(session.get("cart", {}).values())}


@app.route("/")
def index():
    conn = db()
    items = conn.execute("SELECT * FROM menu_items WHERE available=1 ORDER BY category,name").fetchall()
    conn.close()
    return render_template("index.html", items=items)


@app.post("/cart/add/<int:item_id>")
def add_cart(item_id):
    conn = db()
    item = conn.execute("SELECT id FROM menu_items WHERE id=? AND available=1", (item_id,)).fetchone()
    conn.close()
    if not item:
        flash("That menu item is not available.", "error")
        return redirect(url_for("index"))
    cart = session.setdefault("cart", {})
    key = str(item_id)
    cart[key] = int(cart.get(key, 0)) + 1
    session.modified = True
    flash("Item added to your order.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/cart")
def cart():
    items, total = cart_items()
    return render_template("cart.html", items=items, total=total)


@app.post("/cart/update")
def update_cart():
    cart = session.get("cart", {})
    for key, value in request.form.items():
        if key.startswith("qty_"):
            item_id = key[4:]
            try:
                qty = int(value)
                if qty <= 0:
                    cart.pop(item_id, None)
                else:
                    cart[item_id] = min(qty, 99)
            except ValueError:
                pass
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.post("/cart/clear")
def clear_cart():
    session.pop("cart", None)
    return redirect(url_for("cart"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        email = request.form.get("email", "").strip()
        password = request.form["password"]
        if not name or not phone or not password:
            flash("Name, phone and password are required.", "error")
            return redirect(url_for("register"))
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO customers(name,phone,email,password,created_at) VALUES(?,?,?,?,?)",
                (name, phone, email, password, datetime.now().isoformat(timespec="seconds")))
            conn.commit()
            session["customer_id"] = cur.lastrowid
            session["customer_name"] = name
            session["customer_phone"] = phone
            flash("Account created.", "success")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash("That phone number is already registered.", "error")
        finally:
            conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone, password = request.form["phone"].strip(), request.form["password"]
        conn = db()
        row = conn.execute("SELECT * FROM customers WHERE phone=? AND password=?",
                           (phone, password)).fetchone()
        conn.close()
        if row:
            session["customer_id"] = row["id"]
            session["customer_name"] = row["name"]
            session["customer_phone"] = row["phone"]
            return redirect(url_for("index"))
        flash("Invalid phone number or password.", "error")
    return render_template("login.html")


@app.get("/logout")
def logout():
    for key in ("customer_id", "customer_name", "customer_phone"):
        session.pop(key, None)
    return redirect(url_for("index"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total = cart_items()
    if not items:
        return redirect(url_for("cart"))
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        order_type = request.form["order_type"]
        table_no = request.form.get("table_no", "").strip()
        address = request.form.get("address", "").strip()
        if not name or not phone:
            flash("Name and phone are required.", "error")
            return redirect(url_for("checkout"))
        if order_type == "Dine-in" and not table_no:
            flash("Enter your table number for dine-in.", "error")
            return redirect(url_for("checkout"))
        if order_type == "Delivery" and not address:
            flash("Enter the delivery address.", "error")
            return redirect(url_for("checkout"))

        conn = db()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        order_no = f"ORD-{stamp}-{conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM orders').fetchone()[0]}"
        cur = conn.execute("""INSERT INTO orders
            (order_no,customer_id,customer_name,phone,order_type,table_no,address,total,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (order_no, session.get("customer_id"), name, phone, order_type,
             table_no, address, total, "Received",
             datetime.now().isoformat(timespec="seconds")))
        order_id = cur.lastrowid
        for x in items:
            conn.execute("""INSERT INTO order_items
                (order_id,menu_item_id,item_name,quantity,unit_price,subtotal)
                VALUES(?,?,?,?,?,?)""",
                (order_id, x["item"]["id"], x["item"]["name"], x["qty"],
                 x["item"]["price"], x["subtotal"]))
        conn.commit()
        conn.close()
        session.pop("cart", None)
        return render_template("order_success.html", order_no=order_no, total=total)
    return render_template("checkout.html", items=items, total=total)


@app.route("/track", methods=["GET", "POST"])
def track():
    order = None
    items = []
    order_no = request.values.get("order_no", "").strip()
    if order_no:
        conn = db()
        order = conn.execute("SELECT * FROM orders WHERE order_no=?", (order_no,)).fetchone()
        if order:
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?",
                                 (order["id"],)).fetchall()
        conn.close()
        if not order:
            flash("Order not found. Check the order number.", "error")
    return render_template("track.html", order=order, items=items)


@app.get("/my-orders")
def my_orders():
    if not session.get("customer_id"):
        return redirect(url_for("login"))
    conn = db()
    orders = conn.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC",
                          (session["customer_id"],)).fetchall()
    conn.close()
    return render_template("my_orders.html", orders=orders)


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        date = request.form["date"]
        time = request.form["time"]
        guests = int(request.form["guests"])
        conn = db()
        conn.execute("""INSERT INTO bookings
            (customer_id,customer_name,phone,booking_date,booking_time,guests,created_at)
            VALUES(?,?,?,?,?,?,?)""",
            (session.get("customer_id"), name, phone, date, time, guests,
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        conn.close()
        flash("Booking request submitted. The restaurant will confirm it.", "success")
        return redirect(url_for("book"))
    return render_template("book.html")


def staff_required():
    return session.get("staff") is True


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        conn = db()
        row = conn.execute("SELECT * FROM staff WHERE username=? AND password=?",
                           (request.form["username"], request.form["password"])).fetchone()
        conn.close()
        if row:
            session["staff"] = True
            return redirect(url_for("admin"))
        flash("Invalid staff login.", "error")
    return render_template("admin_login.html")


@app.get("/admin/logout")
def admin_logout():
    session.pop("staff", None)
    return redirect(url_for("index"))


@app.get("/admin")
def admin():
    if not staff_required():
        return redirect(url_for("admin_login"))
    conn = db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
    bookings = conn.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT 30").fetchall()
    menu = conn.execute("SELECT * FROM menu_items ORDER BY category,name").fetchall()
    stats = {
        "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM orders WHERE status NOT IN ('Completed','Cancelled')").fetchone()[0],
        "sales": conn.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status='Completed'").fetchone()[0],
        "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
    }
    conn.close()
    return render_template("admin.html", orders=orders, bookings=bookings, menu=menu, stats=stats)


@app.post("/admin/order/<int:order_id>/status")
def order_status(order_id):
    if not staff_required():
        return redirect(url_for("admin_login"))
    status = request.form["status"]
    allowed = {"Received", "Preparing", "Ready", "Completed", "Cancelled"}
    if status in allowed:
        conn = db()
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        conn.commit()
        conn.close()
    return redirect(url_for("admin"))


@app.post("/admin/booking/<int:booking_id>/status")
def booking_status(booking_id):
    if not staff_required():
        return redirect(url_for("admin_login"))
    status = request.form["status"]
    if status in {"Pending", "Confirmed", "Completed", "Cancelled"}:
        conn = db()
        conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
        conn.commit()
        conn.close()
    return redirect(url_for("admin"))


@app.post("/admin/menu/add")
def menu_add():
    if not staff_required():
        return redirect(url_for("admin_login"))
    conn = db()
    conn.execute("INSERT INTO menu_items(name,category,description,price) VALUES(?,?,?,?)",
                 (request.form["name"], request.form["category"],
                  request.form.get("description",""), float(request.form["price"])))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.post("/admin/menu/<int:item_id>/toggle")
def menu_toggle(item_id):
    if not staff_required():
        return redirect(url_for("admin_login"))
    conn = db()
    conn.execute("UPDATE menu_items SET available=CASE available WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
                 (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
