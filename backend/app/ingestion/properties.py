"""Only factual structured fields explicitly present in authorized source JSON-LD."""
from __future__ import annotations
from sqlalchemy import select
from app.db.models import Property
from app.db.session import session_factory


def _float(value):
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _int(value):
    value = _float(value)
    return int(value) if value is not None and value >= 0 and value.is_integer() else None


def _text(value):
    return str(value).strip()[:200] if isinstance(value, (str, int, float)) else None


def save_structured(source: str, url: str, records: list[dict]):
    with session_factory()() as db:
        for item in records[:15]:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            if not name:
                continue
            location = item.get("address") or {}
            if isinstance(location, str):
                location = {"streetAddress": location}
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}
            existing = db.scalars(select(Property).where(Property.source_id == source, Property.url == url)).first()
            property_row = existing or Property(source_id=source, url=url, title=name)
            property_row.title = name
            property_row.city = _text(location.get("addressLocality"))
            property_row.country = _text(location.get("addressCountry"))
            property_row.property_type = _text(item.get("@type"))
            property_row.price = _float(offers.get("price"))
            property_row.currency = _text(offers.get("priceCurrency"))
            property_row.area = _float((item.get("floorSize") or {}).get("value") if isinstance(item.get("floorSize"), dict) else None)
            property_row.bedrooms = _int(item.get("numberOfBedrooms"))
            property_row.bathrooms = _int(item.get("numberOfBathroomsTotal"))
            property_row.facts = {"jsonld_type": item.get("@type", ""), "source": "source_jsonld"}
            if not existing:
                db.add(property_row)
        db.commit()
