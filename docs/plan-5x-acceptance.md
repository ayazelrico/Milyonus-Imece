# PLAN-5X kabul kaydı

Son devam: kullanıcı canlı kıyaslama ve denetim için izin verdi. Canlı
kampanyada baseline ve adayda dörder sonuç satırı kaydedildi; iki tarafta
birer belirsiz çağrı oluştuğunda gözetmen durdu. Kullanıcı çağrı başına ücret
dökümü bulunmadığını bildirdi. Ayrı Codex oturumlarının teknik bulguları ve
düzeltmeleri [kampanya kaydında](audits/2026-11-05-campaign.md) bulunur.
6 Kasım devamında ek beş alanlı örneklem tamamlandı: iki kolda da 4/5
doğrulanmış kabul; bir bütçe sonucu ve bir belirsiz çağrı korundu.
[Sonuç kaydı](experiments/compact-five-domains-2026-11-06.md).
Kesinti sonrası token hesabı ve varsayılan duruş için ayrı model incelemesinin
iki bulgusu yerel regresyonlarla düzeltildi.
P2'nin gerçek Docker tekrar yükünde 15 süreç 3'e indi (%80); kaynak, kontrol
ve timeout değişimleri yeniden yürütüldü. Bu sınırlı sentetik ölçüm tüm matris
veya tüm ortam değişimleri için kabul sağlamaz.
[Ölçüm kaydı](experiments/cache-probe-2026-11-06.md).
P1 gönderim kuyruğunda kabul kontrolü sıranın gelmesinden sonra yapılır;
önceki çağrının bütçe veya belirsizlik durumu bekleyen çağrıya uygulanır.
Son ortam düzeltmesi kanıtı seçilen imaj, daemon/kernel/sürüm/güvenlik
özellikleri ve yürütme komutuna bağladı; metadata yokken yeniden kullanım
engellenir. Gerçek Docker politika ve erişilemeyen bağlam testleri geçti.
Ek kimlik sorguları dahil toplam CLI süreç azalması %26,7'dir; %80 sadece
doğrulama konteynerleri içindir.
[Güncel ölçüm](experiments/cache-runtime-probe-2026-11-06.md).
Hata paketleri artık kapıdaki ortam/politika parmak izini taşır; dosya
azaltma başlamadan önce ve replay sonuçlarında eşleşme aranır. Gerçek Docker
kapı → yakalama → azaltma akışı geçti. Eski kimliksiz paketler açık izinle
yalnızca ortamı doğrulanmamış sonuç üretebilir.
Beceri yayımlamasında staging/metadata değişimi engellendi; iki yayımlama
yolu taşıma hatasında eski sürümü geri koyar veya geri alma da başarısızsa
kurtarma yolunda korur. Onarım kapısında yalnızca gerçek `True` kabul edilir.
Yayımlama sırasında oracle iptali regresyonu geçti; otomatik çökme kurtarması
bu değişikliğin kapsamında değildir.
Son tam yerel koşu Docker dahil **548 geçti, atlanan test yok** sonucunu verdi.
Önceki aşamaların test sayıları aşağıda tarihçe olarak korunur.

6 Kasım 2026 itibarıyla plan tamamlanmış değildir. Aşağıdaki ayrım, kod
bulunmasını kabul edilmiş sonuç olarak saymayı önler. Bu kayıt deney sonucu
veya bağımsız denetim belgesi değildir.

| Aşama | Uygulanan akış | Açık kabul koşulu |
| --- | --- | --- |
| P0 | 50 görev, v2 hatalı başlangıç programları, dondurulmuş protokol, çift hazırlık, hata arşivi | Temsil gücü incelemesi; baseline ve aday için 250'şer gerçek koşu; Hermes komutunun gerçek kurulumla doğrulanması; CI sonucu |
| P1 | Çağrı kimliği, günlükten tekrar kullanma, belirsiz çağrı engeli, durdurma, çağrı kotası, sağlayıcı rezervasyon defteri; yerel kesinti ve rezervasyon regresyonları geçti | CLI için çağrı öncesi katı dolar rezervasyonu sağlanmıyor; gerçek servis kesintisi kabulü açık |
| P2 | Seçilen imaj/daemon/komuta bağlı kanıt, operatör izinli önbellek, hedefli onarım, hata sınıfları; sentetik yükte %80 konteyner, metadata dahil %26,7 toplam CLI azalması; dört boyutta gerçek geçersizleşme | Tam matris/temsili yükte yüzde 60 doğrulama azalması; diğer sağlıklı imaj/daemon ortamlarında gerçek geçersizleşme kanıtı |
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
