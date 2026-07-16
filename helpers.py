import requests
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

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
    return "finance.db"  # Default database name

def table_reconciliation(buyVal, sellVal, db, user_id): 
    # Implement a dict to avoid nested loop
    stock_mapping = {} 
    for index, i in enumerate(buyVal):
        stock_mapping[i["stock"]] = index
    for j in sellVal:
        i = buyVal[stock_mapping[j["stock"]]]
        stock = i["stock"]
        check = db.execute("SELECT stock FROM ownedStock WHERE stock = ? AND id = ?", (stock, user_id))
        tst = check.fetchone()
        if not tst:
            # Initialising some values of the table
            db.execute("INSERT INTO ownedStock (id, stock, amount, price, totalValue) VALUES (?, ?, ?, ?, ?)", (user_id, stock, 0, "0", "0"))
        amount = int(i["SUM(amount)"]) - j["SUM(amount)"]
        tmp = lookup(stock)
        price = tmp["price"]
        db.execute("UPDATE ownedStock SET amount = ?, price = ?, totalValue = ? WHERE id = ? AND stock = ?", (amount, price, usd(amount * tmp["price"]), user_id, stock))
    db.commit()
    