import sqlite3
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from helpers import apology, login_required, lookup, usd, get_db_name, table_reconciliation
from fastapi.staticfiles import StaticFiles

# Configure application
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Custom filter
templates = Jinja2Templates(directory="./templates")
templates.env.filters["usd"] = usd

# Configure session with middleware to use signed cookies
app.add_middleware(SessionMiddleware, secret_key="some-secret-key")

@app.middleware("http") 
async def add_headers_to_request(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response

@app.get("/me")
async def me(request: Request, auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth  
    
    user_id = auth
    return {"user_id": user_id}

@app.get("/")
def index(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth  
    
    user_id = auth
    db = sqlite3.connect(db_name)
    db.row_factory = sqlite3.Row

    # Look up for your current cash
    tmp = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,))
    yourCash = tmp.fetchone()
    # Create a purchase history db if there is none
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
    check = cursor.fetchone()
    if not check:
        db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    # Look up for portfolio of stocks
    cursor1 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Buy' AND id = ? GROUP BY stock", (user_id,))
    cursor2 = db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Sell' AND id = ? GROUP BY stock", (user_id,))
    buyVal = cursor1.fetchall()
    sellVal = cursor2.fetchall()
    # Create a new table to keep track the stocks of users if there is none
    tmp = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("ownedStock",))
    test = tmp.fetchone()
    if not test:
        db.execute("CREATE TABLE ownedStock (id NOT NULL, stock TEXT NOT NULL, amount INTEGER NOT NULL, price TEXT NOT NULL, totalValue TEXT NOT NULL)")
        db.commit()
    # Update the table(s) with current stocks and their values
    if not buyVal:
        db.close()
        return apology(request, "You haven't bought anything")
    elif not sellVal:
        for i in buyVal:
            stock = i["stock"]
            tmp = db.execute("SELECT * FROM ownedStock WHERE stock = ? AND id = ?", (stock, user_id))
            check = tmp.fetchone()
            if not check:
                # Initialising some values of the table
                db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (user_id, stock, 0, "0", "0"))
            tmp = lookup(stock)
            currentPrice = tmp["price"]
            totalValue = float(currentPrice) * i["SUM(amount)"]
            db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (int(i["SUM(amount)"]), currentPrice, totalValue, user_id, stock))
            db.commit()
    else:
        # Update ownedstock table based on past transactions
        table_reconciliation(buyVal, sellVal, db, user_id)

    # Delete the stocks with 0 amount
    db.execute("DELETE FROM ownedStock WHERE amount = ?", (0,))
    db.commit()

    # Send the results to the index page
    rawResults = db.execute("SELECT * FROM ownedStock WHERE id = ?", (user_id,))
    results = [dict(result) for result in rawResults.fetchall()]
    # Format the money value
    for result in results: 
        result["price"] = usd(result["price"])
        result["totalValue"] = usd(result["totalValue"])
    db.close()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "purchases": results,
            "money": usd(yourCash[0]),
        },  
    )

@app.get("/buy")
def render_buy_page(request: Request, auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    # Render the buy page
    return templates.TemplateResponse(
        request=request,
        name="buy.html",
    )

@app.post("/buy")
async def buy(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth

    # Get buying info 
    form = await request.form()
    symbol = form.get("symbol")
    shares = form.get("shares")
    value = lookup(symbol)

    # Check for invalid inputs
    if not value:
        return apology(request,"Not found")
    if not shares or not shares.isdigit() or int(shares) <= 0:
        return apology(request, "Invalid input of shares")
    
    # Operating the purchase
    db = sqlite3.connect(db_name)
    cursor = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,))
    cash = cursor.fetchone()
    if int(shares) * value["price"] > cash[0]:
        db.close()
        return apology(request, "You are impoverished:)")
    else:
        # Create a purchase history db if there's none
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
        check = cursor.fetchone()
        if not check:
            db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
        
        # Format the date of the purchase
        today = datetime.now()
        formatted_date = today.strftime("%d/%m/%Y")
        db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (user_id, value["symbol"], int(shares), "Buy", int(shares) * value["price"], formatted_date))
        
        # Subtract the money in the user's account
        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] - int(shares) * value["price"], user_id))
        db.commit()
        db.close()
        return RedirectResponse(url="/", status_code=303)

@app.get("/history")
def history(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth

    # Show history of transactions
    history = sqlite3.connect(db_name)
    history.row_factory = sqlite3.Row
    spending = {}
    cursor = history.execute("SELECT spending, id, amount, stock, status, time FROM history WHERE id = ?", (user_id,))
    results = cursor.fetchall()
    for i in results:
        spending[i["spending"]] = usd(i["spending"])
    history.close()
    return templates.TemplateResponse(
        request=request,
        name="history.html", 
        context={ 
            "purchases": results, 
            "spending": spending
        },
    )

@app.get("/login")
def render_login_page(request: Request):
    # Render the login page
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
async def login(request: Request, db_name: str = Depends(get_db_name)):
    # Log user in only after forgetting any cached user_id
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
    
    # Query db for username
    db = sqlite3.connect(db_name)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM users WHERE username = ?", (username,))
    rows = rows.fetchall()

    # Ensure username exists and password is correct
    if not rows or not check_password_hash(rows[0]["hash"], password):
        db.close()
        return apology(request, "Invalid username and/or password", 403)
    
    # Remember which user has logged in
    request.session["user_id"] = rows[0]["id"]

    db.close()

    # Redirect user to home page
    return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    # Log out by forgetting any user_id
    request.session.clear()

    # Redirect user to login form
    return RedirectResponse(url="/", status_code=303)

@app.get("/quote")
def render_quote_page(request: Request, auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    # Render the quote page
    return templates.TemplateResponse(
        request=request,
        name="quote.html",
    )

@app.post("/quote")
async def quote(request: Request, auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    form = await request.form()
    input = form.get("symbol")
    value = lookup(input)

    # Look up for the stock that is searched
    if value:
        name = value["name"]
        price = usd(value["price"])
        symbol = value["symbol"]
        return templates.TemplateResponse(
            request=request,
            name="quoted.html", 
            context={
                "value": (name, price, symbol)
            }
        )
    else: 
        return apology(request, "Not found")

@app.get("/register")
def render_register_page(request: Request):
    # Render the register page
    return templates.TemplateResponse(
        request=request,
        name="register.html"
    )

@app.post("/register")
async def register(request: Request, db_name: str = Depends(get_db_name)):
    # Register user
    form = await request.form()
    db = sqlite3.connect(db_name)
    username = form.get("username")
    password = form.get("password")
    confirm = form.get("confirmation")

    if username:
        if not password:
            return apology(request, "Must provide password", 403)
        # Check if there exists a similar name
        check = db.execute("SELECT username FROM users WHERE username = ?", (username,))
        if check.fetchone():
            db.close()
            return apology(request, "Already chosen username")
    else: 
        # Check for blank input
        db.close()
        return apology(request, "Username musn't be blank")
    # Check the password
    if password and confirm and password == confirm:
        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", (username, generate_password_hash(password)))
        db.commit()
        db.close()
    else: 
        db.close()
        return apology(request, "Please check your password again")
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/sell")
def render_sell_page(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth 

    db = sqlite3.connect(db_name)
    tmp = db.execute("SELECT stock FROM ownedStock WHERE id = ? GROUP BY stock", (user_id,))
    opts = tmp.fetchall()
    db.close()

    if opts:
        return templates.TemplateResponse(
            request=request,
            name="sell.html", 
            context={
                "options": opts
            }
        )
    else:
        return apology(request, "You don't own any stocks")

@app.post("/sell")
async def sell(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth
    db = sqlite3.connect(db_name)

    # Create a purchase history db if there is none
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("history",))
    check = cursor.fetchone()
    if not check:
        db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    
    today = datetime.now()
    formatted_date = today.strftime("%d/%m/%Y")
    form = await request.form()
    symbol = form.get("symbol")
    shares = form.get("shares")
    cursor = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,))
    cash = cursor.fetchone()
    value = lookup(symbol)

    # Check for amount in ownedStock
    tmp = db.execute("SELECT amount FROM ownedStock WHERE stock = ? AND id = ?", (symbol, user_id))
    amount = tmp.fetchone()
    # Handle the case where user tries to sell stock they don't own
    if not amount: 
        db.close()
        return apology(request, "You don't own this stock")
    if not shares or not shares.isdigit() or int(shares) <= 0 or (int(shares) > int(amount[0])):
        db.close()
        return apology(request, "Invalid input of shares")
    else:
        db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (user_id, symbol, int(shares), "Sell", int(shares) * value["price"], formatted_date))
        # Increase the money in the user's account
        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash[0] + int(shares) * value["price"], user_id))
        db.commit()
        db.close()
        return RedirectResponse(url="/", status_code=303)
