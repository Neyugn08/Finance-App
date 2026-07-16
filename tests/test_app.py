import os
import sqlite3
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient 
import pytest
from starlette.templating import Jinja2Templates
from helpers import get_db_name, table_reconciliation, usd
from app import app 

templates = Jinja2Templates(directory="templates")
app.dependency_overrides[get_db_name] = lambda: "test.db"

# Create a TestClient fixture to prevent cookie/session issues between tests
@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client

# Create a db fixture
@pytest.fixture
def test_db(): 
    test_db = sqlite3.connect("test.db")
    test_db.row_factory = sqlite3.Row
    yield test_db
    test_db.close()
    if os.path.exists("test.db"):
        os.remove("test.db")

@pytest.fixture
def loggedin_user(client, test_db):
    # Set up a temporary database for testing
    test_db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, username TEXT NOT NULL UNIQUE, hash TEXT NOT NULL, cash NUMERIC NOT NULL DEFAULT 10000.00)")
    # Register a test user
    response = client.post("/register", follow_redirects=False, data={"username": "testuser", "password": "testpass", "confirmation": "testpass"})
    # Log in the test user
    response = client.post("/login", follow_redirects=False, data={"username": "testuser", "password": "testpass"})
    yield response

def test_register(client, test_db):
    # Create a temporary database for testing
    test_db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, username TEXT NOT NULL UNIQUE, hash TEXT NOT NULL, cash NUMERIC NOT NULL DEFAULT 10000.00)")
    response = client.post("/register", follow_redirects=False, data={"username": "testuser", "password": "testpass", "confirmation": "testpass"})
    assert response.status_code == 303
    assert response.headers["location"] == "/" # Redirect to home page means successful registration

    # Edge case testing
    # Blank username
    response = client.post("/register", follow_redirects=False, data={"username": "", "password": "testpass", "confirmation": "testpass"})
    assert response.headers["content-type"] == "text/html; charset=utf-8" # html response means apology message

    # No password
    response = client.post("/register", follow_redirects=False, data={"username": "test_user", "password": "", "confirmation": ""})
    assert response.headers["content-type"] == "text/html; charset=utf-8" # html response means apology message

def test_buy_stock(loggedin_user, client, monkeypatch, test_db):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying a stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)
    assert response.status_code == 303  
    assert response.headers["location"] == "/"  # Redirecting to home page after buying means successful purchase

    # Check whether the history table was updated correctly
    user_id = client.get("/me").json()["user_id"]
    cursor = test_db.execute("SELECT stock, amount, status, spending FROM history WHERE id = ?", (user_id,))
    test = cursor.fetchone()
    assert test["stock"] == "RANDOM"
    assert test["amount"] == 1
    assert test["status"] == "Buy"
    assert test["spending"] == 150 * 1

@pytest.mark.parametrize("shares", [0, 0.5, -1, "number"])
def test_buy_stock_invalid_shares(loggedin_user, client, monkeypatch, shares): 
     # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying a stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": shares}, follow_redirects=False)
    assert response.headers["content-type"] == "text/html; charset=utf-8" # html response means apology message

def test_login_page(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8" # Check if the page is rendered as HTML

@pytest.mark.parametrize("path", ["/", "/buy", "/sell", "/history", "/quote"])
def test_login_required_redirect(client, path):
    # Simulate a request without a user_id in the session
    response = client.get(path, follow_redirects=False)  
    assert response.status_code == 303
    assert response.headers["location"] == "/login"  # Check if it redirects to the login page
    
def test_login_with_id_with_past_transaction(loggedin_user, client, monkeypatch):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
    # Simulate buying a stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)
    response = client.get("/", follow_redirects=False) 
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8" # HTML response means the portfolio page is rendered with past transactions
    
def test_login_with_id_no_past_transaction(loggedin_user, client): 
    response = client.get("/", follow_redirects=False)  
    assert response.status_code == 400 # 400 means an apology message due to no past transactions
    assert response.headers["content-type"] == "text/html; charset=utf-8" 

def test_quote(loggedin_user, client):
    # Test for unavailable quote 
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)
    assert response.status_code == 400 # 400 means an apology message due to no stock was found
    assert response.headers["content-type"] == "text/html; charset=utf-8" 

def test_sell(loggedin_user, client, monkeypatch, test_db):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("app.lookup", lambda symbol: {"name": "RANDOM", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "2"}, follow_redirects=False)

    # Access the index page so tables can be created
    response = client.get("/")

    # Simulate selling stock 
    response = client.post("/sell", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)

    # Check whether the history table was updated correctly
    user_id = client.get("/me").json()["user_id"]
    cursor = test_db.execute("SELECT stock, amount, spending FROM history WHERE id = ? AND status = ?", (user_id, "Sell"))
    test = cursor.fetchone()
    assert test["stock"] == "RANDOM"
    assert test["amount"] == 1
    assert test["spending"] == 150 * 1

    # Check whether user's cash was updated correctly
    cursor = test_db.execute("SELECT cash from users where id = ?", (user_id,))
    test = cursor.fetchone()
    assert test["cash"] == 10000 - 2 * 150 + 1 * 150

    # Edge case testing 
    # User sells stock they don't own
    response = client.post("/sell", data={"symbol": "AAPL", "shares": "1"}, follow_redirects=False)
    assert response.status_code == 400

# A unit test for the reconciliation logic in endpoint "/"
def test_table_reconciliation(test_db, monkeypatch):
    # Set up testing variables
    test_user_id = 0
    test_stock = "RANDOM"
    buy_amount = 4
    sell_amount = 3
    sell_value = 200
    monkeypatch.setattr("helpers.lookup", lambda symbol: {"name": test_stock, "price": sell_value, "symbol": symbol.upper()})

    # Set up a temporary db for testing
    test_db.row_factory = sqlite3.Row
    test_db.execute("CREATE TABLE history (id INTEGER NOT NULL, stock TEXT NOT NULL, amount NUMERIC NOT NULL, status TEXT NOT NULL, spending NUMERIC NOT NULL, time TEXT NOT NULL)")
    test_db.execute("CREATE TABLE ownedStock (id NOT NULL, stock TEXT NOT NULL, amount INTEGER NOT NULL, price TEXT NOT NULL, totalValue TEXT NOT NULL)")
    test_db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (test_user_id, test_stock, buy_amount, "Buy", buy_amount * sell_value, "None"))
    test_db.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (?, ?, ?, ?, ?, ?)", (test_user_id, test_stock, sell_amount, "Sell", sell_amount * sell_value, "None"))
    
    # The logic in index
    cursor1 = test_db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Buy' AND id = 0 GROUP BY stock")
    cursor2 = test_db.execute("SELECT stock, SUM(amount), SUM(spending) FROM history WHERE status='Sell' AND id = 0 GROUP BY stock")
    buyVal = cursor1.fetchall()
    sellVal = cursor2.fetchall()
    table_reconciliation(buyVal, sellVal, test_db, test_user_id)

    # Check
    test_cursor = test_db.execute("SELECT amount, price, totalValue, id, stock FROM ownedStock")
    tmp = test_cursor.fetchone()
    assert tmp["id"] == test_user_id
    assert tmp["stock"] == test_stock
    assert int(tmp["amount"]) == buy_amount - sell_amount
    assert int(tmp["price"]) == sell_value