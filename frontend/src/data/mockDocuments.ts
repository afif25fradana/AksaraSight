import { DocumentItem, EngineSettings } from '../types';

export const INITIAL_DOCUMENTS: DocumentItem[] = [
  {
    id: 'doc-1',
    name: 'invoice-scan-03.pdf',
    pages: 3,
    size: '1.4 MB',
    status: 'Done',
    processedPages: 3,
    currentPage: 1,
    docType: 'invoice',
    pagesData: {
      1: {
        pageNumber: 1,
        text: `FAKTUR PENJUALAN\nCOMMERCIAL TAX INVOICE\nNo: INV-2023-003\nDate: 14/10/2023\n\nDiterbitkan Oleh (Vendor):\nPT. NUSANTARA SISTEM GRAFIKA\nJl. Raden Saleh No. 42A, Cikini, Jakarta Pusat 10330 - ID\nNPWP: 01.423.890.4-021.000\n\nTagihan Kepada (Billed To):\nARSIP NASIONAL REPUBLIKA\nDivisi Preservasi Manuskrip, Gedung Arsip B, Lantai 3\nPO Ref: PO-PRE-8842\n\nITEM & DESCRIPTION:\n1. Konservasi Kertas Bebas Asam (pH 8.5) - Grade A75 Archival Lining Paper | 10 Rim @ IDR 850.000 = IDR 8.500.000\n2. Methyl Cellulose Adhesive (High Viscosity) - Kemasan 1000g food-grade safe | 4 Jar @ IDR 320.000 = IDR 1.280.000\n3. Micro-Chamber Archival Storage Folio - Ukuran Folio Standard 38x26 cm | 50 Unit @ IDR 45.000 = IDR 2.250.000\n\nSubtotal: IDR 12.030.000\nPPN (11%): IDR 1.323.300\nTOTAL: IDR 13.353.300\n\nTransfer: Bank Mandiri 122-00-9831920-1\nStatus: LUNAS (PAID 15/10/2023)\nVerification Hash: 8bfa92e10a`,
        table: `| No | Item & Deskripsi | Kuantitas | Tarif (IDR) | Total (IDR) |\n|---|---|:---:|---:|---:|\n| 1 | Konservasi Kertas Bebas Asam (pH 8.5) | 10 Rim | 850.000 | 8.500.000 |\n| 2 | Methyl Cellulose Adhesive (High Viscosity) | 4 Jar | 320.000 | 1.280.000 |\n| 3 | Micro-Chamber Archival Storage Folio | 50 Unit | 45.000 | 2.250.000 |\n| **Subtotal** | | | | **12.030.000** |\n| **PPN (11%)** | | | | **1.323.300** |\n| **TOTAL** | | | | **IDR 13.353.300** |`,
        formula: `\\text{Subtotal} = 12.030.000 \\text{ IDR}\n\\text{PPN} = 1.323.300 \\text{ IDR}\n\\text{Total} = 13.353.300 \\text{ IDR}`
      },
      2: {
        pageNumber: 2,
        text: `LAMPIRAN SERTIFIKASI MATERIAL KERTAS ARSIP\nNo. Sertifikat: CERT-2023-A75-09\n\nSpesifikasi Uji Laboratorium:\n- Kandungan Asam: pH 8.5 (Bebas asam teruji ISO 9706)\n- Cadangan Alkali: Kalsium Karbonat 2.5%\n- Ketahanan Robek: 450 mN (arah mesin)\n- Penuaan Dipercepat: Lolos uji 100 tahun simulasi penuaan\n\nPenguji Material: Balai Pengujian Bahan Pulp dan Kertas Bandung.`,
      },
      3: {
        pageNumber: 3,
        text: `BERITA ACARA PENERIMAAN BARANG\nRef: BAP-INV-2023-003\n\nSeluruh barang telah diterima dalam kondisi segel utuh dan sesuai dengan spesifikasi faktur. Pembayaran telah diverifikasi lunas per tanggal 15 Oktober 2023.\n\nPetugas Penerima: Ahmad Fauzi\nNIP: 19820411 200801 1 004\nUnit Logistik Preservasi Digital.`,
      }
    },
    extractedText: `FAKTUR PENJUALAN\nCOMMERCIAL TAX INVOICE\nNo: INV-2023-003\nDate: 14/10/2023\n\nDiterbitkan Oleh (Vendor):\nPT. NUSANTARA SISTEM GRAFIKA\nJl. Raden Saleh No. 42A, Cikini, Jakarta Pusat 10330 - ID\nNPWP: 01.423.890.4-021.000\n\nTagihan Kepada (Billed To):\nARSIP NASIONAL REPUBLIKA\nDivisi Preservasi Manuskrip, Gedung Arsip B, Lantai 3\nPO Ref: PO-PRE-8842\n\nITEM & DESCRIPTION:\n1. Konservasi Kertas Bebas Asam (pH 8.5) - Grade A75 Archival Lining Paper | 10 Rim @ IDR 850.000 = IDR 8.500.000\n2. Methyl Cellulose Adhesive (High Viscosity) - Kemasan 1000g food-grade safe | 4 Jar @ IDR 320.000 = IDR 1.280.000\n3. Micro-Chamber Archival Storage Folio - Ukuran Folio Standard 38x26 cm | 50 Unit @ IDR 45.000 = IDR 2.250.000\n\nSubtotal: IDR 12.030.000\nPPN (11%): IDR 1.323.300\nTOTAL: IDR 13.353.300\n\nTransfer: Bank Mandiri 122-00-9831920-1\nStatus: LUNAS (PAID 15/10/2023)\nVerification Hash: 8bfa92e10a`,
    extractedTable: `| No | Item & Deskripsi | Kuantitas | Tarif (IDR) | Total (IDR) |\n|---|---|:---:|---:|---:|\n| 1 | Konservasi Kertas Bebas Asam (pH 8.5) | 10 Rim | 850.000 | 8.500.000 |\n| 2 | Methyl Cellulose Adhesive (High Viscosity) | 4 Jar | 320.000 | 1.280.000 |\n| 3 | Micro-Chamber Archival Storage Folio | 50 Unit | 45.000 | 2.250.000 |\n| **Subtotal** | | | | **12.030.000** |\n| **PPN (11%)** | | | | **1.323.300** |\n| **TOTAL** | | | | **IDR 13.353.300** |`,
    extractedFormula: `\\text{Subtotal} = \\sum_{i=1}^{3} (\\text{Qty}_i \\times \\text{Rate}_i) = 12.030.000 \\text{ IDR}\n\\text{PPN} = 0.11 \\times \\text{Subtotal} = 1.323.300 \\text{ IDR}\n\\text{Total} = \\text{Subtotal} + \\text{PPN} = 13.353.300 \\text{ IDR}\n\\text{Checksum}_{\\text{SHA256}} = \\mathtt{8bfa92e10a56d901}`
  },
  {
    id: 'doc-2',
    name: 'surat-perjanjian-v2.pdf',
    pages: 12,
    size: '3.8 MB',
    status: 'Processing',
    processedPages: 3,
    currentPage: 1, // viewing page 1 while 3 of 12 pages are processed
    docType: 'legal-agreement',
    pagesData: {
      1: {
        pageNumber: 1,
        text: `SURAT PERJANJIAN KERJASAMA\nNomor: 042/SPK/AKS/XI/2023\n\nPada hari ini, Senin tanggal dua puluh November tahun dua ribu dua puluh tiga, bertempat di Bandung, para pihak sepakat mengadakan perjanjian pemindaian dan preservasi naskah arsip digital dengan ketentuan bahwa seluruh data diproses secara lokal tanpa transmisi pihak ketiga.\n\nPIHAK PERTAMA: Dr. Hendra Gunawan (Balai Konservasi Naskah Kuno)\nPIHAK KEDUA: AksaraSight Lab (Preservasi Digital)\n\nPara pihak sepakat mengadakan perjanjian pemindaian dan preservasi naskah arsip digital dengan ketentuan bahwa seluruh data diproses secara lokal tanpa transmisi pihak ketiga.\n\nSegala bentuk hasil transkripsi teks optik akan diverifikasi secara langsung menggunakan parameter pencocokan karakter minimum 98%.`,
        table: `| Pihak | Perwakilan Instansi | Penanggung Jawab | Status Otorisasi |\n|---|---|---|---|\n| PIHAK PERTAMA | Balai Konservasi Naskah Kuno | Dr. Hendra Gunawan | NIP. 19740512 199903 1 002 |\n| PIHAK KEDUA | AksaraSight Lab (Preservasi Digital) | AksaraSight Core | ID: AKS-CORE-SYS-42 |`,
        formula: `\\text{Tingkat Akurasi OCR} \\ge 98.0\\%\n\\text{Integritas Arsip} = \\mathcal{H}(\\text{Page}_{01} \\parallel \\mathtt{SEC\\_LOCAL})`
      },
      2: {
        pageNumber: 2,
        text: `PASAL 1: RUANG LINGKUP PEKERJAAN\n1. Pelaksanaan digitasi berkas manuskrip beraksara Latin dan Jawi sebanyak 1.250 lembar folio.\n2. Ekstraksi teks berbasis model inferensi lokal tanpa transmisi awan pihak ketiga demi kerahasiaan data sejarah negara.\n3. Validasi hash kriptografis SHA-256 pada setiap lembar citra beresolusi tinggi sebelum dan sesudah rekonstruksi teks.`,
      },
      3: {
        pageNumber: 3,
        text: `PASAL 2: SPESIFIKASI DAN PARAMETER TEKNIS\n1. Resolusi pindaian minimum 100 DPI dengan toleransi kontras adaptive binarization.\n2. Segmentasi wilayah layout: pemisahan otomatis blok paragraf, tabel register, dan paraf legalitas.\n3. Format keluaran arsip: OpenDocument (.docx), Markdown (.md), dan teks murni (.txt).`,
      }
      // Pages 4 through 12 are not processed yet!
    },
    extractedText: `SURAT PERJANJIAN KERJASAMA\nNomor: 042/SPK/AKS/XI/2023\n\nPada hari ini, Senin tanggal dua puluh November tahun dua ribu dua puluh tiga, bertempat di Bandung, para pihak sepakat mengadakan perjanjian pemindaian dan preservasi naskah arsip digital dengan ketentuan bahwa seluruh data diproses secara lokal tanpa transmisi pihak ketiga.\n\nPIHAK PERTAMA: Dr. Hendra Gunawan (Balai Konservasi Naskah Kuno)\nPIHAK KEDUA: AksaraSight Lab (Preservasi Digital)`,
    extractedTable: `| Pihak | Perwakilan Instansi | Penanggung Jawab | Status Otorisasi |\n|---|---|---|---|\n| PIHAK PERTAMA | Balai Konservasi Naskah Kuno | Dr. Hendra Gunawan | NIP. 19740512 199903 1 002 |\n| PIHAK KEDUA | AksaraSight Lab (Preservasi Digital) | AksaraSight Core | ID: AKS-CORE-SYS-42 |`,
    extractedFormula: `\\text{Tingkat Akurasi OCR} = \\left( 1 - \\frac{\\text{Levenshtein}(T_{\\text{raw}}, T_{\\text{ref}})}{\\max(|T_{\\text{raw}}|, |T_{\\text{ref}}|)} \\right) \\times 100\\% \\ge 98.0\\%\n\\text{Integritas Arsip} = \\mathcal{H}(\\text{Page}_{03} \\parallel \\mathtt{SEC\\_LOCAL})`
  },
  {
    id: 'doc-3',
    name: 'arsip-kolonial-1892.png',
    pages: 8,
    size: '6.2 MB',
    status: 'Truncated',
    statusNote: 'Page 2 output hit token limit (4096 tokens). Text on that page may be incomplete.',
    processedPages: 8, // Goal 4: all pages are processed; specific pages carry incomplete flag
    currentPage: 1,
    docType: 'historical-paper',
    pagesData: {
      1: {
        pageNumber: 1,
        text: `UITTREKSEL UIT HET REGISTER DER BESLUITEN\nVAN DEN GOUVERNEUR-GENERAAL VAN NEDERLANDSCH-INDIË\n\nBuitenzorg, den 14den October 1892. No. 18.\nGelezen het verzoekschrift van den Resident ter Assistentie van Bataviasche Archieven aangaande de overbrenging van historische documenten der voormalige Oost-Indische Compagnie...`,
      },
      2: {
        pageNumber: 2,
        isTruncated: true, // Page 2 output hit token limit
        text: `FOLIO REGISTER DER TRANSACTIES EN OVEREENKOMSTEN (1892)\n\n[Lijst van geverifieerde contracten en recognitie-gelden]\n1. Overeenkomst met het Regentschap Bandoeng betreffende de houtvesterij ter bergflanken van Tangkoeban Prahoe.\n2. Recognitie der waterrechten van de rivier Tji-Taroem ten behoeve der thee-ondernemingen.\n3. Overname van pakhuisgebouwen te Tandjoeng Priok ter opslag van specerijen en koffiebonen.\n4. Uitgifte van erfpachtpercelen aan particuliere planters in het district Tjiandjoer...\n\n[Peringatan Sistem OCR: Batas token keluaran tercapai pada halaman ini (4096 tokens). Teks pada halaman ini terpotong.]`,
        table: `| Folio | Register Nummer | Datum van Besluit | Status Preservasi |\n|---|---|---|---|\n| Folio 14 | REG-BAT-1892-018 | 14 October 1892 | Fragile - Asam Tinggi |\n| Folio 15 | REG-BAT-1892-019 | 15 October 1892 | Terpotong (Truncated - Hit 4096 tokens) |`,
        formula: `T_{\\text{tokens}} = 4096 / 4096 \\quad (\\text{Hit Token Ceiling})`
      },
      3: {
        pageNumber: 3,
        text: `BIJBLAD TOT HET STAATSBLAD VAN NEDERLANDSCH-INDIË (1892)\n\nVoorschriften nopens de bewaring van registers en stukken berustende onder de hoofden van gewestelijk bestuur. De secretaris-generaal gelast de stipte naleving der archiefvoorschriften.`,
      },
      4: {
        pageNumber: 4,
        text: `INVENTARIS DER REGEERINGSARCHIEVEN - DEEL IV\nStaat van overgedragen cartulaire banden afkomstig van de algemeene secretarie. Totaal tien banden in lederen band met goudopdruk.`,
      },
      5: {
        pageNumber: 5,
        text: `BESLUIT VAN DEN RAAD VAN INDIË\nGehoord het advies der commissie van toezicht op het archiefwezen. Goedgekeurd en bekrachtigd te Batavia.`,
      },
      6: {
        pageNumber: 6,
        text: `STATISTISCH OVERZICHT DER ARCHIEFSTUKKEN\nAantal behandelde verzoekschriften over het dienstjaar 1892 bedroeg vierhonderd twee en twintig registers.`,
      },
      7: {
        pageNumber: 7,
        text: `RAPPORT DER CONSERVERINGSCOMMISSIE\nMaatregelen tot herstel van vochtschade aan pergamenten oorkonden. Behandeling met thymol en gelatineuze lijm.`,
      },
      8: {
        pageNumber: 8,
        text: `SLOTBEPALING EN ONDERTEEKENING\nAfschrift dezer zal worden toegezonden aan de hoofden van departementen van algemeen bestuur. Geregistreerd onder nummer 1892-XII-42.`,
      }
    },
    extractedText: `UITTREKSEL UIT HET REGISTER DER BESLUITEN\nVAN DEN GOUVERNEUR-GENERAAL VAN NEDERLANDSCH-INDIË\n\nBuitenzorg, den 14den October 1892. No. 18.\nGelezen het verzoekschrift van den Resident ter Assistentie van Bataviasche Archieven...\n\n[Peringatan: Batas token keluaran tercapai pada Halaman 2 (4096 tokens). Teks pada halaman tersebut terpotong.]`,
    extractedTable: `| Folio | Register Nummer | Datum van Besluit | Status Preservasi |\n|---|---|---|---|\n| Folio 14 | REG-BAT-1892-018 | 14 October 1892 | Fragile - Asam Tinggi |\n| Folio 15 | REG-BAT-1892-019 | 15 October 1892 | Terpotong (Truncated) |`,
    extractedFormula: `T_{\\text{tokens}} = 4096 / 4096 \\quad (\\text{Hit Token Ceiling})`
  },
  {
    id: 'doc-4',
    name: 'laporan-keuangan-2023.pdf',
    pages: 14,
    size: '4.5 MB',
    status: 'Waiting',
    statusNote: 'Queued #1',
    queuePosition: 1,
    processedPages: 0,
    currentPage: 1,
    docType: 'financial',
    extractedText: '', // Unprocessed file has no extracted text
    extractedTable: '',
    extractedFormula: ''
  },
  {
    id: 'doc-5',
    name: 'manuscript-scan-blur.tiff',
    pages: 1,
    size: '18.9 MB',
    status: 'Failed',
    statusNote: 'Image was too large to process (exceeded pixel safety limit) and was not sent to the engine.',
    processedPages: 0,
    currentPage: 1,
    docType: 'historical-paper',
    extractedText: '',
    extractedTable: '',
    extractedFormula: ''
  }
];

export const INITIAL_SETTINGS: EngineSettings = {
  status: 'running',
  backend: 'llama-cpp',
  runtimeSource: 'managed',
  customLlamaServerPath: 'C:\\Users\\Fradana\\AppData\\Local\\AksaraSight\\runtimes\\b10930-cuda\\llama-server.exe',
  targetBackend: 'cuda',
  autoStart: false,
  renderDpi: 100, // documented step: 72, 100, 150, 200
  maxImageSize: 2048,
  maxTokensPerPage: 4096,
  maxPagesPerDoc: '',
  endpointUrl: 'http://127.0.0.1:8080/v1',
  allowRemote: false,
  timeout: 60,
  retries: 2,
  modelRepo: 'ggml-org/GLM-OCR-GGUF'
};
