import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

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


def row_month(row):
    try:
        return datetime.strptime(row.get("Waktu Pesanan Dibuat", ""), "%Y-%m-%d %H:%M").strftime("%Y-%m")
    except ValueError:
        return ""


def previous_month(month, offset=1):
    year, month_number = map(int, month.split("-"))
    absolute = year * 12 + month_number - 1 - offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def active_filters(args):
    names = {
        "status": "Status", "provinsi": "Provinsi", "kategori": "Kategori",
        "subkategori": "Subkategori", "metode_pembayaran": "Metode pembayaran",
        "bulan_dari": "Bulan dari", "bulan_sampai": "Bulan sampai", "q": "Pencarian",
    }
    result = {label: args.get(key, "").strip() for key, label in names.items() if args.get(key, "").strip()}
    for key, value in args.items():
        if key.startswith("col_exact_") and value.strip():
            result[f"Kolom {key.removeprefix('col_exact_')}"] = value.strip()
    return result


def filter_dataset(rows, args, category_parents, include_month=True):
    query = args.get("q", "").strip().casefold()
    exact_column_filters = {
        key.removeprefix("col_exact_"): value.strip().casefold()
        for key, value in args.items()
        if key.startswith("col_exact_") and value.strip()
    }
    filters = {
        "status": args.get("status", "").strip().casefold(),
        "provinsi": args.get("provinsi", "").strip().casefold(),
        "kategori": args.get("kategori", "").strip().casefold(),
        "subkategori": args.get("subkategori", "").strip().casefold(),
        "metode_pembayaran": args.get("metode_pembayaran", "").strip().casefold(),
        "bulan_dari": args.get("bulan_dari", "").strip() if include_month else "",
        "bulan_sampai": args.get("bulan_sampai", "").strip() if include_month else "",
    }
    filtered = []
    for row in rows:
        if any(
            value != (normalize_status(row.get(column, "")) if column == "Status Pesanan" else str(row.get(column, ""))).casefold()
            for column, value in exact_column_filters.items()
        ):
            continue
        if query and not any(query in str(value).casefold() for value in row.values()):
            continue
        if filters["status"] and filters["status"] not in normalize_status(row.get("Status Pesanan", "")).casefold():
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
        month = row_month(row)
        if filters["bulan_dari"] and month < filters["bulan_dari"]:
            continue
        if filters["bulan_sampai"] and month > filters["bulan_sampai"]:
            continue
        filtered.append(row)
    return filtered


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
    monthly = defaultdict(lambda: {"orders": 0, "revenue": 0, "gross_revenue": 0})
    revenue_total = gross_revenue_total = qty_total = returned_total = discount_total = 0
    cancelled = 0

    for row in rows:
        state = normalize_status(row.get("Status Pesanan", ""))
        prov = row.get("Provinsi", "") or "Tidak diketahui"
        row_categories = normalize_category(row.get("product_categories", ""))
        payment = row.get("Metode Pembayaran", "") or "Tidak diketahui"
        courier = row.get("Opsi Pengiriman", "") or "Tidak diketahui"
        paid = number(row.get("Total Pembayaran"))
        discount = number(row.get("Total Diskon"))
        # Total Pembayaran already reflects discounts. Exclude canceled orders from revenue.
        revenue = 0 if state.casefold() == "batal" else paid
        # The source only has returned quantities, not refunded currency. Never infer a cash refund from unit count.
        gross_revenue = revenue + (discount if state.casefold() != "batal" else 0)
        status[state] += 1
        province[prov]["orders"] += 1
        province[prov]["revenue"] += revenue
        province[prov]["items"] += number(row.get("total_qty"))
        province[prov]["returns"] += number(row.get("total_returned_qty"))
        province[prov]["discount"] += discount
        for category in row_categories:
            parent = category_parents.get(category, category)
            categories[parent] += 1
            category_details[parent][category] += 1
        payments[payment] += 1
        shipping[courier] += 1
        revenue_total += revenue
        gross_revenue_total += gross_revenue
        qty_total += number(row.get("total_qty"))
        returned_total += number(row.get("total_returned_qty"))
        discount_total += discount if state.casefold() != "batal" else 0
        cancelled += state.lower() == "batal"
        created = row.get("Waktu Pesanan Dibuat", "")
        try:
            month = datetime.strptime(created, "%Y-%m-%d %H:%M").strftime("%Y-%m")
            monthly[month]["orders"] += 1
            monthly[month]["revenue"] += revenue
            monthly[month]["gross_revenue"] += gross_revenue
        except ValueError:
            pass

    return {
        "orders": total,
        "revenue": clean_number(revenue_total),
        "gross_revenue": clean_number(gross_revenue_total),
        "refund_amount": None,
        "highest_order_value": clean_number(max((number(row.get("Total Pembayaran")) for row in rows if normalize_status(row.get("Status Pesanan", "")).casefold() != "batal"), default=0)),
        "average_order_value": clean_number(revenue_total / max(1, total - cancelled)),
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
            {"month": k, "orders": v["orders"], "revenue": clean_number(v["revenue"]), "gross_revenue": clean_number(v["gross_revenue"])}
            for k, v in sorted(monthly.items())
        ],
    }


def period_comparison(rows, category_parents, args):
    available = sorted({row_month(row) for row in rows if row_month(row)})
    if not available:
        return {"label": "Tidak ada periode", "current": 0, "previous": 0, "delta": 0, "change_pct": None, "mode": "previous"}
    first_month = args.get("bulan_perbandingan_1", "").strip()
    second_month = args.get("bulan_perbandingan_2", "").strip()
    manual_months = args.get("comparison_mode", "") == "months"
    if manual_months:
        if not first_month or not second_month:
            first_month, second_month = available[-1], previous_month(available[-1])
        if first_month not in available or second_month not in available:
            first_month, second_month = available[-1], previous_month(available[-1])
        current_month, prior_month = first_month, second_month
        current_start, current_end = current_month, current_month
        prior_start, prior_end = prior_month, prior_month
        label = f"{current_month} vs {prior_month}"
    else:
        current_start = args.get("bulan_dari", "").strip() or available[-1]
        current_end = args.get("bulan_sampai", "").strip() or (current_start if args.get("bulan_dari", "").strip() else available[-1])
        if current_start not in available and not args.get("bulan_dari", "").strip():
            current_start = available[-1]
        if current_end < current_start:
            current_end = current_start
        span = (int(current_end[:4]) * 12 + int(current_end[5:7])) - (int(current_start[:4]) * 12 + int(current_start[5:7])) + 1
        prior_start = previous_month(current_start, span)
        prior_end = previous_month(current_end)
        label = f"{current_start} s.d. {current_end} vs {prior_start} s.d. {prior_end}"
    comparison_args = args.copy()
    comparison_province = comparison_args.get("comparison_province", "").strip()
    # The comparison's province selector is independent from the dashboard-wide province filter.
    comparison_args = comparison_args.to_dict() if hasattr(comparison_args, "to_dict") else dict(comparison_args)
    comparison_args["provinsi"] = comparison_province
    base_rows = filter_dataset(rows, comparison_args, category_parents, include_month=False)
    current_rows = [row for row in base_rows if current_start <= row_month(row) <= current_end]
    previous_rows = [row for row in base_rows if prior_start <= row_month(row) <= prior_end]
    current = summarize(current_rows, category_parents)["revenue"]
    previous = summarize(previous_rows, category_parents)["revenue"]
    return {
        "label": label,
        "province": comparison_province or "Semua provinsi",
        "mode": "months" if manual_months else "previous",
        "current_month": current_start,
        "previous_month": prior_start,
        "current": current, "previous": previous, "delta": clean_number(current - previous),
        "change_pct": round((current - previous) * 100 / previous, 2) if previous else None,
    }


def build_anomalies(insights):
    actions = []
    monthly = insights["monthly"]
    if len(monthly) >= 2:
        latest, prior = monthly[-1], monthly[-2]
        change = latest["revenue"] - prior["revenue"]
        pct = round(change * 100 / prior["revenue"], 1) if prior["revenue"] else None
        if pct is not None and pct <= -20:
            actions.append({"level": "warning", "title": f"Omzet turun {abs(pct):.1f}% pada {latest['month']}", "detail": f"{latest['month']} dibanding {prior['month']}.", "action": "Periksa transaksi batal, retur, dan perubahan pesanan per provinsi."})
        elif pct is not None and pct >= 20:
            actions.append({"level": "positive", "title": f"Omzet naik {pct:.1f}% pada {latest['month']}", "detail": f"{latest['month']} dibanding {prior['month']}.", "action": "Lihat provinsi dan kategori yang paling berkontribusi pada kenaikan."})
    if insights["cancellation_rate"] >= 10:
        actions.append({"level": "warning", "title": f"Pembatalan {insights['cancellation_rate']:.1f}%", "detail": f"{insights['cancelled_orders']:,} dari {insights['orders']:,} pesanan pada hasil filter.", "action": "Tinjau alasan pembatalan terbanyak sebelum mengubah promosi atau stok."})
    if insights["top_provinces"]:
        top = insights["top_provinces"][0]
        actions.append({"level": "info", "title": f"Provinsi omzet tertinggi: {top['name']}", "detail": f"{top['revenue']:,} dari omzet terhitung; {top['orders']:,} pesanan.", "action": "Bandingkan kontribusi ini dengan provinsi lain sebelum menetapkan alokasi promosi."})
    if insights["top_categories"]:
        top = insights["top_categories"][0]
        actions.append({"level": "info", "title": f"Kategori paling sering dipesan: {top['name']}", "detail": f"{top['count']:,} kemunculan kategori pada baris transaksi.", "action": "Pastikan stok kategori ini tersedia; jumlah kategori bukan ukuran omzet."})
    return actions


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    try:
        headers, all_rows = read_dataset()
        category_parents = build_category_parents(all_rows)
        filtered = filter_dataset(all_rows, request.args, category_parents)

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

        insights = summarize(filtered, category_parents)
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
            "insights": insights,
            "comparison": period_comparison(all_rows, category_parents, request.args),
            "anomalies": build_anomalies(insights),
            "export_metadata": {
                "exported_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "date_range": f"{request.args.get('bulan_dari', '').strip() or 'awal data'} s.d. {request.args.get('bulan_sampai', '').strip() or 'akhir data'}",
                "filters": active_filters(request.args),
            },
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


@app.route("/api/export.csv")
def export_csv():
    try:
        headers, all_rows = read_dataset()
        category_parents = build_category_parents(all_rows)
        filtered = filter_dataset(all_rows, request.args, category_parents)
        insights = summarize(filtered, category_parents)
        exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        report_headers = ["Waktu Ekspor", "Rentang Bulan", "Filter Aktif", "Jumlah Pesanan", "Omzet Bruto Estimasi", "Omzet Bersih Terbayar", "Nominal Refund Tercatat", "Jumlah Barang Diretur"]
        report_values = [
            exported_at,
            f"{request.args.get('bulan_dari', '').strip() or 'awal data'} s.d. {request.args.get('bulan_sampai', '').strip() or 'akhir data'}",
            "; ".join(f"{key}: {value}" for key, value in active_filters(request.args).items()) or "Tidak ada",
            insights["orders"], insights["gross_revenue"], insights["revenue"], "Tidak tersedia pada sumber data", insights["returned_items"],
        ]
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output, delimiter=";", lineterminator="\n")
        writer.writerow(["RINGKASAN LAPORAN"])
        writer.writerow(report_headers)
        writer.writerow(report_values)
        writer.writerow([])
        writer.writerow(headers)
        for row in filtered:
            writer.writerow([row.get(header, "") for header in headers])
        response = Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = "attachment; filename=laporan_transaksi.csv"
        return response
    except OSError as error:
        return jsonify({"status": "error", "message": f"File data tidak dapat dibaca: {error}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
