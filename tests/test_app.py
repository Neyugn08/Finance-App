import os
from backend.config import *
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient 
import pytest
from starlette.templating import Jinja2Templates
from backend.helpers import get_db_name, table_reconciliation, setup_db
from backend.app import app 

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / ".." / "frontend" / "templates"))
app.dependency_overrides[get_db_name] = lambda: "test"
if instance_connection_name: 
    conn_info = f"host={DB_HOST} user={DB_USER} password={DB_PASSWORD}"
else: 
    conn_info = f"host={DB_HOST} port=5432 user={DB_USER} password={DB_PASSWORD}"
db_name = "test"

@pytest.fixture
def neutral_cursor():
    neutral_info = f"{conn_info} dbname=postgres"
    with psycopg.connect(neutral_info, autocommit=True) as neutral_conn:
        with neutral_conn.cursor() as neutral_cursor:
            neutral_cursor.execute(f"CREATE DATABASE {db_name}")
            setup_db(conn_info, db_name)
            yield neutral_cursor
            neutral_cursor.execute(f"DROP DATABASE {db_name}")

# Create a TestClient fixture to prevent cookie/session issues between tests
@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client

# Create a cursor for the test db fixture
@pytest.fixture
def test_cursor(neutral_cursor): 
    with psycopg.connect(f"{conn_info} dbname={db_name}", row_factory=dict_row) as conn: 
        with conn.cursor() as cursor:
            yield cursor

@pytest.fixture
def loggedin_user(client, test_cursor):
    # Register a test user
    response = client.post("/register", follow_redirects=False, data={"username": "testuser", "password": "testpass", "confirmation": "testpass"})
    # Log in the test user
    response = client.post("/login", follow_redirects=False, data={"username": "testuser", "password": "testpass"})
    yield response

def test_register(client, test_cursor):
    # Create a temporary database for testing
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

def test_buy_stock(loggedin_user, client, monkeypatch, test_cursor):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("backend.app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying a stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)
    assert response.status_code == 303  
    assert response.headers["location"] == "/"  # Redirecting to home page after buying means successful purchase

    # Check whether the history table was updated correctly
    user_id = client.get("/me").json()["user_id"]
    test_cursor.execute("SELECT stock, amount, status, spending FROM history WHERE id = %s", (user_id,))
    test = test_cursor.fetchone()
    assert test["stock"] == "RANDOM"
    assert test["amount"] == 1
    assert test["status"] == "Buy"
    assert test["spending"] == 150 * 1

@pytest.mark.parametrize("shares", [0, 0.5, -1, "number"])
def test_buy_stock_invalid_shares(loggedin_user, client, monkeypatch, shares, neutral_cursor): 
     # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("backend.app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying a stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": shares}, follow_redirects=False)
    assert response.headers["content-type"] == "text/html; charset=utf-8" # html response means apology message

def test_login_page(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8" # Check if the page is rendered as HTML

@pytest.mark.parametrize("path", ["/", "/buy", "/sell", "/history", "/quote"])
def test_login_required_redirect(client, path, neutral_cursor):
    # Simulate a request without a user_id in the session
    response = client.get(path, follow_redirects=False)  
    assert response.status_code == 303
    assert response.headers["location"] == "/login"  # Check if it redirects to the login page
    
def test_login_with_id_with_past_transaction(loggedin_user, client, monkeypatch):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("backend.app.lookup", lambda symbol: {"name": "Apple Inc.", "price": 150.00, "symbol": symbol.upper()})
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

def test_sell(loggedin_user, client, monkeypatch, test_cursor):
    # Mock the lookup function to return a fixed stock price for testing
    monkeypatch.setattr("backend.app.lookup", lambda symbol: {"name": "RANDOM", "price": 150.00, "symbol": symbol.upper()})
    
    # Simulate buying stock
    response = client.post("/buy", data={"symbol": "RANDOM", "shares": "2"}, follow_redirects=False)

    # Access the index page so tables can be created
    response = client.get("/")

    # Simulate selling stock 
    response = client.post("/sell", data={"symbol": "RANDOM", "shares": "1"}, follow_redirects=False)

    # Check whether the history table was updated correctly
    user_id = client.get("/me").json()["user_id"]
    test_cursor.execute("SELECT stock, amount, spending FROM history WHERE id = %s AND status = %s", (user_id, "Sell"))
    test = test_cursor.fetchone()
    assert test["stock"] == "RANDOM"
    assert test["amount"] == 1
    assert test["spending"] == 150 * 1

    # Check whether user's cash was updated correctly
    test_cursor.execute("SELECT cash from users where id = %s", (user_id,))
    test = test_cursor.fetchone()
    assert test["cash"] == 10000 - 2 * 150 + 1 * 150

    # Edge case testing 
    # User sells stock they don't own
    response = client.post("/sell", data={"symbol": "AAPL", "shares": "1"}, follow_redirects=False)
    assert response.status_code == 400

# A unit test for the reconciliation logic in endpoint "/"
def test_table_reconciliation(test_cursor, monkeypatch):
    # Set up testing variables
    test_user_id = 0
    test_stock = "RANDOM"
    buy_amount = 4
    sell_amount = 3
    sell_value = 200
    monkeypatch.setattr("backend.helpers.lookup", lambda symbol: {"name": test_stock, "price": sell_value, "symbol": symbol.upper()})

    # Set up a temporary db for testing
    test_cursor.execute("INSERT INTO users (id, username, hash) VALUES (%s, %s, %s)", (test_user_id, "testuser", "fake_hash"))
    test_cursor.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (%s, %s, %s, %s, %s, %s)", (test_user_id, test_stock, buy_amount, "Buy", buy_amount * sell_value, "None"))
    test_cursor.execute("INSERT INTO history (id, stock, amount, status, spending, time) VALUES (%s, %s, %s, %s, %s, %s)", (test_user_id, test_stock, sell_amount, "Sell", sell_amount * sell_value, "None"))
    
    # The logic in index
    test_cursor.execute("SELECT stock, SUM(amount) AS total_amount, SUM(spending) FROM history WHERE status='Buy' AND id = 0 GROUP BY stock")
    buyVal = test_cursor.fetchall()
    test_cursor.execute("SELECT stock, SUM(amount) AS total_amount, SUM(spending) FROM history WHERE status='Sell' AND id = 0 GROUP BY stock")
    sellVal = test_cursor.fetchall()
    table_reconciliation(buyVal, sellVal, test_cursor, test_user_id)

    # Check
    test_cursor.execute("SELECT amount, price, total_value, id, stock FROM ownedStock")
    tmp = test_cursor.fetchone()
    assert tmp["id"] == test_user_id
    assert tmp["stock"] == test_stock
    assert int(tmp["amount"]) == buy_amount - sell_amount
    assert int(tmp["price"]) == sell_value
