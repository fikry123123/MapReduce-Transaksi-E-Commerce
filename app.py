import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
DATA_FILE = Path(__file__).with_name("all_months_clean.csv")
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def read_dataset():
    """Read the source once per request; only the selected page is returned."""
    with DATA_FILE.open(mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows


def number(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0


def clean_number(value):
    value = number(value)
    return int(value) if value.is_integer() else value


def normalize_status(value):
    """Merge date-specific buyer return-window messages into one status."""
    status = (value or "").strip()
    if status.lower().startswith("pesanan diterima, namun pembeli masih dapat mengajukan pengembalian"):
        return "Pesanan diterima, masih dalam masa pengajuan pengembalian"
    return status or "Tidak diketahui"


def normalize_category(value):
    """Use the first category as the concise filter/insight category."""
    category = (value or "").strip()
    return category.split(",", 1)[0].strip() if category else "Tidak diketahui"


def summarize(rows):
    total = len(rows)
    status = Counter()
    province = defaultdict(lambda: {"orders": 0, "revenue": 0})
    categories, payments, shipping = Counter(), Counter(), Counter()
    monthly = defaultdict(lambda: {"orders": 0, "revenue": 0})
    revenue_total = qty_total = returned_total = discount_total = 0
    cancelled = 0

    for row in rows:
        state = normalize_status(row.get("Status Pesanan", ""))
        prov = row.get("Provinsi", "") or "Tidak diketahui"
        category = normalize_category(row.get("product_categories", ""))
        payment = row.get("Metode Pembayaran", "") or "Tidak diketahui"
        courier = row.get("Opsi Pengiriman", "") or "Tidak diketahui"
        revenue = number(row.get("Total Pembayaran"))
        status[state] += 1
        province[prov]["orders"] += 1
        province[prov]["revenue"] += revenue
        categories[category] += 1
        payments[payment] += 1
        shipping[courier] += 1
        revenue_total += revenue
        qty_total += number(row.get("total_qty"))
        returned_total += number(row.get("total_returned_qty"))
        discount_total += number(row.get("Total Diskon"))
        cancelled += state.lower() == "batal"
        created = row.get("Waktu Pesanan Dibuat", "")
        try:
            month = datetime.strptime(created, "%Y-%m-%d %H:%M").strftime("%Y-%m")
            monthly[month]["orders"] += 1
            monthly[month]["revenue"] += revenue
        except ValueError:
            pass

    return {
        "orders": total,
        "revenue": clean_number(revenue_total),
        "average_order_value": clean_number(revenue_total / total if total else 0),
        "items": clean_number(qty_total),
        "returned_items": clean_number(returned_total),
        "discount": clean_number(discount_total),
        "cancelled_orders": cancelled,
        "cancellation_rate": round(cancelled * 100 / total, 2) if total else 0,
        "statuses": [{"name": k, "count": v} for k, v in status.most_common()],
        "top_provinces": [
            {"name": k, "orders": v["orders"], "revenue": clean_number(v["revenue"])}
            for k, v in sorted(province.items(), key=lambda item: item[1]["revenue"], reverse=True)[:10]
        ],
        "top_categories": [{"name": k, "count": v} for k, v in categories.most_common(10)],
        "payment_methods": [{"name": k, "count": v} for k, v in payments.most_common()],
        "shipping_methods": [{"name": k, "count": v} for k, v in shipping.most_common(10)],
        "monthly": [
            {"month": k, "orders": v["orders"], "revenue": clean_number(v["revenue"])}
            for k, v in sorted(monthly.items())
        ],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    try:
        headers, all_rows = read_dataset()
        query = request.args.get("q", "").strip().casefold()
        filters = {
            "status": request.args.get("status", "").strip().casefold(),
            "provinsi": request.args.get("provinsi", "").strip().casefold(),
            "kategori": request.args.get("kategori", "").strip().casefold(),
            "metode_pembayaran": request.args.get("metode_pembayaran", "").strip().casefold(),
        }
        filtered = []
        for row in all_rows:
            if query and not any(query in str(value).casefold() for value in row.values()):
                continue
            if filters["status"] and filters["status"] not in row.get("Status Pesanan", "").casefold():
                continue
            if filters["provinsi"] and filters["provinsi"] not in row.get("Provinsi", "").casefold():
                continue
            category = normalize_category(row.get("product_categories", ""))
            if filters["kategori"] and filters["kategori"] != category.casefold():
                continue
            if filters["metode_pembayaran"] and filters["metode_pembayaran"] not in row.get("Metode Pembayaran", "").casefold():
                continue
            filtered.append(row)

        try:
            limit = min(MAX_LIMIT, max(1, int(request.args.get("limit", DEFAULT_LIMIT))))
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            return jsonify({"status": "error", "message": "limit dan offset harus berupa angka."}), 400

        return jsonify({
            "status": "success",
            "headers": headers,
            "total_rows": len(all_rows),
            "filtered_rows": len(filtered),
            "limit": limit,
            "offset": offset,
            "rows": filtered[offset:offset + limit],
            "insights": summarize(filtered),
            "options": {
            "statuses": sorted({normalize_status(r.get("Status Pesanan", "")) for r in all_rows}),
                "provinces": sorted({r.get("Provinsi", "") for r in all_rows if r.get("Provinsi", "")}),
                "categories": sorted({normalize_category(r.get("product_categories", "")) for r in all_rows}),
                "payment_methods": sorted({r.get("Metode Pembayaran", "") for r in all_rows if r.get("Metode Pembayaran", "")}),
            },
        })
    except OSError as error:
        return jsonify({"status": "error", "message": f"File data tidak dapat dibaca: {error}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
