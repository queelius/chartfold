"""Lab-specific extractors — CEA, CBC, CMP, etc."""


def extract_cea_from_fhir(observations: list[dict]) -> list[dict]:
    """Extract CEA values from FHIR Observations."""
    from chartfold.core.cda import format_date

    cea_values = []
    for obs in observations:
        text = obs["text"].lower()
        if "carcinoembryonic" in text or text == "cea":
            cea_values.append({
                "date": obs["date"],
                "date_iso": obs["date_iso"],
                "date_fmt": format_date(obs["date"]),
                "value": obs["value"],
                "unit": obs["unit"],
                "ref_range": obs["ref_range"],
                "notes": obs["notes"],
                "source": "FHIR",
            })
    return sorted(cea_values, key=lambda x: x["date_iso"])


def extract_cea_from_labs(labs: list[dict]) -> list[dict]:
    """Extract CEA values from parsed lab results (CCDA or Epic)."""
    from chartfold.core.cda import format_date

    cea_values = []
    seen_dates = set()
    for lab in labs:
        test_name = lab.get("test", lab.get("panel", "")).lower()
        if "carcinoembryonic" in test_name or test_name == "cea":
            date_key = lab.get("date_iso", lab.get("date", ""))
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            value = lab.get("value", "")
            # For Epic format, value might be in components
            if not value and "components" in lab:
                for comp in lab["components"]:
                    if comp["name"].upper() == "CEA":
                        value = comp["value"]
                        break

            cea_values.append({
                "date_iso": lab.get("date_iso", ""),
                "date_fmt": format_date(lab.get("date_iso", lab.get("date", ""))),
                "value": value,
                "unit": lab.get("unit", ""),
                "ref_range": lab.get("ref_range", ""),
                "source": "CCDA",
            })
    return sorted(cea_values, key=lambda x: x.get("date_iso", ""))
