# Data sources

Public documents used as the stand-in corpus. The PDFs are git-ignored; this file records where each one came from so the set can be rebuilt. All files were retrieved on 2026-09-30.

## Clause documents (`data/clauses/`)

Wording is `new` when the flight-delay exclusions mention 海上颱風警報 and 已取得罷工權 (the reference clauses in force from 2026-04-01) and `old` otherwise. This was checked against the extracted text of every file.

| File | Insurer | Contents | Wording | Pages | SHA-256 |
|---|---|---|---|---|---|
| `clauses/cathay/travel-bundle.new-wording.pdf` | 國泰產物 Cathay Century | Bundle: 享樂遊／享暢行海外旅行綜合保險, 新旅行平安保障保險 and riders | new | 27 | `ac6ef56bf2b29bcfbe349ef0ff547d6c2b617a947d0dea7ae9b77b9df9ff1e9d` |
| `clauses/cathay/travel-bundle.old-wording.pdf` | 國泰產物 Cathay Century | Same bundle, earlier file (海外旅遊險相關條款) | old | 59 | `2afd085cb94d365bf36217522a0bc20d1ea943c2b70a06ec2d3f97abadd916f0` |
| `clauses/fubon/overseas-inconvenience.new-wording.pdf` | 富邦產物 Fubon | 富邦產物個人海外旅行不便保險 | new | 12 | `c305b4b1995a23565b48271decacba01fa43934f655dafe2d4bb6be479a25fe5` |
| `clauses/fubon/travel-bundle.old-wording.pdf` | 富邦產物 Fubon | Bundle opening with 富邦產物旅行平安保險; 個人海外旅行不便保險 starts on page 24 (reported). Third-party broker mirror, not a Fubon domain | old | 46 | `74c504dfea37b8ed4510ab53543b73be03b166947273e93520ebe9086d85ca4b` |
| `clauses/shinkong/inconvenience-online.new-wording.pdf` | 新光產物 Shinkong | 新光產物個人海外旅行不便綜合保險(A), online-sales edition (115.06) | new | 4 | `6c0da623e182eeee6bac0f0c9ffb9a3b83561fc97e257e9c77cd880e1f197019` |
| `clauses/shinkong/travel-comprehensive-overseas.new-wording.pdf` | 新光產物 Shinkong | 新光產物個人海外旅行不便綜合保險(A), overseas-travel edition (115.06) | new | 10 | `abea4c5e7f83b002e7a30b996b0204b8bee63011e24a3bec620059a67581cea3` |
| `clauses/shinkong/overseas-inconvenience.old-wording.pdf` | 新光產物 Shinkong | 新光產物個人海外旅行不便綜合保險 (11208 edition) | old | 8 | `4b38ca243f5f4316fdf07d1d1619aa30758134405ba2cc5510a24419ca428b29` |
| `clauses/mingtai/overseas-travel-bundle.new-wording.pdf` | 明台產物 MSIG Mingtai | Bundle: 新國外／新國內旅行綜合保險, 新旅行平安保險 and riders. Page 1 is an image cover | new | 82 | `fa50d67e8e4787ea8fedb41d3bb9f30eb93b87a95d69678dbdd931464cb43603` |
| `clauses/huanan/travel-comprehensive.new-wording.pdf` | 華南產物 South China | 華南產物旅行綜合保險 | new | 26 | `2341c82ad5dc039d434e41ecf37179a07157d0649b7b2b57a072eb0f2f4cba36` |
| `clauses/huanan/travel-comprehensive-general.old-wording.pdf` | 華南產物 South China | 華南產物旅行綜合保險 (一般用) | old | 18 | `724dc90c0757b390d6a4544cb96630d0fe0db0e24276a40e21d293fa0f8c354c` |
| `clauses/hotai/world-travel-comprehensive.new-wording.pdf` | 和泰產物 Hotai | 和泰產物環遊世界旅行綜合保險 | new | 33 | `28806cf27414a385fb2f7ea9f456c88aba5f72cb3d7957e9496cf657562958b7` |
| `clauses/tfmi/travel-comprehensive.new-wording.pdf` | 臺灣產物 Taiwan Fire & Marine | 臺灣產物旅遊綜合保險 (from page 3; pages 1–2 are a terrorism rider) | new | 13 | `589ca91d565bdf7ea38e04679d5498c389cb8ac89934826ca21a967023a73562` |
| `clauses/chungkuo/overseas-inconvenience.old-wording.pdf` | 兆豐產物 Chung Kuo | 兆豐產物新個人海外旅行不便保險 (name as reported; not matched in the extracted text) | old | 8 | `c8821e8680e6ac637436262e1ee48a6b8ecfde0c9351b97ef8837fa624f3f8f0` |

### Source URLs

Chinese characters in a URL must be percent-encoded when fetching.

- `clauses/cathay/travel-bundle.new-wording.pdf`  
  https://www.cathay-ins.com.tw/cathayins/-/media/990e1b37dcb74ff7ba17410f150acc09.pdf
- `clauses/cathay/travel-bundle.old-wording.pdf`  
  https://gcp.cathay-ins.com.tw/CXIDocs/PF/doc/assets/bobe/travel/overseas_travel.pdf
- `clauses/fubon/overseas-inconvenience.new-wording.pdf`  
  https://b2c.518fb.com/fubon518/content/富邦產物個人海外旅行不便保險(旅-20260401).pdf
- `clauses/fubon/travel-bundle.old-wording.pdf`  
  https://api.einsure.com.tw/upload/doc/fubon/%E5%AF%8C%E9%82%A6%E7%94%A2%E7%89%A9_%E5%9C%8B%E5%A4%96%E6%97%85%E5%B9%B3%E9%9A%AA%E6%A2%9D%E6%AC%BE_231107175354.pdf
- `clauses/shinkong/inconvenience-online.new-wording.pdf`  
  https://www.sk858.com.tw/DocsRoot/Docs/share/新光產物個人旅行綜合保險(網投不便險)(115.06).pdf
- `clauses/shinkong/travel-comprehensive-overseas.new-wording.pdf`  
  https://www.sk858.com.tw/DocsRoot/Docs/share/%E6%96%B0%E5%85%89%E7%94%A2%E7%89%A9%E5%80%8B%E4%BA%BA%E6%97%85%E8%A1%8C%E7%B6%9C%E5%90%88%E4%BF%9D%E9%9A%AA(%E5%9C%8B%E5%A4%96%E6%97%85%E9%81%8A%E9%81%A9%E7%94%A8)(115.06).pdf
- `clauses/shinkong/overseas-inconvenience.old-wording.pdf`  
  https://www.sk858.com.tw/DocsRoot/Docs/%E6%96%B0%E5%85%89%E7%94%A2%E7%89%A9%E5%80%8B%E4%BA%BA%E6%B5%B7%E5%A4%96%E6%97%85%E8%A1%8C%E4%B8%8D%E4%BE%BF%E7%B6%9C%E5%90%88%E4%BF%9D%E9%9A%AA.pdf
- `clauses/mingtai/overseas-travel-bundle.new-wording.pdf`  
  https://www.msig-mingtai.com.tw/MobileWeb/FilesToDownload/Travel/foreign_travel_260601.pdf
- `clauses/huanan/travel-comprehensive.new-wording.pdf`  
  https://www.south-china.com.tw/Content/Upload/download/華南產物旅行綜合保險條款.pdf
- `clauses/huanan/travel-comprehensive-general.old-wording.pdf`  
  https://www.south-china.com.tw/Content/Upload/download/%E8%8F%AF%E5%8D%97%E7%94%A2%E7%89%A9%E6%97%85%E8%A1%8C%E7%B6%9C%E5%90%88%E4%BF%9D%E9%9A%AA%E6%A2%9D%E6%AC%BE(%E4%B8%80%E8%88%AC%E7%94%A8).pdf
- `clauses/hotai/world-travel-comprehensive.new-wording.pdf`  
  https://www.hotains.com.tw/WebImage/Portal/DocumentDownload/20260901_c083b5fc-b743-4b8f-9961-c3ede2899210/3a3d7e43-a777-4ebd-9ff3-d4adb7d706e2.pdf
- `clauses/tfmi/travel-comprehensive.new-wording.pdf`  
  https://ec.tfmi.com.tw/Product/clauses/travel/01.%E8%87%BA%E7%81%A3%E7%94%A2%E7%89%A9%E6%97%85%E9%81%8A%E7%B6%9C%E5%90%88%E4%BF%9D%E9%9A%AA_%E4%BF%9D%E5%96%AE%E6%A2%9D%E6%AC%BE.pdf
- `clauses/chungkuo/overseas-inconvenience.old-wording.pdf`  
  https://www.cki.com.tw/Content/files/%E4%BF%9D%E9%9A%AA%E5%95%86%E5%93%81/%E6%97%85%E9%81%8A%E4%BF%9D%E9%9A%AA/%E5%80%8B%E4%BA%BA%E6%97%85%E8%A1%8C%E7%B6%9C%E5%90%88%E4%BF%9D%E9%9A%AA/102141223037010001-A.pdf

### Access notes

- **Fubon (b2c.518fb.com):** a direct request returns an HTML error page. Load https://b2c.518fb.com/fubon518/car_list?index3=5522 first and reuse that session cookie and Referer.
- **Hotai:** the download URL contains a rotating GUID. Read the current link from https://www.hotains.com.tw/download/terms/travel/1.
- **Shinkong:** the index of clause PDFs is https://www.sk858.com.tw/Announce/ano/terms.
- Every file has a text layer; none is scanned.

## Ombudsman decisions (`data/cases/foi/`)

Anonymised decisions from the Financial Ombudsman Institution search site, https://ods.foi.org.tw/. Each file is `https://ods.foi.org.tw/download.aspx?article=<id>`.

| File | Decision | Article id | Pages | SHA-256 |
|---|---|---|---|---|
| `cases/foi/foi-113-2803.pdf` | 113年評字第2803號 | 1131105052 | 6 | `760442cb064e1d32fb44ab9fcdce658970b30835aa2947c2bd64bc1a0632297c` |
| `cases/foi/foi-113-5349.pdf` | 113年評字第5349號 | 1131109436 | 7 | `7a45c3e6d3144e84b733318ca92b3b0ca62af15fb34ae863c7491a0e0cbb9dc0` |
| `cases/foi/foi-114-5560.pdf` | 114年評字第5560號 | 1141111083 | 6 | `c49f0a49211535c443f713678324ab4d761588fa3ef40939af50831226981723` |
| `cases/foi/foi-114-5630.pdf` | 114年評字第5630號 | 1140020800 | 4 | `e65d0387e843d00370eab78f41cacf8edc58b3577945c0657d10bc94a1d2edb5` |
| `cases/foi/foi-114-5717.pdf` | 114年評字第5717號 | 1141111368 | 4 | `622ab1de751971be5c8beaf654d84b3b03ba6da3e9c8395d52f4e8ead872f9b6` |
| `cases/foi/foi-114-6156.pdf` | 114年評字第6156號 | 1140022869 | 4 | `576a2a05a047665a16667e8beaac344fe7d446aee9effa545d3d5915f4686f6d` |

## Industry Q&A (`data/cases/nlia/`)

`cases/nlia/nlia_qa.txt` is the Non-Life Insurance Association's Q&A on the new wording: 35 scenario-and-answer items, revised 2026-07-30. It is git-ignored.

- Source: https://www.hotains.com.tw/download/terms/travel/1. The text is embedded in that page's site data as news item 182, 「0401新制海外旅行不便保險QA(0730增訂版)」. No copy hosted by the association itself was found.
- The worked example in Q7 is an image in the original, so it is missing from the text file.
- SHA-256: `3e5baf1c15e24189785566b454b252880cc0516127f4916bb0e2b15d33c48faf`

## Benefit amounts (`data/amounts.csv`)

Benefit amounts per plan, transcribed from insurers' public product pages. This file is committed; every row carries its source URL.

- 89 rows. 85 are amounts read from the page named in `source_url`. The other 4 (`verified=no`) are placeholders for insurers whose amounts were not found.
- Amounts found: Cathay Century, Fubon, Shinkong, MSIG Mingtai. Not found: South China, Hotai, Taiwan Fire & Marine, Chung Kuo; their amounts appear to be shown only inside online quote tools, which were not run.
- These are online-channel plans only. Insurers sell other plans offline.
- MSIG Mingtai's table gives flight-delay amounts without the step rule or the per-event cap.
