# PLAN-5X kabul kaydı

5 Kasım 2026 itibarıyla plan tamamlanmış değildir. Aşağıdaki ayrım, kod
bulunmasını kabul edilmiş sonuç olarak saymayı önler. Bu kayıt deney sonucu
veya bağımsız denetim belgesi değildir.

| Aşama | Uygulanan akış | Açık kabul koşulu |
| --- | --- | --- |
| P0 | 50 görev, v2 hatalı başlangıç programları, dondurulmuş protokol, çift hazırlık, hata arşivi | Temsil gücü incelemesi; baseline ve aday için 250'şer gerçek koşu; Hermes komutunun gerçek kurulumla doğrulanması; CI sonucu |
| P1 | Çağrı kimliği, günlükten tekrar kullanma, belirsiz çağrı engeli, durdurma, çağrı kotası, sağlayıcı rezervasyon defteri | CLI için çağrı öncesi katı dolar rezervasyonu sağlanmıyor; kesinti ve eşzamanlılık kabul testleri çalıştırılmadı |
| P2 | Donmuş ortam ve kanıt kimliği, operatör izinli önbellek, hedefli onarım, hata sınıfları | Sabit Docker imajında cache invalidation ve yüzde 60 süreç azalması kanıtı |
| P3 | Uyarlanan üretim genişliği, ayrı onarım koltuğu, sınırlı sentez bağlamı, emsal kimliği, durgunluk duruşu | Bağımsız model kökenleri; token başına doğrulanmış sonuçta iki kat iyileşme ölçümü; davranış regresyonları |
| P4 | Sınırlı yeniden üretim paketi, inceleme şablonu, staging, iki görevle yükseltme, kalıcı kaynak iptali | Paketler otomatik küçültülmüş minimal örnek değildir; bağımsız görevlerde gerçek beceri kabulü ve hata turu azalması ölçümü |
| P5 | Tam matris, yanlış kabul ve başarı sınırı, fatura eşleştirme, denetim kökeni ve 5X karşılaştırma kapısı | Gerçek koşu raporları, doğrulanmış ücretler, bağımsız denetçi ve ölçülmüş en az 5X kazanç |

Çift hazırlama `evals.imece.prepare_pair`, koşu inceleme
`evals.imece.inspect_run`, hata arşivi `evals.imece.failures`, fatura eşleştirme
`evals.imece.billing` ve nihai karşılaştırma `evals.imece.compare` ile yapılır.
Hazırlık araçları model çağrısı yapmaz. Kullanıcının test ve canlı kıyaslama
atlama talimatı bu çalışma sırasında korunmuştur.

Mevcut ortamda Docker çalıştırılabilir dosyası bulunamadı. Codex ve Antigravity
Gemini çağrıları son denemelerde kota hatası verdi. Başka bir CLI kopyası
aynı hesap kotasını otomatik olarak kaldırmaz. Harici fiyat, model bağımsızlığı
ve denetçi onayı uydurularak bu koşullar tamamlanamaz.
