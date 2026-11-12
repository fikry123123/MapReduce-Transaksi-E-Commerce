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


def is_number(value):
    try:
        float(str(value).replace(",", "."))
        return True
    except (TypeError, ValueError):
        return False


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
    """Split source category lists while preserving their detailed names."""
    return [part.strip() for part in (value or "").split(",") if part.strip()] or ["Tidak diketahui"]


def build_category_parents(rows):
    """Map source category labels to useful business-level parent groups."""
    groups = {
        "Aksesoris": {
            "Aksesoris ID Card", "Aksesoris Mandi", "Aksesoris Motor", "Aksesoris Pintu",
        },
        "Alat Makan": {
            "Botol / Gelas / Mug", "Lunch Box / Rantang", "Mangkok", "Mangkok Sambal / Saus",
            "Nampan / Tray", "Peralatan Makan", "Piring", "Saringan / Strainer", "Talenan",
            "Teko / Jug", "Tempat Nasi",
        },
        "Peralatan Dapur": {
            "Baskom / Mangkok Besar", "Cobek / Ulekan", "Pengolah Bumbu / Sayur",
            "Pisau / Alat Potong", "Spatula",
        },
        "Peralatan Mandi & Kebersihan": {
            "Gayung", "Peralatan Kamar Mandi", "Sapu / Pembersih Lantai", "Sikat / Pembersih",
        },
        "Perlengkapan Rumah": {
            "Bangku / Kursi Kecil", "Celengan", "Gantungan Baju / Hanger", "Keranjang",
            "Plastik / Wadah Plastik", "Pot Tanaman / Bunga", "Rak / Rak Serbaguna",
            "Tempat Sampah", "Toples / Sealware",
        },
        "Perkakas & Perbaikan": {"Perkakas", "Seal / Baut / Roof"},
        "Perlengkapan Kantor": {"Stempel / Alat Kantor"},
    }
    parent_by_category = {category: parent for parent, categories in groups.items() for category in categories}
    names = {name for row in rows for name in normalize_category(row.get("product_categories", ""))}
    # Categories without a defined parent stay available as their own standalone group.
    return {name: parent_by_category.get(name, name) for name in names}


def category_hierarchy(rows, parents):
    groups = defaultdict(set)
    for row in rows:
        for category in normalize_category(row.get("product_categories", "")):
            groups[parents.get(category, category)].add(category)
    return [
        {"name": parent, "subcategories": [{"name": child} for child in sorted(children)]}
        for parent, children in sorted(groups.items())
    ]


def summarize(rows, category_parents):
    total = len(rows)
    status = Counter()
    province = defaultdict(lambda: {"orders": 0, "revenue": 0, "items": 0, "returns": 0, "discount": 0})
    categories, category_details, payments, shipping = Counter(), defaultdict(Counter), Counter(), Counter()
    monthly = defaultdict(lambda: {"orders": 0, "revenue": 0})
    revenue_total = qty_total = returned_total = discount_total = 0
    cancelled = 0

    for row in rows:
        state = normalize_status(row.get("Status Pesanan", ""))
        prov = row.get("Provinsi", "") or "Tidak diketahui"
        row_categories = normalize_category(row.get("product_categories", ""))
        payment = row.get("Metode Pembayaran", "") or "Tidak diketahui"
        courier = row.get("Opsi Pengiriman", "") or "Tidak diketahui"
        revenue = number(row.get("Total Pembayaran"))
        status[state] += 1
        province[prov]["orders"] += 1
        province[prov]["revenue"] += revenue
        province[prov]["items"] += number(row.get("total_qty"))
        province[prov]["returns"] += number(row.get("total_returned_qty"))
        province[prov]["discount"] += number(row.get("Total Diskon"))
        for category in row_categories:
            parent = category_parents.get(category, category)
            categories[parent] += 1
            category_details[parent][category] += 1
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
        "highest_order_value": clean_number(max((number(row.get("Total Pembayaran")) for row in rows), default=0)),
        "average_order_value": clean_number(revenue_total / total if total else 0),
        "items": clean_number(qty_total),
        "returned_items": clean_number(returned_total),
        "discount": clean_number(discount_total),
        "cancelled_orders": cancelled,
        "cancellation_rate": round(cancelled * 100 / total, 2) if total else 0,
        "statuses": [{"name": k, "count": v} for k, v in status.most_common()],
        "top_provinces": [
            {
                "name": k,
                "orders": v["orders"],
                "revenue": clean_number(v["revenue"]),
                "items": clean_number(v["items"]),
                "returns": clean_number(v["returns"]),
                "discount": clean_number(v["discount"]),
            }
            for k, v in sorted(province.items(), key=lambda item: item[1]["revenue"], reverse=True)
        ],
        "top_categories": [{"name": k, "count": v} for k, v in categories.most_common(10)],
        "category_groups": [
            {"name": parent, "count": total, "subcategories": [{"name": name, "count": count} for name, count in details.most_common()]}
            for parent, total in categories.most_common()
            for details in [category_details[parent]]
        ],
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
        category_parents = build_category_parents(all_rows)
        query = request.args.get("q", "").strip().casefold()
        exact_column_filters = {
            key.removeprefix("col_exact_"): value.strip().casefold()
            for key, value in request.args.items()
            if key.startswith("col_exact_") and value.strip()
        }
        filters = {
            "status": request.args.get("status", "").strip().casefold(),
            "provinsi": request.args.get("provinsi", "").strip().casefold(),
            "kategori": request.args.get("kategori", "").strip().casefold(),
            "subkategori": request.args.get("subkategori", "").strip().casefold(),
            "metode_pembayaran": request.args.get("metode_pembayaran", "").strip().casefold(),
            "bulan_dari": request.args.get("bulan_dari", "").strip(),
            "bulan_sampai": request.args.get("bulan_sampai", "").strip(),
        }
        filtered = []
        for row in all_rows:
            if any(
                value != (normalize_status(row.get(column, "")) if column == "Status Pesanan" else str(row.get(column, ""))).casefold()
                for column, value in exact_column_filters.items()
            ):
                continue
            if query and not any(query in str(value).casefold() for value in row.values()):
                continue
            if filters["status"] and filters["status"] not in row.get("Status Pesanan", "").casefold():
                continue
            if filters["provinsi"] and filters["provinsi"] not in row.get("Provinsi", "").casefold():
                continue
            row_categories = normalize_category(row.get("product_categories", ""))
            if filters["kategori"] and not any(filters["kategori"] == category_parents.get(c, c).casefold() for c in row_categories):
                continue
            if filters["subkategori"] and not any(filters["subkategori"] == c.casefold() for c in row_categories):
                continue
            if filters["metode_pembayaran"] and filters["metode_pembayaran"] not in row.get("Metode Pembayaran", "").casefold():
                continue
            row_month = row.get("Waktu Pesanan Dibuat", "")[:7]
            if filters["bulan_dari"] and row_month < filters["bulan_dari"]:
                continue
            if filters["bulan_sampai"] and row_month > filters["bulan_sampai"]:
                continue
            filtered.append(row)

        sort_column = request.args.get("sort_column", "")
        sort_direction = request.args.get("sort_direction", "asc")
        numeric_columns = [
            header for header in headers
            if any(str(row.get(header, "")).strip() for row in all_rows)
            and all(is_number(str(row.get(header, "")).strip()) for row in all_rows if str(row.get(header, "")).strip())
        ]
        column_filter_options = {}
        for header in headers:
            if header in numeric_columns:
                continue
            values = {
                normalize_status(row.get(header, "")) if header == "Status Pesanan" else str(row.get(header, ""))
                for row in all_rows if str(row.get(header, "")).strip()
            }
            if len(values) <= 60:
                column_filter_options[header] = sorted(values)
        if sort_column in headers and sort_direction in {"asc", "desc"}:
            nonempty = [row for row in filtered if str(row.get(sort_column, "")).strip()]
            empty = [row for row in filtered if not str(row.get(sort_column, "")).strip()]
            nonempty.sort(
                key=lambda row: number(row.get(sort_column, "")) if sort_column in numeric_columns else str(row.get(sort_column, "")).casefold(),
                reverse=sort_direction == "desc",
            )
            filtered = nonempty + empty

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
            "sort_column": sort_column,
            "sort_direction": sort_direction,
            "rows": filtered[offset:offset + limit],
            "insights": summarize(filtered, category_parents),
            "options": {
            "statuses": sorted({normalize_status(r.get("Status Pesanan", "")) for r in all_rows}),
                "provinces": sorted({r.get("Provinsi", "") for r in all_rows if r.get("Provinsi", "")}),
                "categories": sorted(set(category_parents.values())),
                "category_groups": category_hierarchy(all_rows, category_parents),
                "payment_methods": sorted({r.get("Metode Pembayaran", "") for r in all_rows if r.get("Metode Pembayaran", "")}),
                "months": sorted({r.get("Waktu Pesanan Dibuat", "")[:7] for r in all_rows if r.get("Waktu Pesanan Dibuat", "")}),
                "numeric_columns": numeric_columns,
                "column_filter_options": column_filter_options,
            },
        })
    except OSError as error:
        return jsonify({"status": "error", "message": f"File data tidak dapat dibaca: {error}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
