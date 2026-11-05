# PLAN-5X kabul kaydı

5 Kasım 2026 itibarıyla plan tamamlanmış değildir. Aşağıdaki ayrım, kod
bulunmasını kabul edilmiş sonuç olarak saymayı önler. Bu kayıt deney sonucu
veya bağımsız denetim belgesi değildir.

| Aşama | Uygulanan akış | Açık kabul koşulu |
| --- | --- | --- |
| P0 | 50 görev, v2 hatalı başlangıç programları, dondurulmuş protokol, çift hazırlık, hata arşivi | Temsil gücü incelemesi; baseline ve aday için 250'şer gerçek koşu; Hermes komutunun gerçek kurulumla doğrulanması; CI sonucu |
| P1 | Çağrı kimliği, günlükten tekrar kullanma, belirsiz çağrı engeli, durdurma, çağrı kotası, sağlayıcı rezervasyon defteri; yerel kesinti ve rezervasyon regresyonları geçti | CLI için çağrı öncesi katı dolar rezervasyonu sağlanmıyor; gerçek servis kesintisi kabulü açık |
| P2 | Donmuş ortam ve kanıt kimliği, operatör izinli önbellek, hedefli onarım, hata sınıfları | Sabit Docker imajında cache invalidation ve yüzde 60 süreç azalması kanıtı |
| P3 | Uyarlanan üretim genişliği, ayrı onarım koltuğu, sınırlı sentez bağlamı, emsal kimliği, durgunluk duruşu | Bağımsız model kökenleri; token başına doğrulanmış sonuçta iki kat iyileşme ölçümü; davranış regresyonları |
| P4 | Sınırlı yeniden üretim paketi, sandbox içinde dosya azaltma, inceleme şablonu, staging, iki görevle yükseltme, kalıcı kaynak iptali | Dosya azaltma küresel minimalite kanıtı değildir; bağımsız görevlerde gerçek beceri kabulü ve hata turu azalması ölçümü |
| P5 | Tam matris, yanlış kabul ve başarı sınırı, fatura eşleştirme, denetim kökeni ve 5X karşılaştırma kapısı | Gerçek koşu raporları, doğrulanmış ücretler, bağımsız denetçi ve ölçülmüş en az 5X kazanç |

Çift hazırlama `evals.imece.prepare_pair`, koşu inceleme
`evals.imece.inspect_run`, hata arşivi `evals.imece.failures`, fatura eşleştirme
`evals.imece.billing` ve nihai karşılaştırma `evals.imece.compare` ile yapılır.
Hazırlık araçları model çağrısı yapmaz. Kullanıcı 5 Kasım'daki devamda yerel
testlerin çalıştırılmasına izin verdi; canlı kıyaslamayı atlama talimatını korudu.
Tam yerel testler ve yeni kurtarma/önbellek regresyonları çalıştırıldı.
`tests/test_imece_evidence.py` yürütme sınırında sahte sandbox sonucu kullanır;
bu testlerin geçmesi gerçek Docker izolasyonunun doğrulandığı anlamına gelmez.
CI artık `evals` kodunu da lint ve biçim kontrolüne dahil eder.

Son tam yerel koşu: **447 geçti, 1 atlandı** (`uv run pytest -q`). Atlanan
test gerçek Docker yürütücüsü içindir. Starlette/httpx kullanımı için bir
bağımlılık kullanım dışı bırakma uyarısı bildirildi. `ruff check src tests
evals`, `ruff format --check src tests evals` ve `git diff --check` geçti.

Docker CLI ve Colima kuruldu; `imece-tests` profiliyle gerçek izolasyon testi
geçti. Son tam koşuda **459 test geçti, atlanan test yok**; gerçek Docker
dosya azaltma testi de bu koşuya dahildir. Kullanılan
Python imajı `python:3.12-slim`, indirilen digest
`sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e`.
Bu test koşusu 250 görevlik model kıyaslaması değildir.

Son P5 veri türü ve tamamlanma durumu regresyonları eklendikten sonraki
yerel koşu: **466 geçti, 2 Docker opt-in testi atlandı**. Bu devamda Docker
VM kapalı tutuldu; önceki gerçek Docker doğrulamaları yukarıda kaydedilmiştir.
Dokuz yeni regresyon bozuk ücret defterlerinin ve bitmemiş kontrol noktalarının
5X kanıtı olarak kabul edilmesini engeller. Lint ve biçim kontrolleri geçti.

Codex ve Antigravity
Gemini çağrıları son denemelerde kota hatası verdi. Başka bir CLI kopyası
aynı hesap kotasını otomatik olarak kaldırmaz. Harici fiyat, model bağımsızlığı
ve denetçi onayı uydurularak bu koşullar tamamlanamaz.
