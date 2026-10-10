# Laporan Dokumentasi & Audit Teknis AksaraSight Web UI Mockup

Dokumen ini adalah berkas tunggal referensi teknis dan catatan perkembangan (*changelog & behavioral pass*) untuk antarmuka AksaraSight. Seluruh pembaruan didokumentasikan secara terpusat di dalam berkas ini.

---

## BAGIAN I: Pembaruan Terkini — Redesain Panel Settings (Compact & Non-Scrollable Tabbed Layout)

### Latar Belakang & Masalah
Sebelumnya, halaman Pengaturan (*Settings*) menggabungkan seluruh formulir panjang secara vertikal dalam satu kartu tunggal (Engine & Hardware, Processing DPI, Image Limits, dan Advanced Accordion). Hal ini membuat pengguna harus melakukan *scroll* panjang ke bawah untuk menemukan pengaturan tertentu atau untuk mencapai tombol konfirmasi penyimpanan.

### Solusi & Implementasi Baru
Halaman Pengaturan kini direfaktor menjadi tata letak **Kategori Berbasis Tab (*Tabbed Segmented Categories*)** yang ringkas, modern, dan dirancang pas di layar (*viewport-anchored*) tanpa memerlukan *vertical scroll* panjang:

1. **Struktur Kategori Tab (3 Tab Tematik):**
   - **Tab 1: Engine & Hardware (`memory`):**
     - Pilihan radio backend (`llama-cpp`, `ollama`, `vllm`) dengan aksen teal.
     - Pilihan sumber runtime (`Managed` vs `Custom`).
     - Kartu perangkat keras terdeteksi (GPU RTX 3050, 6.0 GB VRAM, tombol *Refresh*, target backend tombol pill, status instalasi biner netral `<runtime dir>/llama-cpp/b10930-cuda/llama-server`, tombol *Reinstall / Update*).
     - Sakelar toggle otomatisasi *Start server automatically*.
   - **Tab 2: Processing & Quality (`tune`):**
     - Slider resolusi rendering DPI dengan *snapping steps* (72, 100, 150, 200 DPI), aksen track teal, label angka klik langsung, serta kartu panduan perkiraan durasi per halaman (~1.5s s/d ~9.2s).
     - Grid batas komputasi numerik (*Max image size px*, *Max output tokens per page*, dan *Max pages per document*).
   - **Tab 3: Advanced & Network (`terminal`):**
     - Masukan teks *Endpoint URL*.
     - Sakelar toggle *Allow remote endpoints*.
     - Pengaturan numerik *Timeout* (detik) dan *Max retries*.
     - Pengaturan *Model repository*.
2. **Keunggulan Pengalaman Pengguna (UX):**
   - **Tanpa Scroll Panjang:** Setiap tab memiliki tinggi ringkas (berkisar antara ~300px hingga ~380px) sehingga pas berada di dalam viewport desktop standar (1080p, 900p, maupun 768p).
   - **Persistensi State Formulir Terpadu:** Seluruh nilai pengaturan (`formData`) tetap tersimpan di dalam state yang sama saat berpindah antar tab.
   - **Deteksi Perubahan (*Dirty State*):** Tombol *Save settings* di footer tetap aktif secara pintar hanya jika ada parameter yang diubah di salah satu tab, dan menyimpan seluruh konfigurasi secara serentak disertai toast notifikasi hijau.

---

## BAGIAN II: Laporan Final Behavioral Pass (Mockup Frozen Reference)

### 1. Ringkasan Satu Baris per Goal
- **Goal 1 (Queued State for First-Time Extraction):** Dokumen berstatus `Waiting` yang telah terdaftar di dalam antrean kini menampilkan pill status *"Queued #N"* disertai tombol aksi *ghost* *"Remove from queue"* pada panel kanan (menggantikan tombol *"Add to queue"*); mengeklik aksi tersebut mengembalikan dokumen ke status *"Not extracted"* dan mengurutkan ulang (*renumber*) posisi antrean dokumen lainnya secara otomatis.
- **Goal 2 (Non-Destructive Re-Extraction):** Ekstraksi ulang pada dokumen `Done` atau `Truncated` saat job lain sedang berjalan kini memasukkannya ke dalam antrean tanpa merusak atau mengubah status dan teks yang ada: status tetap `Done`/`Truncated`, aksi Copy dan Export tetap aktif, muncul badge sekunder *"Re-extraction queued #N"* (dengan tombol *ghost* *"Remove from queue"*) pada panel kanan dan baris antrean, serta baru beralih ke `Processing` saat gilirannya tiba.
- **Goal 3 (Clean Document Preview):** Menghapus seluruh interaksi klik sorotan (*click-to-highlight*) dan bingkai teal paragraf pada panel pratinjau dokumen; pratinjau lembar surat perjanjian kini bersih sebagai halaman naskah statis murni tanpa ilusi koordinat bounding box.
- **Goal 4 (State Consistency):** Menegakkan konsistensi bahwa maksimal hanya satu dokumen yang dapat berstatus `Processing` di seluruh aplikasi dan harus merupakan pemilik job aktif (`runningJobDocId`); status default maupun parameter `?state=processing` secara ketat memenuhi aturan ini tanpa ada job tumpang tindih.

---

### 2. Matriks Status Dokumen & Ketersediaan Aksi (Final Frozen Matrix)

Kolom:
1. **Extract** (Ekstraksi dokumen utama)
2. **Add to queue** (Menambahkan dokumen belum diproses ke antrean saat ada job aktif)
3. **Re-extract** (Ekstraksi ulang dokumen yang sudah selesai)
4. **Cancel** (Membatalkan proses yang sedang berjalan)
5. **Copy** (Menyalin teks hasil ekstraksi)
6. **Clear** (Menghapus teks editor dengan konfirmasi)
7. **Export** (Mengekspor teks ke format .docx / .md / .txt)

| Status Dokumen / Kondisi Mesin | Extract | Add to queue | Re-extract | Cancel | Copy text | Clear text | Export (.docx/.md/.txt) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Done (Standar)** | *Tidak tampil* | *Tidak tampil* | **Enabled** (Ghost) | *Tidak tampil* | **Enabled** | **Enabled** | **Enabled** (Primary Teal) |
| **Done + re-extraction queued** | *Tidak tampil* | *Tidak tampil* | *Digantikan badge "Re-extraction queued #N" + Remove* | *Tidak tampil* | **Enabled** | **Enabled** | **Enabled** (Primary Teal) |
| **Processing (Pemilik Job)** | *Tidak tampil* | *Tidak tampil* | *Tidak tampil* | **Enabled** (Merah) | **Disabled** | **Disabled** | **Disabled** |
| **Waiting (queued)** | *Tidak tampil* | *Digantikan badge "Queued #N" + Remove* | *Tidak tampil* | *Tidak tampil* | **Disabled** | **Disabled** | **Disabled** |
| **Not extracted (Ada job jalan)** | *Tidak tampil* | **Enabled** (Teal) | *Tidak tampil* | *Tidak tampil* | **Disabled** | **Disabled** | **Disabled** |
| **Not extracted (Tidak ada job)** | **Enabled** (Primary Teal) | *Tidak tampil* | *Tidak tampil* | *Tidak tampil* | **Disabled** | **Disabled** | **Disabled** |
| **Truncated** | *Tidak tampil* | *Tidak tampil* | **Enabled** (Ghost) | *Tidak tampil* | **Enabled** | **Enabled** | **Enabled** (Primary Teal) |
| **Failed** | *Tidak tampil* | *Tidak tampil* | *Tidak tampil* | *Tidak tampil* | **Disabled** | **Disabled** | **Disabled** |
| **Engine Offline** | **Disabled** (Abu-abu) | *Tidak tampil* | *Tidak tampil* | *Tidak tampil* | **Disabled** | **Disabled** | **Disabled** |

---

### 3. Inventaris Lengkap Seluruh Elemen Interaktif (Clickable) di Luar Brief Ini

1. **Top Navigation Bar:** Teks jenama **"AksaraSight"**, tab navigasi **"Workspace"**, tab navigasi **"Settings"**, tombol **"Output folder"**.
2. **File Queue Panel (Kolom Kiri):** Dropzone / tombol browse file picker, baris dokumen antrean, tombol teks *"Remove"* pada dokumen `Waiting`, tombol teks *"Remove from queue"* pada dokumen `Re-extraction queued`, tombol *"Clear queue"* (dengan konfirmasi inline *Yes / No*), tombol *"Open settings"* pada kartu *Truncated*, tombol *"Retry"* dan *"Remove from queue"* pada kartu *Failed*.
3. **Document Source Preview Panel (Kolom Tengah):** Toolbar pager *"Previous"* & *"Next"*, toolbar zoom *"-"* dan *"+"*, tombol zoom *"Fit"*. *(Seluruh klik bounding box teal telah dihilangkan sesuai Goal 3).*
4. **Extracted Text Panel (Kolom Kanan):** Tab format tampilan (`Text`, `Table`, `Formula`), tombol *"Copy text"*, tombol *"Clear text"* (dengan konfirmasi inline *Yes / No*), dropdown panah tombol Export (`expand_more`) untuk memilih format (.docx, .md, .txt), tombol *"Start engine"* & *"Open settings"* pada kartu saat engine offline.
5. **Settings Page:** Tab kategori (`Engine & Hardware`, `Processing & Quality`, `Advanced & Network`), pilihan radio backend inferensi, tab sumber runtime, tombol refresh hardware, tab target backend, sakelar *"Start server automatically"*, slider dan label angka DPI, input limit numerik (image size, token, pages), masukan endpoint & toggle remote, tombol footer *"Cancel"* & *"Save settings"*.
6. **Output Directory Modal:** Item daftar riwayat berkas, tombol *"Download"* berkas fisik via browser, tombol ikon sampah dengan konfirmasi inline (*Delete? Yes / No*), tombol silang *"X"* dan tombol footer *"Close"*.

---

### 4. Analisis Keselarasan Struktur Kode (Apakah Ada yang Kontradiktif?)
**Tidak ada kontradiksi struktural.** Seluruh model yang diminta selaras dengan arsitektur React state pada aplikasi:
1. **Pemisahan State Ekstraksi Ulang:** Penambahan properti `isReExtractionQueued: boolean` dan `queuePosition: number` pada `DocumentItem` memisahkan status riil dokumen (`Done` / `Truncated`) dari status antrean pekerja (*worker queue*).
2. **Kemandirian Penghapusan Antrean:** Fungsi `handleRemoveFromQueue` secara cerdas membedakan apakah dokumen yang dibatalkan antreannya adalah dokumen baru (kembali ke `Not extracted`) atau dokumen selesai yang sedang antre ekstraksi ulang.
3. **Pembersihan Pratinjau Dokumen:** Menghapus tag dan event handler bounding box pada `DocumentPreviewPanel.tsx` menyederhanakan kode rendering lembar dokumen menjadi murni presentasional.

---

## BAGIAN III: Jawaban & Klarifikasi Teknis Mendalam (Diskusi Pass Sebelumnya)

1. **Dokumen Waiting / Queued:** Redundansi tombol *"Add to queue"* pada dokumen yang sudah `Waiting` telah diatasi dengan tombol status `"Queued #N"` dan aksi pembatalan antrean `"Remove from queue"`.
2. **Re-extract saat Dokumen Lain Berjalan:** Mekanisme non-destruktif (`isReExtractionQueued`) mempertahankan status dokumen, isi teks lama, serta tombol Copy dan Export tetap aktif.
3. **Bounding Box Pratinjau:** Telah dikonfirmasi murni dekoratif tanpa dukungan koordinat pada data model; kini telah dieliminasi sepenuhnya pada Pass Final.
4. **Klarifikasi Kontradiksi Laporan:** Telah diverifikasi bahwa arsitektur timer adalah tunggal (`extractionTimerRef`) dengan flag boolean global; inkonsistensi teks sebelumnya disebabkan oleh pemilihan diksi penjelasan yang kurang presisi.
5. **Kritik Batasan Hardware vs Desain:** Model GLM-OCR berukuran 0.9B memiliki kebutuhan komputasi ringan, sehingga perilaku pemrosesan satu per satu diposisikan murni sebagai *design choice* dari antrean pekerja (*worker queue*), tanpa menyertakan narasi batasan perangkat keras pada antarmuka pengguna.

---

## BAGIAN IV: Catatan Audit Awal Kode Sumber (Baseline Audit)

1. **Pemisahan Counter:** Menyatukan label progres ganda menjadi satu hitungan terpadu (*"3 of 12 pages processed"*).
2. **Retensi Teks Modular:** Menyimpan dan menampilkan teks per halaman dengan pembatas halaman (*page divider*), bukan kartu loading layar penuh yang me-*unmount* teks.
3. **Netralitas Sistem Operasi:** Standardisasi path biner runtime menjadi format netral `<runtime dir>/llama-cpp/b10930-cuda/llama-server` dan path direktori keluaran `/var/data/aksarasight/exports/`.
