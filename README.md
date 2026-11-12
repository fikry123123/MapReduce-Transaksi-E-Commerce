# Dashboard Insight Transaksi E-Commerce

Aplikasi dashboard berbasis Flask untuk menjelajahi data transaksi e-commerce. Dashboard menampilkan KPI, tren omzet dan pesanan, komposisi status, sebaran omzet provinsi, kategori produk, simulasi pengurangan diskon, perbandingan periode, ringkasan anomali, serta tabel transaksi dengan filter dan ekspor CSV.

## Fitur

- Filter transaksi berdasarkan status, provinsi, kategori dan subkategori, metode pembayaran, rentang bulan, pencarian, serta nilai kolom tabel.
- Pengambilan data tabel secara bertahap dengan pilihan jumlah baris per halaman dan pengurutan kolom.
- KPI omzet bruto estimasi dan omzet bersih terbayar. Pesanan berstatus **Batal** tidak dihitung sebagai omzet.
- Grafik tren omzet dan pesanan bulanan, komposisi pesanan, kategori, serta grafik atau heatmap omzet provinsi.
- Simulasi dampak pengurangan diskon dengan pilihan provinsi dan asumsi penurunan jumlah pesanan.
- Perbandingan omzet bersih untuk rentang periode dengan periode sebelumnya, atau membandingkan dua bulan pilihan. Perbandingan dapat mencakup semua provinsi atau satu provinsi.
- Ringkasan perubahan omzet, pembatalan, provinsi dengan omzet tertinggi, dan kategori yang sering dipesan beserta saran tindak lanjut.
- Ekspor CSV transaksi sesuai filter, dilengkapi waktu ekspor, rentang bulan, filter aktif, dan ringkasan KPI.

## Persyaratan

- Python 3.9 atau lebih baru.
- Flask.
- Koneksi internet saat membuka dashboard untuk memuat Tailwind CSS, Chart.js, dan Leaflet dari CDN.

## Menjalankan aplikasi

Buka terminal pada folder proyek, lalu jalankan:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install Flask
python app.py
```

Bash/macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install Flask
python app.py
```

Buka alamat berikut di browser:

```text
http://127.0.0.1:5000
```

Aplikasi berjalan pada port `5000` dalam mode debug saat dijalankan melalui `python app.py`.

## Sumber data

File data default adalah `all_months_clean.csv` di folder yang sama dengan `app.py`. File harus memakai encoding UTF-8 (BOM diperbolehkan) dan pemisah titik koma (`;`). Kolom yang digunakan dashboard antara lain:

- `order_id`
- `total_qty`, `total_returned_qty`, `total_weight_gr`
- `Total Diskon`, `Total Pembayaran`
- `product_categories`, `num_product_categories`
- `Status Pesanan`, `Alasan Pembatalan`
- `Provinsi`, `Kota/Kabupaten`
- `Metode Pembayaran`, `Opsi Pengiriman`
- `Waktu Pesanan Dibuat` dengan format `YYYY-MM-DD HH:MM`

Ganti isi file tersebut untuk memakai dataset lain, dengan mempertahankan nama kolom dan format yang digunakan aplikasi.

## Definisi omzet dan keterbatasan data

- **Omzet bersih terbayar** adalah jumlah `Total Pembayaran` untuk pesanan selain yang berstatus `Batal`.
- **Omzet bruto estimasi** adalah omzet bersih terbayar ditambah `Total Diskon` pada pesanan selain yang berstatus `Batal`.
- `Total Pembayaran` diasumsikan sudah memperhitungkan diskon. Karena itu omzet bruto berlabel estimasi dan bergantung pada definisi kolom di dataset.
- Dataset mencatat kuantitas retur, tetapi tidak mencatat nilai uang refund atau nilai barang per unit. Dashboard menampilkan jumlah barang yang diretur, tetapi tidak mengurangi omzet dengan estimasi refund yang tidak didukung data.
- Simulasi pengurangan diskon menghasilkan estimasi dampak omzet, bukan laba. Data biaya pokok barang (COGS) tidak tersedia.
- Identitas pembeli yang konsisten juga belum tersedia, sehingga analisis kohort atau retensi pelanggan belum dapat dihitung secara akurat.

## Endpoint

- `GET /` — dashboard.
- `GET /api/data` — data tabel bertahap, KPI, insight, opsi filter, dan perbandingan.
- `GET /api/export.csv` — unduh transaksi hasil filter beserta metadata dan ringkasan KPI.

Parameter filter `/api/data` dan `/api/export.csv` mengikuti kontrol dashboard seperti `status`, `provinsi`, `kategori`, `subkategori`, `metode_pembayaran`, `bulan_dari`, `bulan_sampai`, `q`, dan `col_exact_<nama kolom>`.

## Susunan berkas

```text
├── app.py
├── all_months_clean.csv
├── README.md
├── templates/
│   └── index.html
└── static/
    └── indonesia_provinces.geojson
```
