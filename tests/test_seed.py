import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import PriceList, PriceListItem
from app.seed import DEFAULT_ITEMS, seed_price_list


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


def test_seed_creates_list_with_all_items(session):
    price_list, count = seed_price_list(session)
    assert count == len(DEFAULT_ITEMS)
    items = session.scalars(select(PriceListItem)).all()
    assert len(items) == count
    drilling = [i for i in items if i.category == "drilling"]
    assert any(i.code == "DRL.MIC.200" for i in drilling)


def test_seed_refuses_to_overwrite_without_replace(session):
    seed_price_list(session)
    with pytest.raises(ValueError):
        seed_price_list(session)


def test_seed_replace_recreates(session):
    first, _ = seed_price_list(session)
    second, _ = seed_price_list(session, replace=True)
    assert second.name == first.name
    all_lists = session.scalars(select(PriceList)).all()
    assert len(all_lists) == 1
    assert len(session.scalars(select(PriceListItem)).all()) == len(DEFAULT_ITEMS)


def test_seed_currency_stored(session):
    price_list, _ = seed_price_list(session, currency="EGP")
    assert price_list.currency == "EGP"
