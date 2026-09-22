from app.connectors.espocrm import build_schema_from_field_defs


def test_narrows_to_extractable_fields_only():
    field_defs = {
        "firstName": {"type": "varchar"},
        "lastName": {"type": "varchar"},
        "id": {"type": "varchar"},  # not extractable -- must not appear
        "createdAt": {"type": "datetime"},  # not extractable
    }
    schema = build_schema_from_field_defs("Contact", field_defs)
    assert set(schema["properties"]) == {"firstName", "lastName"}
    assert schema["additionalProperties"] is False


def test_missing_field_defs_are_skipped_not_crashed_on():
    # EXTRACTABLE_FIELDS lists "source" for Lead, but a field_defs dict
    # that doesn't have it (e.g. custom EspoCRM install) shouldn't blow up.
    schema = build_schema_from_field_defs("Lead", {"firstName": {"type": "varchar"}})
    assert set(schema["properties"]) == {"firstName"}


def test_enum_fields_get_their_options_as_a_json_schema_enum():
    field_defs = {"source": {"type": "enum", "options": ["Website", "Referral", "Email"]}}
    schema = build_schema_from_field_defs("Lead", field_defs)
    assert schema["properties"]["source"]["type"] == "string"
    assert schema["properties"]["source"]["enum"] == ["Website", "Referral", "Email"]


def test_field_descriptions_dont_leak_across_fields_of_the_same_type():
    # Regression test: properties[field] used to alias the very same
    # shared ESPOCRM_TYPE_MAP dict object across every varchar field, so
    # attaching a description to one field leaked it onto all of them.
    field_defs = {
        "firstName": {"type": "varchar"},
        "lastName": {"type": "varchar"},
    }
    schema = build_schema_from_field_defs("Contact", field_defs)
    first = schema["properties"]["firstName"]
    last = schema["properties"]["lastName"]
    assert first is not last
    assert first["description"] != last["description"]
