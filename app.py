import os
import sqlite3
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd
app.debug = True

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    db = sqlite3.connect("finance.db")
    db.row_factory = sqlite3.Row
    """Show your current money"""
    tmp = db.execute("SELECT cash FROM users WHERE id = ?", (session["user_id"],))
    yourCash = tmp.fetchone()
    """Create a purchase history db"""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
    check = cursor.fetchone()
    if not check:
        db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    """Show portfolio of stocks"""
    cursor1 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Buy' AND id = ? GROUP BY stock", (session["user_id"],))
    cursor2 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Sell' AND id = ? GROUP BY stock", (session["user_id"],))
    buyVal = cursor1.fetchall()
    sellVal = cursor2.fetchall()
    """Create a new table to keep track the stocks of users"""
    tmp = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("ownedStock",))
    test = tmp.fetchone()
    if not test:
        db.execute("CREATE TABLE ownedStock (id NOT NULL, stock TEXT NOT NULL, amount INTEGER NOT NULL, price TEXT NOT NULL, totalValue TEXT NOT NULL)")
        db.commit()
    if not sellVal:
        for i in buyVal:
            stock = i["stock"]
            tmp = db.execute("SELECT * FROM ownedStock WHERE stock = ? AND id = ?", (stock, session["user_id"]))
            check = tmp.fetchone()
            if not check:
                """Initialising some values of the table"""
                db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (session["user_id"], stock, 0, "0", "0"))
            """Format the money"""
            tmp = lookup(stock)
            currentPrice = tmp["price"]
            formatedPrice = usd(currentPrice)
            formatedTotalValue = usd(int(currentPrice) * i["SUM(amount)"])
            db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (int(i["SUM(amount)"]), formatedPrice, formatedTotalValue, session["user_id"], stock))
            db.commit()
    elif not buyVal:
        return apology("You haven't bought anything")
    else:
        for i in buyVal:
            for j in sellVal:
                if i["stock"] == j["stock"]:
                    stock = i["stock"]
                    check = db.execute("SELECT stock FROM ownedStock WHERE stock = ? AND id = ?", (stock, session["user_id"]))
                    tst = check.fetchone()
                    if not tst:
                         """Initialising some values of the table"""
                         db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (session["user_id"], stock, 0, "0", "0"))
                    amount = int(i["SUM(amount)"]) - j["SUM(amount)"]
                    tmp = lookup(stock)
                    price = usd(tmp["price"])
                    db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (amount, price, usd(amount * tmp["price"]), session["user_id"], stock))
                    db.commit()
    db.execute("DELETE FROM ownedStock WHERE amount = ?", (0,))
    db.commit()
    """Send the results"""
    rawResults = db.execute("SELECT * FROM ownedStock WHERE id = ?", (session["user_id"],))
    results = rawResults.fetchall()
    return render_template("index.html", purchases=results, money=usd((yourCash[0])))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        shares = request.form.get("shares")
        value = lookup(request.form.get("symbol"))
        """Check for invalid inputs"""
        if not value:
            return apology("Not found")
        if int(shares) <= 0 or not shares.isdigit():
            return apology("Invalid shares")
        """Operating the purchase"""
        db = sqlite3.connect("finance.db")
        cursor = db.execute("SELECT cash FROM users WHERE id = ?", (session["user_id"],))
        cash = cursor.fetchone()
        if int(shares) * value["price"] > cash[0]:
            return apology("You are impoverished:)")
        else:
            """Create a purchase history db"""
            cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
            check = cursor.fetchone()
            if not check:
                db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
            today = datetime.now()
            formatted_date = today.strftime("%d/%m/%Y")
            db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (session["user_id"], value["symbol"], int(shares), "Buy", int(shares) * value["price"], formatted_date))
            """Subtract the money in the user's account"""
            db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] - int(shares) * value["price"], session["user_id"]))
            db.commit()
            return redirect("/")
    elif request.method == "GET":
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    history = sqlite3.connect("finance.db")
    history.row_factory = sqlite3.Row
    spending = {}
    cursor = history.execute("SELECT spending, id, amount, stock, status, time FROM history WHERE id = ?", (session["user_id"],))
    results = cursor.fetchall()
    for i in results:
        spending[i["spending"]] = usd(i["spending"])
    return render_template("history.html", purchases=results, spending=spending)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    elif request.method == "POST":
        input = request.form.get("symbol")
        value = lookup(input)
        if value:
            name = value["name"]
            price = usd(value["price"])
            symbol = value["symbol"]
            return render_template("quoted.html", value=(name, price, symbol))
        else: return apology("Not found")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
         db = sqlite3.connect("finance.db")
         username = request.form.get("username")
         password = request.form.get("password")
         confirm = request.form.get("confirmation")
         if username:
             """Check if there exists a similar name"""
             check = db.execute("SELECT username FROM users WHERE username = ?", (username,))
             if check.fetchone():
                return apology("Already chosen username")
             else: print(username)
         else: return apology("Username musn't be blank")
         """Check the password"""
         if password and confirm and password == confirm:
             db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", (username, generate_password_hash(password)))
             db.commit()
         else: return apology("Please check your password again")
         return redirect("/")
    elif request.method == "GET":
         return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    db = sqlite3.connect("finance.db")
    if request.method == "GET":
        tmp = db.execute("SELECT stock FROM ownedStock WHERE id = ? GROUP BY stock", (session["user_id"],))
        opts = tmp.fetchall()
        if opts:
            return render_template("sell.html", options=opts)
        else:
            return apology("You don't own any stocks")
    else:
        """Update history table"""
        """Create a purchase history db"""
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
        check = cursor.fetchone()
        if not check:
            db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
        today = datetime.now()
        formatted_date = today.strftime("%d/%m/%Y")
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")
        cursor = db.execute("SELECT cash FROM users WHERE id = ?", (session["user_id"],))
        cash = cursor.fetchone()
        value = lookup(symbol)
        """Check for amount in ownedStock"""
        tmp = db.execute("SELECT amount FROM ownedStock WHERE stock = ? AND id = ?", (symbol, session["user_id"]))
        amount = tmp.fetchone()
        if int(shares) > int(amount[0]):
            return apology("Invalid input of shares")
        else:
            db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (session["user_id"], symbol, int(shares), "Sell", int(shares) * value["price"], formatted_date))
            """Increase the money in the user's account"""
            db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] + int(shares) * value["price"], session["user_id"]))
            db.commit()
            return redirect("/")
