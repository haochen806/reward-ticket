import json
import logging

from .models import AwardSeat

log = logging.getLogger(__name__)

CABIN_FILTER = {
    "J": "BUSINESS",
    "F": "FIRST",
}

SOLUTION_KEY = {
    "J": "REFUNDABLE_BUSINESS",
    "F": "REFUNDABLE_FIRST",
}


def parse_sveltekit(raw: str, max_miles: int, cabin: str) -> list[AwardSeat]:
    """Parse SvelteKit NDJSON __data.json response for award seats."""
    if not raw:
        return []

    results = []
    lines = raw.strip().split("\n")

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Flight data is in "chunk" type entries with departureStation
        if obj.get("type") == "chunk" and isinstance(obj.get("data"), list):
            data = obj["data"]
            if not data or not isinstance(data[0], dict):
                continue
            if "departureStation" not in data[0]:
                continue

            results.extend(_parse_chunk(data, max_miles, cabin))

    log.debug(f"Parsed {len(results)} business seats (cabin={cabin}, max_miles={max_miles})")
    return results


def _parse_chunk(data: list, max_miles: int, cabin: str) -> list[AwardSeat]:
    """Parse a single SvelteKit devalue chunk containing flight rows."""
    results = []
    root = data[0]
    departure_station = _resolve(data, root.get("departureStation"))
    arrival_station = _resolve(data, root.get("arrivalStation"))

    row_indices = _resolve(data, root.get("rows"))
    if not isinstance(row_indices, list):
        return results

    solution_key = SOLUTION_KEY.get(cabin, "REFUNDABLE_BUSINESS")

    for row_idx in row_indices:
        row = data[row_idx] if isinstance(row_idx, int) and row_idx < len(data) else None
        if not isinstance(row, dict):
            continue

        solutions = row.get("solutions")
        if not isinstance(solutions, dict):
            continue

        biz = solutions.get(solution_key)
        if biz is None:
            continue

        biz_data = data[biz] if isinstance(biz, int) and biz < len(data) else biz
        if not isinstance(biz_data, dict):
            continue

        miles = _resolve(data, biz_data.get("atmosPoints"))
        if not isinstance(miles, (int, float)) or miles <= 0 or miles > max_miles:
            continue

        tax = _resolve(data, biz_data.get("grandTotal"))
        if not isinstance(tax, (int, float)):
            tax = 0.0

        seats_remaining = _resolve(data, biz_data.get("seatsRemaining"))
        if not isinstance(seats_remaining, int):
            seats_remaining = 0

        # Get booking codes
        booking_codes = _resolve(data, biz_data.get("bookingCodes"))
        fare_class = ""
        if isinstance(booking_codes, list) and booking_codes:
            first_code = _resolve(data, booking_codes[0])
            fare_class = first_code if isinstance(first_code, str) else ""

        # Get flight segments
        seg_indices = _resolve(data, row.get("segments"))
        flight_parts = []
        first_origin = departure_station
        last_dest = arrival_station
        operating_airline = "AS"

        if isinstance(seg_indices, list):
            for seg_idx in seg_indices:
                seg = data[seg_idx] if isinstance(seg_idx, int) and seg_idx < len(data) else None
                if not isinstance(seg, dict):
                    continue
                carrier_ref = seg.get("publishingCarrier")
                carrier = data[carrier_ref] if isinstance(carrier_ref, int) and carrier_ref < len(data) else None
                if isinstance(carrier, dict):
                    code = _resolve(data, carrier.get("carrierCode"))
                    num = _resolve(data, carrier.get("flightNumber"))
                    if code and num is not None:
                        flight_parts.append(f"{code}{num}")
                        if not operating_airline or operating_airline == "AS":
                            operating_airline = code if isinstance(code, str) else "AS"
                seg_origin = _resolve(data, seg.get("departureStation"))
                seg_dest = _resolve(data, seg.get("arrivalStation"))
                if seg_origin and not first_origin:
                    first_origin = seg_origin
                if seg_dest:
                    last_dest = seg_dest

        flight_number = "+".join(flight_parts) if flight_parts else "?"

        # Get departure date from first segment
        flight_date = ""
        if isinstance(seg_indices, list) and seg_indices:
            first_seg = data[seg_indices[0]] if isinstance(seg_indices[0], int) else None
            if isinstance(first_seg, dict):
                depart_time = _resolve(data, first_seg.get("departureTime"))
                if isinstance(depart_time, str) and len(depart_time) >= 10:
                    flight_date = depart_time[:10]

        seat = AwardSeat(
            airline=operating_airline,
            flight_number=flight_number,
            origin=first_origin or departure_station or "",
            destination=last_dest or arrival_station or "",
            date=flight_date,
            cabin=cabin,
            miles=int(miles),
            tax=float(tax),
            fare_class=fare_class,
            seat_type="SAVER" if miles < 100000 else "MAIN",
        )
        results.append(seat)

    return results


def _resolve(data: list, ref) -> any:
    """Resolve a SvelteKit devalue reference. If ref is an int, look up data[ref]."""
    if isinstance(ref, int) and 0 <= ref < len(data):
        val = data[ref]
        # Don't recursively resolve dicts/lists — only scalar indirections
        if isinstance(val, (str, int, float, bool)) or val is None:
            return val
        return val
    return ref
