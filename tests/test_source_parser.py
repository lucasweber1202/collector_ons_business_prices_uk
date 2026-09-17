from datetime import UTC, datetime

import pytest

from scripts.extract import parse_csv


def test_parser_fails_closed_when_ons_structure_is_missing() -> None:
    with pytest.raises(ValueError, match="structure drifted"):
        parse_csv(
            b"wrong,columns\n",
            "ons_ppi",
            {"G67M"},
            "snapshot",
            "https://ons.gov.uk",
            datetime.now(UTC),
        )
