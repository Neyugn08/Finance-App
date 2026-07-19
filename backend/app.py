from backend.config import *
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from decimal import Decimal
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from backend.helpers import apology, login_required, lookup, usd, get_db_name, table_reconciliation, setup_db
from fastapi.staticfiles import StaticFiles

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / ".." / "frontend" / "static"), name="static")
if instance_connection_name: 
    conn_info = f"host={DB_HOST} user={DB_USER} password={DB_PASSWORD}"
else: 
    conn_info = f"host={DB_HOST} port=5432 user={DB_USER} password={DB_PASSWORD}"
setup_db(conn_info, get_db_name())

# Custom filter
templates = Jinja2Templates(directory=str(BASE_DIR / ".." / "frontend" / "templates"))
templates.env.filters["usd"] = usd

# Configure session with middleware to use signed cookies
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

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

    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            # Look up for your current cash
            cursor.execute("SELECT cash FROM users WHERE id = %s", (user_id,))
            cash = cursor.fetchone()["cash"]

            # Look up for portfolio of stocks
            cursor.execute("SELECT stock, SUM(amount) as total_amount, SUM(spending) as total_spending FROM history WHERE status = 'Buy' AND id = %s GROUP BY stock", (user_id,))
            buyVal = cursor.fetchall()
            cursor.execute("SELECT stock, SUM(amount) as total_amount, SUM(spending) as total_spending FROM history WHERE status = 'Sell' AND id = %s GROUP BY stock", (user_id,))
            sellVal = cursor.fetchall()

           # Update the table(s) with current stocks and their values
            if not buyVal:
                return apology(request, "You haven't bought anything")
            elif not sellVal:
                for i in buyVal:
                    stock = i["stock"]
                    cursor.execute("SELECT * FROM ownedStock WHERE stock = %s AND id = %s", (stock, user_id))
                    check = cursor.fetchone()
                    if not check:
                        # Initialising some values of the table
                        cursor.execute("INSERT INTO ownedStock (id, stock, amount, price, total_value) VALUES (%s, %s, %s, %s, %s)", (user_id, stock, 0, 0, 0))
                    tmp = lookup(stock)
                    currentPrice = tmp["price"]
                    total_value = Decimal(str(currentPrice)) * i["total_amount"]
                    cursor.execute("UPDATE ownedStock SET amount = %s, price = %s, total_value = %s WHERE id = %s AND stock = %s", (int(i["total_amount"]), currentPrice, total_value, user_id, stock))
            else:
                # Update ownedstock table based on past transactions
                table_reconciliation(buyVal, sellVal, cursor, user_id)

            # Delete the stocks with 0 amount
            cursor.execute("DELETE FROM ownedStock WHERE amount = %s", (0,))

            # Send the results to the index page
            cursor.execute("SELECT * FROM ownedStock WHERE id = %s", (user_id,))
            results = cursor.fetchall()
            # Format the money value
            for result in results: 
                result["price"] = usd(result["price"])
                result["totalValue"] = usd(result["total_value"])
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "purchases": results,
                    "money": usd(cash),
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
    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor:  
            cursor.execute("SELECT cash FROM users WHERE id = %s", (user_id,))
            cash = cursor.fetchone()["cash"]
            if int(shares) * value["price"] > cash:
                return apology(request, "You are impoverished:)")
            else:
                # Format the date of the purchase
                today = datetime.now()
                formatted_date = today.strftime("%d/%m/%Y")
                cursor.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, value["symbol"], int(shares), "Buy", int(shares) * value["price"], formatted_date))
        
                # Subtract the money in the user's account
                cursor.execute("UPDATE users SET cash = %s WHERE id = %s", (cash - int(shares) * Decimal(str(value["price"])), user_id))

                # Update owned stock 

                return RedirectResponse(url="/", status_code=303)

@app.get("/history")
def history(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth

    # Show history of transactions
    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            spending = {}
            cursor.execute("SELECT spending, id, amount, stock, status, time FROM history WHERE id = %s", (user_id,))
            results = cursor.fetchall()
            for i in results:
                spending[i["spending"]] = usd(i["spending"])
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
    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            rows = cursor.fetchall()

            # Ensure username exists and password is correct
            if not rows or not check_password_hash(rows[0]["hash"], password):
                return apology(request, "Invalid username and/or password", 403)
    
            # Remember which user has logged in
            request.session["user_id"] = rows[0]["id"]

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
    username = form.get("username")
    password = form.get("password")
    confirm = form.get("confirmation")

    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            if username:
                if not password:
                    return apology(request, "Must provide password", 403)
                # Check if there exists a similar name
                cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    return apology(request, "Already chosen username")
            else: 
                # Check for blank input
                return apology(request, "Username musn't be blank")
            # Check the password
            if password and confirm and password == confirm:
                cursor.execute("INSERT INTO users (username, hash) VALUES(%s, %s)", (username, generate_password_hash(password)))
            else: 
                return apology(request, "Please check your password again")
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/sell")
def render_sell_page(request: Request, db_name: str = Depends(get_db_name), auth = Depends(login_required)):
    # Redirect to login if not logged in
    if isinstance(auth, RedirectResponse):
        return auth
    
    user_id = auth 

    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            cursor.execute("SELECT stock FROM ownedStock WHERE id = %s GROUP BY stock", (user_id,))
            opts = cursor.fetchall()

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

    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor: 
            today = datetime.now()
            formatted_date = today.strftime("%d/%m/%Y")
            form = await request.form()
            symbol = form.get("symbol")
            shares = form.get("shares")
            cursor.execute("SELECT cash FROM users WHERE id = %s", (user_id,))
            cash = cursor.fetchone()["cash"]
            value = lookup(symbol)

            # Check for amount in ownedStock
            cursor.execute("SELECT amount FROM ownedStock WHERE stock = %s AND id = %s", (symbol, user_id))
            check = cursor.fetchone()
            # Handle the case where user tries to sell stock they don't own
            if not check: 
                return apology(request, "You don't own this stock")
            amount = check["amount"]
            if not shares or not shares.isdigit() or int(shares) <= 0 or (int(shares) > int(amount)):
                return apology(request, "Invalid input of shares")
            else:
                cursor.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, symbol, int(shares), "Sell", int(shares) * value["price"], formatted_date))
                # Increase the money in the user's account
                cursor.execute("UPDATE users SET cash = %s WHERE id = %s", (cash + int(shares) * Decimal(str(value["price"])), user_id))
                # Update owned stock
                return RedirectResponse(url="/", status_code=303)
