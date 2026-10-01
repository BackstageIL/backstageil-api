from decimal import Decimal

from app.schemas.hall_fields import HallTechnicalFields
from app.schemas.venue_import import HallImport
from app.schemas.venues import HallDocument


def test_import_and_api_share_the_technical_fields() -> None:
    technical = set(HallTechnicalFields.model_fields)

    assert technical <= set(HallImport.model_fields)
    assert technical <= set(HallDocument.model_fields)


def test_meters_are_exact_decimals_in_python_and_numbers_in_json() -> None:
    fields = HallTechnicalFields(stage_width_m=Decimal("24.50"), first_pipe_distance_m=Decimal(0))

    assert fields.model_dump()["stage_width_m"] == Decimal("24.50")
    as_json = fields.model_dump(mode="json")
    assert as_json["stage_width_m"] == 24.5
    assert as_json["first_pipe_distance_m"] == 0.0
    assert as_json["stage_depth_m"] is None
