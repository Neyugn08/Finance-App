import os
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from helpers import apology, login_required, lookup, usd

# Configure application
app = FastAPI()

# Custom filter
templates = Jinja2Templates(directory="./templates")
templates.env.filters["usd"] = usd

# Configure session to use signed cookies
app.add_middleware(SessionMiddleware, secret_key="some-secret-key")

@app.middleware("http") 
async def add_headers_to_request(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response

@app.get("/")
def index(request: Request, user_id: int = login_required):
    # Redirect to login if not logged in
    if isinstance(user_id, RedirectResponse):
        return user_id  
    db = sqlite3.connect("./finance.db")
    db.row_factory = sqlite3.Row
    """Show your current money"""
    tmp = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,))
    yourCash = tmp.fetchone()
    """Create a purchase history db"""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
    check = cursor.fetchone()
    if not check:
        db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    """Show portfolio of stocks"""
    cursor1 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Buy' AND id = ? GROUP BY stock", (user_id,))
    cursor2 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Sell' AND id = ? GROUP BY stock", (user_id,))
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
            tmp = db.execute("SELECT * FROM ownedStock WHERE stock = ? AND id = ?", (stock, user_id))
            check = tmp.fetchone()
            if not check:
                """Initialising some values of the table"""
                db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (user_id, stock, 0, "0", "0"))
            """Format the money"""
            tmp = lookup(stock)
            currentPrice = tmp["price"]
            formatedPrice = usd(currentPrice)
            formatedTotalValue = usd(int(currentPrice) * i["SUM(amount)"])
            db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (int(i["SUM(amount)"]), formatedPrice, formatedTotalValue, user_id, stock))
            db.commit()
    elif not buyVal:
        return apology(request, "You haven't bought anything")
    else:
        for i in buyVal:
            for j in sellVal:
                if i["stock"] == j["stock"]:
                    stock = i["stock"]
                    check = db.execute("SELECT stock FROM ownedStock WHERE stock = ? AND id = ?", (stock, user_id))
                    tst = check.fetchone()
                    if not tst:
                         """Initialising some values of the table"""
                         db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (user_id, stock, 0, "0", "0"))
                    amount = int(i["SUM(amount)"]) - j["SUM(amount)"]
                    tmp = lookup(stock)
                    price = usd(tmp["price"])
                    db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (amount, price, usd(amount * tmp["price"]), user_id, stock))
                    db.commit()
    db.execute("DELETE FROM ownedStock WHERE amount = ?", (0,))
    db.commit()
    """Send the results"""
    rawResults = db.execute("SELECT * FROM ownedStock WHERE id = ?", (user_id,))
    results = rawResults.fetchall()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "purchases": results,
            "money": usd(yourCash[0]),
        },
    )   

@app.get("/buy")
def render_buy_page(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    """Render the buy page"""
    return templates.TemplateResponse("buy.html", {"request": request})

@app.post("/buy")
async def buy(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    """Buy shares of stock"""
    shares = request.form.get("shares")
    form = await request.form()
    symbol = form.get("symbol")
    value = lookup(symbol)
    """Check for invalid inputs"""
    if not value:
        return apology(request,"Not found")
    if int(shares) <= 0 or not shares.isdigit():
        return apology(request, "Invalid shares")
    """Operating the purchase"""
    db = sqlite3.connect("finance.db")
    cursor = db.execute("SELECT cash FROM users WHERE id = ?", (request.session["user_id"],))
    cash = cursor.fetchone()
    if int(shares) * value["price"] > cash[0]:
        return apology(request, "You are impoverished:)")
    else:
        """Create a purchase history db"""
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
        check = cursor.fetchone()
        if not check:
            db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
        today = datetime.now()
        formatted_date = today.strftime("%d/%m/%Y")
        db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (request.session["user_id"], value["symbol"], int(shares), "Buy", int(shares) * value["price"], formatted_date))
        """Subtract the money in the user's account"""
        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] - int(shares) * value["price"], request.session["user_id"]))
        db.commit()
        return RedirectResponse(url="/", status_code=303)

@app.get("/history")
def history(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    """Show history of transactions"""
    history = sqlite3.connect("finance.db")
    history.row_factory = sqlite3.Row
    spending = {}
    cursor = history.execute("SELECT spending, id, amount, stock, status, time FROM history WHERE id = ?", (request.session["user_id"],))
    results = cursor.fetchall()
    for i in results:
        spending[i["spending"]] = usd(i["spending"])
    return templates.TemplateResponse(
        "history.html", 
        { 
            "request": request,
            "purchases": results, 
            "spending": spending
        },
    )

@app.get("/login")
def render_login_page(request: Request):
    """Render the login page"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request):
    """Log user in"""
    # Forget any user_id
    request.session.clear()
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    # Ensure username was submitted
    if not username:
        return apology(request, "Must provide username", 403)
    # Ensure password was submitted
    elif not password:
        return apology(request, "Must provide password", 403)
    # Query database for username
    db = sqlite3.connect("./finance.db")
    rows = db.execute("SELECT * FROM users WHERE username = ?", username)
    # Ensure username exists and password is correct
    if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
        return apology(request, "Invalid username and/or password", 403)
    # Remember which user has logged in
    request.session["user_id"] = rows[0]["id"]
    # Redirect user to home page
    return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    """Log user out"""
    # Forget any user_id
    request.session.clear()
    # Redirect user to login form
    return RedirectResponse(url="/")

@app.get("/quote")
def render_quote_page(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    """Render the quote page"""
    return templates.TemplateResponse("quote.html", {"request": request})

@app.post("/quote")
async def quote(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    form = await request.form()
    input = form.get("symbol")
    value = lookup(input)
    if value:
        name = value["name"]
        price = usd(value["price"])
        symbol = value["symbol"]
        return templates.TemplateResponse("quoted.html", {"request": request, "value": (name, price, symbol)})
    else: 
        return apology(request, "Not found")

@app.get("/register")
def render_register_page(request: Request):
    """Render the register page"""
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(request: Request):
    """Register user"""
    form = await request.form()
    db = sqlite3.connect("finance.db")
    username = form.get("username")
    password = form.get("password")
    confirm = form.get("confirmation")
    if username:
        """Check if there exists a similar name"""
        check = db.execute("SELECT username FROM users WHERE username = ?", (username,))
        if check.fetchone():
            return apology(request, "Already chosen username")
        else: 
            print(username)
    else: 
        return apology(request, "Username musn't be blank")
    """Check the password"""
    if password and confirm and password == confirm:
        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", (username, generate_password_hash(password)))
        db.commit()
    else: \
        return apology(request, "Please check your password again")
    return RedirectResponse(url="/")

@app.get("/sell")
def render_sell_page(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    db = sqlite3.connect("finance.db")
    tmp = db.execute("SELECT stock FROM ownedStock WHERE id = ? GROUP BY stock", (request.session["user_id"],))
    opts = tmp.fetchall()
    if opts:
        return templates.TemplateResponse("sell.html", {"request": request, "options": opts})
    else:
        return apology(request, "You don't own any stocks")

@app.post("/sell")
async def sell(request: Request, auth: int = login_required):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    """Sell shares of stock"""
    db = sqlite3.connect("finance.db")
    """Update history table"""
    """Create a purchase history db"""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
    check = cursor.fetchone()
    if not check:
        db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    today = datetime.now()
    formatted_date = today.strftime("%d/%m/%Y")
    form = await request.form()
    symbol = form.get("symbol")
    shares = form.get("shares")
    cursor = db.execute("SELECT cash FROM users WHERE id = ?", (request.session["user_id"],))
    cash = cursor.fetchone()
    value = lookup(symbol)
    """Check for amount in ownedStock"""
    tmp = db.execute("SELECT amount FROM ownedStock WHERE stock = ? AND id = ?", (symbol, request.session["user_id"]))
    amount = tmp.fetchone()
    if int(shares) > int(amount[0]):
        return apology(request, "Invalid input of shares")
    else:
        db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (request.session["user_id"], symbol, int(shares), "Sell", int(shares) * value["price"], formatted_date))
        """Increase the money in the user's account"""
        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] + int(shares) * value["price"], request.session["user_id"]))
        db.commit()
        return RedirectResponse(url="/")
