import requests
from pathlib import Path
import psycopg 
from decimal import Decimal
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / ".." / "frontend" / "templates"))

def apology(request, message, code=400):
    """Render message as an apology to user."""

    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [
            ("-", "--"),
            (" ", "-"),
            ("_", "__"),
            ("?", "~q"),
            ("%", "~p"),
            ("#", "~h"),
            ("/", "~s"),
            ('"', "''"),
        ]:
            s = s.replace(old, new)
        return s

    return templates.TemplateResponse(
        request=request,
        name="apology.html",
        context={
            "top": code,
            "bottom": escape(message),
        },
        status_code=code
    )

def login_required(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)
    return user_id

def lookup(symbol):
    """Look up quote for symbol."""
    url = f"https://finance.cs50.io/quote?symbol={symbol.upper()}"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for HTTP error responses
        quote_data = response.json()
        return {
            "name": quote_data["companyName"],
            "price": quote_data["latestPrice"],
            "symbol": symbol.upper()
        }
    except requests.RequestException as e:
        print(f"Request error: {e}")
    except (KeyError, ValueError) as e:
        print(f"Data parsing error: {e}")
    return None

def usd(value):
    value = float(value)
    """Format value as USD."""
    return f"${value:,.2f}"

def get_db_name(): 
    return "finance"  # Default database name

def table_reconciliation(buyVal, sellVal, cursor, user_id): 
    # Implement a dict to avoid nested loop
    stock_mapping = {} 
    for index, i in enumerate(buyVal):
        stock_mapping[i["stock"]] = index
    for j in sellVal:
        i = buyVal[stock_mapping[j["stock"]]]
        stock = i["stock"]
        cursor.execute("SELECT stock FROM ownedStock WHERE stock = %s AND id = %s", (stock, user_id))
        tst = cursor.fetchone()
        if not tst:
            # Initialising some values of the table
            cursor.execute("INSERT INTO ownedStock (id, stock, amount, price, total_value) VALUES (%s, %s, %s, %s, %s)", (user_id, stock, 0, "0", "0"))
        amount = i["total_amount"] - j["total_amount"]
        tmp = lookup(stock)
        price = Decimal(str(tmp["price"]))
        cursor.execute("UPDATE ownedStock SET amount = %s, price = %s, total_value = %s WHERE id = %s AND stock = %s", (amount, price, amount * price, user_id, stock))
    
def setup_db(info, db_name):
    with psycopg.connect(f"{info} dbname={db_name}") as conn: 
        with conn.cursor() as cursor: 
            # Create new tables if there's none
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT NOT NULL, hash TEXT NOT NULL, cash NUMERIC NOT NULL DEFAULT 10000.00)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS username ON users (username)")
            cursor.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER NOT NULL REFERENCES users(id), stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS ownedStock (id INTEGER NOT NULL REFERENCES users(id), stock TEXT NOT NULL, amount INTEGER NOT NULL, price NUMERIC NOT NULL, total_value NUMERIC NOT NULL)")
