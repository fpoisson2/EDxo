import pytest

from utils.openai_pricing import calculate_call_cost, get_model_pricing
from app.models import OpenAIModel
from src.app import db


@pytest.fixture
def pricing_model(app):
    with app.app_context():
        model = OpenAIModel(name="test-model", input_price=1.0, output_price=2.0)
        db.session.add(model)
        db.session.commit()
        yield model


def test_calculate_call_cost(pricing_model):
    cost = calculate_call_cost(1000, 500, pricing_model.name)
    assert cost == pytest.approx(0.002)


def test_get_model_pricing_existing(pricing_model):
    pricing = get_model_pricing(pricing_model.name)
    assert pricing == {"input": 1.0, "output": 2.0}


def test_get_model_pricing_missing(app):
    with app.app_context():
        with pytest.raises(ValueError):
            get_model_pricing("unknown-model")
