# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_db
from api.mocker import MockDatabase

@pytest.fixture
def mock_db():
    return MockDatabase()

@pytest.fixture
def client(mock_db):
    # Правильная подмена асинхронной зависимости
    async def override_get_db():
        yield mock_db
        
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as c:
        yield c
        
    app.dependency_overrides.clear()