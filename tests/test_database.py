"""Tests para la base de datos SQLite y CRUD de items."""

from hunterbot.database import Database
from hunterbot.models import Item, ItemCategory


def test_database_crud(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(db_file)
    db.connect()

    item1 = Item(
        id="idealista:123",
        provider="idealista",
        category=ItemCategory.REAL_ESTATE,
        title="Casa de campo",
        price=150000.0,
        url="http://idealista.com/123",
    )

    is_new = db.upsert_item(item1)
    assert is_new is True

    fetched = db.get_item("idealista:123")
    assert fetched is not None
    assert fetched.title == "Casa de campo"
    assert fetched.price == 150000.0

    # Actualizar precio
    item1.price = 130000.0
    is_new2 = db.upsert_item(item1)
    assert is_new2 is False

    history = db.get_price_history("idealista:123")
    assert len(history) == 2
    assert history[0][0] == 150000.0
    assert history[1][0] == 130000.0

    drops = db.get_price_drops(min_drop_percent=5.0)
    assert len(drops) == 1
    assert drops[0].item_id == "idealista:123"

    db.close()
